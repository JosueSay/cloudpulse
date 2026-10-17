-- CloudPulse — Log Analytics SQL para la API de pedidos
--
-- Vista consultada: la que crea Terraform en infra/logging.tf
--   google_logging_project_bucket_config.cloudpulse  -> bucket  cloudpulse-logs
--   google_logging_log_view.cloudpulse_requests      -> vista   cloudpulse_requests
--
-- La cláusula FROM de una vista de logs tiene el formato
--   `PROJECT_ID.LOCATION.BUCKET_ID.LOG_VIEW_ID`
-- y aquí se escribe con los valores de infra/terraform.tfvars:
--   `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
-- Si cambian project_id, region, log_bucket_id o log_view_id, hay que
-- sustituir los cuatro componentes en todas las consultas.
--
-- QUÉ TRAE LA VISTA, Y QUÉ FILTRA CADA CONSULTA
--
-- El campo `filter` de una Log View solo admite CONJUNCIONES con AND de
-- SOURCE(), resource.type y LOG_ID(), más sus negaciones con NOT (referencia
-- REST de projects.locations.buckets.views). Nada de payload, y nada de OR:
-- un grupo entre paréntesis ya excede el límite de anidamiento 1.
--
-- Filtro REAL de la vista, el que la API aceptó:
--   resource.type="cloud_run_revision"
--
-- Es decir: la vista NO puede quedarse solo con los eventos
-- `request_completed`, y además contiene las entradas de auditoría
-- (`cloudaudit.googleapis.com/*`, con proto_payload) y las del sistema
-- (`run.googleapis.com/varlog/system`, con text_payload) que el sink enruta al
-- mismo bucket.
--
-- Esa selección la hace cada consulta, con
--   JSON_VALUE(json_payload.message) = 'request_completed'
-- que además implica json_payload IS NOT NULL. No quites ese predicado: sin él
-- se cuela cualquier otra línea que el contenedor escriba en stdout o stderr.
--
-- Los filtros de las métricas basadas en logs (infra/logging.tf) sí usan
-- jsonPayload: un filtro de métrica no tiene esa restricción. Son dos
-- gramáticas distintas.

-- Acceso a los campos (esquema de Log Analytics):
--   timestamp                    TIMESTAMP, instante del log entry
--   severity                     STRING a nivel de entrada; NO existe
--                                jsonPayload.severity: Cloud Run lo eleva
--   resource.type                STRING
--   resource.labels              JSON  -> JSON_VALUE(resource.labels.x)
--   json_payload                 JSON  -> JSON_VALUE(json_payload.x)
--   números del payload          JSON_VALUE devuelve texto: hay que castear
--
-- AVISO SOBRE EL TIEMPO (importante para las consultas 4, 5 y 6)
--
-- El simulador planifica cada solicitud en un minuto `scheduled_min` extraído
-- de una normal N(mu=30, sigma=10). Ese valor NO viaja a Cloud Logging: el
-- backend no lo recibe ni lo registra. En Log Analytics solo existe
-- `timestamp`, el instante real del evento.
--
-- Por tanto, estas consultas miden el minuto de llegada OBSERVADO, calculado
-- como la distancia al primer evento de la corrida. No reconstruyen
-- `scheduled_min`.
--
-- MEDIDO en la corrida oficial `cc4f0755` (2026-10-16): el eje temporal
-- observado esta COMPRIMIDO un 2,767 % respecto al plan. El despachador se
-- temporiza con CLOCK_MONOTONIC y en WSL2 ese reloj avanzo mas despacio que el
-- reloj de pared, de forma lineal (-1,6602 s por minuto planificado, residuo
-- maximo 485 ms). Consecuencias para estas consultas:
--
--   * la ventana real duro 58 min 21 s, no 60;
--   * la media y la desviacion observadas salen escaladas por 0,9724:
--     media 29,09 min (plan 29,92) y sigma 9,73 (plan 10,00). Los dos ratios
--     coinciden en la cuarta cifra, asi que la CAMPANA SE CONSERVA: es un
--     reescalado del eje, no una deformacion;
--   * la ventana del escenario [35,45) del plan cae en el tiempo observado en
--     [34,03, 43,76). Las consultas 5a y 5b usan los bordes literales 35 y 45,
--     asi que miran una ventana desplazada ~1 minuto. La 5c compensa el
--     desvio.
--
-- Para comparar contra el plan hay que cruzar
-- `outputs/simulator/requests.csv` (columnas request_id y scheduled_min) con
-- el campo json_payload.request_id de los logs; eso se hace fuera de Log
-- Analytics.


-- ===========================================================================
-- 1. Solicitudes por minuto
-- ===========================================================================
-- Reconstruye la curva de tráfico de la corrida. Es la fuente del panel 5b
-- del dashboard.

SELECT
  TIMESTAMP_TRUNC(timestamp, MINUTE) AS minute,
  COUNT(*) AS requests
FROM
  `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
WHERE
  JSON_VALUE(json_payload.message) = 'request_completed'
  AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
  AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
GROUP BY
  minute
ORDER BY
  minute;


-- ===========================================================================
-- 2. Solicitudes agrupadas por outcome
-- ===========================================================================
-- Reparto global entre success, client_error y server_error, con la latencia
-- que midió la propia función (json_payload.latency_ms, que no incluye cold
-- start ni red).

SELECT
  JSON_VALUE(json_payload.outcome) AS outcome,
  COUNT(*) AS requests,
  ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS share_pct,
  ROUND(AVG(SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64)), 3)
    AS avg_latency_ms,
  ROUND(
    APPROX_QUANTILES(
      SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64), 100
    )[OFFSET(95)],
    3
  ) AS p95_latency_ms
FROM
  `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
WHERE
  JSON_VALUE(json_payload.message) = 'request_completed'
  AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
  AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
GROUP BY
  outcome
ORDER BY
  requests DESC;


-- ===========================================================================
-- 3. Errores por endpoint
-- ===========================================================================
-- `endpoint` guarda la plantilla de ruta (`GET /orders/{id}`), nunca el id
-- concreto, así que agrupar por él da exactamente una fila por operación.
-- `error_type` separa el 500 inyectado (simulated_failure) de un defecto real
-- (unhandled_exception).

SELECT
  JSON_VALUE(json_payload.endpoint) AS endpoint,
  JSON_VALUE(json_payload.outcome) AS outcome,
  SAFE_CAST(JSON_VALUE(json_payload.status_code) AS INT64) AS status_code,
  JSON_VALUE(json_payload.error_type) AS error_type,
  COUNT(*) AS errors
FROM
  `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
WHERE
  JSON_VALUE(json_payload.message) = 'request_completed'
  AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
  AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  AND JSON_VALUE(json_payload.outcome) != 'success'
GROUP BY
  endpoint,
  outcome,
  status_code,
  error_type
ORDER BY
  errors DESC;


-- ===========================================================================
-- 4. AVG y STDDEV del minuto de llegada OBSERVADO
-- ===========================================================================
-- Lee el aviso sobre el tiempo de la cabecera: esto NO es la media ni la
-- desviación de `scheduled_min`. Mide los instantes reales de los logs,
-- expresados en minutos desde el primer evento de la corrida.
--
-- Referencia del plan (simulator/config.json): mu_min = 30, sigma_min = 10,
-- con los instantes truncados a [0, 60].
--
-- Resultado MEDIDO en la corrida `cc4f0755` (debe reproducirse al ejecutar):
--   run_started_at       2026-10-16T10:56:57.356008Z
--   run_ended_at         2026-10-16T11:55:17.864529Z
--   requests             6000
--   avg_observed_min     29.0874
--   stddev_observed_min  9.7280
--   min / max            0.0000 / 58.3418
-- La diferencia con 30 y 10 es el reescalado del 2,767 % del aviso de arriba,
-- no un error de la simulacion.

WITH
  events AS (
    SELECT timestamp
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
    WHERE JSON_VALUE(json_payload.message) = 'request_completed'
      AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
      AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  ),
  run AS (
    SELECT MIN(timestamp) AS started_at, MAX(timestamp) AS ended_at
    FROM events
  ),
  observed AS (
    SELECT
      TIMESTAMP_DIFF(events.timestamp, run.started_at, MILLISECOND) / 60000.0
        AS observed_min
    FROM events
    CROSS JOIN run
  )
SELECT
  (SELECT started_at FROM run) AS run_started_at,
  (SELECT ended_at FROM run) AS run_ended_at,
  COUNT(*) AS requests,
  ROUND(AVG(observed_min), 4) AS avg_observed_min,
  ROUND(STDDEV_SAMP(observed_min), 4) AS stddev_observed_min,
  ROUND(MIN(observed_min), 4) AS min_observed_min,
  ROUND(MAX(observed_min), 4) AS max_observed_min
FROM
  observed;


-- ===========================================================================
-- 5. Incremento de errores durante el escenario configurado
-- ===========================================================================
-- El escenario de simulator/config.json duplica la proporción de errores
-- intencionales del cliente para `electronics` entre los minutos 35 y 45 del
-- plan. La ventana se evalúa sobre el minuto OBSERVADO, así que sus bordes son
-- aproximados.
--
-- CAVEAT DE CATEGORÍA: dos de las seis variantes de payload inválido
-- (`bad_category`, que envía "furniture", y `not_an_object`) hacen que el
-- backend no registre `category`, porque solo guarda valores que pertenecen al
-- esquema. Esos errores llegan al log con category NULL y no se atribuyen a
-- `electronics`. La fila `electronics` es por tanto un suelo, no el total; el
-- efecto completo se ve en la tasa global de client_error dentro de la
-- ventana, que es la que compara la consulta 5b.

-- CORRECCION APLICADA (5a, 5b y 5c): la subconsulta `run` lleva AHORA la misma
-- ventana temporal que `events`. Sin ella, MIN(timestamp) se anclaba en el
-- evento mas antiguo de la vista —de las pruebas previas de las 10:09— y todos
-- los minutos observados salian desplazados ~47 minutos, de modo que
-- `in_scenario` nunca llegaba a ser verdadero. La ejecucion defectuosa quedo
-- registrada en el historial de depuracion (119 filas).
--
-- SEGUNDA CAUSA, independiente de la anterior: el `GROUP BY minute,
-- observed_min` original partia en dos casi cada minuto de reloj, porque la
-- corrida empezo a las 10:56:57 y un minuto de reloj abarca dos minutos
-- observados. Solo por eso la consulta habria devuelto 102 filas aun con la
-- ventana puesta. Agrupar unicamente por `minute`, resumiendo con
-- MIN(observed_min) y LOGICAL_OR(...), da una fila por minuto.
--
-- Con las dos correcciones, 5b devuelve 60 filas: verificado en la consola y
-- capturado en outputs/reports/evidence/06-errors-per-minute.png.
--
-- APROXIMACION QUE SIGUE EN PIE en 5b: marca el minuto de reloj completo si
-- CUALQUIER evento suyo cae en la ventana (LOGICAL_OR), y la corrida empezo a
-- las 10:56:57, asi que un minuto de reloj no coincide con un minuto
-- observado. Calculado sobre los 6.000 eventos reales, eso marca 11 minutos
-- (11:31-11:41 UTC) con 1.491 solicitudes, en vez de las 1.288 que caen
-- estrictamente en el intervalo observado [35,45). Por eso existe 5c, que
-- autocalibra la ventana y no depende del minuto de reloj.

-- 5a. Por categoría, dentro y fuera de la ventana.
WITH
  run AS (
    SELECT MIN(timestamp) AS started_at
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
    WHERE JSON_VALUE(json_payload.message) = 'request_completed'
      AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
      AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  ),
  events AS (
    SELECT
      TIMESTAMP_DIFF(logs.timestamp, run.started_at, MILLISECOND) / 60000.0
        AS observed_min,
      JSON_VALUE(logs.json_payload.outcome) AS outcome,
      JSON_VALUE(logs.json_payload.category) AS category
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
      AS logs
    CROSS JOIN run
    WHERE JSON_VALUE(logs.json_payload.message) = 'request_completed'
      AND logs.timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
      AND logs.timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  )
SELECT
  IF(observed_min >= 35 AND observed_min < 45, 'scenario', 'baseline')
    AS time_window,
  IFNULL(category, '(sin categoría)') AS category,
  COUNT(*) AS requests,
  COUNTIF(outcome = 'client_error') AS client_errors,
  ROUND(100 * COUNTIF(outcome = 'client_error') / COUNT(*), 2)
    AS client_error_pct
FROM
  events
GROUP BY
  time_window,
  category
ORDER BY
  time_window,
  category;

-- 5b. Tasa global de client_error minuto a minuto, con la ventana marcada.
--     Es la forma más robusta de ver el escalón, porque no depende de que la
--     categoría haya sobrevivido al payload roto.
WITH
  run AS (
    SELECT MIN(timestamp) AS started_at
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
    WHERE JSON_VALUE(json_payload.message) = 'request_completed'
      AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
      AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  ),
  events AS (
    SELECT
      TIMESTAMP_TRUNC(logs.timestamp, MINUTE) AS minute,
      CAST(
        FLOOR(
          TIMESTAMP_DIFF(logs.timestamp, run.started_at, MILLISECOND) / 60000.0
        ) AS INT64
      ) AS observed_min,
      JSON_VALUE(logs.json_payload.outcome) AS outcome
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
      AS logs
    CROSS JOIN run
    WHERE JSON_VALUE(logs.json_payload.message) = 'request_completed'
      AND logs.timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
      AND logs.timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  )
SELECT
  minute,
  MIN(observed_min) AS observed_min,
  LOGICAL_OR(observed_min >= 35 AND observed_min < 45) AS in_scenario,
  COUNT(*) AS requests,
  COUNTIF(outcome = 'client_error') AS client_errors,
  ROUND(
    100 * COUNTIF(outcome = 'client_error') / COUNT(*), 2
  ) AS client_error_pct
FROM events
GROUP BY minute
ORDER BY minute;


-- 5c. La misma ventana, AUTOCALIBRADA contra el desvío de reloj.
--     En vez de usar los bordes literales 35 y 45 del plan, escala la ventana
--     por el factor que la propia corrida revela: span observado / 60 min.
--     Para `cc4f0755` ese factor es 58,3418 / 60 = 0,9724, así que la ventana
--     del plan se evalúa en [34,03, 43,76) del tiempo observado.
--
--     Resultado MEDIDO: requests = 1406 · client_errors = 136 · 9,67 %
--     frente al 7,75 % del resto de la corrida.
WITH
  run AS (
    SELECT
      MIN(timestamp) AS started_at,
      TIMESTAMP_DIFF(MAX(timestamp), MIN(timestamp), MILLISECOND) / 60000.0
        AS span_min
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
    WHERE JSON_VALUE(json_payload.message) = 'request_completed'
      AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
      AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  ),
  events AS (
    SELECT
      TIMESTAMP_DIFF(logs.timestamp, run.started_at, MILLISECOND) / 60000.0
        AS observed_min,
      run.span_min / 60.0 AS clock_factor,
      JSON_VALUE(logs.json_payload.outcome) AS outcome
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
      AS logs
    CROSS JOIN run
    WHERE JSON_VALUE(logs.json_payload.message) = 'request_completed'
      AND logs.timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')  -- inicio de la corrida
      AND logs.timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')  -- fin de la corrida
  )
SELECT
  IF(
    observed_min >= 35 * clock_factor AND observed_min < 45 * clock_factor,
    'scenario',
    'baseline'
  ) AS time_window,
  ROUND(ANY_VALUE(clock_factor), 6) AS clock_factor,
  COUNT(*) AS requests,
  COUNTIF(outcome = 'client_error') AS client_errors,
  ROUND(100 * COUNTIF(outcome = 'client_error') / COUNT(*), 2)
    AS client_error_pct
FROM
  events
GROUP BY
  time_window
ORDER BY
  time_window;


-- ===========================================================================
-- 6. Correlación por request_id (trazabilidad del laboratorio)
-- ===========================================================================
-- Devuelve el evento de la API para un identificador concreto del simulador.
-- Es el puente manual con outputs/simulator/requests.csv, que es el único
-- sitio donde vive `scheduled_min`.

SELECT
  timestamp,
  severity,
  JSON_VALUE(json_payload.request_id) AS request_id,
  JSON_VALUE(json_payload.endpoint) AS endpoint,
  SAFE_CAST(JSON_VALUE(json_payload.status_code) AS INT64) AS status_code,
  JSON_VALUE(json_payload.outcome) AS outcome,
  JSON_VALUE(json_payload.error_type) AS error_type,
  SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64) AS latency_ms,
  JSON_VALUE(json_payload.order_id) AS order_id,
  JSON_VALUE(json_payload.order_status) AS order_status,
  JSON_VALUE(json_payload.category) AS category,
  JSON_VALUE(json_payload.customer_tier) AS customer_tier,
  SAFE_CAST(JSON_VALUE(json_payload.amount) AS FLOAT64) AS amount
FROM
  `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
WHERE
  JSON_VALUE(json_payload.message) = 'request_completed'
  -- Identificadores reales de la corrida oficial `cc4f0755`, para copiar:
  --   sim-cc4f0755-000000  creacion valida        -> 201
  --   sim-cc4f0755-000006  payload invalido       -> 400
  --   sim-cc4f0755-000039  identificador ausente  -> 404
  --   sim-cc4f0755-000070  secuencia imposible    -> 409
  --   sim-cc4f0755-000120  fallo inyectado        -> 500
  --   sim-cc4f0755-000003  degradacion del pool   -> 404 (columna fallback del CSV)
  AND JSON_VALUE(json_payload.request_id) = 'sim-cc4f0755-000070'
ORDER BY
  timestamp;
