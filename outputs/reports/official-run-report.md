# CloudPulse — Informe de la corrida oficial

**Corrida:** `cc4f0755` · **Proyecto:** `cloudpulse-lab-2026` · **Región:** `us-central1`
**Función:** `orders-api` (`python313`, 512Mi, `max_instances=1`, `concurrency=1`, privada)
**Inicio:** 2026-10-16T10:56:56Z · **Fin:** 2026-10-16T11:55:18Z · **Código de salida:** 0
**CSV:** `outputs/simulator/requests.csv` (6.000 filas) · **Log:** `outputs/logs/official-run.log`
**Validación de observabilidad:** `outputs/reports/log-analytics-validation.md`
(consultas listas para copiar, resultados esperados y checklist de capturas)

Ninguna cifra de este informe es estimada: todas vienen del CSV de la corrida, de
`gcloud logging read` o de la API de Cloud Monitoring. Donde una medición no se
pudo hacer, se dice explícitamente.

## 1. Veredicto

> ## ✅ CORRIDA COMPLETADA
>
> 6.000 de 6.000 solicitudes enviadas y registradas. **Cero errores de
> transporte, cero timeouts, cero fallos de autenticación y cero excepciones no
> controladas en el backend.** Las 6.000 filas del CSV se correlacionan una a
> una con los 6.000 eventos `request_completed` de Cloud Logging, con los mismos
> códigos de estado en ambos lados.

Hay dos desviaciones reales que no invalidan el experimento y se documentan en
§8: la ventana duró **58 min 21 s** en vez de 60 min por un desvío de reloj del
2,77 % en WSL2, y el escenario `double_errors` midió **1,83×** en vez de 2,00×
por ruido de muestreo (−0,84σ).

## 2. Preflight

`bash scripts/preflight.sh` → `PREFLIGHT OK`, 0 fallos, 1 aviso.

| Grupo | Resultado |
| --- | --- |
| Configuración | 6.000 instantes · ventana 3.600 s · `N(mu=30, sigma=10)` · semilla 42 · `double_errors [35,45)` sobre `electronics` · CSV escribible y sin sobrescribir nada |
| Calidad local | `make check`: 265 passed |
| Identidad y coste | cuenta activa · facturación activa · ⚠️ presupuesto no legible (permisos/API `billingbudgets`) |
| Función | `ACTIVE` · `python313` · 512Mi · `max_instances=1` |
| Superficie pública | sin `allUsers`: la invocación exige identidad |
| Autenticación | token obtenido (no mostrado) · sondeo `HTTP 404` correcto |
| Observabilidad | las 4 métricas `cloudpulse_*` **ya existían antes del tráfico** · bucket con Log Analytics · vista `cloudpulse_requests` · dashboard presente |

Configuración efectiva en el momento del lanzamiento: `n_requests=6000`,
`duration_min=60`, `seconds_per_minute=60`, `mu_min=30`, `sigma_min=10`,
`invalid_share=0.08`, `seed=42`, `timeout_s=10`, `max_connections=50`,
`token_refresh_s=1800` (2 renovaciones dentro de la corrida).

## 3. Respuestas HTTP

| Código | Solicitudes | Significado |
| --- | --- | --- |
| `200` | 2.716 | consultas y cancelaciones válidas |
| `201` | 2.662 | pedidos creados |
| `400` | 253 | payload inválido intencional |
| `404` | 192 | identificador inexistente intencional (+5 degradaciones del pool) |
| `409` | 47 | cancelar lo ya cancelado (secuencia imposible) |
| `500` | 130 | fallo inyectado por el backend |

| Familia | Solicitudes | Proporción |
| --- | --- | --- |
| 2xx | **5.378** | 89,63 % |
| 4xx | **492** | 8,20 % |
| 5xx | **130** | 2,17 % |
| Sin respuesta (transporte/timeout) | **0** | 0,00 % |

- **4xx = 8,20 %** frente al `invalid_share = 8 %` configurado.
- **5xx = 2,17 %** frente al `FAILURE_RATE = 0.02` del backend (+0,6σ sobre 6.000 ensayos).
- Clasificación del simulador: `as_expected` **5.870**, `server_error` **130**, `unexpected` **0**, `transport_error` **0**.
- Los 130 `500` se reparten en 121 sobre solicitudes válidas y 9 sobre solicitudes que ya iban rotas a propósito: el backend inyecta el fallo **antes** de validar, y el CSV los separa igualmente porque un `5xx` nunca se cuenta como error intencional del cliente.

