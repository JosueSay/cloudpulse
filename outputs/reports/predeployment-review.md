# CloudPulse — Auditoría previa al despliegue (fase 5)

**Fecha:** 2026-10-16
**Actualizado:** 2026-10-16 — fase 3 completada (`infra/main.tf` implementado) y
ajustes finales de predespliegue: memoria de la función a `512Mi` y `.gitignore`
endurecido para ficheros de credenciales. Secciones revisadas: veredicto, §1,
§4, §6, §7.1 y §7.2–§7.5.
**Proyecto GCP:** `cloudpulse-lab-2026` (facturación activa, `billingEnabled: true`)
**Alcance:** revisión integral del repositorio y de las validaciones ejecutables en
local, sin desplegar infraestructura ni lanzar la corrida de 6.000 solicitudes.

## Veredicto

> ## 🟢 READY — para `apply` con autorización explícita
>
> El bloqueante anterior está resuelto: `infra/main.tf` define los 19 recursos
> de cómputo que faltaban (9 `google_project_service`, 2 cuentas de servicio,
> 4 bindings IAM, bucket y objeto del código fuente, espera de propagación de
> IAM y la `google_cloudfunctions2_function` con runtime `python313` y entry
> point `handle`). `terraform plan` anuncia ahora **27 recursos a crear, 0 a
> modificar, 0 a destruir**: los 19 de cómputo más los 8 de observabilidad que
> ya existían.
>
> Las dos decisiones de diseño están tomadas y escritas en la configuración:
> `max_instances = 1` (coherencia del almacén en memoria) y
> `allow_unauthenticated = false` (sin endpoint público). Las seis variables que
> no tenían consumidor ahora lo tienen.
>
> **Nada está aplicado.** El veredicto significa «la configuración está lista
> para que alguien autorice el `apply`», no «el laboratorio está desplegado».

Queda un riesgo residual que solo el primer `apply` puede confirmar y dos
decisiones operativas que exigen autorización: ver §4.6 y §6.

Lo que ya estaba listo y verificado sigue igual: el backend, el simulador, las
226 pruebas y todas las definiciones de observabilidad (métricas, SQL y
dashboard).

## 1. Estado por componente

| Componente | Estado | Evidencia |
| --- | --- | --- |
| `backend/main.py` | ✅ Completo | 3 operaciones, 6 códigos de respuesta y el evento JSON verificados contra la función real levantada con Functions Framework (§3.1). |
| `simulator/` | ✅ Completo | Plan de 6.000 instantes, distribución, concurrencia, CSV y manejo de fallos de transporte verificados (§3.2). |
| `tests/` | ✅ Completo | 226 pruebas, 226 pasan. |
| `infra/logging.tf` | ✅ Definido, no aplicado | 7 recursos en `plan`; `validate` correcto. |
| `infra/monitoring.tf` + plantilla | ✅ Definido, no aplicado | Dashboard de 8 tiles renderizado en `plan`. |
| `infra/main.tf` | ✅ Completo | 19 recursos de cómputo en `plan`; `validate` correcto; `fmt -check` limpio (§4.2). |
| `infra/variables.tf` | ✅ Completo | 21 variables, todas con consumidor. Cinco nuevas: `min_instances`, `function_memory`, `function_timeout_s`, `allow_unauthenticated` y las validaciones de los topes (§4.3). |
| `infra/outputs.tf` | ✅ Completo | 13 outputs: 8 de cómputo (incluida `function_url` y el comando listo del simulador) y 5 de observabilidad. |
| `infra/versions.tf` | ✅ Completo | Añadidos `hashicorp/archive ~> 2.7` y `hashicorp/time ~> 0.13`, con el motivo documentado en la cabecera del archivo (§4.4). |
| `docs/` | ✅ Actualizado en esta fase | `guide.md` ampliado, `README.md` escrito, nota de alcance en `architecture.md`. |
| `README.md` | ✅ Escrito en esta fase | Estaba vacío (0 bytes). |
| `AGENTS.md` | ✅ Coherente | Responsabilidades y restricciones alineadas con el laboratorio. |
| `Makefile` | ✅ Funcional | Los 8 objetivos ejecutados. |
| `pyproject.toml` | 🟡 Mínimo | Sin configuración de `ruff` ni de `pytest`; se usan los valores por defecto. |

## 2. Pruebas ejecutadas y resultados reales

Todo lo de esta tabla se ejecutó durante la auditoría. Ningún resultado es
heredado de una fase anterior.

| Comando | Resultado | Código de salida |
| --- | --- | --- |
| `make test` | `226 passed in 9.18s` | 0 |
| `make lint` | `All checks passed!` | 0 |
| `uv run ruff format --check backend simulator tests` | `13 files already formatted` | 0 |
| `make check` (lint + test + infra-fmt) | Todo correcto | 0 |
| `make infra-fmt` | Sin cambios pendientes | 0 |
| `make infra-validate` | `Success! The configuration is valid.` | 0 |
| `terraform -chdir=infra init -backend=false` | `Terraform has been successfully initialized!` | 0 |
| `terraform -chdir=infra plan -lock=false` | `Plan: 8 to add, 0 to change, 0 to destroy.` | 0 |
| `uv lock --check` | `Resolved 31 packages` | 0 |

Versiones: Terraform v1.16.6 (requisito `>= 1.9`), provider `hashicorp/google`
v8.7.0 (requisito `~> 8.7`), Python 3.13.7, pytest 9.1.1, ruff 0.17.0.

`terraform plan` contacta con las APIs de Google Cloud para leer el estado, pero
no escribe: se comprobó después que `infra/` no contiene ningún `.tfstate`.

## 3. Verificaciones funcionales en local

### 3.1. Backend

Función levantada con `functions-framework --target handle --source backend/main.py`.
Códigos observados, uno por petición real:

| Petición | Código | Verificado |
| --- | --- | --- |
| `POST /orders` con payload válido | `201` | ✅ |
| `GET /orders/{id}` existente | `200` | ✅ |
| `GET /orders/{id}` inexistente | `404` | ✅ |
| `POST /orders` con `{"customer_tier":"x"}` | `400` | ✅ |
| `POST /orders/{id}/cancel` abierto | `200` | ✅ |
| `POST /orders/{id}/cancel` ya cancelado | `409` | ✅ |
| `POST /orders/{id}/cancel` inexistente | `404` | ✅ |
| `GET /healthz` (sin ruta) | `404`, `endpoint="unknown"` | ✅ |
| Con `FAILURE_RATE=0.1` | `500`, `error_type="simulated_failure"` | ✅ |

