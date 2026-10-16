# CloudPulse — Observabilidad (fase 4)

Define las métricas, las consultas SQL y el dashboard del laboratorio **sin desplegar nada**. Todo lo que hay aquí es declarativo o documental: no se ejecutó `terraform apply`, no se creó ningún dashboard, no se habilitó ningún servicio y no se generó tráfico.

## 1. Estado del que parte esta fase

Verificado al inicio, no asumido:

| Comprobación | Resultado |
| --- | --- |
| Pruebas del repositorio | 226 / 226 (`uv run python -m pytest tests/`) |
| Fase 1 — backend | Entregada. `backend/main.py` emite un evento `request_completed` por petición. |
| Fase 2 — simulador | Entregada. `simulator/simulator.py` + `simulator/config.json`. |
| Fase 3 — infraestructura | **No entregada.** `infra/main.tf` estaba vacío y sigue vacío. |
| Servicios habilitados en `cloudpulse-lab-2026` | `logging`, `monitoring`, `bigquery`, `storage`… **`run.googleapis.com` NO está habilitado.** |
| Dashboards existentes en el proyecto | Ninguno. |

Consecuencia directa: la fase 4 entrega **definiciones**, no recursos. Nada de esto puede aplicarse hasta que la fase 3 provisione los servicios, la cuenta de servicio y la Cloud Run function.

Esta fase sí añadió a `infra/` el andamiaje mínimo que las definiciones de observabilidad necesitan para poder validarse: `versions.tf` (requisitos de Terraform y provider) y `variables.tf` (las nueve variables que ya estaban en `terraform.tfvars` sin declarar, más las nuevas de observabilidad). Sin ellos `terraform validate` no puede ejecutarse. `main.tf` sigue vacío: los recursos de cómputo son de la fase 3.

## 2. El orden importa

Una métrica basada en logs **solo cuenta entradas ingeridas después de su creación**. No hay backfill. El orden obligatorio es:

```text
fase 3: apply de servicios + función        →  la API existe y escribe logs
fase 4: apply de logging.tf y monitoring.tf →  bucket, sink, vista, 4 métricas, dashboard
         ↓  (esperar a que las métricas aparezcan en Cloud Monitoring)
fase 5: simulador, 6.000 peticiones / 60 min
```

Lanzar el simulador antes del `apply` de la fase 4 significa repetir —y pagar— la corrida de 60 minutos.

## 3. Superficie de análisis

`infra/logging.tf` crea tres recursos encadenados:

| Recurso | Terraform | Para qué |
| --- | --- | --- |
| Bucket regional `cloudpulse-logs` | `google_logging_project_bucket_config.cloudpulse` | `enable_analytics = true`: es lo que hace los logs consultables con SQL. Log Analytics exige bucket **regional**, por eso `region` valida que no sea `global`. |
| Sink `cloudpulse-orders-api` | `google_logging_project_sink.cloudpulse` | Enruta los logs de la función al bucket. |
| Vista `cloudpulse_requests` | `google_logging_log_view.cloudpulse_requests` | Restringe la vista a `jsonPayload.message="request_completed"`. Es la superficie que consultan las SQL. |

Dos advertencias reales:

- **El sink es aditivo.** El sink `_Default` sigue escribiendo las mismas entradas en el bucket `_Default`, así que cada entrada se ingiere dos veces. A escala del laboratorio (~6.000 entradas pequeñas) es despreciable frente al nivel gratuito, pero no es cero. Mantener el `_Default` es deliberado: el panel 6 del dashboard y la consola leen de ahí.
- **Observability Analytics no se puede desactivar.** Una vez que un bucket de logs se actualiza para usar Observability Analytics, **no puede degradarse** para quitar esa capacidad.

## 4. Métricas basadas en logs

Cuatro definiciones en `infra/logging.tf`. Todas filtran sobre los campos reales que escribe `backend/main.py`.

