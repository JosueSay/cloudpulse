# CloudPulse — Guion de presentación y preflight de pruebas adicionales

Documento de apoyo para la clase. Las cifras provienen de la corrida oficial
`cc4f0755` (2026-10-16) y están contrastadas con `outputs/simulator/requests.csv`,
Cloud Logging y la API de Cloud Monitoring. El informe completo, con las diez
evidencias, está en `outputs/reports/cloudpulse-final-report.md`.

## Parte 1 — Guion de presentación

### 1. Arquitectura (1 minuto)

Tres piezas y un hilo que las cose:

| Pieza | Qué es |
| --- | --- |
| **Simulador** | Python con HTTPX y NumPy: genera el tráfico según una normal y escribe `requests.csv` |
| **API** | Cloud Run functions gen 2, runtime `python313`, tres operaciones de pedidos, un evento JSON por solicitud |
| **Observabilidad** | Terraform: bucket regional con Log Analytics, sink, vista, 4 métricas basadas en logs, 3 métricas nativas y un dashboard |

El hilo es **`X-Request-ID`**: el simulador lo genera, la API lo devuelve y lo
registra, y permite unir las tres superficies —plan, ejecución y análisis—.

> Frase para decir en voz alta: *«La función es privada. Las 6.000 solicitudes
> se autenticaron con tokens de identidad renovados cada 30 minutos; nunca se
> concedió acceso a `allUsers`.»*

### 2. Metodología (1 minuto)

| Parámetro | Valor |
| --- | --- |
| Solicitudes | 6.000 |
| Llegadas | `N(mu=30, sigma=10)` minutos, truncada a `[0, 60]`, semilla 42 |
| Errores intencionales | 8 % (`invalid_share`) |
| Escenario | `double_errors` en `[35, 45)` sobre `electronics` |
| Fallo inyectado en el backend | 2 % (`FAILURE_RATE`) |
| Operaciones | crear 50 % · consultar 30 % · cancelar 20 % |
| Concurrencia | una tarea `asyncio` por solicitud, pool de 50 conexiones |

El plan es **determinista**: la misma configuración y la misma semilla producen
siempre el mismo experimento, y puede inspeccionarse sin enviar tráfico
(`--dry-run`).

### 3. Resultados (2 minutos)

| Indicador | Resultado |
| --- | ---: |
| Solicitudes enviadas y registradas | **6.000 / 6.000** |
| HTTP 2xx | 5.378 (89,63 %) |
| HTTP 4xx | 492 (8,20 %) |
| HTTP 5xx | 130 (2,17 %) |
| Errores de transporte y timeouts | **0** |
| Respuestas inesperadas | **0** |
| Correlación CSV ↔ Cloud Logging | **6.000 / 6.000**, sin discrepancias de estado |
| Excepciones no controladas en el backend | **0** |

> Frase: *«El 8,20 % de errores de cliente frente al 8 % configurado, y el
> 2,17 % de errores de servidor frente al 2 % inyectado. El experimento hizo lo
> que dijo que iba a hacer.»*

### 4. La campana de Gauss (1 minuto)

| Medida | Planificado | Teórico |
| --- | ---: | ---: |
| Media | 29,918 min | 30 |
| Desviación | 10,004 min | 10 |
| Dentro de μ±σ | 68,68 % | 68,27 % |
| Dentro de μ±2σ | 95,38 % | 95,45 % |

```text
[ 0-10):  142   ██
[10-20):  820   ███████████
[20-30): 2014   ███████████████████████████
[30-40): 2107   ████████████████████████████
[40-50):  782   ██████████
[50-60):  135   ██
```

**Mostrar la figura 9** (dashboard): el panel 1 dibuja esa misma campana en
tiempo real, con un pico de **275 solicitudes por minuto** hacia el minuto 30.

> Matiz honesto que conviene decir: *«La ventana se planificó para 60 minutos y
> la ejecución duró 58 minutos y 21 segundos, por un desvío de reloj del 2,767 %
> del entorno. La forma de la campana no cambia: media y desviación observadas
> salen escaladas por el mismo factor, 0,9724 y 0,9723.»*

### 5. Errores simulados (1-2 minutos)