**Logging JSON estructurado:** se capturaron 11 eventos, uno por petición, todos
con las 13 claves del contrato y `severity` coherente con el `outcome`
(`INFO`/`WARNING`/`ERROR`). Ejemplo real del `409`:

```json
{"severity": "WARNING", "message": "request_completed", "request_id": "21615e48ed87470ebcbe82801a1708b2", "endpoint": "POST /orders/{id}/cancel", "status_code": 409, "outcome": "client_error", "error_type": "conflict", "latency_ms": 0.069, "customer_tier": "premium", "category": "books", "amount": 42.5, "order_id": "ord_709408f3c8ee4b9abe2619bef54a4cd9", "order_status": "cancelled"}
```

**Propagación de `X-Request-ID`:** verificada en tres variantes.

| Entrada | Cabecera devuelta | `request_id` del log |
| --- | --- | --- |
| `audit-201` | `audit-201` | `audit-201` |
| (sin cabecera) | `eed8db105424457cacee10bde78cc74a` | el mismo valor generado |
| `bad id<script>$(x)` | `badidscriptx` | `badidscriptx` |

El saneado elimina todo lo que no sea `[A-Za-z0-9._:-]` y trunca a 64
caracteres, así que una cabecera hostil no puede inyectar caracteres en el
evento ni inflar la cardinalidad de una etiqueta.

**Variables de entorno:** `FAILURE_RATE` y `EXTRA_LATENCY_MS` se leen en cada
petición y se saturan a rango seguro. Las pruebas cubren `abc`, cadena vacía,
espacios, `nan`, `inf`, negativos y valores por encima del máximo; todos caen al
valor por defecto o al límite en lugar de romper la petición.

**Compatibilidad con Functions Framework:** la propia suite carga la función con
`functions_framework.create_app(target="handle", source=...)`, que es el mismo
mecanismo que usa el runtime desplegado. `backend/requirements.txt` fija
`functions-framework==3.10.2` y deja que arrastre su Flask compatible.

**Concurrencia y múltiples instancias.** Dentro de una instancia el
comportamiento es correcto: `_STORE_LOCK` serializa el read-modify-write de
`cancel`, y la prueba con 16 hilos sobre el mismo pedido resuelve en exactamente
un `200` y quince `409`. Entre instancias **no hay estado compartido**: un `GET`
o un `cancel` que caiga en una instancia distinta a la del `POST` responde `404`
legítimo. Esto no es un defecto del código, es el diseño; pero es una decisión
pendiente (§6).

### 3.2. Simulador

Plan de la configuración oficial (`simulator/config.json`, semilla 42), medido
sobre los 6.000 instantes generados:

| Requisito | Esperado | Medido |
| --- | --- | --- |
| Instantes generados | 6.000 configurables | 6.000 ✅ |
| Rango | `[0, 60]` min | min `0.0`, max `60.0` ✅ |
| Media | 30 min | **29.9184** ✅ |
| Desviación estándar | 10 min | **10.0049** ✅ |
| Dentro de ±1σ | ≈68,3 % | **68,68 %** ✅ |
| Identificadores únicos | 6.000 distintos | 6.000 distintos ✅ |
| Errores intencionales | 8 % | 496 (8,3 %) ✅ |
| Escenario `double_errors` | `[35,45)` × `electronics`, ×2 | 355 solicitudes afectadas ✅ |

El truncado es por `clip`, no por descarte: hay 9 instantes exactamente en `0.0`
y 10 en `60.0` (≈0,16 % por cola), que es el precio de conservar exactamente
6.000 filas. Está documentado en el propio módulo y en `docs/guide.md` §6.3.

Efecto real del escenario, medido sobre el plan:

| Segmento | Proporción de errores intencionales |
| --- | --- |
| `electronics` dentro de `[35,45)` | **14,37 %** (355 solicitudes) |
| `electronics` fuera de la ventana | 7,86 % (1.120 solicitudes) |
| Resto de categorías | 7,89 % (4.525 solicitudes) |

Corrida pequeña real contra la función local (120 solicitudes, reloj comprimido,
`FAILURE_RATE=0.1`):

```text
requests sent      120
by result          as_expected 109, server_error 11
by status          200 51, 201 49, 400 4, 404 5, 500 11
intentional errors 9
transport errors   0
client latency     p50 2.294 ms, p95 4.356 ms
```

Comprobaciones sobre el CSV y los logs de esa corrida:

| Comprobación | Resultado |
| --- | --- |
| Una fila por solicitud | 120 filas / 120 solicitudes ✅ |
| Identificadores únicos en el CSV | 120 distintos ✅ |
| Columnas | 20 ✅ |
| `response_request_id == request_id` | 120 / 120 ✅ |
| Eventos `request_completed` del backend | 120 ✅ |
| Filas del CSV unidas a su evento por `X-Request-ID` | 120 / 120 ✅ |
| Discrepancias de código entre CSV y log | 0 ✅ |

**Envío concurrente sin bloquear:** una tarea `asyncio` por solicitud sobre un
único `httpx.AsyncClient`; el despachador solo duerme hasta el siguiente instante
y nunca espera la respuesta anterior. Hay pruebas dedicadas
(`test_a_slow_response_does_not_delay_the_next_scheduled_request`,
`test_requests_due_together_are_sent_concurrently`,
`test_many_requests_overlap_on_one_client`).

**Errores de red y timeouts:** corrida real contra un puerto sin servicio
(8 solicitudes): 8 filas conservadas, `status_code` vacío,
`result=transport_error`, `error=ConnectError`. Ninguna fila perdida. Los
timeouts tienen cobertura equivalente en `tests/test_simulator_runtime.py`.

## 4. Terraform

### 4.1. Lo que está