Sobre el esquema: Cloud Run parsea el JSON de stdout a `jsonPayload` y **eleva `severity` al nivel de la entrada**. Por eso los filtros usan `severity` suelto y nunca `jsonPayload.severity`, que no existe.

| # | Métrica | Tipo | Filtro | Etiquetas |
| --- | --- | --- | --- | --- |
| 1 | `cloudpulse_requests_by_outcome` | DELTA / INT64 | evento `request_completed` del servicio | `outcome`, `endpoint` |
| 2 | `cloudpulse_client_errors` | DELTA / INT64 | `+ jsonPayload.outcome="client_error"` | `endpoint`, `status_code`, `error_type` |
| 3 | `cloudpulse_server_errors` | DELTA / INT64 | `+ jsonPayload.outcome="server_error"` | `endpoint`, `error_type` |
| 4 | `cloudpulse_order_amount` | DELTA / DISTRIBUTION | `+ endpoint="POST /orders" AND status_code=201` | `category`, `customer_tier` |

Filtro base compartido, construido con `join(" AND ", ...)` en el `locals` del archivo:

```text
resource.type="cloud_run_revision"
AND resource.labels.service_name="orders-api"
AND jsonPayload.message="request_completed"
```

Decisiones que no son obvias:

- **`endpoint` como etiqueta es seguro.** El backend guarda la plantilla de ruta (`GET /orders/{id}`), nunca el id concreto, así que la cardinalidad son tres endpoints más `unknown`.
- **`status_code` solo en la métrica de errores de cliente.** Es lo que separa un 400 de validación de un 404 de pedido inexistente y de un 409 por cancelar dos veces.
- **`error_type` en la de servidor.** Separa el `simulated_failure` inyectado por `FAILURE_RATE` de un `unhandled_exception`, que sería un defecto real. Esa distinción es la única forma de saber si un 500 del dashboard es parte del experimento o un bug.
- **El histograma de `amount` se restringe a creaciones exitosas.** `amount` también viaja en los eventos de lectura y de cancelación, porque se copia del pedido almacenado. Contar toda entrada que lleve el campo pesaría un mismo pedido tantas veces como se le toque. El filtro `status_code=201` deja exactamente una muestra por pedido creado.
- **Buckets lineales, no exponenciales.** El simulador extrae `amount` de una uniforme en `[5, 500]` (`MIN_AMOUNT`/`MAX_AMOUNT` en `simulator/simulator.py`). 20 buckets de ancho 25 cubren `[0, 500]` con resolución uniforme, que es la forma informativa de histogramar una uniforme. La API acepta hasta 100.000; esos valores caerían en el bucket de desborde.
- **`amount` es un número JSON en el evento**, así que `EXTRACT(jsonPayload.amount)` lo toma directamente, sin regex.

Lo que estas métricas **no** cubren: la latencia. El evento lleva `latency_ms`, pero p50 y p95 se toman de la métrica nativa (sección 5), que mide desde el borde de Cloud Run. Si más adelante interesa comparar las dos mediciones, haría falta una quinta métrica de distribución sobre `jsonPayload.latency_ms`; no se ha definido porque el laboratorio pide las latencias de las métricas nativas.

## 5. Métricas nativas

**Verificadas contra la API de Cloud Monitoring del proyecto real** (`projects/cloudpulse-lab-2026/metricDescriptors`, filtrando `run.googleapis.com/`: 49 descriptores devueltos). No son nombres recordados.

| Panel | Metric type | Kind | Value | Unit | Recursos monitorizados | Etiquetas |
| --- | --- | --- | --- | --- | --- | --- |
| Solicitudes/min | `run.googleapis.com/request_count` | DELTA | INT64 | `1` | `cloud_run_instance`, `cloud_run_revision` | `response_code`, `response_code_class`, `route` |
| Latencia p50/p95 | `run.googleapis.com/request_latencies` | DELTA | DISTRIBUTION | `ms` | `cloud_run_instance`, `cloud_run_revision` | `response_code`, `response_code_class`, `route` |
| Instancias | `run.googleapis.com/container/instance_count` | GAUGE | INT64 | `1` | `cloud_run_instance`, `cloud_run_revision`, `cloud_run_worker_pool` | `state` (`active` / `idle`) |

