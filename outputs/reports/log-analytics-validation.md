# CloudPulse — Validación final de observabilidad

**Corrida validada:** `cc4f0755` · 6.000 solicitudes · 2026-10-16T10:56:57Z → 11:55:18Z
**Vista:** `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
**Filtro real de la vista:** `resource.type="cloud_run_revision"`

Este documento contiene (1) la auditoría de compatibilidad de las siete
consultas, (2) las consultas listas para copiar con el resultado que debe
devolver cada una, (3) el análisis de las métricas del dashboard y (4) el
checklist de capturas.

**Todo lo marcado como «esperado» está calculado sobre los 6.000 eventos reales
de Cloud Logging de esta corrida**, no estimado. Si la consola devuelve otra
cifra, la discrepancia es real y hay que investigarla.

## 1. Auditoría de compatibilidad con la vista

| # | Consulta | Compatible | Notas |
| --- | --- | --- | --- |
| 1 | Solicitudes por minuto | ✅ | — |
| 2 | Solicitudes por outcome | ⚠️ | Usa `APPROX_QUANTILES` y una ventana `SUM(...) OVER ()`. Si Log Analytics rechaza alguna, abajo hay una variante sin ellas |
| 3 | Errores por endpoint | ✅ | — |
| 4 | AVG y STDDEV del minuto observado | ✅ | Mide tiempo observado, no `scheduled_min` |
| 5a | Escenario por categoría | ✅ | La fila `(sin categoría)` necesita lectura: §2.5 |
| 5b | Escenario minuto a minuto | ✅ | Ventana aproximada al minuto de reloj: ±1 min |
| 5c | Escenario autocalibrado | ✅ | **Nueva**: compensa el desvío de reloj |
| 6 | Correlación por `request_id` | ✅ | Tenía un id de ejemplo inexistente; corregido |

### Problemas encontrados y corregidos en `docs/log-analytics-queries.sql`

1. **La cabecera describía un filtro de vista que no es el desplegado.** Decía
   `resource.type AND resource.labels.service_name AND (log_id(stdout) OR
   log_id(stderr))`; el filtro real es solo `resource.type="cloud_run_revision"`,
   porque la API rechazó las dos versiones anteriores (payload no permitido, y
   límite de anidamiento 1 que prohíbe el `OR`). Corregido con la cita de la
   referencia REST.
2. **Consecuencia funcional de ese filtro:** la vista también contiene las
   entradas de auditoría (`proto_payload`) y de sistema (`text_payload`) que el
   sink enruta al mismo bucket. Por eso **el predicado
   `JSON_VALUE(json_payload.message) = 'request_completed'` es obligatorio en
   las 9 lecturas de la vista** (verificado: las 9 lo llevan).
3. **El aviso sobre el tiempo atribuía la diferencia al truncado.** La causa
   medida es el desvío de reloj del 2,767 % (§4). Corregido con las cifras.
4. **La consulta 6 filtraba por `sim-000001`, que no existe** en ninguna
   corrida: devolvía 0 filas. Ahora usa `sim-cc4f0755-000070` y lista seis
   identificadores reales de esta corrida, uno por cada código de respuesta.
5. **Añadida la consulta 5c**, que autocalibra la ventana del escenario.

Funciones usadas: `JSON_VALUE`, `SAFE_CAST`, `TIMESTAMP_TRUNC`,
`TIMESTAMP_DIFF`, `COUNTIF`, `STDDEV_SAMP`, `APPROX_QUANTILES`, `IF`, `IFNULL`,
`ANY_VALUE`, `FLOOR`, `ROUND`, `CROSS JOIN`, CTEs y una función de ventana.
Todas son SQL estándar de BigQuery; **no pude verificar remotamente que Log
Analytics acepte `APPROX_QUANTILES` ni la función de ventana** (no hay forma de
validar SQL sin ejecutarlo en la consola o crear un *linked dataset*). La
variante 2-bis de §2.2 evita ambas.

## 2. Consultas listas para copiar, con el resultado esperado

El `FROM` ya está relleno con los valores reales del proyecto. Péguelas en
**Logging → Log Analytics**, seleccionando la vista `cloudpulse_requests`.

### 2.1. Consulta 1 — Solicitudes por minuto

```sql
SELECT
  TIMESTAMP_TRUNC(timestamp, MINUTE) AS minute,
  COUNT(*) AS requests