| Requisito del laboratorio | Estado |
| --- | --- |
| Configuración del proveedor Google | ✅ `hashicorp/google ~> 8.7`, `required_version >= 1.9`, bloque `provider` con proyecto y región. Lock file versionado. |
| Cloud Logging | ✅ Bucket regional con `enable_analytics = true`, sink de proyecto y vista restringida a `request_completed`. |
| Log Analytics | ✅ El bucket es regional y la vista es la que consultan las SQL. `region` valida que no sea `global`. |
| Cloud Monitoring | ✅ Un dashboard, 8 tiles, con métricas nativas, métrica basada en logs, dos gráficas SQL y panel de logs. |
| Métricas basadas en logs | ✅ Cuatro: `requests_by_outcome`, `client_errors`, `server_errors`, `order_amount` (distribución con buckets lineales). |
| Recursos de Cloud Run functions | ✅ `google_cloudfunctions2_function.orders_api`, gen 2, con `build_config` y `service_config` completos. |
| Runtime Python 3.13 (`python313`) | ✅ `build_config.runtime = var.runtime` → `python313` en el plan. |
| Entry point `handle` | ✅ `build_config.entry_point = "handle"`, que es la función de `backend/main.py:400`. |
| Cuentas de servicio y permisos IAM | ✅ Dos cuentas dedicadas y cuatro bindings de mínimo privilegio (§4.2). |
| Cloud Storage (bucket del código) | ✅ Bucket regional con acceso uniforme y prevención de acceso público forzada, más el objeto zip. |
| Habilitación de APIs | ✅ Nueve `google_project_service` con `disable_on_destroy = false`. |
| Configuración de costos y escalamiento | ✅ `max_instance_count`, `min_instance_count`, `max_instance_request_concurrency`, `available_memory`, `available_cpu` y `timeout_seconds` explícitos. |
| Variables | ✅ 21 declaradas, todas con consumidor. |
| Outputs | ✅ 13, incluidos `function_url`, `scaling` y `simulator_command`. |
| Ausencia de secretos versionados | ✅ Ver §7.1. |

### 4.2. Lo que se implementó en la fase 3

`infra/main.tf` pasó de 0 bytes a 19 recursos. Agrupados por función:

| Grupo | Recursos | Detalle |
| --- | --- | --- |
| APIs | `google_project_service.required` × 9 | `artifactregistry`, `cloudbuild`, `cloudfunctions`, `cloudresourcemanager`, `iam`, `logging`, `monitoring`, `run`, `storage`. `disable_on_destroy = false` para que un `destroy` del laboratorio no apague capacidades del proyecto. |
| Identidades | `google_service_account.runtime`, `google_service_account.build` | `orders-api-run@…` y `orders-api-build@…`. La función **no** usa la cuenta por defecto de Compute Engine, que arrastra `roles/editor`. |
| IAM de ejecución | `google_project_iam_member.runtime_log_writer` | `roles/logging.logWriter` y nada más: la API no habla con ningún otro servicio. |
| IAM de compilación | `google_project_iam_member.build_log_writer`, `…build_artifact_writer`, `google_storage_bucket_iam_member.build_source_reader` | `roles/logging.logWriter` + `roles/artifactregistry.writer` a nivel de proyecto; la lectura del zip se concede **solo sobre el bucket** (`roles/storage.objectViewer`), no sobre todo el proyecto como en el ejemplo oficial del proveedor. |
| IAM de revisión | `google_project_iam_member.reviewer_monitoring`, `…reviewer_logging` | `for_each` sobre `student_members`, vacío por defecto → 0 recursos. Roles de solo lectura concretos, nunca `roles/viewer`. |
| Código fuente | `google_storage_bucket.source`, `data.archive_file.source`, `google_storage_bucket_object.source` | Bucket regional, acceso uniforme, `public_access_prevention = "enforced"`, regla de ciclo de vida a 30 días y `force_destroy = true`. El zip se arma con una lista explícita de ficheros (`main.py` + `requirements.txt`), así que `__pycache__` queda fuera por construcción y el hash es estable. El nombre del objeto incluye el MD5 del zip, de modo que un cambio en el backend genera un objeto nuevo y la función se redespliega. |
| Propagación de IAM | `time_sleep.build_iam_propagation` | Espera de 60 s tras crear los permisos del builder. Es la mitigación que prescribe el ejemplo oficial del proveedor: IAM es eventualmente consistente y una compilación que arranca demasiado pronto no puede leer el zip. |
| Función | `google_cloudfunctions2_function.orders_api` | Gen 2, `python313`, entry point `handle`, cuenta de ejecución dedicada, variables de entorno `FAILURE_RATE="0.02"` y `EXTRA_LATENCY_MS="0"`, `ingress_settings = "ALLOW_ALL"`. |
| Invocación pública | `google_cloud_run_service_iam_member.public_invoker` | `count = var.allow_unauthenticated ? 1 : 0` → **0 recursos en el plan**. Preparado, no habilitado. |

Valores de escalamiento y coste que el plan confirma en el recurso de la función:

```text
max_instance_count               = 1
min_instance_count               = 0
max_instance_request_concurrency = 1
available_cpu                    = "1"
available_memory                 = "512Mi"
timeout_seconds                  = 60
service_account_email            = orders-api-run@cloudpulse-lab-2026.iam.gserviceaccount.com
```

### 4.3. Variables: de seis sin consumidor a cero

| Variable | Consumidor real ahora |
| --- | --- |
| `runtime` | `build_config.runtime` |
| `max_instances` | `service_config.max_instance_count` |
| `concurrency` | `service_config.max_instance_request_concurrency` |
| `failure_rate` | `service_config.environment_variables.FAILURE_RATE` |
| `extra_latency_ms` | `service_config.environment_variables.EXTRA_LATENCY_MS` |
| `student_members` | `google_project_iam_member.reviewer_monitoring` y `…reviewer_logging` |

Nuevas, todas con validación de rango salvo `function_memory` y
`allow_unauthenticated`: `min_instances`, `function_memory`,
`function_timeout_s`, `allow_unauthenticated`.

Cambio de valor por defecto: `max_instances` pasó de **10 a 1**, y
`terraform.tfvars` quedó alineado. El motivo y su coste están en la cabecera de
`main.tf` y en §6.2.

### 4.4. Proveedores auxiliares añadidos

| Proveedor | Para qué | Por qué no se evitó |
| --- | --- | --- |
| `hashicorp/archive ~> 2.7` | Empaquetar `backend/` en el zip que se sube al bucket | Terraform no sabe crear archivos zip. La alternativa —un zip construido fuera de Terraform— haría que `plan` dependiera de un paso manual previo. |
| `hashicorp/time ~> 0.13` | Esperar 60 s a que propaguen los permisos del builder | Sin la espera, el primer `apply` puede fallar al leer el zip. Es la solución del ejemplo oficial del proveedor para una cuenta de compilación propia. |