## 4. Latencia

Medida por el cliente (incluye internet, TLS y el proxy de Cloud Run):

| Percentil | ms |
| --- | --- |
| mínimo | 72,8 |
| **p50** | **81,2** |
| p90 | 91,4 |
| **p95** | **192,8** |
| p99 | 222,5 |
| máximo | 427,1 |
| media | 89,5 |

Por operación (p50 / p95 / máx, ms): `create` 80,8 / 163,6 / 427,1 · `read`
82,4 / 185,9 / 388,9 · `cancel` 80,8 / 202,0 / 346,9. Ningún código responde
sistemáticamente más lento: el p50 va de 80,4 (`409`) a 82,1 (`404`).

**Tres miradores distintos de la misma latencia**, todos medidos:

| Fuente | p50 | p95 | Qué incluye |
| --- | --- | --- | --- |
| Cliente (CSV) | 81,2 ms | 192,8 ms | red, TLS, proxy y función |
| Función (evento de log) | 0,187 ms | 0,376 ms | solo el tiempo dentro de `handle` |
| Cloud Run (`request_latencies`) | media 3,5 ms | — | dentro de la plataforma |

La sobrecarga de red y plataforma es de **81,0 ms en el p50**: el 99,8 % de lo
que mide el cliente ocurre fuera de la función. Las tres series no son
comparables y el dashboard las muestra en paneles separados a propósito.

## 5. Distribución de llegadas

Instantes planificados (`scheduled_min`, los que define el plan):

| Medida | Valor | Teórico |
| --- | --- | --- |
| media | 29,918 min | 30 |
| desviación | 10,004 min | 10 |
| dentro de μ±σ [20,40] | 68,68 % | 68,27 % |
| dentro de μ±2σ [10,50] | 95,38 % | 95,45 % |
| mínimo / máximo | 0,00 / 60,00 | truncado a [0,60] |

Histograma por decenas de minuto:

```text
[0-10):  142   ██
[10-20): 820   ███████████
[20-30): 2014  ███████████████████████████
[30-40): 2107  ████████████████████████████
[40-50): 782   ██████████
[50-60): 135   ██
```

Campana centrada en el minuto 30, como exige el laboratorio. La acumulación en
los bordes por el truncado es de **9 solicitudes en el minuto 0** y **10 en el
minuto 60** (0,32 % del total, frente al 0,27 % teórico de las dos colas).

Espaciado real entre envíos consecutivos: mínimo 0,3 ms, p50 **252 ms**, p95
1,83 s, máximo 47,6 s (los huecos grandes son las colas de la campana).

## 6. Escenario `double_errors`

| Segmento | n | Errores intencionales | Configurado |
| --- | --- | --- | --- |
| `electronics` **dentro** de [35,45) | 355 | **14,37 %** | 16 % |
| `electronics` **fuera** de la ventana | 1.120 | 7,86 % | 8 % |
| Otras categorías **dentro** de la ventana | 1.051 | 8,28 % | 8 % |

- Solicitudes etiquetadas con el escenario: **355**, exactamente las que anunció el plan.
- Ratio medido **1,83×** frente al objetivo 2,00×. Es ruido de muestreo, no un defecto: con n=355 y p=0,16 se esperaban 56,8 errores y hubo 51 (σ=6,9 → **−0,84σ**). La *probabilidad* sí se duplica exactamente —`error_probability(40, "electronics") == 0.16`, fijado por pruebas unitarias—; lo que varía es la realización.
- El escenario no contaminó al resto: las otras categorías dentro de la ventana se quedaron en el 8,28 %.
- Códigos dentro de la ventana para `electronics`: `200` 141, `201` 154, `400` 27, `404` 20, `409` 4, `500` 9.

### Familias de error intencional

Las tres exigidas por el laboratorio aparecieron, y las seis variantes de payload roto se ejercitaron:

| Evento | n |
| --- | --- |
| `create_invalid_payload` (400) | 259 |
| `read_missing_order` (404) | 138 |
| `cancel_missing_order` (404) | 50 |
| `cancel_already_cancelled` (409) | 49 |