FROM
  `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
WHERE
  JSON_VALUE(json_payload.message) = 'request_completed'
GROUP BY
  minute
ORDER BY
  minute;
```

**Esperado:** 60 filas, de `10:56` a `11:55`, que **suman exactamente 6.000**.

| Minuto | requests |
| --- | --- |
| 10:56 | 9 |
| 10:57 | 4 |
| 10:58 | 4 |
| 10:59 | 11 |
| 11:00 | 7 |
| … | … |
| **11:29 (pico)** | **280** |
| 11:26 | 265 |
| 11:25 | 259 |
| … | … |
| 11:53 | 9 |
| 11:54 | 3 |
| 11:55 | 11 |

La curva debe subir desde ~4-9 solicitudes/min hasta el pico de 280 alrededor
de `11:29` y volver a bajar: es la campana `N(30,10)` vista en tiempo real.

### 2.2. Consulta 2 — Solicitudes por outcome

```sql
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
GROUP BY
  outcome
ORDER BY
  requests DESC;
```

**Esperado:**

| outcome | requests | share_pct | avg_latency_ms | p95_latency_ms |
| --- | --- | --- | --- | --- |
| `success` | 5.378 | 89,63 | ≈0,212 | ≈0,383 |
| `client_error` | 492 | 8,20 | ≈0,172 | ≈0,308 |
| `server_error` | 130 | 2,17 | ≈0,180 | ≈0,226 |

Esas latencias son las **del interior de la función** (`json_payload.latency_ms`):
décimas de milisegundo. No son las del cliente (p50 81,2 ms) ni las de Cloud Run
(p50 5,06 ms). Las tres miden cosas distintas (§3.2).

**Variante 2-bis**, si la consola rechaza `APPROX_QUANTILES` o la función de ventana:

```sql
SELECT
  JSON_VALUE(json_payload.outcome) AS outcome,
  COUNT(*) AS requests,
  ROUND(AVG(SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64)), 3)
    AS avg_latency_ms,
  ROUND(MAX(SAFE_CAST(JSON_VALUE(json_payload.latency_ms) AS FLOAT64)), 3)
    AS max_latency_ms
FROM
  `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
WHERE
  JSON_VALUE(json_payload.message) = 'request_completed'
GROUP BY
  outcome
ORDER BY
  requests DESC;
```

### 2.3. Consulta 3 — Errores por endpoint

```sql
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
  AND JSON_VALUE(json_payload.outcome) != 'success'
GROUP BY
  endpoint, outcome, status_code, error_type
ORDER BY
  errors DESC;