Ninguno de los dos crea recursos en la nube ni tiene coste. `terraform init`
los descargó (`archive v2.8.1`, `time v0.14.2`) y actualizó
`infra/.terraform.lock.hcl`, que **no está versionado todavía** (ver N7).

### 4.5. Resumen de `terraform plan`

```text
Plan: 27 to add, 0 to change, 0 to destroy.
```

| Bloque | Recursos |
| --- | --- |
| Cómputo (fase 3, nuevo) | 19 |
| Observabilidad (fase 4, sin cambios) | 8 |
| Acceso público | 0 (`allow_unauthenticated = false`) |

Los 8 de observabilidad son exactamente los de antes: bucket de logs regional,
sink, vista, cuatro métricas basadas en logs y el dashboard. El plan no anuncia
ninguna modificación ni destrucción, porque no hay estado previo: es la primera
creación.

Outputs que el plan ya resuelve sin aplicar:

```text
log_analytics_from_clause = "cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests"
runtime_service_account   = "orders-api-run@cloudpulse-lab-2026.iam.gserviceaccount.com"
source_bucket             = "cloudpulse-lab-2026-orders-api-source"
scaling                   = { max_instances = 1, min_instances = 0, concurrency = 1, memory = "256Mi", timeout_s = 60 }
function_url              = (known after apply)
```

### 4.6. Lo que el plan no puede demostrar

| # | Incógnita | Qué pasa si falla | Remedio |
| --- | --- | --- | --- |
| P1 | Si `roles/storage.objectViewer` **sobre el bucket** le basta a Cloud Build para leer el zip. El ejemplo oficial concede `roles/storage.objectAdmin` a nivel de proyecto; aquí se eligió el mínimo | El primer `apply` falla en la compilación con un error de permisos de Storage | Cambiar ese binding por `roles/storage.objectAdmin` sobre el bucket, o el `roles/cloudbuild.builds.builder` documentado, y repetir `apply`. El fallo es recuperable e idempotente. |
| P2 | Si los 60 s de `time_sleep` bastan para la propagación de IAM | Mismo síntoma que P1 | Repetir `apply`: en el segundo intento los permisos ya están propagados. |
| ~~P3~~ | ~~Si 256 MiB bastan para el arranque en frío~~ | — | ✅ Cerrado antes del despliegue: `function_memory` pasó a `512Mi` por defecto y en `terraform.tfvars`, verificado en el plan (`available_memory = "512Mi"`). El runtime ronda los 100 MB en reposo, así que hay margen de sobra. |

Ninguna de las tres es un bloqueante de configuración: son verificaciones que
exigen un `apply` autorizado.

### 4.7. Estado remoto confirmado (lectura, sin modificar nada)

| Comprobación | Resultado |
| --- | --- |
| `gcloud monitoring dashboards list` | vacío |
| `gcloud logging metrics list` | vacío |
| `gcloud logging sinks list` | solo `_Required` y `_Default` |
| `gcloud logging buckets list` | solo los dos buckets `global` por defecto, **sin analytics** |
| `gcloud iam service-accounts list` | `Listed 0 items.` |
| `gcloud storage buckets list` | vacío |
| APIs habilitadas | `logging`, `monitoring`, `bigquery*`, `storage*`, `cloudtrace`, `dataplex`, `datastore`… |
| **`run.googleapis.com`** | ❌ **no habilitada** |
| `cloudfunctions`, `cloudbuild`, `artifactregistry`, `iam` | ❌ no habilitadas |

No se creó, modificó ni habilitó nada durante la auditoría.

**Comprobaciones añadidas en la fase 3** (todas de lectura):

| Comprobación | Resultado |
| --- | --- |
| `gcloud config get-value account` | `jeyhelloworld@gmail.com` |
| Roles de esa cuenta en el proyecto | `roles/owner` → puede habilitar APIs, crear cuentas de servicio y actuar como ellas (`iam.serviceAccounts.actAs`). No hace falta ningún permiso extra para el `apply`. |
| `gcloud storage buckets describe gs://cloudpulse-lab-2026-orders-api-source` | `404 not found` → el nombre global del bucket del código está libre. |

Las cinco APIs de cómputo siguen sin habilitar, pero eso **ya no es un
pendiente manual**: las declara `google_project_service` y las habilita el
propio `apply`.

## 5. Observabilidad

| Requisito | Estado | Evidencia |
| --- | --- | --- |
| Métricas nativas | ✅ Preparadas | Tres descriptores (`request_count`, `request_latencies`, `container/instance_count`) verificados contra la API del proyecto real; PromQL renderizado en `plan`. |
| Métricas basadas en logs | ✅ Preparadas | Cuatro `google_logging_metric` con filtros que casan campo a campo con el evento que emite el backend. |
| Consultas SQL | ✅ Preparadas | Siete consultas en `docs/log-analytics-queries.sql`; dos de ellas incrustadas en el dashboard. |
| Dashboard unificado | ✅ Preparado | Un solo recurso, 8 tiles, renderizado correctamente en `terraform plan`. |
| Panel de logs | ✅ Preparado | `logsPanel` con `severity>=WARNING` sobre el proyecto, declarado en el JSON. Sin pasos manuales. |
| Correlación por `X-Request-ID` | ✅ Verificada en local | 120/120 filas del CSV unidas a su evento (§3.2). Consulta 6 del archivo SQL hace el puente en Log Analytics. |

**Orden de creación de las métricas respecto al tráfico.** El requisito se cumple
*por diseño documentado*, no por un mecanismo que lo fuerce:

- Las cuatro métricas son recursos del mismo `terraform apply` que crea el resto,
  así que existen antes de que nadie lance el simulador a mano.
- El dashboard lleva un `depends_on` explícito sobre
  `google_logging_metric.requests_by_outcome` y sobre la vista.
- La advertencia («una métrica solo cuenta entradas ingeridas después de
  crearse, no hay backfill») está en la cabecera de `infra/logging.tf`, en
  `docs/observability.md` §2 y ahora en `docs/guide.md` §8.4 y §10.1.
- No existe ninguna comprobación automática que impida lanzar el simulador antes
  del `apply`. El paso de verificación manual
  (`gcloud logging metrics list` debe devolver las cuatro) está documentado en
  `docs/guide.md` §10.1.