Las tres son GA, con `samplePeriod` 60 s e `ingestDelay` 120 s. Una Cloud Run function de 2.ª generación se ejecuta sobre Cloud Run, así que el recurso correcto es `cloud_run_revision` y estas son las métricas nativas aplicables.

**Hallazgo que condiciona el diseño:** el descriptor de `request_count` documenta la etiqueta `route` como *"Always empty."* No se puede desglosar el tráfico nativo por endpoint. Ese desglose solo existe en las métricas basadas en logs, vía `jsonPayload.endpoint`. Es la razón concreta por la que el dashboard necesita las dos familias de métricas y no solo las nativas.

Segundo límite: `request_latencies` mide desde que la petición llega al contenedor en marcha hasta que sale, y **no incluye el cold start**. El `latency_ms` del evento de log se mide dentro de `handle`, y el `client_latency_ms` del CSV incluye red y cold start. Son tres mediciones distintas del mismo viaje; no son comparables directamente.

### PromQL

Todas las consultas pasaron el linter de la skill `cloud-monitoring-promql-query` (14 consultas, 0 errores). Los dos avisos sobre `container_instance_count` son falsos positivos: el linter infiere "contador" del sufijo `_count`, pero el descriptor dice GAUGE, así que no debe envolverse en `rate()`.

```promql
sum(rate(run_googleapis_com:request_count{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) * 60
```

```promql
histogram_quantile(0.50, sum(rate(run_googleapis_com:request_latencies_bucket{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) by (le))
```

```promql
histogram_quantile(0.95, sum(rate(run_googleapis_com:request_latencies_bucket{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) by (le))
```

```promql
sum(run_googleapis_com:container_instance_count{monitored_resource="cloud_run_revision",service_name="orders-api"}) by (state)
```

```promql
sum(rate(logging_googleapis_com:user_cloudpulse_requests_by_outcome{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) by (outcome) * 60
```

Notas de traducción:

- `rate()` da un valor por segundo; el `* 60` lo convierte en peticiones por minuto, que es la unidad del laboratorio. La unidad declarada en el widget es `1/min`.
- La ventana `[5m]` es el mínimo seguro para métricas de 60 s de muestreo (al menos dos muestras consecutivas). Suaviza la curva: el recuento por minuto exacto lo da la SQL del panel 5b, no esta serie.
- En `histogram_quantile(..., rate(...))` la unidad de salida es la del bucket (`ms`), no una tasa.

Otras consultas validadas y disponibles, aunque no estén en el dashboard:

```promql
sum(rate(run_googleapis_com:request_count{monitored_resource="cloud_run_revision",service_name="orders-api",response_code_class="5xx"}[5m])) * 60
```

```promql
sum(rate(logging_googleapis_com:user_cloudpulse_client_errors{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) by (endpoint) * 60
```

```promql
sum(rate(logging_googleapis_com:user_cloudpulse_server_errors{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) by (error_type) * 60
```

```promql
histogram_quantile(0.95, sum(rate(logging_googleapis_com:user_cloudpulse_order_amount_bucket{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) by (le, category))
```

Media de una métrica de distribución: en PromQL hay que dividir las series `_sum` y `_count`; `avg()` sobre el nombre base no da la media de la distribución.

```promql
sum(rate(logging_googleapis_com:user_cloudpulse_order_amount_sum{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m])) / sum(rate(logging_googleapis_com:user_cloudpulse_order_amount_count{monitored_resource="cloud_run_revision",service_name="orders-api"}[5m]))
```

## 6. Log Analytics SQL

Las consultas están en **`docs/log-analytics-queries.sql`**, con comentarios. Leen la vista que crea Terraform:

```sql
FROM `cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests`
```

El formato de la cláusula `FROM` de una vista de logs es `PROJECT_ID.LOCATION.BUCKET_ID.LOG_VIEW_ID`; `terraform output log_analytics_from_clause` devuelve el valor ya montado.