```

**Esperado: exactamente 7 filas que suman 622.**

| endpoint | outcome | status | error_type | errors |
| --- | --- | --- | --- | --- |
| `POST /orders` | client_error | 400 | validation_error | 253 |
| `GET /orders/{id}` | client_error | 404 | not_found | 138 |
| `POST /orders` | server_error | 500 | simulated_failure | 63 |
| `POST /orders/{id}/cancel` | client_error | 404 | not_found | 54 |
| `POST /orders/{id}/cancel` | client_error | 409 | conflict | 47 |
| `GET /orders/{id}` | server_error | 500 | simulated_failure | 45 |
| `POST /orders/{id}/cancel` | server_error | 500 | simulated_failure | 22 |

**Ninguna fila debe tener `error_type = unhandled_exception`**: eso sería un
defecto real del backend, y no hubo ninguno. Los tres `simulated_failure` suman
130, el fallo inyectado por `FAILURE_RATE = 0.02`.

Los 54 `404` de cancelación son 50 intencionales (`cancel_missing_order`) más
4 de las 5 degradaciones del pool del minuto 0.

### 2.4. Consulta 4 — Media y desviación del minuto observado

```sql
WITH
  events AS (
    SELECT timestamp
    FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
    WHERE JSON_VALUE(json_payload.message) = 'request_completed'
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
```

**Esperado: una fila.**

| Campo | Valor |
| --- | --- |
| `run_started_at` | `2026-10-16T10:56:57.356008Z` |
| `run_ended_at` | `2026-10-16T11:55:17.864529Z` |
| `requests` | **6000** |
| `avg_observed_min` | **29,0874** |
| `stddev_observed_min` | **9,7280** |
| `min_observed_min` | 0,0000 |
| `max_observed_min` | **58,3418** |

Media ≈29,09 y sigma ≈9,73 frente a los 30 y 10 del plan: **es el reescalado del
2,767 % del §4, no un error de la simulación.** Sobre el plan, los valores son
29,918 y 10,004 (CSV, columna `scheduled_min`).

### 2.5. Consulta 5a — Escenario por categoría

```sql
WITH run AS (
  SELECT MIN(timestamp) AS started_at
  FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
  WHERE JSON_VALUE(json_payload.message) = 'request_completed'
    AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')
    AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')
),
events AS (
  SELECT
    TIMESTAMP_DIFF(
      logs.timestamp, run.started_at, MILLISECOND
    ) / 60000.0 AS observed_min,
    JSON_VALUE(logs.json_payload.outcome) AS outcome,
    JSON_VALUE(logs.json_payload.category) AS category
  FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests` AS logs
  CROSS JOIN run
  WHERE JSON_VALUE(logs.json_payload.message) = 'request_completed'
    AND logs.timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')
    AND logs.timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')
)
SELECT
  IF(observed_min >= 35 AND observed_min < 45, 'scenario', 'baseline') AS time_window,
  IFNULL(category, '(sin categoría)') AS category,
  COUNT(*) AS requests,
  COUNTIF(outcome = 'client_error') AS client_errors,
  ROUND(100 * COUNTIF(outcome = 'client_error') / COUNT(*), 2) AS client_error_pct
FROM events
GROUP BY time_window, category
ORDER BY time_window, category;
```

**Esperado: 10 filas.**

| time_window | category | requests | client_errors | pct |
| --- | --- | --- | --- | --- |
| baseline | (sin categoría) | 270 | 213 | 78,89 |
| baseline | apparel | 1.048 | 29 | 2,77 |
| baseline | books | 1.175 | 44 | 3,74 |
| baseline | electronics | 1.082 | 42 | 3,88 |
| baseline | grocery | 1.137 | 42 | 3,69 |
| scenario | (sin categoría) | 85 | 73 | 85,88 |
| scenario | apparel | 278 | 15 | 5,40 |
| scenario | books | 305 | 8 | 2,62 |
| scenario | **electronics** | 298 | **18** | **6,04** |
| scenario | grocery | 322 | 8 | 2,48 |

**Cómo leer esta tabla — la fila `(sin categoría)` no es un error.** El backend
solo registra atributos de negocio que pertenecen al esquema, así que 355
eventos llegan al log sin `category`, y **casi todos son errores por
construcción**:

| Origen de los 355 sin categoría | n |
| --- | --- |
| `read_missing_order` — no hay pedido que leer | 138 |
| `create_invalid_payload` con `bad_category` (manda `furniture`) o `not_an_object` | 96 |
| `cancel_missing_order` — no hay pedido que cancelar | 50 |
| Solicitudes válidas que recibieron el `500` inyectado antes de tocar el pedido | 69 |
| Degradaciones del pool del minuto 0 | 2 |

De ahí el 78-86 % de `client_error` en esa fila: es un cubo hecho de errores.
**Consecuencia para el laboratorio:** la fila `electronics / scenario` es un
**suelo**, no el efecto total del escenario, porque 96 de los errores
intencionales de payload perdieron su categoría. El efecto completo se ve en 5b
y 5c, que no dependen de la categoría.

Comparación de `electronics`: **6,04 % dentro** frente a **3,88 % fuera** = 1,56×
sobre la tasa de `client_error` observada en los logs. Sobre la intención
registrada en el CSV —que sí conoce la categoría de cada solicitud— el ratio es
14,37 % / 7,86 % = **1,83×** (objetivo 2,00×, desviación −0,84σ).

### 2.6. Consulta 5b — Escenario minuto a minuto

```sql
WITH run AS (
  SELECT MIN(timestamp) AS started_at
  FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
  WHERE JSON_VALUE(json_payload.message) = 'request_completed'
    AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')
    AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')
),
events AS (
  SELECT
    TIMESTAMP_TRUNC(logs.timestamp, MINUTE) AS minute,
    CAST(
      FLOOR(
        TIMESTAMP_DIFF(logs.timestamp, run.started_at, MILLISECOND) / 60000.0
      ) AS INT64
    ) AS observed_min,
    TIMESTAMP_DIFF(logs.timestamp, run.started_at, MILLISECOND)
      / 60000.0 >= 35
      AND TIMESTAMP_DIFF(logs.timestamp, run.started_at, MILLISECOND)
      / 60000.0 < 45 AS in_scenario,
    JSON_VALUE(logs.json_payload.outcome) AS outcome
  FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests` AS logs
  CROSS JOIN run
  WHERE JSON_VALUE(logs.json_payload.message) = 'request_completed'
    AND logs.timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')
    AND logs.timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')
)
SELECT
  minute,
  MIN(observed_min) AS observed_min,
  LOGICAL_OR(in_scenario) AS in_scenario,
  COUNT(*) AS requests,
  COUNTIF(outcome = 'client_error') AS client_errors,
  ROUND(
    100 * COUNTIF(outcome = 'client_error') / COUNT(*), 2
  ) AS client_error_pct
FROM events
GROUP BY minute
ORDER BY minute;
```

**Esperado: ~60 filas**, con **10 marcadas `in_scenario = true`**, de `11:31` a
`11:40`.

| Agregado | requests | client_errors | pct |
| --- | --- | --- | --- |
| `in_scenario = true` (10 minutos) | 1.422 | 137 | **9,63 %** |
| resto de la corrida | 4.578 | 355 | 7,75 % |
| escalón | | | **1,24×** |

El escalón se ve, pero **diluido**: 1,24× en vez de ~2×. Hay dos razones y las
dos son de medición, no del simulador:

1. El escenario solo dobla los errores de **una** de las cuatro categorías, así
   que sobre el total de la ventana el efecto queda dividido entre ~4.
2. La ventana de 5b está desplazada hasta 1 minuto (marca minutos de reloj
   completos y la corrida empezó a las 10:56:57), e incluye 1.422 solicitudes en
   vez de las 1.288 que caen estrictamente en el intervalo observado [35,45).

### 2.7. Consulta 5c — Escenario con la ventana autocalibrada (nueva)

```sql

WITH run AS (
  SELECT
    MIN(timestamp) AS started_at,
    TIMESTAMP_DIFF(
      MAX(timestamp), MIN(timestamp), MILLISECOND
    ) / 60000.0 AS span_min
  FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
  WHERE JSON_VALUE(json_payload.message) = 'request_completed'
    AND timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')
    AND timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')
),
events AS (
  SELECT
    TIMESTAMP_DIFF(
      logs.timestamp, run.started_at, MILLISECOND
    ) / 60000.0 AS observed_min,
    run.span_min / 60.0 AS clock_factor,
    JSON_VALUE(logs.json_payload.outcome) AS outcome
  FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests` AS logs
  CROSS JOIN run
  WHERE JSON_VALUE(logs.json_payload.message) = 'request_completed'
    AND logs.timestamp >= TIMESTAMP('2026-10-16 10:56:56+00')
    AND logs.timestamp <= TIMESTAMP('2026-10-16 11:55:18+00')
)
SELECT
  IF(
    observed_min >= 35 * clock_factor
    AND observed_min < 45 * clock_factor,
    'scenario',
    'baseline'
  ) AS time_window,
  ROUND(ANY_VALUE(clock_factor), 6) AS clock_factor,
  COUNT(*) AS requests,
  COUNTIF(outcome = 'client_error') AS client_errors,
  ROUND(
    100 * COUNTIF(outcome = 'client_error') / COUNT(*), 2
  ) AS client_error_pct
FROM events
GROUP BY time_window
ORDER BY time_window;
```

**Esperado: 2 filas**, con `clock_factor ≈ 0,972363`.

| time_window | requests | client_errors | pct |
| --- | --- | --- | --- |
| scenario (observado [34,03 , 43,76)) | 1.406 | 136 | **9,67 %** |
| baseline | 4.594 | 356 | 7,75 % |

Esta consulta es la que hay que citar como evidencia del escenario en Log
Analytics: no depende de que la categoría sobreviviera al payload roto ni del
desvío de reloj.

### 2.8. Consulta 6 — Trazabilidad por `X-Request-ID`

```sql
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
  AND JSON_VALUE(json_payload.request_id) = 'sim-cc4f0755-000070'
ORDER BY
  timestamp;
```

**Esperado: exactamente 1 fila** con `status_code = 409`,
`outcome = client_error`, `error_type = conflict`, `endpoint = POST
/orders/{id}/cancel`. Es la secuencia imposible del laboratorio: cancelar un
pedido ya cancelado.

Identificadores para repetir la traza con cada código:

| `request_id` | Qué demuestra | status |
| --- | --- | --- |
| `sim-cc4f0755-000000` | creación válida | 201 |
| `sim-cc4f0755-000006` | payload inválido | 400 |
| `sim-cc4f0755-000039` | identificador inexistente | 404 |
| `sim-cc4f0755-000070` | secuencia imposible | 409 |
| `sim-cc4f0755-000120` | fallo inyectado por el backend | 500 |
| `sim-cc4f0755-000003` | degradación del pool (minuto 0) | 404 |

Para cerrar el puente con el plan, buscar el mismo `request_id` en
`outputs/simulator/requests.csv`: ahí están `scheduled_min`, `intended_event`,
`client_latency_ms` y `result`, que no viajan a Cloud Logging.

## 3. Métricas del dashboard

Todas estas cifras salen de la API de Cloud Monitoring con **alineación
explícita** sobre la ventana de la corrida (10:56–11:56 UTC).

### 3.1. Solicitudes por minuto · panel 1

`run.googleapis.com/request_count`, `ALIGN_DELTA` 60 s + `REDUCE_SUM`:

| Medida | Valor |
| --- | --- |
| Puntos | 61 |
| **Suma** | **6.001** = 6.000 de la corrida + 1 sondeo del preflight |
| Pico | **275 solicitudes/min** a las `11:30` |
| Media | 98,4 solicitudes/min |
| Primeros / últimos minutos | 0, 8, 6 … 9, 3, 11 |

Cuadra con el CSV al dígito. El pico de la métrica nativa (275 a las 11:30) y el
del log (280 a las 11:29) difieren porque una cuenta en el borde del proxy y la
otra al cerrar la petición.

### 3.2. Latencia p50/p95 · panel 2

`run.googleapis.com/request_latencies`, `ALIGN_PERCENTILE_*` sobre la hora:

| Percentil | Cloud Run | Función (log) | Cliente (CSV) |
| --- | --- | --- | --- |
| p50 | **5,06 ms** | 0,187 ms | **81,2 ms** |
| p95 | **9,62 ms** | 0,376 ms | **192,8 ms** |
| p99 | 11,22 ms | — | 222,5 ms |

Las tres miden tramos distintos del mismo viaje y **el dashboard las separa a
propósito**: dentro de `handle` (0,19 ms), dentro de la plataforma (5,06 ms) y
desde el portátil con internet y TLS por medio (81,2 ms). El p50 del cliente es
~16× el de Cloud Run y ~434× el de la función: el experimento mide sobre todo
red.

### 3.3. Instancias activas · panel 3

`run.googleapis.com/container/instance_count`, `ALIGN_MAX`:
**máximo 1 `active` y 1 `idle`.**

Es el resultado correcto para `max_instances = 1`, y el coste aceptado de esa
decisión: **el panel de escalado es plano y el laboratorio no puede demostrar
escalamiento horizontal**. Con 275 solicitudes/min de pico y 5 ms de servicio, una
instancia trabajó al ~2 % de su capacidad.

### 3.4. Errores por outcome · panel 4

`cloudpulse_requests_by_outcome` (métrica basada en logs), `ALIGN_DELTA` 60 s +
`REDUCE_SUM`:

| outcome | Métrica | CSV/logs |
| --- | --- | --- |
| `success` | — | 5.378 |
| `client_error` | — | 492 |
| `server_error` | — | 130 |
| **Total** | **6.002** | **6.001** (6.000 + sondeo) |

`cloudpulse_client_errors`: 493 (`400` 253, `404` 193, `409` 47) — exacto
contando el sondeo. `cloudpulse_server_errors`: 130, todos
`simulated_failure` — exacto. `cloudpulse_order_amount`: 12 segmentos
`(category, tier)`, importe medio ≈254.

> ⚠️ **Cómo leer las métricas basadas en logs sin equivocarse.** Con
> `alignmentPeriod = 60s` la suma es 6.002 (verdad 6.001). Con
> `alignmentPeriod = 3600s` sube a **6.037 (+0,6 %)**: el bucket de una hora
> asigna puntos enteros de 60 s a un lado u otro del borde. Es un artefacto de
> agregación, no de los datos — demostrado comparando las dos alineaciones. Para
> cifras exactas, los logs; para tendencias, el dashboard.

### 3.5. Contraste global

| Medida | CSV | Cloud Logging | Métricas | ¿Cuadra? |
| --- | --- | --- | --- | --- |
| Solicitudes | 6.000 | 6.000 | 6.001 (+sondeo) | ✅ |
| 2xx | 5.378 | 5.378 | — | ✅ |
| 4xx | 492 | 492 | 493 (+sondeo) | ✅ |
| 5xx | 130 | 130 | 130 | ✅ |
| Sin respuesta | 0 | — | — | ✅ |
| `401`/`403` | 0 | 0 | **0** | ✅ |
| `unhandled_exception` | — | 0 | 0 | ✅ |
| Media del minuto | 29,918 (plan) | 29,087 (observado) | — | ✅ §4 |
| Desviación | 10,004 (plan) | 9,728 (observado) | — | ✅ §4 |

## 4. La desviación de duración (58 min 21 s frente a 60 min)

**No se ha corregido ningún resultado por este motivo.** Lo que sigue documenta
la desviación y cómo afecta a cada cifra.

| Dato | Valor |
| --- | --- |
| Duración planificada | 3.600 s (60 min) |
| Duración real | **3.501 s (58 min 21 s)** |
| Déficit | 99 s (2,75 %) |
| Pendiente del desfase | **−1,6602 s por minuto planificado** |
| Desvío de reloj implícito | **2,767 %** |
| Intercepto / residuo máximo | 0,196 s / 485 ms |

Causa: el despachador se temporiza con `CLOCK_MONOTONIC` y la columna
`scheduled_at` se calcula con el reloj de pared. En WSL2 los dos relojes
avanzaron a ritmos distintos durante la hora. La linealidad casi perfecta
(residuo ≤485 ms sobre 3.500 s) descarta que sea congestión, cola o latencia.

**Qué queda intacto:** la forma de la distribución. Ratios observado/planificado:
media 0,9724 y desviación 0,9723 — coinciden en la cuarta cifra, así que el eje
se reescaló sin deformarse. Las 6.000 solicitudes, los 6.000 eventos, los
códigos de respuesta, la proporción de errores y el escenario no dependen del
reloj.

**Qué sí hay que tener en cuenta al validar:**

1. `avg_observed_min` ≈ 29,09 y `stddev_observed_min` ≈ 9,73 en Log Analytics
   son **correctos**; los 30 y 10 del plan se leen en el CSV (`scheduled_min`:
   29,918 y 10,004).
2. La ventana del escenario [35,45) del plan cae en el tiempo observado en
   [34,03 , 43,76): usar los bordes literales desplaza la ventana ~1 minuto.
   La consulta 5c lo compensa autocalibrando el factor.
3. `scheduled_at` del CSV arrastra el desvío (hasta −99,5 s en las últimas
   filas). **Para análisis temporal, `sent_at` es la verdad y `scheduled_min` es
   el plan.**

Mitigación futura (no aplicada): temporizar el despachador contra el reloj de
pared, o medir el desvío antes de la corrida y compensarlo.

## 5. Checklist de capturas de pantalla

Evidencia mínima para demostrar el cumplimiento del laboratorio. Cada captura
debe incluir la barra de URL o el nombre del proyecto visible.

### Dashboard de Cloud Monitoring

- [ ] **C1 — Dashboard completo**, los 8 tiles, rango de tiempo fijado a
  `2026-10-16 10:56–11:56 UTC`. Demuestra «un solo dashboard» con métricas
  nativas, métrica basada en logs, SQL y panel de logs.
- [ ] **C2 — Panel 1, solicitudes por minuto**: campana con el pico de ~275 en
  `11:30`.
- [ ] **C3 — Panel 2, latencia p50/p95**: p50 ≈5 ms y p95 ≈10 ms.
- [ ] **C4 — Panel 3, instancias activas**: línea plana en 1 (con la nota de que
  es consecuencia de `max_instances = 1`).
- [ ] **C5 — Panel 4, errores por outcome**: `client_error` ≈492 y
  `server_error` 130 con sus etiquetas `endpoint`/`error_type`.
- [ ] **C6 — Paneles 5a y 5b (SQL de Log Analytics incrustado)** con datos.
- [ ] **C7 — Panel 6, logs** con `severity >= WARNING`: deben verse eventos
  `request_completed` con `WARNING` (4xx) y `ERROR` (5xx).

### Log Analytics (una captura por consulta)

- [ ] **C8 — Consulta 1**: 60 filas, suma 6.000, pico 280 en `11:29`.
- [ ] **C9 — Consulta 2**: tres outcomes con 5.378 / 492 / 130.
- [ ] **C10 — Consulta 3**: 7 filas de error, sin `unhandled_exception`.
- [ ] **C11 — Consulta 4**: `requests = 6000`, `avg ≈ 29,09`, `stddev ≈ 9,73`.
- [ ] **C12 — Consulta 5a**: 10 filas, `electronics/scenario` al 6,04 %.
- [ ] **C13 — Consulta 5b**: 10 minutos `in_scenario = true`, 9,63 % frente a
  7,75 %.
- [ ] **C14 — Consulta 5c**: `clock_factor ≈ 0,9724`, escenario 9,67 % frente a
  7,75 %.
- [ ] **C15 — Consulta 6**: la fila única de `sim-cc4f0755-000070` con `409`.

### Infraestructura y trazabilidad

- [ ] **C16 — `gcloud logging metrics list`**: las cuatro métricas
  `cloudpulse_*`.
- [ ] **C17 — Bucket `cloudpulse-logs`** con Log Analytics habilitado y la vista
  `cloudpulse_requests` con su filtro.
- [ ] **C18 — La función en Cloud Run**: `ACTIVE`, `python313`, 512Mi,
  `max_instances = 1`, **y la política IAM sin `allUsers`** (prueba de que el
  experimento corrió contra una función privada).
- [ ] **C19 — Terminal con el resumen de la corrida**: las 6.000 solicitudes,
  `as_expected 5870`, `server_error 130`, `transport errors 0`, p50/p95.
- [ ] **C20 — Trazabilidad de punta a punta**: una fila de
  `outputs/simulator/requests.csv` y el evento de Cloud Logging con el **mismo
  `X-Request-ID`**, lado a lado.

## 6. Requisitos pendientes de validación manual

| # | Pendiente | Por qué no lo pude hacer |
| --- | --- | --- |
| M1 | **Ejecutar las 8 consultas en la consola** de Log Analytics y comparar con los valores esperados de §2 | No hay *linked dataset* de BigQuery, y `gcloud logging` no tiene subcomando de analytics. Crear el dataset es infraestructura nueva |
| M2 | **Confirmar que Log Analytics acepta `APPROX_QUANTILES` y la función de ventana** de la consulta 2 | Solo se puede comprobar ejecutándola; hay variante de respaldo en §2.2 |
| M3 | **Las 20 capturas** de §5 | No hay forma de capturar pantalla desde la CLI |
| M4 | **Ver los paneles 5a/5b del dashboard renderizados** | Mismo motivo; los datos que consumen sí están verificados |
| M5 | **Lectura del presupuesto** de facturación | Permisos o API `billingbudgets`; el tope real de gasto son `max_instances = 1` y la concurrencia |

Lo que **sí** está verificado sin la consola: que los 6.000 eventos están en el
bucket de analytics y visibles a través de la vista (6.000 `insertId` únicos
leídos con `--bucket`/`--view`), que las siete métricas del dashboard tienen
datos, y que los valores esperados de cada consulta están calculados sobre esos
mismos 6.000 eventos.