🟡 Riesgo residual aceptado: el orden depende de que el operador siga el
procedimiento. Lanzar el simulador antes del `apply` cuesta repetir —y pagar— los
60 minutos.

## 6. Requisitos pendientes

### 6.1. Bloqueantes

Ninguno de configuración.

| # | Pendiente anterior | Estado |
| --- | --- | --- |
| B1 | `infra/main.tf` vacío | ✅ Resuelto en esta fase: 19 recursos de cómputo, `validate` y `plan` correctos. |
| B2 | APIs de cómputo sin habilitar | ✅ Resuelto: las declaran nueve `google_project_service`; el `apply` las habilita. Ya no es un paso manual. |

Lo único que falta para que exista el laboratorio es la **autorización humana
para ejecutar `terraform apply`**, que esta fase no tiene y no asume.

### 6.2. Decisiones de diseño: tomadas

| # | Decisión | Qué quedó escrito | Coste aceptado |
| --- | --- | --- | --- |
| D1 | **Acceso a la función** | `allow_unauthenticated` (bool, por defecto `false`) y un binding `roles/run.invoker` → `allUsers` con `count = var.allow_unauthenticated ? 1 : 0`. Hoy el plan crea **0** bindings de invocación. | El simulador no firma peticiones, así que con la función privada las 6.000 solicitudes recibirían `403`. Para la corrida hay que habilitar el flag **temporalmente** (procedimiento de cuatro pasos al final de `main.tf`) o añadir tokens de identidad al simulador. La decisión de habilitarlo es operativa y requiere autorización. |
| D2 | **Almacén en memoria** | `max_instances = 1` como valor por defecto y en `terraform.tfvars`, con validación de rango `[1, 100]`. | El escalamiento horizontal deja de ser observable: el panel `container/instance_count` del dashboard se queda plano en 1. La alternativa real —almacenamiento compartido— está fuera del alcance del laboratorio. La única palanca de rendimiento que queda es `concurrency`. |

**Capacidad con un solo instancia y `concurrency = 1`.** El plan de 6.000
solicitudes tiene su pico alrededor del minuto 30, a unas 239 solicitudes por
minuto (≈ 4 por segundo). La latencia medida en local fue p50 2,6 ms y p95
4,9 ms, así que una instancia serializando peticiones tiene unos dos órdenes de
magnitud de margen. El margen se consume si se sube `extra_latency_ms`: a partir
de unos 250 ms por petición, 4 por segundo ya no caben en serie y empezaría a
haber cola —y, si la cola crece, `429`—. En ese caso hay que subir `concurrency`
(seguro dentro de una instancia: el almacén está protegido por un lock y hay
pruebas de concurrencia que lo verifican), no `max_instances`.

### 6.3. No bloqueantes

| # | Pendiente | Severidad |
| --- | --- | --- |
| N1 | ~~Variables sin consumidor~~ | ✅ Resuelto en la fase 3 (§4.3) |
| N2 | ~~Falta un output con la URL de la función~~ | ✅ Resuelto: outputs `function_url` y `simulator_command` |
| N10 | `infra/.terraform.lock.hcl` cambió al añadir los proveedores `archive` y `time`, y el archivo sigue sin versionar (mismo caso que N7) | 🟡 Sin el lock versionado, otra máquina puede resolver versiones distintas |
| N3 | `simulator/simulator.py:180` — el comentario afirma que `output_csv` «está excluido a propósito» de `_OVERRIDABLE_FIELDS`, pero la línea 194 lo incluye. Consecuencia real: un `quick.output_csv` relativo se resuelve contra el directorio de trabajo, no contra el archivo de configuración | 🟡 Comentario que contradice al código |
| N4 | `pyproject.toml` sin `[tool.ruff]` ni `[tool.pytest.ini_options]`: `make lint` solo aplica las reglas por defecto de Ruff (`E`, `F`) | 💭 Cobertura de linter más débil de lo que parece |
| N5 | `make check` no incluye `infra-validate` (solo `infra-fmt`) | 💭 Una validación disponible queda fuera del comando de calidad |
| N6 | `docs/architecture.md` describe la fase 1 con cifras antiguas (86 pruebas, `infra/` vacío) | 💭 Mitigado en esta fase con una nota de alcance al inicio |
| N7 | El trabajo de las fases 1 a 4 está sin commitear: `backend/main.py`, `simulator/`, `infra/logging.tf`, `infra/monitoring.tf`, `docs/` y `tests/` aparecen como modificados o sin seguimiento | 🟡 Riesgo de pérdida; no se crearon commits porque la fase lo prohíbe |
| N8 | El `order_id` que llega al log en un `404` es el segmento de ruta que mandó el cliente, sin sanear | 💭 No se usa como etiqueta de métrica (solo se consulta por SQL) y `json.dumps` lo escapa, así que no hay inyección ni cardinalidad en métricas |
| N9 | `_ORDERS` crece sin límite durante la corrida (~3.000 pedidos) | 💭 Irrelevante al volumen del laboratorio |

## 7. Seguridad y costos

### 7.1. Credenciales y archivos ignorados

| Comprobación | Resultado |
| --- | --- |
| `.env` ignorado por Git | ✅ `.gitignore:272` |
| `infra/terraform.tfvars` ignorado | ✅ `.gitignore:236` (`*.tfvars`) |
| `outputs/**` ignorado salvo `.gitkeep` | ✅ `.gitignore:281` |
| `*.tfstate`, `*.tfstate.*`, `.terraform/`, `*.tfplan` ignorados | ✅ |
| `keys/*` ignorado salvo `.gitkeep` | ✅ y el directorio está vacío |
| Archivos sensibles ya versionados | ✅ Ninguno: `git ls-files` solo devuelve los cinco `.gitkeep` |
| Búsqueda de secretos en el código | ✅ 0 coincidencias de claves privadas, `AIza…`, `ya29.`, `AKIA…` o `"private_key"` |
| Ficheros de credenciales en la raíz del repositorio | ✅ Endurecido en esta fase. Antes, un `credentials.json` o un `service-account.json` descargado por error en la raíz era versionable; ahora `.gitignore` cubre `credentials.json`, `*-credentials.json`, `client_secret*.json`, `service-account*.json`, `*-sa-key.json`, `adc.json`, `application_default_credentials.json`, `*.pem`, `*.p12` y `*.key` (con `!**/*.pub`). Comprobado con `git check-ignore`; ningún archivo ya versionado quedó oculto. |
| Planes de Terraform sin extensión | ✅ Endurecido en esta fase: `tfplan` y `tfplan-*` añadidos a `.gitignore`, además de `*.tfplan` y `planout` que ya estaban. |
| Credenciales en `backend/` o `simulator/` | ✅ Ninguna. El backend nunca registra cabeceras, cuerpos ni el entorno, y hay una prueba de que la cabecera `Authorization` no llega al log |
| ADC | ✅ En `~/.config/gcloud/`, fuera del repositorio |
| `.env` real | ✅ Contiene solo parámetros no sensibles (id de proyecto, región, nombre de función, tasas); ninguna credencial |