| # | Consulta | Qué devuelve |
| --- | --- | --- |
| 1 | Solicitudes por minuto | Una fila por minuto. Alimenta el panel 5b. |
| 2 | Solicitudes por `outcome` | Reparto global, con media y p95 de `latency_ms`. |
| 3 | Errores por endpoint | Una fila por `endpoint` × `outcome` × `status_code` × `error_type`. |
| 4 | AVG y STDDEV del minuto de llegada **observado** | Una fila: `requests`, `avg_observed_min`, `stddev_observed_min`, mínimo y máximo. |
| 5a | Errores por categoría, dentro y fuera de la ventana | Compara `[35, 45)` con el resto, por categoría. |
| 5b | Tasa de `client_error` minuto a minuto | Ve el escalón sin depender de la categoría. |
| 6 | Correlación por `request_id` | Puente manual con `outputs/simulator/requests.csv`. |

Acceso a campos, conforme al esquema de Log Analytics: `resource.labels` y `json_payload` son columnas **JSON**, así que hay que usar `JSON_VALUE(...)`; `resource.type`, `timestamp` y `severity` son columnas escalares y se comparan directamente. `JSON_VALUE` devuelve texto, por lo que los números necesitan `SAFE_CAST(... AS FLOAT64 | INT64)`.

### El tiempo programado no está en Cloud Logging

Esto condiciona las consultas 4, 5a y 5b, y hay que decirlo sin ambigüedad:

**El minuto programado del simulador no se puede reconstruir con SQL.** El simulador deriva `scheduled_min` de una normal `N(mu=30, sigma=10)` y lo escribe en `outputs/simulator/requests.csv`. Ese valor no viaja en la petición: el backend no lo recibe y no lo registra. En Cloud Logging solo existe `timestamp`, el instante real del evento.

Lo que las consultas sí calculan es el **minuto de llegada observado**, como distancia al primer evento de la corrida. Las dos series difieren por tres razones concretas:

1. La latencia entre el envío programado y el momento en que la función escribe el log.
2. El plan trunca los instantes al intervalo `[0, 60]` con `clip` en lugar de descartarlos, lo que acumula ~0,13 % del tráfico en cada extremo y reduce ligeramente la sigma observada.
3. El primer evento observado no es exactamente el minuto 0 del plan, así que el origen está desplazado.

Para comparar contra el plan hay que cruzar `request_id` entre el CSV y `json_payload.request_id`. Eso es un join entre dos sistemas distintos y se hace fuera de Log Analytics; la consulta 6 es el lado de los logs de ese cruce.

### El escenario de errores y la categoría perdida

El escenario de `simulator/config.json` duplica la proporción de errores intencionales para `electronics` entre los minutos 35 y 45. Dos de las seis variantes de payload inválido —`bad_category`, que envía `"furniture"`, y `not_an_object`— impiden que el backend registre `category`, porque `record_submitted` solo guarda valores que pertenecen al esquema. Esos errores llegan al log con `category` nula y **no se atribuyen a `electronics`**.

Por eso hay dos consultas: la 5a desglosa por categoría (la fila `electronics` es un suelo, no el total) y la 5b mide la tasa global de `client_error` minuto a minuto, que ve el escalón sin depender de que la categoría haya sobrevivido al payload roto.

## 7. Dashboard

Un único dashboard, declarado en `infra/monitoring.tf` a partir de la plantilla `infra/dashboards/orders-api.json.tftpl`. La plantilla se renderiza con `templatefile()`, así que renombrar la función en `terraform.tfvars` reapunta todas las gráficas a la vez.

`mosaicLayout` de 12 columnas, 8 tiles:

| Tile | Posición | Panel del laboratorio | Widget | Fuente de datos |
| --- | --- | --- | --- | --- |
| 0 | `0,0` 12×2 | — | `text` (MARKDOWN) | Texto fijo: cómo leer el dashboard y la advertencia sobre el tiempo programado. |
| 1 | `0,2` 6×4 | **1.** Solicitudes por minuto | `xyChart` LINE | `prometheusQuery` → `run.googleapis.com/request_count` |
| 2 | `6,2` 6×4 | **2.** Latencia p50 y p95 | `xyChart` LINE ×2 | `prometheusQuery` → `run.googleapis.com/request_latencies` |
| 3 | `0,6` 6×4 | **3.** Instancias activas | `xyChart` STACKED_AREA | `prometheusQuery` → `run.googleapis.com/container/instance_count` por `state` |
| 4 | `6,6` 6×4 | **4.** Errores por `outcome` | `xyChart` STACKED_AREA | `prometheusQuery` → `logging.googleapis.com/user/cloudpulse_requests_by_outcome` por `outcome` |
| 5 | `0,10` 6×4 | **5.** Media y desviación | `timeSeriesTable` NUMBER | `opsAnalyticsQuery` (SQL de Log Analytics, consulta 4) |
| 6 | `6,10` 6×4 | **5.** (visualización) | `xyChart` STACKED_BAR | `opsAnalyticsQuery` (SQL de Log Analytics, consulta 1) |
| 7 | `0,14` 12×5 | **6.** Panel de logs | `logsPanel` | `severity>=WARNING` sobre `projects/cloudpulse-lab-2026` |

El panel 5 son dos tiles porque la media y la desviación son dos escalares, no una serie temporal: el tile 5 los da como números y el tile 6 dibuja la curva de llegadas de la que salen. Entre los dos cubren el requisito y hacen legible si la distribución observada se parece a la normal del plan.

Las cuatro familias de fuentes que pedía el laboratorio están presentes: métricas nativas (tiles 1-3), métrica basada en logs (tile 4), SQL de Log Analytics (tiles 5-6) y panel de logs (tile 7).

El tile 3 grafica `active` **e** `idle`, no solo `active`. La etiqueta `state` del descriptor tiene esos dos valores y verlos juntos es lo que muestra el escalado: una instancia que pasa a `idle` sigue facturando hasta que se recicla. Para ver solo las activas:

```promql
sum(run_googleapis_com:container_instance_count{monitored_resource="cloud_run_revision",service_name="orders-api",state="active"})
```

`google_monitoring_dashboard` lleva un `depends_on` explícito sobre la métrica basada en logs y la vista: las gráficas las resuelven por nombre, que no es una referencia de Terraform, así que sin el `depends_on` el dashboard puede crearse antes de que exista el descriptor y el panel 4 renderiza vacío hasta el siguiente refresco.

### Nada de esto requiere pasos manuales

Los ocho tiles —incluidos el panel de logs y las dos gráficas SQL— se declaran por completo en el JSON del dashboard: `logsPanel` y `opsAnalyticsQuery` son campos del recurso `Dashboard` de la API v1 de Cloud Monitoring, y `google_monitoring_dashboard` acepta ese JSON entero. **No hay ningún componente que haya que crear a mano en la consola.**

Lo que sí es manual es el bucket de logs si se prefiere no usar Terraform; la sección 8 recoge el procedimiento equivalente.

## 8. Procedimiento manual equivalente

Alternativa a `terraform apply`, con la sintaxis de cada comando verificada con `gcloud help <comando>`. **Ninguno se ha ejecutado.**

Orden: bucket → sink → vista → métricas → dashboard.

```bash
# 1. Bucket regional con Observability Analytics.
#    Advertencia: una vez habilitado, NO se puede degradar para quitarlo.
gcloud logging buckets create cloudpulse-logs \
    --project=cloudpulse-lab-2026 \
    --location=us-central1 \
    --retention-days=30 \
    --description="CloudPulse orders API logs, queryable with Log Analytics SQL." \
    --enable-analytics
```