Tres familias, todas intencionales, ninguna es un defecto:

| Familia | Mecanismo | Código | Medido |
| --- | --- | --- | ---: |
| Payload incorrecto | 6 variantes, una por regla del esquema | 400 | 253 |
| Identificador inexistente | `ord_missing_NNNNNN`, inventado por el simulador | 404 | 192 |
| Secuencia imposible | Cancelar lo ya cancelado | 409 | 47 |

Y aparte, **inyectados por el backend**: 130 respuestas `500`, todas con
`error_type = simulated_failure`. **Cero** con `unhandled_exception`.

**Escenario `double_errors`:** 355 solicitudes etiquetadas; `electronics` dentro
de la ventana al **14,37 %** frente al **7,86 %** fuera, es decir **1,83×** sobre
el objetivo de 2,00×. La diferencia es ruido de muestreo (−0,84σ), no un fallo:
la probabilidad sí se duplica exactamente.

> Frase: *«Un 500 nunca se cuenta como error intencional del cliente, aunque la
> solicitud fuese defectuosa. El backend inyecta el fallo antes de validar, y el
> registro los separa.»*

### 6. Latencias: tres miradores (1 minuto)

| Punto de medición | p50 | p95 | Qué incluye |
| --- | ---: | ---: | --- |
| **Cliente** | **81,2 ms** | **192,8 ms** | internet, TLS, proxy y función |
| **Cloud Run** | 5,06 ms | 9,62 ms | el tramo dentro de la plataforma |
| **Función** | 0,187 ms | 0,376 ms | solo el interior de `handle` |

> Frase: *«El 99,8 % de lo que mide el cliente ocurre fuera de la función. Este
> experimento mide sobre todo la red; por eso el dashboard las presenta en
> paneles separados y no las mezcla.»*

### 7. Limitaciones (1 minuto, no omitir)

| Limitación | Consecuencia |
| --- | --- |
| **`max_instances = 1`** | **No se puede demostrar escalamiento horizontal**: el panel de instancias es una línea plana en 1 |
| Almacén en memoria | Es la razón del techo anterior: con dos instancias, lecturas legítimas darían `404` |
| Desvío de reloj del entorno | La ejecución duró 58 min 21 s en lugar de 60 |
| Latencia dominada por la red | La latencia de la función es tres órdenes de magnitud menor que la del cliente |
| Sin *linked dataset* de BigQuery | Las consultas SQL solo se ejecutan desde la consola |
| Filtro de la vista poco selectivo | La vista incluye auditoría y sistema; cada consulta debe filtrar por `message` |

> Cierre sugerido: *«La observabilidad cumple lo que se le pidió: completitud
> —6.000 solicitudes, 6.000 eventos—, trazabilidad por identificador y
> separación entre error intencional y defecto. Lo que no demuestra, y lo decimos
> explícitamente, es el escalamiento horizontal.»*

### Orden sugerido de figuras

1. **Figura 9** (dashboard completo) — para situar.
2. **Figura 1 o el panel 1** — la campana.
3. **Figura 3** — los siete grupos de error, sin `unhandled_exception`.
4. **Figura 7** — el escenario medido sin ambigüedad (5c).
5. **Figura 8** — trazabilidad de una solicitud concreta por `X-Request-ID`.
6. **Figura 10** — el panel de logs con `severity >= WARNING`.

## Parte 2 — Preflight para las pruebas adicionales

Lista de comprobación **antes** de cualquier prueba nueva que indique el
catedrático. No ejecutar nada de esto todavía.

### Paso 0 — Comprobación automática

```bash
bash scripts/preflight.sh
```

Debe terminar en `PREFLIGHT OK`. Verifica en un solo paso: configuración del
simulador, 265 pruebas locales, identidad y facturación, estado de la función,
**ausencia de `allUsers`**, autenticación real (envía una sola petición de
sondeo) y que las cuatro métricas basadas en logs existan.

### Paso 1 — Decidir y anotar qué cambia