⚠️ `outputs/reports/predeployment-review.md` —este archivo— **está ignorado por
Git** (`outputs/**`). Si el informe debe quedar versionado, hay que copiarlo
fuera de `outputs/` o añadir una excepción al `.gitignore`.

### 7.2. Permisos públicos de la función

**El binding está declarado pero desactivado**: `count = 0` mientras
`allow_unauthenticated` sea `false`, que es el valor por defecto y el de
`terraform.tfvars`. El plan actual no crea ninguna política de invocación, así
que al aplicar esta configuración la función responde `403` a cualquier llamada
sin autenticar.

El binding concede `roles/run.invoker` —el rol estrecho y documentado para
esto—, nunca un rol básico, y solo sobre el endpoint `run.app` que devuelve el
output `function_url`. La dirección heredada `cloudfunctions.net` (`gcf_uri`) se
gobierna con `roles/cloudfunctions.invoker` y **no** se concede: una sola
superficie pública es suficiente.

Procedimiento para habilitarlo únicamente durante el experimento autorizado
(escrito también al final de `main.tf`):

1. `terraform apply -var allow_unauthenticated=true` justo antes de la corrida.
2. Lanzar el simulador contra la URL del output `function_url`.
3. `terraform apply -var allow_unauthenticated=false` inmediatamente después;
   esto elimina el binding y deja intactos los datos, los logs y las métricas.
4. Mantener `max_instances` bajo durante todo el proceso y no publicar la URL.

Las dos salidas siguen teniendo coste:

- **Conceder `roles/run.invoker` a `allUsers`** deja un endpoint HTTP público y
  sin autenticar. Al ser un laboratorio con datos sintéticos el riesgo de datos
  es nulo, pero el riesgo de **coste** no: cualquiera que descubra la URL puede
  generar invocaciones facturables. Mitigaciones ya en la configuración:
  `max_instances = 1` como tope duro y la ventana de exposición reducida a los
  60 minutos del procedimiento de arriba. Mitigación que queda en manos del
  operador: borrar el servicio al terminar y no publicar la URL.
- **Mantenerla privada** obliga a añadir un token de identidad al simulador, que
  hoy no lo soporta: `_execute` solo envía `X-Request-ID`.

### 7.3. Cuentas de servicio

Dos cuentas declaradas, ninguna creada todavía (nada está aplicado). La función
**no** usa la cuenta por defecto de Compute Engine, que trae `roles/editor`
sobre todo el proyecto.

| Cuenta | Roles | Alcance |
| --- | --- | --- |
| `orders-api-run@…` (ejecución) | `roles/logging.logWriter` | Proyecto. Es el único permiso que necesita: la API no accede a ningún otro servicio de Google Cloud. |
| `orders-api-build@…` (compilación) | `roles/logging.logWriter`, `roles/artifactregistry.writer` | Proyecto |
| `orders-api-build@…` (compilación) | `roles/storage.objectViewer` | **Solo el bucket del código**, no el proyecto |
| `student_members` (revisores) | `roles/monitoring.viewer`, `roles/logging.viewer` | Proyecto, y solo si la lista no está vacía (hoy lo está → 0 bindings) |

Ningún binding usa roles básicos (`owner`, `editor`, `viewer`) ni concede
permisos a `allUsers` fuera del caso de invocación de §7.2.

### 7.4. Límites de escalamiento

| Parámetro | Valor en `terraform.tfvars` | Llega a la función |
| --- | --- | --- |
| `max_instances` | **1** (antes 10) | ✅ `service_config.max_instance_count` |
| `min_instances` | 0 | ✅ `service_config.min_instance_count` — escala a cero, nada se factura entre corridas |
| `concurrency` | 1 | ✅ `service_config.max_instance_request_concurrency` |
| `function_memory` | **`512Mi`** (antes `256Mi`) | ✅ `service_config.available_memory` |
| `function_timeout_s` | 60 | ✅ `service_config.timeout_seconds` |
| `failure_rate` | 0.02 | ✅ `environment_variables.FAILURE_RATE = "0.02"` |
| `extra_latency_ms` | 0 | ✅ `environment_variables.EXTRA_LATENCY_MS = "0"` |

🟢 El tope existe y es explícito. Cloud Run usaría 100 instancias por defecto;
aquí el techo es 1, verificado en el plan. Las validaciones de `variables.tf`
impiden además escribir un `max_instances` fuera de `[1, 100]` o un
`concurrency` fuera de `[1, 1000]`, así que un error de dedo en
`terraform.tfvars` falla en `plan` en vez de en la factura.

### 7.5. Riesgos de facturación y presupuesto de US$5

> ⚠️ **El presupuesto de US$5 con alertas no es un límite de gasto.** Google
> Cloud **no suspende** los servicios al alcanzar el importe. Las alertas llegan
> con retraso (el gasto se evalúa de forma periódica, no instantánea). **Es
> posible superar los US$5** y nada en el proyecto lo impide automáticamente.

Para el perfil de este laboratorio —una corrida de 6.000 solicitudes pequeñas, un
dashboard, cuatro métricas y unos pocos MB de logs— el consumo esperado cae
holgadamente dentro de los niveles gratuitos. Los riesgos no están en la corrida
prevista, sino en lo que la rodea:

| Riesgo | Por qué supera el presupuesto | Mitigación |
| --- | --- | --- |
| ~~Sin tope de instancias~~ (§7.4) | Era el escenario de gasto descontrolado: 100 instancias por defecto | ✅ Mitigado: `max_instance_count = 1` en el recurso, con validación de rango. Verificado en el plan. |
| **Objetos del bucket del código acumulados** | Cada redespliegue sube un zip nuevo, porque el nombre incluye el hash | Regla de ciclo de vida que borra los objetos a los 30 días, ya declarada |
| **Endpoint público descubierto** | Invocaciones facturables que nadie controla, 24/7 | Borrar el servicio al terminar; no publicar la URL |
| **Recursos persistentes olvidados** | El bucket de logs, las imágenes de Artifact Registry, el bucket del código y el bucket de logs siguen cobrando mientras existan, aunque el laboratorio haya terminado | Ejecutar la limpieza de §7.7 tras la corrida |
| **Repetir la corrida de 60 minutos** | Si las métricas se crean después del tráfico, hay que repetir todo | Verificar `gcloud logging metrics list` antes de lanzar |
| **Doble ingestión de logs** | El sink nuevo es aditivo: `_Default` sigue recibiendo las mismas entradas, así que cada una se ingiere dos veces | A ~6.000 entradas pequeñas es despreciable frente al nivel gratuito; es deliberado para que el panel de logs siga funcionando |
| **Retención de 30 días** | El bucket conserva los logs 30 días después de la corrida | Reducir `log_bucket_retention_days` o borrar el bucket al terminar |
| **Compilaciones repetidas** | Cada `apply` que cambie el código fuente dispara Cloud Build y deja una imagen nueva en Artifact Registry | Limitar los redespliegues; limpiar imágenes antiguas |

No se modificó la facturación ni el presupuesto durante la auditoría.

### 7.6. Log Analytics y el bucket `_Default`

La configuración actual **no toca `_Default`**: crea un bucket regional aparte
(`cloudpulse-logs`) y le enruta los logs del servicio con un sink adicional. Esa
es la decisión correcta, y conviene dejar escrito por qué:

| Si se habilitara Log Analytics en `_Default` | Consecuencia |
| --- | --- |
| Es **irreversible** | Una vez que un bucket se actualiza a Observability Analytics **no puede degradarse** para quitar esa capacidad. `_Default` no se puede borrar, así que el cambio sería permanente en el proyecto. |
| Alcance de todo el proyecto | `_Default` recibe los logs de **todos** los servicios, no solo de `orders-api`. Las consultas SQL tendrían que filtrar el ruido de la plataforma. |
| `_Default` es global, no regional | Log Analytics exige un bucket regional. Habría que recrear el enrutado de todas formas. |
| Pérdida de aislamiento | Hoy la vista `cloudpulse_requests` restringe la superficie a `jsonPayload.message="request_completed"`. Sobre `_Default` ese filtrado habría que repetirlo en cada consulta. |

El coste de la vía elegida es la doble ingestión, ya contabilizada arriba.

### 7.7. Recursos persistentes

Lo que quedaría vivo tras la corrida y cobrando mientras exista:

| Recurso | Lo crea | Persiste |
| --- | --- | --- |
| Bucket de logs `cloudpulse-logs` | Terraform | Sí, con 30 días de retención |
| Cuatro métricas basadas en logs | Terraform | Sí |
| Sink `cloudpulse-orders-api` | Terraform | Sí |
| Dashboard | Terraform | Sí (sin coste material) |
| Cloud Run function + revisión | Terraform (cuando exista) | Sí |
| Bucket del código fuente | Terraform (cuando exista) | Sí |
| Imágenes de Artifact Registry | Cloud Build, **no Terraform** | Sí, y `destroy` no se las lleva |
| Entradas en `_Default` | El sink `_Default` del proyecto | Hasta que caduquen por retención |

Procedimiento de limpieza y lista de comprobación: `docs/guide.md` §11.

## 8. Riesgos técnicos

| # | Riesgo | Severidad | Nota |
| --- | --- | --- | --- |
| T1 | `main.tf` vacío: la observabilidad podría aplicarse sin que exista la función, dejando métricas que no cuentan nada y un dashboard vacío | 🔴 | Bloqueante B1 |
| T2 | El simulador no puede autenticarse contra una función privada | 🔴 | Decisión D1; rompe la corrida completa |
| T3 | Almacén en memoria: `404` de fondo que no son defectos y contaminan la métrica de `client_errors` | 🟡 | Decisión D2; documentado desde la fase 1 |
| T4 | Los topes de escalado existen como variable pero no como configuración | 🟡 | Riesgo técnico y de coste a la vez (§7.4) |
| T5 | Los `500` inyectados no son reproducibles entre corridas (`random()` sin semilla) | 💭 | Deliberado; las pruebas fijan solo los extremos 0 y 1 |
| T6 | Tres mediciones distintas de latencia (`client_latency_ms`, `jsonPayload.latency_ms`, métrica nativa) que no son comparables | 💭 | Documentado en `docs/observability.md` §5 |
| T7 | `scheduled_min` no viaja a Cloud Logging, así que el dashboard mide el minuto *observado* | 💭 | Documentado en el tile 0 del dashboard y en la cabecera del archivo SQL |
| T8 | Nada verifica que las métricas existan antes del tráfico | 🟡 | Paso manual en `docs/guide.md` §10.1 |
| T9 | Los extractores de etiquetas (`EXTRACT(jsonPayload.…)`) no se pueden validar sin tráfico real | 🟡 | Solo una petición contra la función desplegada lo demuestra |
| T10 | Fase 1-4 sin commitear | 🟡 | N7 |

## 9. Problemas bloqueantes

Ninguno de configuración. Los tres de la auditoría anterior están cerrados:

1. ~~`infra/main.tf` está vacío.~~ ✅ 19 recursos de cómputo, con los requisitos
   del enunciado §4 cubiertos: Cloud Run function gen 2, runtime `python313`,
   entry point `handle`, dos cuentas de servicio con permisos mínimos, bucket y
   objeto del código, y los topes de coste y escalamiento explícitos.
2. ~~Las APIs de cómputo no están habilitadas.~~ ✅ Nueve
   `google_project_service` las declaran; el `apply` las habilita. Nada se
   habilitó a mano en esta fase.
3. ~~El acceso a la función está sin decidir.~~ ✅ Decidido y escrito:
   `allow_unauthenticated = false`, binding preparado con `count = 0` y un
   procedimiento de habilitación temporal documentado (§7.2). **Pero sigue
   siendo una decisión operativa pendiente de autorización**: sin habilitar el
   flag, las 6.000 solicitudes del simulador recibirían `403`.