Variantes de payload: `not_an_object` 52 · `bad_category` 44 ·
`amount_not_a_number` 42 · `missing_amount` 42 · `negative_amount` 41 ·
`unknown_field` 38. **Las 496 solicitudes intencionalmente inválidas
recibieron 4xx** (salvo las que el backend convirtió en `500` por la inyección).

## 7. Correlación y observabilidad

### 7.1. `X-Request-ID`

| Comprobación | Resultado |
| --- | --- |
| Filas en el CSV | 6.000 |
| `X-Request-ID` únicos | 6.000 / 6.000 |
| Eco de la cabecera en la respuesta | 6.000 / 6.000 |
| Eventos `request_completed` en Cloud Logging | **6.000** (`insertId` únicos) |
| Filas sin evento | **0** |
| Eventos sin fila | **0** |
| Discrepancias de `status_code` | **0** |
| Discrepancias de `category` en creaciones válidas | **0** |
| Credenciales en el CSV | 0 coincidencias de `Bearer`/`eyJ`/`authorization` |

El CLI devolvió 6.006 líneas para 6.000 `insertId` únicos: 6 entradas repetidas
en los bordes de página del propio `gcloud`, **no** duplicación en Logging.

### 7.2. Lo que vio el backend

`outcome`: `success` 5.378 · `client_error` 492 · `server_error` 130.
`error_type`: `none` 5.378 · `validation_error` 253 · `not_found` 192 ·
`conflict` 47 · `simulated_failure` 130.

**`unhandled_exception`: 0.** Los 130 `5xx` son el fallo inyectado; ninguno es
un defecto del código.

### 7.3. Log Analytics

Las 6.000 entradas de la corrida son visibles a través de la vista
`cloudpulse_requests` del bucket regional `cloudpulse-logs`
(verificado con `--bucket`/`--location`/`--view`: 6.000 `insertId` únicos).

**Las consultas SQL no se pudieron ejecutar desde la CLI**: `gcloud logging` no
tiene subcomando de analytics y `bq` falla con
`Not found: Dataset cloudpulse-lab-2026:us-central1.cloudpulse-logs`, porque no
existe un *linked dataset* de BigQuery — crearlo es infraestructura nueva y no
estaba autorizado. Lo verificable sin él está verificado: los datos están en el
bucket de analytics y la vista los expone. Las siete consultas de
`docs/log-analytics-queries.sql` se pueden ejecutar en la consola de Log
Analytics; sus cifras deben coincidir con las de §3 y §5.

### 7.4. Métricas del dashboard (con alineación explícita)

Releídas con `aggregation` explícita, que es lo que hace el dashboard. Las
cifras de esta tabla sustituyen a las de la primera lectura del informe, que
sumaba puntos crudos sin alinear.

| Métrica | Alineación | Resultado | Contraste |
| --- | --- | --- | --- |
| `run/request_count` | `ALIGN_DELTA` 60 s + `REDUCE_SUM` | **6.001** · pico **275/min** a las 11:30 · media 98,4/min | exacto (6.000 + sondeo del preflight) |
| `run/request_latencies` | `ALIGN_PERCENTILE_50/95/99` | **p50 5,06 ms · p95 9,62 ms · p99 11,22 ms** | lado plataforma |
| `run/container/instance_count` | `ALIGN_MAX` | **1 `active`, 1 `idle`** | `max_instances=1` |
| `cloudpulse_requests_by_outcome` | `ALIGN_DELTA` 60 s + `REDUCE_SUM` | **6.002** | verdad 6.001 (+1) |
| `cloudpulse_client_errors` | 1 h | 493 · `400` 253, `404` 193, `409` 47 | exacto con el sondeo |
| `cloudpulse_server_errors` | 1 h | 130, todos `simulated_failure` | exacto |
| `cloudpulse_order_amount` | 1 h | 12 segmentos · importe medio ≈254 | 2.662 creaciones |

**Los cuatro paneles del dashboard tienen datos**: tráfico, latencia, escalado y
errores por outcome.

#### Resuelto: el descuadre de +36 era de agregación, no de datos

La primera lectura de `cloudpulse_requests_by_outcome` daba 6.037. Comparando
alineaciones sobre la misma métrica:

| Alineación | Suma | Desvío sobre la verdad (6.001) |
| --- | --- | --- |
| `60s` | **6.002** | +1 (0,02 %) |
| `3600s` | 6.037 | +36 (0,60 %) |

El bucket de una hora asigna puntos enteros de 60 s a un lado u otro del borde.
Queda demostrado que **los datos de la métrica son correctos** y que el
descuadre venía de leerla con una ventana de agregación demasiado ancha. Para
cifras exactas, los logs; para tendencias, el dashboard.

Tres latencias del mismo viaje, todas medidas: **0,187 ms** dentro de `handle`,
**5,06 ms** dentro de Cloud Run, **81,2 ms** desde el cliente. El p50 del cliente
es ~16× el de la plataforma y ~434× el de la función: este experimento mide
sobre todo red.

### 7.5. Las siete consultas SQL

Auditadas contra la vista desplegada y preparadas para ejecución manual en
`outputs/reports/log-analytics-validation.md`, con el resultado esperado de cada
una calculado sobre los 6.000 eventos reales. Correcciones aplicadas a
`docs/log-analytics-queries.sql`:

| # | Problema | Corrección |
| --- | --- | --- |
| 1 | La cabecera describía un filtro de vista que no es el desplegado | Documentado el real (`resource.type="cloud_run_revision"`) con la cita de la referencia REST |
| 2 | El aviso del tiempo atribuía la desviación al truncado | Sustituido por el desvío de reloj medido (2,767 %) |
| 3 | La consulta 6 filtraba por `sim-000001`, que no existe: devolvía 0 filas | Ahora usa `sim-cc4f0755-000070` (un `409` real) y lista 6 identificadores, uno por código |
| 4 | 5b marca minutos de reloj completos, con la ventana desplazada ~1 min | Documentado, y añadida **5c** que autocalibra la ventana con el factor que revela la propia corrida |
| 5 | La fila `(sin categoría)` de 5a parece un fallo | Descompuesta: 355 eventos sin `category`, de los que 284 son errores intencionales que el backend no puede atribuir |

## 8. Desviaciones reales

### 8.1. La ventana duró 58 min 21 s, no 60 min

Primer envío 10:56:57,333 · último 11:55:17,846 → **3.501 s** de reloj para un
plan de 3.600 s.

La causa está medida, no supuesta: el desfase entre `sent_at` (reloj de pared) y
`scheduled_at` (reloj de pared en el arranque + offset del plan) crece
**linealmente** con el minuto programado, con pendiente **−1,6602 s por minuto**
(= **2,767 % de desvío**), intercepto 0,196 s y residuo máximo 485 ms. El
despachador se temporiza con `time.monotonic()` y la columna `scheduled_at` se
calcula con el reloj de pared: en WSL2 esos dos relojes avanzaron a ritmos
distintos durante la hora.

Consecuencia: el eje temporal está comprimido un 2,77 % de forma **uniforme**,
así que la forma de la campana se conserva exactamente. Medias y desviaciones
observadas frente a planificadas:

| | Media | Desviación |
| --- | --- | --- |
| Planificado | 29,918 min | 10,004 min |
| Observado | 29,094 min | 9,727 min |
| Ratio | **0,9724** | **0,9723** |

Los dos ratios coinciden en la cuarta cifra: un reescalado del eje, no una
deformación. **Para analizar la corrida, `sent_at` es la verdad y
`scheduled_min` es el plan; `scheduled_at` arrastra el desvío** (hasta −99,5 s
en las últimas solicitudes).

### 8.2. Degradaciones del pool: 5

Las 5 son del **minuto 0,00**, donde el truncado acumula 9 solicitudes
simultáneas: consultas y cancelaciones que salieron antes de que ninguna
creación hubiera sido *respondida*, así que apuntaron a identificadores
inexistentes y recibieron `404`. Están marcadas en la columna `fallback`, no se
cuentan como defecto y su `expected_status` se ajustó a 404 — por eso el CSV no
tiene ni una fila `unexpected`.

### 8.3. El escenario midió 1,83× en vez de 2,00×

Ver §6: −0,84σ, ruido de muestreo.

### 8.4. Pedidos tocados: 2.855 sobre 2.662 creados