| Si la prueba pide… | Ajustar | Dónde |
| --- | --- | --- |
| Menos tráfico | `--n-requests N` | línea de comandos |
| Una ventana más corta | `--seconds-per-minute S` (comprime el reloj) | línea de comandos |
| Otra tasa de error del cliente | `invalid_share` | `simulator/config.json` |
| Otra tasa de fallo del servidor | `FAILURE_RATE` | variable de entorno de la función (**requiere `terraform apply`**) |
| Latencia artificial | `EXTRA_LATENCY_MS` | ídem |
| Otro escenario temporal | bloque `scenarios` | `simulator/config.json` |
| Ver escalamiento | `max_instances` | `infra/terraform.tfvars` (**requiere `apply` y rompe la coherencia del almacén en memoria**) |

> Cualquier cambio en la función —`FAILURE_RATE`, `EXTRA_LATENCY_MS`,
> `max_instances`, memoria— **exige `terraform apply` y autorización explícita**.
> Los cambios de la columna «línea de comandos» y de `config.json` no tocan la
> nube.

### Paso 2 — Antes de lanzar

- [ ] `PREFLIGHT OK` con fecha del día de la prueba.
- [ ] **Salvaguardar el CSV anterior**: `outputs/simulator/requests.csv` se
  sobrescribe. Copiarlo con otro nombre si la corrida oficial debe conservarse.
- [ ] Elegir un `--run-id` distinto (p. ej. `--run-id clase01`) para que los
  `X-Request-ID` no se confundan con los de la corrida oficial en Cloud Logging.
- [ ] Fijar un `--output` propio, p. ej. `outputs/simulator/requests_clase01.csv`.
- [ ] Decidir la autenticación: `--renew-token` para cualquier corrida de más de
  media hora; el token fijo solo para pruebas cortas.
- [ ] Confirmar que las métricas basadas en logs ya existen: **una métrica no
  cuenta entradas anteriores a su creación**, así que crear métricas nuevas
  después del tráfico obliga a repetir la corrida.
- [ ] Anotar la hora UTC de inicio: hace falta para la ventana temporal de todas
  las consultas SQL.

### Paso 3 — Durante la prueba

- [ ] Vigilar `401`/`403`: indicarían que la autenticación falló.
- [ ] Vigilar errores de transporte: más de unos pocos sugieren problema de red
  o de la función, no del experimento.
- [ ] Vigilar que la tasa de `500` se parezca a `FAILURE_RATE`; una desviación
  grande merece investigarse antes de seguir.

### Paso 4 — Después

- [ ] Comprobar el número de filas del CSV.
- [ ] Sustituir la ventana temporal en las consultas de
  `docs/log-analytics-queries.sql` por la de la nueva corrida:

  ```sql
  AND timestamp >= TIMESTAMP('AAAA-MM-DD HH:MM:SS+00')   -- inicio
  AND timestamp <= TIMESTAMP('AAAA-MM-DD HH:MM:SS+00')   -- fin
  ```

  **Las ocho consultas la llevan**; en 5a, 5b y 5c va en las **dos**
  subconsultas, porque `run` fija el origen del eje temporal. Olvidarla en `run`
  fue el defecto documentado en §7.3 del informe final.
- [ ] Contrastar el CSV con Cloud Logging por `X-Request-ID`.
- [ ] Guardar las capturas nuevas en `outputs/reports/evidence/` con nombre
  propio, sin sobrescribir las diez de la corrida oficial.

### Lo que no se debe hacer sin autorización explícita

- `terraform apply` o `terraform destroy`.
- Conceder `roles/run.invoker` a `allUsers` (haría pública la función).
- Modificar IAM, facturación o el presupuesto.
- Borrar logs, métricas, buckets o el dashboard.
- Lanzar una corrida de 6.000 solicitudes adicional sin acordarlo: genera
  tráfico facturable y vuelve a escribir sobre el CSV oficial.

### Recordatorio de costos

El laboratorio sigue desplegado. La función, los dos buckets, el sink, las
cuatro métricas, el dashboard y **las imágenes de Artifact Registry —que
`terraform destroy` no elimina—** siguen existiendo y facturando mientras no se
limpien. El presupuesto de US$5 **alerta pero no suspende nada**. El
procedimiento de limpieza está en `docs/guide.md` §11 y **no se ha ejecutado**.