```bash
# 2. Sink hacia el bucket. Esto empieza a facturar almacenamiento.
gcloud logging sinks create cloudpulse-orders-api \
    projects/cloudpulse-lab-2026/locations/us-central1/buckets/cloudpulse-logs \
    --project=cloudpulse-lab-2026 \
    --log-filter='resource.type="cloud_run_revision" AND resource.labels.service_name="orders-api"' \
    --description="Routes orders API logs to the Log Analytics bucket."
```

```bash
# 3. Vista que consultan las SQL.
gcloud logging views create cloudpulse_requests \
    --project=cloudpulse-lab-2026 \
    --bucket=cloudpulse-logs \
    --location=us-central1 \
    --log-filter='jsonPayload.message="request_completed"' \
    --description="One row per completed request of the orders API."
```

Las métricas 1 a 3 llevan etiquetas y la 4 es una distribución, así que ninguna entra en la forma simple de `--log-filter`. Hay que usar `--config-from-file`, cuyo contenido es el recurso `LogMetric` en YAML o JSON:

```bash
# 4. Métricas basadas en logs. Crear ANTES de lanzar el simulador.
gcloud logging metrics create cloudpulse_requests_by_outcome \
    --project=cloudpulse-lab-2026 \
    --config-from-file=metric_requests_by_outcome.yaml
```

```yaml
# metric_requests_by_outcome.yaml
name: cloudpulse_requests_by_outcome
description: Completed requests of the orders API, labelled by outcome and endpoint.
filter: >-
  resource.type="cloud_run_revision" AND
  resource.labels.service_name="orders-api" AND
  jsonPayload.message="request_completed"
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
  unit: "1"
  displayName: CloudPulse requests by outcome
  labels:
    - key: outcome
      valueType: STRING
    - key: endpoint
      valueType: STRING
labelExtractors:
  outcome: EXTRACT(jsonPayload.outcome)
  endpoint: EXTRACT(jsonPayload.endpoint)
```

Las otras tres se escriben igual, copiando `filter`, `metric_descriptor`, `label_extractors` y —en la cuarta— `value_extractor` y `bucket_options` desde `infra/logging.tf`.

```bash
# 5. Dashboard, con el JSON ya renderizado.
gcloud monitoring dashboards create \
    --project=cloudpulse-lab-2026 \
    --config-from-file=orders-api.json
```

Validarlo sin guardarlo (lo que se hizo en esta fase):

```bash
gcloud monitoring dashboards create --validate-only \
    --project=cloudpulse-lab-2026 \
    --config-from-file=orders-api.json
```

Crear métricas basadas en logs y enrutar logs a un bucket son operaciones que **generan facturación**. Pedir confirmación explícita antes de ejecutarlas.

## 9. Validaciones ejecutadas

Lo que se comprobó de verdad, con el comando y el resultado:

| Qué | Cómo | Resultado |
| --- | --- | --- |
| Pruebas del repositorio | `uv run python -m pytest tests/` | 226 / 226 |
| Formato de Terraform | `terraform -chdir=infra fmt -check -recursive` | Sin cambios pendientes |
| Sintaxis de Terraform | `terraform -chdir=infra validate` | `Success! The configuration is valid.` |
| Esquema del provider | `terraform providers schema -json` | Confirmados `enable_analytics`, `bucket_options`, `label_extractors`, `value_extractor`, `metric_descriptor.labels`, `dashboard_json` |
| Tipos de métrica nativos | API de Cloud Monitoring del proyecto, `metricDescriptors?filter=starts_with("run.googleapis.com/")` | 49 descriptores; confirmados kind, value type, unidad, recursos y etiquetas de los tres usados |
| Etiquetas del recurso | API `monitoredResourceDescriptors/cloud_run_revision` | `project_id`, `service_name`, `revision_name`, `location`, `configuration_name` |
| PromQL | Linter de `cloud-monitoring-promql-query` | 14 / 14 válidas (2 avisos falsos positivos, explicados en §5) |
| Widgets | Scripts `compute_labels` / `assemble_widget_proto` / `validate_chart` de `cloud-monitoring-chart-generation` | 3 textprotos generados y validados |
| Esquema del dashboard | Documento de descubrimiento de `monitoring` v1 | Confirmados `opsAnalyticsQuery.sql`, `logsPanel.filter`, `mosaicLayout.tiles`, `Dimension`, `Measure`, `timeSeriesTable` |
| Dashboard renderizado | `templatefile()` vía `terraform console`, y después `gcloud monitoring dashboards create --validate-only` | Aceptado por el servidor. `gcloud monitoring dashboards list` → vacío: **no se creó nada** |
| Filtros LQL | `gcloud logging read "<filtro>" --limit=1` sobre los 7 filtros | Los 7 parsean. 0 entradas, que es lo esperado sin despliegue. Un filtro roto a propósito devolvió `Unparseable filter`, así que la prueba discrimina |
| Sintaxis SQL | Dry run de BigQuery (`dryRun: true`) sobre las 7 sentencias, con la vista sustituida por una tabla stub de los mismos tipos | 7 / 7 válidas |
| Coherencia filtros ↔ campos JSON | Revisión campo a campo contra `backend/main.py` y `tests/test_observability.py` | Los 13 campos del evento están cubiertos o justificados |