`order_id` distintos en el CSV: 2.855 > 2.662 creaciones con `201`. La
diferencia son los identificadores inexistentes que el simulador inventa a
propósito (`ord_missing_NNNNNN`, 188 de ellos) para provocar los `404`.

## 9. Lo que no se pudo verificar

| # | Límite | Por qué |
| --- | --- | --- |
| 1 | Ejecución del SQL de Log Analytics | Requiere un *linked dataset* de BigQuery (infraestructura nueva, sin autorizar). Verificada la disponibilidad de los datos en la vista, no la ejecución |
| 2 | Lectura del presupuesto | Permisos o API `billingbudgets`; el preflight lo marca como aviso. El tope real de gasto son `max_instances=1` y la concurrencia |
| 3 | Que la renovación del token se ejecutara dos veces | Se demuestra por ausencia: `401`/`403` = **0** en toda la ventana según la métrica nativa, y el token inicial habría caducado ~11:56. Los fallos de renovación se imprimen al final de la corrida y el log no tiene ninguno. Pero el simulador no registra en vivo cada renovación con éxito — mejora pendiente |
| 4 | Captura visual del dashboard | No hay forma de tomarla desde la CLI; los datos de sus cuatro fuentes están verificados por la API de Monitoring (§7.4) |
| 5 | Que Log Analytics acepte `APPROX_QUANTILES` y la función de ventana de la consulta 2 | Solo se comprueba ejecutándola; hay variante de respaldo en el documento de validación |

### Pendiente de validación manual

Las 20 capturas y las 8 ejecuciones de consulta están especificadas, con su
resultado esperado, en `outputs/reports/log-analytics-validation.md` §5 y §2.
Resumen de lo que requiere a una persona delante de la consola:

| # | Requisito | Evidencia esperada |
| --- | --- | --- |
| M1 | Ejecutar las 8 consultas en Log Analytics | Cada resultado debe coincidir con los valores precalculados (§2 del documento de validación) |
| M2 | Capturar los 7 paneles del dashboard | C1–C7 |
| M3 | Capturar las 8 consultas | C8–C15 |
| M4 | Capturar la infraestructura y la trazabilidad | C16–C20, incluida la política IAM **sin `allUsers`** |
| M5 | Lectura del presupuesto | Pendiente por permisos |

## 10. Riesgos y pendientes

1. **Los recursos siguen vivos y facturando** mientras existan: función, bucket del código, bucket de logs (30 días de retención), sink, 4 métricas, dashboard e **imágenes de Artifact Registry que `terraform destroy` no se lleva**. Procedimiento de limpieza en `docs/guide.md` §11. **No se ha ejecutado ninguna limpieza.**
2. **El desvío de reloj de WSL2** volverá a comprimir cualquier corrida futura. Si la duración exacta importa, hay que temporizar el despachador contra el reloj de pared o medir el desvío antes.
3. **Reportar las renovaciones de token en vivo** (y los fallos en el momento, no al final) para que una corrida larga sea supervisable de verdad.
4. **El filtro de la Log View puede endurecerse** con `AND LOG_ID("run.googleapis.com/stdout")`: la corrida confirmó que los eventos están en ese log. Requiere `terraform apply` (update in-place).
5. **El escalamiento horizontal sigue sin observarse**: con `max_instances=1` el panel de instancias es plano. Medirlo exige almacenamiento compartido en lugar del diccionario en memoria.
6. **La corrida no es repetible gratis**: las métricas basadas en logs no rellenan el pasado, así que una segunda corrida necesita que las métricas sigan existiendo (lo siguen) y volvería a generar tráfico facturable.

## 11. Restricciones respetadas

| Restricción | Cumplida |
| --- | --- |
| Una sola corrida oficial, sin compresión ni `--quick` | ✅ `--renew-token`, 3.600 s de plan, `seconds_per_minute=60` |
| Sin corridas adicionales | ✅ Única petición ajena a la corrida: el sondeo del preflight (1) |
| No ejecutar `terraform apply` / `destroy` | ✅ |
| No modificar IAM, facturación ni el backend | ✅ La función siguió privada todo el tiempo; el tráfico fue autenticado con token de identidad |
| No crear commits | ✅ HEAD sigue en `5f2aed0` |
| No limpiar recursos | ✅ Detenido antes de cualquier limpieza |