Lo que queda abierto no es un defecto de la configuración:

| Abierto | Tipo |
| --- | --- |
| Autorizar y ejecutar `terraform apply` | Decisión humana; esta fase no la asume |
| Habilitar `allow_unauthenticated` durante la corrida, o firmar las peticiones del simulador | Decisión operativa con implicación de coste (§7.2) |
| P1–P3 de §4.6 (permiso del builder sobre el bucket, 60 s de propagación, 256 MiB de memoria) | Verificaciones que solo el primer `apply` puede hacer; las tres son recuperables repitiendo el `apply` |
| El escalamiento horizontal no será observable con `max_instances = 1` | Coste aceptado de D2 (§6.2) |

## 10. Checklist de despliegue

Nada de esto se ha ejecutado.

### Antes del `apply`

- [x] ✅ `infra/main.tf` escrito: nueve `google_project_service`, dos cuentas de servicio, cuatro bindings IAM, bucket y objeto del código, espera de propagación y la función gen 2
- [x] ✅ Cuentas dedicadas, **no** la de Compute por defecto; la de ejecución solo con `roles/logging.logWriter`
- [x] ✅ Bucket de Cloud Storage para el código y el objeto comprimido (hash en el nombre)
- [x] ✅ Función con `runtime = var.runtime` (`python313`), entry point `handle`, `max_instance_count = 1`, `max_instance_request_concurrency = 1`, memoria, timeout y las variables `FAILURE_RATE` / `EXTRA_LATENCY_MS`
- [x] ✅ D1 decidido: `allow_unauthenticated = false`, binding preparado con `count = 0`
- [x] ✅ D2 decidido: `max_instances = 1`, con su coste documentado
- [x] ✅ Outputs `function_url`, `simulator_command`, `scaling` y las dos cuentas de servicio
- [x] ✅ Las seis variables sin consumidor quedaron conectadas (§4.3)
- [x] ✅ `make check` en verde (226 pruebas)
- [x] ✅ `terraform fmt -check -recursive` sin cambios
- [x] ✅ `terraform validate` correcto
- [x] ✅ `terraform plan` revisado: 27 a crear, 0 a modificar, 0 a destruir
- [x] ✅ `uv lock --check` sin desajustes
- [x] ✅ Facturación activa y presupuesto de US$5 con alertas configurado
- [x] ✅ Ningún secreto versionado
- [x] ✅ Nombre global del bucket del código libre (`404` al describirlo)
- [x] ✅ La cuenta que ejecutaría el `apply` tiene `roles/owner`
- [ ] 🟡 Commitear el trabajo de las fases 1 a 4 y el `.terraform.lock.hcl` nuevo (N7, N10)
- [ ] 🔴 **Autorización humana explícita para ejecutar `terraform apply`**

### Durante el despliegue — cada paso con aprobación explícita

- [ ] `terraform plan -out=outputs/terraform/tfplan` y leerlo completo
- [ ] `terraform apply` del plan guardado
- [ ] `gcloud logging metrics list` devuelve las cuatro métricas `cloudpulse_*`
- [ ] `terraform output dashboard_url` abre el dashboard con los 8 tiles
- [ ] Una sola petición de humo con `X-Request-ID` conocido responde el código esperado
- [ ] `gcloud logging read` encuentra el evento `request_completed` de esa petición
- [ ] Ensayo `--quick` contra la URL desplegada sin `transport_error`

### La corrida

- [ ] `uv run python simulator/simulator.py --target-url <URL>` (60 minutos)
- [ ] `outputs/simulator/requests.csv` con 6.001 líneas (cabecera + 6.000 filas)
- [ ] Reparto de `result` y de `status_code` revisado
- [ ] Consultas SQL de `docs/log-analytics-queries.sql` ejecutadas con el `FROM` real
- [ ] Al menos un `request_id` trazado del CSV al evento de Cloud Logging

### Después

- [ ] Exportar `requests.csv`, los resultados SQL y el JSON del dashboard
- [ ] Revisar el gasto en Billing
- [ ] `terraform plan -destroy` revisado y `terraform destroy` **solo con aprobación explícita**
- [ ] Comprobar a mano que no quedan imágenes de Artifact Registry ni buckets

## 11. Restricciones respetadas

| Restricción | Cumplida |
| --- | --- |
| No ejecutar `terraform apply` | ✅ |
| No ejecutar `terraform destroy` | ✅ |
| No habilitar APIs | ✅ Solo lecturas (`gcloud services list --enabled`) |
| No crear recursos en GCP | ✅ Verificado: dashboards, métricas, buckets, sinks y cuentas de servicio siguen como estaban |
| No ejecutar las 6.000 solicitudes | ✅ Se ejecutaron 120 + 8 contra `127.0.0.1` y un `--dry-run` del plan completo |
| No modificar facturación ni presupuestos | ✅ |
| No crear commits automáticamente | ✅ |

`terraform plan` sí se ejecutó: es una operación de lectura, no escribió estado
—se comprobó que `infra/` no contiene ningún `.tfstate`— y es la única forma de
demostrar qué recursos declara la configuración.

**Lo que la fase 3 ejecutó, y por qué no viola nada de la tabla:**

| Acción | Naturaleza |
| --- | --- |
| `terraform init` | Descargó los proveedores `archive` y `time` al directorio local `.terraform/` y actualizó `.terraform.lock.hcl`. No toca Google Cloud. Sin él, `validate` y `plan` no pueden ejecutarse. |
| `terraform plan` | Lectura. Creó un único archivo local: `outputs/terraform/orders-api-source.zip` (14 KB, `main.py` + `requirements.txt`), que es lo que hace `data.archive_file` al evaluarse. Ningún recurso remoto. |
| `gcloud config get-value account`, `gcloud projects get-iam-policy`, `gcloud storage buckets describe` | Tres lecturas, sin flags de escritura y sin `--quiet` sobre operaciones mutantes. |
| `make check`, `uv lock --check` | Local. Las 226 pruebas corren contra `127.0.0.1`; ninguna toca Google Cloud. |

No se ejecutó `apply`, ni `destroy`, ni `gcloud services enable`, ni ninguna
petición a la función (no existe), ni se modificó la facturación, ni se creó
ningún commit.