Sobre la última fila: el evento emite `severity`, `message`, `request_id`, `endpoint`, `status_code`, `outcome`, `error_type`, `latency_ms`, `customer_tier`, `category`, `amount`, `order_id`, `order_status`, y `exception_type` solo cuando hay un fallo no controlado. `severity` se filtra a nivel de entrada (panel 6); `message` identifica el evento; `outcome`, `endpoint`, `status_code`, `error_type`, `amount`, `category` y `customer_tier` son filtro o etiqueta de alguna métrica; `request_id`, `latency_ms`, `order_id` y `order_status` se consultan por SQL. `exception_type` no se usa en ninguna definición: aparecería en el panel de logs, que es donde interesa leerlo.

## 10. Pendiente de verificar con datos reales

Nada de lo siguiente se puede comprobar sin despliegue, y por tanto sigue abierto:

1. **Que `apply` funcione.** No se ha ejecutado `terraform plan` ni `apply`. `validate` comprueba sintaxis y tipos, no que la API acepte cada recurso. Además `run.googleapis.com` no está habilitado, así que el `apply` de la fase 4 no puede preceder al de la fase 3.
2. **Que los extractores extraigan.** `EXTRACT(jsonPayload.outcome)` y compañía no tienen validación previa en la API de Logging. Solo una petición real contra la función desplegada demuestra que las etiquetas se pueblan y que el histograma de `amount` recibe valores numéricos.
3. **Que las SQL devuelvan filas.** El dry run de BigQuery valida la gramática y los tipos con una tabla sustituta; no demuestra que la vista de Log Analytics exponga esas columnas con esos nombres ni que haya datos.
4. **Que los paneles pinten.** `--validate-only` acepta el JSON; no garantiza que cada serie resuelva. En particular el panel 4 depende de que el descriptor de la métrica basada en logs ya exista, y las nativas tienen 120 s de `ingestDelay`.
5. **Media y desviación observadas.** No hay cifras. Se conocen los parámetros del plan (`mu_min=30`, `sigma_min=10`) y se espera una sigma observada algo menor por el truncado a `[0, 60]`, pero el valor real sale de la corrida.
6. **El escalón de errores del escenario.** Está por medir cuánto del efecto se ve con categoría y cuánto se pierde en las variantes que la borran.
7. **Los 404 de fondo.** El almacén de pedidos vive en la memoria de cada instancia. Con varias instancias activas, lecturas y cancelaciones legítimas pueden responder 404 y el panel 4 los contará como `client_error`. Hay que decidir antes de la fase 5 si se fija `max_instances = 1` o si esos 404 se miden como parte del experimento. La decisión cambia cómo se lee el dashboard, no las definiciones.
8. **`outputs/reports/`** está vacío a propósito. No se ha generado ningún reporte porque no hay resultados que reportar.
