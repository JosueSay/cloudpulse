# CloudPulse — Guía de instalación y configuración

Documentación del proceso de preparación, desarrollo y despliegue de una API serverless observable en Google Cloud Platform (GCP).

## 1. Descripción del proyecto

**CloudPulse** es un laboratorio de observabilidad que consiste en desarrollar y desplegar una API HTTP serverless en Google Cloud, generar tráfico simulado y analizar su comportamiento mediante métricas, registros estructurados y dashboards.

### Tecnologías

| Tecnología | Propósito |
| --- | --- |
| Python 3.13 | Desarrollo de API y simulador (coincide con el runtime `python313`) |
| uv | Gestión de dependencias y entorno virtual |
| Terraform (HCL) | Infraestructura como código |
| Google Cloud Run functions | Ejecución serverless de API |
| Cloud Logging | Registros estructurados |
| Cloud Monitoring | Métricas y dashboards |
| Git | Control de versiones |
| WSL2 | Entorno de desarrollo Linux |

## 2. Estructura del proyecto

Se creó el repositorio `cloudpulse` con una estructura modular que separa la API, el simulador de tráfico, la infraestructura, las pruebas, la documentación y los archivos generados.

```text
cloudpulse/
├── .agents/
│   ├── agents/
│   └── skills/
├── .env.example
├── .gitignore
├── .python-version
├── AGENTS.md
├── Makefile
├── README.md
├── backend/
│   ├── main.py
│   └── requirements.txt
├── docs/
│   ├── architecture.md
│   ├── guide.md
│   ├── log-analytics-queries.sql
│   └── observability.md
├── infra/
│   ├── dashboards/
│   │   └── orders-api.json.tftpl
│   ├── logging.tf
│   ├── main.tf
│   ├── monitoring.tf
│   ├── outputs.tf
│   ├── terraform.tfvars
│   ├── variables.tf
│   └── versions.tf
├── keys/
│   └── .gitkeep
├── outputs/
│   ├── logs/
│   │   ├── .gitkeep
│   │   └── estructura.log
│   ├── reports/
│   │   └── .gitkeep
│   ├── simulator/
│   │   └── .gitkeep
│   └── terraform/
│       └── .gitkeep
├── pyproject.toml
├── scripts/
│   └── extensions.sh
├── simulator/
│   ├── config.json
│   └── simulator.py
├── skills-lock.json
├── tests/
│   ├── conftest.py
│   ├── test_concurrency.py
│   ├── test_failure_injection.py
│   ├── test_observability.py
│   ├── test_orders_api.py
│   ├── test_simulator_api_contract.py
│   ├── test_simulator_cli.py
│   ├── test_simulator_config.py
│   ├── test_simulator_plan.py
│   ├── test_simulator_runtime.py
│   └── test_validation.py
└── uv.lock
```

*Nota:* Se omiten del árbol algunos archivos ocultos, directorios temporales y contenidos internos de los agentes para mantener la representación legible.

### 2.1. Organización de directorios

| Directorio | Propósito |
| --- | --- |
| `.agents/agents/` | Agentes especializados para desarrollo, infraestructura, observabilidad y revisión. |
| `.agents/skills/` | Skills locales reutilizables para pruebas, depuración y verificación. |
| `.claude/skills/` | Enlace simbólico a `.agents/skills/` para que Claude Code descubra las skills locales sin instalarlas de forma global. |
| `backend/` | Implementación de la API HTTP serverless. |
| `docs/` | Documentación técnica, guía de configuración y consultas SQL de Log Analytics. |
| `infra/` | Definición declarativa de infraestructura mediante Terraform. |
| `keys/` | Directorio reservado para credenciales locales excepcionales, excluidas del control de versiones. |
| `outputs/` | Directorio centralizado para archivos generados durante el desarrollo y la ejecución. |
| `simulator/` | Simulación de tráfico HTTP y escenarios de errores. |
| `tests/` | Pruebas automatizadas del proyecto. |

### 2.2. Organización de archivos generados

Se estableció `outputs/` como ubicación centralizada para los resultados generados por las herramientas del proyecto.

- `outputs/logs/`: registros y archivos de diagnóstico, incluido `estructura.log`.
- `outputs/reports/`: reportes y resultados de análisis.
- `outputs/simulator/`: resultados de simulación, incluido el futuro `requests.csv`.
- `outputs/terraform/`: planes de ejecución y otros artefactos temporales de Terraform.

Cada subdirectorio contiene un archivo `.gitkeep` para conservar su estructura en Git sin versionar los archivos generados.

Los archivos de estado de Terraform permanecen excluidos del repositorio y no deben tratarse como simples reportes, ya que pueden contener información sensible.

### 2.3. Configuración y dependencias

| Archivo | Propósito |
| --- | --- |
| `AGENTS.md` | Instrucciones, responsabilidades y restricciones para agentes de IA. |
| `Makefile` | Atajos de desarrollo: `test`, `lint`, `format`, `check`, `infra-fmt`, `infra-validate`. |
| `skills-lock.json` | Registro de las skills instaladas y sus versiones o referencias. |
| `.env.example` | Plantilla de parámetros locales no sensibles. |
| `.gitignore` | Exclusión de credenciales, entornos virtuales, estados de Terraform y archivos generados. |
| `.python-version` | Versión de Python seleccionada para el proyecto. |
| `pyproject.toml` | Metadatos y dependencias Python administradas con uv. |
| `uv.lock` | Resolución reproducible de dependencias. |
| `README.md` | Descripción general y punto de entrada del repositorio. |

### 2.4. Convenciones de desarrollo

- Separar código fuente, infraestructura, configuración y resultados generados.
- Centralizar los artefactos de ejecución en `outputs/`.
- Versionar archivos de configuración de ejemplo, nunca credenciales.
- Utilizar `.gitkeep` para conservar directorios que deban existir inicialmente vacíos.
- Mantener `uv.lock`, `skills-lock.json` y `.terraform.lock.hcl` bajo control de versiones.
- Utilizar `AGENTS.md` y las skills locales como referencia para el desarrollo asistido por IA.
- Instalar las skills únicamente en el proyecto (`.agents/skills/`), nunca en la configuración global del agente, y exponerlas a Claude Code mediante el enlace relativo `.claude/skills`.
- Mantener parámetros de infraestructura en Terraform y parámetros locales no sensibles en archivos de configuración.
- Evitar duplicar configuraciones y rutas mediante constantes dispersas en el código.

**Adaptación del laboratorio:** El archivo `requests.csv`, originalmente previsto en `simulator/`, se generará en `outputs/simulator/`; esta ruta deberá configurarse explícitamente durante la implementación del simulador.

### 2.5 Seguridad

- No almacenar credenciales en Git.
- No permitir a los agentes acceder a `keys/` ni a archivos sensibles.
- No utilizar `.env` para almacenar secretos.
- Utilizar Application Default Credentials (ADC) para autenticación local con Google Cloud.
- Preferir Google Secret Manager cuando se necesiten secretos en la aplicación.
- Excluir archivos `.tfstate`, credenciales y archivos generados del control de versiones.
- Requerir aprobación explícita antes de ejecutar operaciones de infraestructura.

**Nota:** Las instrucciones de `AGENTS.md` no sustituyen los controles de acceso del sistema operativo ni el aislamiento de herramientas.

## 3. Configuración de Python con uv

> **Nota (fase 1 del backend):** el proyecto se alineó a **Python 3.13** para
> coincidir con el runtime `python313` del laboratorio. `.python-version` ahora
> contiene `3.13` y `pyproject.toml` declara
> `requires-python = ">=3.13,<3.14"`; el entorno virtual usa el CPython 3.13
> del sistema (`/usr/bin/python3.13`). Los comandos y salidas de esta sección
> se conservan tal como se ejecutaron originalmente con 3.12: sustituye `3.12`
> por `3.13` al reproducirlos.

### 3.1. Seleccionar la versión de Python

Desde la raíz del repositorio:

```bash
uv python pin 3.12
```

Esto genera o actualiza `.python-version`:

```text
3.12
```

### 3.2. Inicialización del proyecto

Se intentó ejecutar:

```bash
uv init --bare --python 3.12
```

El comando indicó que el proyecto ya estaba inicializado porque existía `pyproject.toml`.

No es necesario volver a ejecutar `uv init` cuando el proyecto ya dispone de este archivo.

### 3.3. Generar el archivo de bloqueo

Al ejecutar inicialmente:

```bash
uv sync --python 3.12
```

Se produjo un error porque `uv.lock` no tenía un formato válido.

La solución fue regenerarlo:

```bash
rm uv.lock
uv lock --python 3.12
uv sync --python 3.12
```

`uv` creó el entorno virtual `.venv` utilizando CPython 3.12.11.

### 3.4. Activar el entorno virtual

En WSL2:

```bash
source .venv/bin/activate
```

Para desactivarlo:

```bash
deactivate
```

También se puede ejecutar Python sin activar manualmente el entorno:

```bash
uv run python
```

### 3.5. Verificar el aislamiento

Se ejecutaron los siguientes comandos:

```bash
which python
which pip
uv pip list
```

Resultados:

```bash
which python
/home/josue/portfolio/own/cloudpulse/.venv/bin/python

which pip
/usr/bin/pip

uv pip list
# Sin paquetes instalados
```

Esto confirma que el intérprete Python del proyecto pertenece a `.venv`, mientras que el comando `pip` disponible corresponde a la instalación global del sistema.

La lista vacía de `uv pip list` confirma que todavía no se han instalado dependencias en el entorno virtual.

### 3.6. Gestión de dependencias

Para agregar dependencias utilizaremos:

```bash
uv add nombre-paquete
```

Para dependencias de desarrollo:

```bash
uv add --dev nombre-paquete
```

Para sincronizar el entorno:

```bash
uv sync
```

Se utilizará `pyproject.toml` como declaración principal de dependencias y `uv.lock` para reproducir las versiones instaladas.

## 4. Instalación de Terraform y Google Cloud CLI en WSL2

Instalaremos ambas herramientas dentro de WSL2 (Ubuntu), utilizando los repositorios oficiales de HashiCorp y Google Cloud.

### 4.1. Instalar Terraform

Ejecuta los siguientes comandos:

```bash
sudo apt update
sudo apt install -y gnupg software-properties-common curl
```

Agrega la clave de HashiCorp:

```bash
wget -O- https://apt.releases.hashicorp.com/gpg | \
gpg --dearmor | \
sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null
```

Agrega el repositorio:

```bash
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
sudo tee /etc/apt/sources.list.d/hashicorp.list
```

Instala Terraform:

```bash
sudo apt update
sudo apt install -y terraform
```

Verifica:

```bash
terraform version
```

### 4.2. Instalar Google Cloud CLI

Instala los requisitos:

```bash
sudo apt install -y apt-transport-https ca-certificates gnupg curl
```

Agrega la clave oficial de Google Cloud:

```bash
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
```

Agrega el repositorio:

```bash
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | \
sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
```

Instala Google Cloud CLI:

```bash
sudo apt update
sudo apt install -y google-cloud-cli
```

Verifica:

```bash
gcloud version
```

## 5. Configuración de Google Cloud Platform (GCP)

El siguiente paso es autenticar Google Cloud CLI y configurar el proyecto donde desplegaremos CloudPulse.

### 5.1. Iniciar sesión en Google Cloud

Desde WSL2, ejecuta:

```bash
gcloud auth login
```

Se abrirá el navegador para iniciar sesión con tu cuenta de Google.

### 5.2. Configurar Application Default Credentials (ADC)

Terraform utilizará estas credenciales para administrar la infraestructura:

```bash
gcloud auth application-default login
```

En WSL2, si el navegador no se abre automáticamente, puedes utilizar la URL que aparezca en la terminal.

Las credenciales se almacenan localmente fuera del repositorio.

### 5.3. Consultar proyectos disponibles

```bash
gcloud projects list
```

Si ya tienes un proyecto de GCP, identifica su `PROJECT_ID`.

Si todavía no tienes uno, lo crearemos en el siguiente paso.

### 5.4. Crear el proyecto CloudPulse

Ejecuta en WSL2:

```bash
gcloud projects create cloudpulse-lab-2026 --name="CloudPulse"
```

El `PROJECT_ID` debe ser único globalmente; si ya existe, tendremos que elegir otro.

### 5.5. Configurar el proyecto activo

Cuando la creación termine correctamente:

```bash
gcloud config set project cloudpulse-lab-2026
gcloud auth application-default set-quota-project cloudpulse-lab-2026
```

El segundo comando puede requerir permisos adicionales sobre el proyecto.

### 5.6. Verificar la configuración

```bash
gcloud config get-value project
gcloud projects describe cloudpulse-lab-2026
```

Importante: Antes de desplegar Terraform necesitaremos vincular una cuenta de facturación y configurar un presupuesto con alertas; el presupuesto no bloquea automáticamente el gasto.

El proyecto `cloudpulse-lab-2026` se creó correctamente y está activo; Google Cloud CLI y ADC ya están configurados.

El siguiente paso es vincular una cuenta de facturación y configurar alertas de presupuesto antes de desplegar infraestructura.

### 5.7. Verificar facturación

Ejecuta:

```bash
gcloud billing projects describe cloudpulse-lab-2026
```

Si `billingEnabled` aparece como `false`, debes vincular una cuenta de facturación desde [Google Cloud Billing](https://console.cloud.google.com/billing).

### 5.8. Configurar presupuesto en Google Cloud

Desde **Google Cloud Console → Billing → Budgets & caps**, crear un presupuesto para controlar los costos del laboratorio.

**1. Definir**

- Modalidad: `Solo alertas`.
- Nombre: `cloudpulse-lab-2026`.

**2. Alcance**

- Período: `Por mes`.
- Proyecto: `cloudpulse-lab-2026` exclusivamente.
- Servicios: `Todos los servicios`.
- Ahorros: mantener las opciones predeterminadas.

**3. Importe**

- Tipo de presupuesto: `Importe especificado`.
- Importe objetivo: `US$5`.

**4. Acciones**

Configurar las alertas según el gasto real:

| Umbral | Importe | Activación |
| --- | --- | --- |
| 50 % | US$2.50 | Real |
| 90 % | US$4.50 | Real |
| 100 % | US$5.00 | Real |

Habilitar las notificaciones por correo electrónico para administradores de facturación y usuarios; opcionalmente, también para propietarios del proyecto.

Finalmente, seleccionar **Finalizar** para guardar el presupuesto.

**Consideraciones:** El presupuesto de US$5 es una referencia mensual, no un límite obligatorio de consumo. Las alertas pueden llegar con retraso y no suspenden automáticamente los servicios cuando se alcanza el importe configurado.

### 5.9. Verificar facturación y permisos de Google Cloud

Antes de configurar Terraform, verificaremos que `cloudpulse-lab-2026` tenga facturación activa y que tu cuenta pueda administrar los recursos.

#### 5.9.1. Verificar facturación

Ejecuta desde WSL2:

```bash
gcloud billing projects describe cloudpulse-lab-2026
```

El resultado debe contener:

```bash
billingEnabled: true
```

#### 5.9.2. Verificar el proyecto activo

```bash
gcloud config get-value project
```

Resultado esperado:

```bash
cloudpulse-lab-2026
```

#### 5.9.3. Verificar los permisos

```bash
gcloud projects get-iam-policy cloudpulse-lab-2026 \
  --format="table(bindings.role)"
```

Esto permite revisar los roles asignados al proyecto, aunque no muestra todos los permisos efectivos heredados.

## 6. Simulador de tráfico HTTP (fase 2)

El simulador (`simulator/simulator.py`) genera el experimento de tráfico contra la API de pedidos: 6.000 solicitudes distribuidas en 60 minutos según una normal centrada en el minuto 30, con un 8 % de errores intencionales del cliente y un escenario que duplica esa proporción para `electronics` entre los minutos 35 y 45.

### 6.1. Configuración

Todos los parámetros viven en `simulator/config.json`; el módulo no contiene valores del experimento incrustados en el código.

| Clave | Valor | Propósito |
| --- | --- | --- |
| `target_url` | `http://localhost:8080` | Base de la API de pedidos. |
| `n_requests` | `6000` | Solicitudes totales. |
| `mu_min` / `sigma_min` | `30` / `10` | Parámetros de la normal, en minutos. |
| `duration_min` | `60` | Ventana a la que se truncan los instantes. |
| `seconds_per_minute` | `60` | Segundos de reloj por minuto simulado; `60` mantiene el tiempo real. |
| `invalid_share` | `0.08` | Proporción base de errores intencionales. |
| `seed` | `42` | Semilla reproducible. |
| `operation_mix` | `0.5 / 0.3 / 0.2` | Mezcla de crear, consultar y cancelar. |
| `output_csv` | `../outputs/simulator/requests.csv` | Ruta del CSV, relativa al archivo de configuración. |
| `timeout_s` | `10.0` | Tiempo máximo por solicitud. |
| `token_refresh_s` | `1800` | Cada cuántos segundos se renueva el token de identidad con `--renew-token`. Un token vive ~1 h y la corrida dura 60 min, así que renovar a los 30 min lo mantiene siempre en su primera mitad de vida. |
| `max_connections` | `50` | Tope del pool de conexiones. |
| `quick` | `n_requests 30`, `seconds_per_minute 0.05` | Preajuste de la prueba rápida. |
| `scenarios` | `double_errors [35, 45) · electronics` | Escenario del laboratorio. |

La validación rechaza claves desconocidas, rangos imposibles y escenarios que se salgan de la ventana, de modo que una configuración mal escrita falla al arrancar en lugar de producir un experimento silenciosamente distinto.

### 6.2. Ejecución

Inspeccionar el plan sin enviar una sola solicitud:

```bash
uv run python simulator/simulator.py --dry-run
```

Prueba rápida (30 solicitudes en unos 3 segundos):

```bash
uv run python simulator/simulator.py --quick \
  --target-url http://localhost:8088 \
  --output outputs/simulator/requests_quick.csv
```

Corrida oficial de 60 minutos (requiere la API desplegada y las métricas basadas en logs ya creadas):

```bash
uv run python simulator/simulator.py --renew-token --target-url <URL de Cloud Run>
```

`--renew-token` es **obligatorio contra la función privada**: mina un token de
identidad al arrancar y lo renueva cada `token_refresh_s`. Sin él, un token
único caducaría a la hora y las últimas solicitudes de los 60 minutos
recibirían `401`. Ver §6.7.

Cada parámetro tiene su bandera equivalente (`--n-requests`, `--seconds-per-minute`, `--seed`, `--timeout`, `--max-connections`, `--output`, `--run-id`), lo que permite ensayar sin modificar el archivo del laboratorio.

Para levantar la función localmente:

```bash
uv run functions-framework --target handle --source backend/main.py --port 8088
```

*Nota:* el puerto 8080 del laboratorio puede estar ocupado por otro servicio local; en ese caso se usa otro puerto y se pasa `--target-url`.

### 6.3. Diseño

- **Plan determinista.** `build_plan` deriva de `(config, run_id)` los instantes, la operación, el segmento de negocio y la intención de cada solicitud. Los instantes se truncan con `clip` al intervalo `[0, 60]` —no se descartan— así que el plan conserva exactamente `n_requests` filas a cambio de una acumulación de aproximadamente 0,13 % del tráfico en cada extremo.
- **Concurrencia.** Un único `httpx.AsyncClient` y una tarea `asyncio` por solicitud. El despachador solo duerme hasta el siguiente instante programado: nunca espera la respuesta anterior, por lo que una respuesta lenta no retrasa el resto del calendario. La simultaneidad la limita el pool de conexiones (`max_connections`), no el despachador.
- **Errores intencionales.** Se generan de tres formas, todas verificadas contra la API real: payloads inválidos (seis variantes, una por regla del esquema) para `400`, identificadores inexistentes para `404` y una secuencia imposible —cancelar lo ya cancelado— para `409`.
- **Identificadores de pedido.** Lo único que no se puede planificar es qué pedido toca cada consulta o cancelación, porque solo existe cuando un `POST` ha sido respondido. Un pool alimentado por las respuestas resuelve eso en tiempo de envío; si todavía está vacío, la solicitud cae a un identificador inexistente y la fila lo declara en `fallback`, de modo que ese `404` no se confunde con un defecto.
- **Correlación.** Cada solicitud lleva un `X-Request-ID` único (`sim-<run_id>-<índice>`), dentro del juego de caracteres y la longitud que la API acepta sin sanear.

### 6.4. Resultados: `requests.csv`

Una fila por solicitud, escrita y descargada a disco en cuanto la solicitud termina, para que una corrida interrumpida conserve lo ya medido. Las filas quedan en orden de finalización; `scheduled_at` y `scheduled_min` restituyen el orden cronológico.

| Campo | Contenido |
| --- | --- |
| `request_id` | Identificador de correlación enviado en la cabecera. |
| `scheduled_at` / `sent_at` | Instante programado y instante real de envío, en UTC. |
| `operation` / `intended_event` | Operación y lo que la solicitud pretendía provocar. |
| `status_code` | Código recibido; vacío si no hubo respuesta. |
| `client_latency_ms` | Latencia medida por el cliente. |
| `intent` / `expected_status` / `result` | Intención (`valid`/`invalid`), código esperado y comparación (`as_expected`, `unexpected`, `server_error`, `transport_error`). |
| `order_id` | Pedido afectado; para una creación, el identificador que devolvió la API. |
| `category` / `customer_tier` / `amount` | Atributos de negocio del segmento. |
| `scheduled_min` / `scenario` | Minuto del plan y escenario aplicado. |
| `payload_flaw` / `fallback` / `error` | Causa del error intencional, degradación del pool y clase de la excepción de transporte. |
| `response_request_id` | Identificador que devolvió la API, para comprobar la propagación. |

Un `500` se clasifica siempre como `server_error`, incluso cuando la solicitud se envió rota a propósito: el simulador nunca pide un `500`, así que los errores internos del backend quedan separables de los errores intencionales del cliente.

### 6.5. Prueba local realizada

Función ejecutada con Functions Framework en el puerto 8088 y 30 solicitudes comprimidas en 3 segundos (`--quick`):

```text
requests sent      30
by result          as_expected 30
by status          200 12, 201 15, 400 1, 404 2
intentional errors 3
server errors      0
transport errors   0
pool fallbacks     0
client latency     p50 2.604 ms, p95 4.945 ms
```

Las 30 filas del CSV se correlacionaron una a una con los 30 eventos `request_completed` que emitió la API, con los mismos códigos de estado en ambos lados.

Dos ensayos complementarios:

- Contra un puerto sin servicio: 5 solicitudes, 5 filas conservadas con `status_code` vacío, `result=transport_error` y `error=ConnectError`.
- Con `FAILURE_RATE=0.3` en el backend: 60 solicitudes → `as_expected 37`, `server_error 23`, y 8 errores intencionales contabilizados por separado.

No se ha ejecutado todavía la corrida de 6.000 solicitudes ni se ha enviado tráfico a Google Cloud.

### 6.6. Límites conocidos

- El reloj comprimido (`--quick`) adelanta las consultas respecto a las respuestas de creación, así que en los ensayos muy rápidos aparecen degradaciones `pool_empty`. Con la configuración oficial hay unos 0,6 s entre solicitudes y el pool no se queda frío.
- `client_latency_ms` incluye red y cold start; el `latency_ms` del evento de log del backend no. Las dos series no son comparables directamente.
- El almacén de pedidos vive en la memoria de cada instancia de Cloud Run: con varias instancias activas, consultas y cancelaciones legítimas pueden responder `404`. Esas filas aparecerán como `unexpected` en el CSV y hay que decidir antes del despliegue si se fija una sola instancia o si se miden como parte del experimento.

### 6.7. Autenticación contra la función privada

La función no concede acceso a `allUsers`, así que responde `403` a cualquier
llamada sin identidad. El simulador no necesita que se abra: presenta un token
de identidad en cada solicitud.

| Forma | Cuándo |
| --- | --- |
| `--renew-token` | **La corrida de 60 minutos.** Ejecuta `gcloud auth print-identity-token` al arrancar y lo repite cada `token_refresh_s` (30 min por omisión). |
| `CLOUDPULSE_AUTH_TOKEN=...` | Pruebas cortas. Un token fijo, sin renovación. |
| `--auth-token ...` | Último recurso: queda en el historial del shell y en la lista de procesos. |

Cómo se protege la credencial:

- **Nunca es un argumento de proceso.** `gcloud auth print-identity-token` la
  devuelve por stdout; el simulador la guarda solo en memoria. Nadie puede
  leerla con `ps`.
- **Nunca entra en la configuración.** No es un campo de `SimulatorConfig`, que
  es el objeto que se imprime en el resumen del plan.
- **Nunca llega al CSV ni a los resúmenes.** Viaja como cabecera por omisión del
  cliente HTTP, así que el camino que construye cada fila no la ve. Hay pruebas
  que lo verifican sobre el texto del CSV y de las salidas.
- **El resumen dice que hay autenticación, no cuál**:
  `authentication    bearer identity token, renewed every 1800 s (values never shown)`.
- **Un fallo de renovación no aborta la corrida**: se avisa por stderr (código de
  salida y primera línea de stderr de `gcloud`, nunca el token) y se sigue con el
  token vigente. Solo rompería si todos los intentos fallaran hasta que el token
  actual caduque.

La renovación ocurre en una tarea de fondo que se cancela al terminar la
corrida; las solicitudes ya en vuelo conservan la cabecera con la que se
construyeron, lo cual es inocuo porque el token anterior sigue siendo válido el
resto de su vida.

## 7. Pruebas locales y calidad

Todo lo de esta sección se ejecuta sin tocar Google Cloud.

### 7.1. Comandos

```bash
make help           # lista los objetivos disponibles
make test           # uv run python -m pytest tests/
make lint           # uv run ruff check backend simulator tests
make format         # uv run ruff format backend simulator tests
make check          # lint + test + infra-fmt
make infra-fmt      # terraform -chdir=infra fmt -check -recursive
make infra-validate # terraform -chdir=infra validate
```

`make infra-validate` requiere que el directorio esté inicializado. Sin credenciales
y sin contactar con ningún backend remoto:

```bash
terraform -chdir=infra init -backend=false
```

### 7.2. Qué cubren las pruebas

| Archivo | Alcance |
| --- | --- |
| `tests/test_orders_api.py` | Las tres operaciones y sus códigos de éxito. |
| `tests/test_validation.py` | Las reglas del esquema y el `400` agregado. |
| `tests/test_failure_injection.py` | `FAILURE_RATE`, `EXTRA_LATENCY_MS`, valores inválidos y la excepción no controlada. |
| `tests/test_observability.py` | Un evento por petición, campos del evento, propagación y saneado de `X-Request-ID`. |
| `tests/test_concurrency.py` | Cancelaciones simultáneas, creaciones simultáneas y un evento por hilo. |
| `tests/test_simulator_config.py` | Validación de `simulator/config.json` y del escenario. |
| `tests/test_simulator_plan.py` | Forma de la campana, instantes, mezcla de operaciones y errores intencionales. |
| `tests/test_simulator_runtime.py` | Concurrencia, pool de pedidos, timeouts, fallos de transporte y el CSV. |
| `tests/test_simulator_api_contract.py` | El simulador contra la API real cargada con Functions Framework. |
| `tests/test_simulator_cli.py` | Banderas, preajuste `--quick` y `--dry-run`. |

Las pruebas del backend cargan `backend/main.py` con `functions_framework.create_app`,
así que ejercitan enrutado, parseo y respuestas sobre HTTP real, no llamando a
funciones internas.

### 7.3. Levantar la función en local

```bash
uv run functions-framework --target handle --source backend/main.py --port 8091
```

Con inyección de fallos y latencia:

```bash
FAILURE_RATE=0.1 EXTRA_LATENCY_MS=50 \
  uv run functions-framework --target handle --source backend/main.py --port 8091
```

Comprobar los seis códigos de respuesta a mano:

```bash
B=http://127.0.0.1:8091
OID=$(curl -s -X POST $B/orders -H 'Content-Type: application/json' \
  -d '{"customer_tier":"premium","category":"books","amount":42.5}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -s -o /dev/null -w '%{http_code}\n' $B/orders/$OID                 # 200
curl -s -o /dev/null -w '%{http_code}\n' $B/orders/ord_nope             # 404
curl -s -o /dev/null -w '%{http_code}\n' -X POST $B/orders \
  -H 'Content-Type: application/json' -d '{"customer_tier":"x"}'        # 400
curl -s -o /dev/null -w '%{http_code}\n' -X POST $B/orders/$OID/cancel  # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST $B/orders/$OID/cancel  # 409
curl -s -o /dev/null -w '%{http_code}\n' $B/healthz                     # 404
```

Comprobar la propagación del identificador de correlación:

```bash
curl -si $B/orders/$OID -H 'X-Request-ID: prueba-local-001' | grep -i '^x-request-id'
```

### 7.4. Ensayo pequeño del simulador

Plan sin enviar nada:

```bash
uv run python simulator/simulator.py --dry-run
```

Ensayo contra la función local (30 solicitudes en unos segundos):

```bash
uv run python simulator/simulator.py --quick \
  --target-url http://127.0.0.1:8091 \
  --output outputs/simulator/requests_quick.csv
```

Comprobar que el CSV y los logs se pueden unir por `X-Request-ID`: cada fila con
`status_code` no vacío debe tener un evento `request_completed` con el mismo
`request_id` y el mismo código.

## 8. Infraestructura con Terraform

### 8.1. Lo que `infra/` declara hoy

| Archivo | Contenido |
| --- | --- |
| `versions.tf` | `required_version >= 1.9` y tres providers: `hashicorp/google ~> 8.7`, `hashicorp/archive ~> 2.7` (empaqueta el zip del código) y `hashicorp/time ~> 0.13` (espera la propagación de IAM). |
| `variables.tf` | Veintiuna variables: proyecto, región, parámetros de la función, topes de coste y observabilidad. Todas tienen consumidor. |
| `main.tf` | Los diecinueve recursos de cómputo: nueve `google_project_service`, dos cuentas de servicio, cuatro bindings IAM, bucket y objeto del código, la espera de propagación y la `google_cloudfunctions2_function`. |
| `logging.tf` | Bucket de logs regional con Log Analytics, sink, vista y las cuatro métricas basadas en logs. |
| `monitoring.tf` | El dashboard único, renderizado desde la plantilla. |
| `dashboards/orders-api.json.tftpl` | Los ocho tiles del dashboard. |
| `outputs.tf` | Trece outputs: ocho de cómputo (`function_url`, `simulator_command`, `scaling`, las dos cuentas de servicio, el bucket del código, el nombre y si es pública) y cinco de observabilidad (bucket de logs, vista, cláusula `FROM`, ids de las métricas y URL del dashboard). |
| `terraform.tfvars` | Valores del laboratorio. **Está en `.gitignore`: no se versiona.** |

El detalle de cada recurso de observabilidad está en `docs/observability.md`.

### 8.2. Variables

Las obligatorias no tienen valor por defecto; el resto sí. `terraform.tfvars`
fija los valores del laboratorio:

```hcl
project_id = "cloudpulse-lab-2026"
region     = "us-central1"

function_name    = "orders-api"
runtime          = "python313"
failure_rate     = 0.02
extra_latency_ms = 0

max_instances      = 1
min_instances      = 0
concurrency        = 1
function_memory    = "512Mi"
function_timeout_s = 60

allow_unauthenticated = false

student_members = []
```

`region` valida que no sea `global`, porque Log Analytics exige un bucket de logs
regional. `max_instances` valida el rango `[1, 100]` y `concurrency` el rango
`[1, 1000]`: un error de dedo falla en `plan`, no en la factura.

Los cuatro valores que gobiernan el coste y la medición:

| Valor | Por qué este |
| --- | --- |
| `max_instances = 1` | La API guarda los pedidos en la memoria de una instancia. Con dos instancias, una consulta encaminada a la otra responde un `404` legítimo que en `requests.csv` parece un defecto. El coste de la decisión es que el escalamiento horizontal deja de ser observable: el panel de instancias se queda plano en 1. |
| `min_instances = 0` | Escala a cero: nada se factura entre corridas, a cambio de un arranque en frío en las primeras peticiones. |
| `concurrency = 1` | Tope explícito. Es la única palanca de rendimiento que queda con una sola instancia: el almacén está protegido por un lock, así que subirlo es seguro *dentro* de la instancia. |
| `function_memory = "512Mi"` | El doble del valor por defecto de la plataforma. El runtime `python313` con Functions Framework ronda los 100 MB en reposo, pero un arranque en frío que no quepa en memoria tumba la revisión, y esta corrida no se puede repetir sin pagarla otra vez. |

### 8.3. Validaciones locales

Ninguno de estos comandos modifica recursos remotos:

```bash
terraform -chdir=infra init -backend=false    # descarga el provider del lock
terraform -chdir=infra fmt -check -recursive  # formato
terraform -chdir=infra validate               # sintaxis y tipos
terraform -chdir=infra plan -lock=false       # lectura; requiere credenciales ADC
```

`plan` sí contacta con las APIs de Google Cloud para leer el estado actual, pero
no escribe nada. Con el estado vacío anuncia **27 recursos a crear, 0 a
modificar y 0 a destruir**: diecinueve de cómputo y ocho de observabilidad.
Ningún binding de invocación pública, porque `allow_unauthenticated = false`.

`plan` escribe un único archivo local: `outputs/terraform/orders-api-source.zip`,
que es lo que produce `data.archive_file` al evaluarse. Contiene exactamente
`main.py` y `requirements.txt`.

### 8.4. Preparación del dashboard

El dashboard es un único recurso, `google_monitoring_dashboard.orders_api`, que
renderiza `dashboards/orders-api.json.tftpl` con `templatefile()`. **No hay
ningún panel que haya que crear a mano en la consola:** el panel de logs y las
dos gráficas de Log Analytics son campos del propio recurso.

Validar el JSON renderizado sin crear nada:

```bash
# 1. Renderizar la plantilla con los valores reales.
terraform -chdir=infra console <<'EOF'
templatefile("dashboards/orders-api.json.tftpl", {
  dashboard_display_name = "CloudPulse — orders API"
  project_id             = "cloudpulse-lab-2026"
  service_name           = "orders-api"
  metric_prefix          = "cloudpulse"
  log_view_path          = "cloudpulse-lab-2026.us-central1.cloudpulse-logs.cloudpulse_requests"
})
EOF

# 2. Validar contra el servidor sin guardarlo.
gcloud monitoring dashboards create --validate-only \
  --project=cloudpulse-lab-2026 \
  --config-from-file=orders-api.json
```

Orden obligatorio al aplicar, porque **una métrica basada en logs solo cuenta
entradas ingeridas después de existir y no hay backfill**:

```text
1. recursos de cómputo (main.tf)     → la función existe y escribe logs
2. logging.tf                        → bucket, sink, vista y las 4 métricas
3. esperar a que los descriptores aparezcan en Cloud Monitoring
4. monitoring.tf                     → el dashboard
5. solo entonces: el simulador
```

Un `terraform apply` sin `-target` crea 1 y 2 en el mismo paso y respeta el
`depends_on` del dashboard, así que basta con no lanzar el simulador hasta que
`gcloud logging metrics list` devuelva las cuatro métricas.

## 9. Procedimiento futuro de despliegue

> **Este procedimiento no se ha ejecutado.** La configuración está completa y
> validada, pero nada está aplicado: no hay función, ni bucket, ni cuentas de
> servicio, ni métricas en el proyecto. Cada paso que crea o cobra necesita
> aprobación explícita.

### 9.1. Requisitos previos

| Requisito | Estado comprobado |
| --- | --- |
| `infra/main.tf` con los recursos de cómputo | ✅ Diecinueve recursos; `validate` correcto y `plan` revisado. |
| APIs de cómputo (`run`, `cloudfunctions`, `cloudbuild`, `artifactregistry`, `iam`) | ✅ Declaradas como `google_project_service`. Siguen sin habilitar en el proyecto: **las habilita el `apply`**, no un paso manual. |
| Cuenta de servicio dedicada | ✅ Dos: ejecución (`roles/logging.logWriter` y nada más) y compilación. La función no usa la cuenta por defecto de Compute. |
| Permisos de quien ejecuta el `apply` | ✅ `roles/owner` sobre el proyecto, así que puede habilitar APIs, crear cuentas y actuar como ellas. |
| Nombre global del bucket del código | ✅ Libre (`gs://cloudpulse-lab-2026-orders-api-source` devuelve `404`). |
| Decisión sobre el almacén en memoria | ✅ Tomada: `max_instances = 1`. |
| Decisión sobre el acceso a la función | 🟡 **Operativa, pendiente de autorización.** `allow_unauthenticated = false`, así que al aplicar esta configuración la función responde `403` a cualquier llamada sin autenticar — incluido el simulador, que no firma peticiones. Ver §9.4. |
| Facturación del proyecto | Activa (`billingEnabled: true`). |
| Presupuesto de referencia | US$5/mes **solo con alertas**; no limita el gasto. |
| Autorización humana para el `apply` | 🔴 Pendiente. Es lo único que falta para que exista el laboratorio. |

### 9.2. Secuencia prevista

```bash
# 1. Autenticación local (no crea nada).
gcloud auth login
gcloud auth application-default login
gcloud config set project cloudpulse-lab-2026

# 2. Revisar qué se va a crear. Lectura; no modifica nada.
terraform -chdir=infra init
terraform -chdir=infra plan -out=../outputs/terraform/tfplan

# 3. Leer el plan completo y pedir aprobación explícita.
terraform -chdir=infra show ../outputs/terraform/tfplan

# 4. Aplicar. CREA RECURSOS Y EMPIEZA A FACTURAR.
terraform -chdir=infra apply ../outputs/terraform/tfplan

# 5. Comprobar que las cuatro métricas existen ANTES de generar tráfico.
gcloud logging metrics list --project=cloudpulse-lab-2026 --format='value(name)'

# 6. Obtener la URL de la función y comprobarla con una sola petición.
terraform -chdir=infra output
curl -si <URL>/orders -H 'Content-Type: application/json' \
  -H 'X-Request-ID: smoke-001' \
  -d '{"customer_tier":"premium","category":"books","amount":42.5}'

# 7. Comprobar que el evento llegó a Cloud Logging.
gcloud logging read \
  'jsonPayload.message="request_completed" AND jsonPayload.request_id="smoke-001"' \
  --project=cloudpulse-lab-2026 --limit=1
```

### 9.3. Habilitar APIs

Habilitar una API no cuesta dinero por sí misma, pero es lo que permite que los
recursos que sí cuestan existan. Declararlas en Terraform mantiene el inventario
en un solo sitio:

Es lo que hace `infra/main.tf`, con nueve APIs en lugar de cinco: las cuatro
restantes (`cloudresourcemanager`, `logging`, `monitoring`, `storage`) ya están
habilitadas en el proyecto, pero declararlas evita que la configuración dependa
de que alguien las habilitara a mano.

```hcl
resource "google_project_service" "required" {
  for_each = toset(local.required_services)

  project = var.project_id
  service = each.value

  disable_on_destroy         = false
  disable_dependent_services = false
}
```

`disable_on_destroy = false` es deliberado: un `destroy` que apagara `run` o
`logging` afectaría a todo el proyecto, no solo al laboratorio, y volver a
habilitarlas es lento.

**No hace falta el equivalente manual** (`gcloud services enable …`): el `apply`
las habilita. Habilitarlas a mano antes solo crea diferencias entre lo que
Terraform cree que gestiona y lo que existe.

### 9.4. Invocación pública: habilitar durante el experimento y revocar después

El simulador no firma sus peticiones: `build_client` solo fija la URL base, los
límites de conexión y el timeout, y cada envío lleva únicamente la cabecera
`X-Request-ID`. Con la función privada —el estado por defecto— las 6.000
solicitudes recibirían `403`.

Por eso el binding existe en `main.tf` pero desactivado:

```hcl
resource "google_cloud_run_service_iam_member" "public_invoker" {
  count = var.allow_unauthenticated ? 1 : 0
  ...
  role   = "roles/run.invoker"
  member = "allUsers"
}
```

Con `allow_unauthenticated = false` el plan crea **cero** bindings. El rol es
`roles/run.invoker`, estrecho y específico, nunca un rol básico, y gobierna solo
el endpoint `run.app` que devuelve el output `function_url`. La dirección
heredada `cloudfunctions.net` (`gcf_uri`) se gobierna con
`roles/cloudfunctions.invoker` y no se concede: una sola superficie pública es
suficiente.

**Qué implica habilitarlo.** Queda un endpoint HTTP público y sin autenticar.
Los datos son sintéticos, así que el riesgo de información es nulo; el riesgo de
**coste** no lo es: cualquiera que descubra la URL puede generar invocaciones
facturables, y el presupuesto de US$5 avisa pero no suspende nada. Las
mitigaciones que ya están en la configuración son el tope de una instancia y una
ventana de exposición de 60 minutos. Lo que queda en manos de quien opera:
no publicar la URL y destruir el servicio al terminar.

**Secuencia completa, con la revocación como parte del procedimiento:**

```bash
# 1. ANTES de la corrida: habilitar la invocación pública.
#    Crea un único recurso: el binding allUsers -> roles/run.invoker.
terraform -chdir=infra apply -var allow_unauthenticated=true

# 2. Comprobar que quedó pública, y con qué URL.
terraform -chdir=infra output function_public   # true
terraform -chdir=infra output function_url

# 3. Comprobar que responde sin credenciales (una sola petición).
curl -s -o /dev/null -w '%{http_code}\n' "$(terraform -chdir=infra output -raw function_url)/orders/ord_inexistente"
# 404 = la función responde y la ruta no existe (correcto)
# 403 = el binding no está activo todavía

# 4. La corrida de 60 minutos (ver §10).
uv run python simulator/simulator.py --target-url "$(terraform -chdir=infra output -raw function_url)"

# 5. INMEDIATAMENTE DESPUÉS: revocar.
#    Elimina el binding; no toca la función, ni los logs, ni las métricas,
#    ni el CSV ya escrito.
terraform -chdir=infra apply -var allow_unauthenticated=false

# 6. Verificar la revocación de dos formas independientes.
terraform -chdir=infra output function_public   # false
gcloud run services get-iam-policy orders-api \
  --region=us-central1 --project=cloudpulse-lab-2026 \
  --format='value(bindings.members)'
# No debe aparecer allUsers

curl -s -o /dev/null -w '%{http_code}\n' "$(terraform -chdir=infra output -raw function_url)/orders/ord_inexistente"
# 403 = revocado
```

> **No dejes `allow_unauthenticated = true` en `terraform.tfvars`.** Pásalo con
> `-var` en los dos `apply` de arriba, de modo que el valor persistido en el
> archivo siga siendo `false` y un `apply` posterior hecho por inercia no vuelva
> a publicar la función.

La alternativa, que evita abrir nada, es añadir al simulador la firma con token
de identidad (`gcloud auth print-identity-token` y una cabecera
`Authorization: Bearer …` por petición, renovada antes de que caduque a los
60 minutos). No está implementada.

## 10. Procedimiento futuro de ejecución del simulador

> **La corrida de 6.000 solicitudes no se ha ejecutado.** Dura 60 minutos
> reales, genera tráfico facturable y solo tiene sentido una vez: las métricas
> basadas en logs no rellenan el pasado, así que lanzarla antes de que existan
> obliga a repetirla.

### 10.1. Preflight: `scripts/preflight.sh`

Un solo comando comprueba todo lo que haría inútil o caro repetir la corrida:

```bash
bash scripts/preflight.sh
```

Es de solo lectura **con una excepción declarada**: envía una (1) petición
autenticada a un pedido inexistente, porque es la única forma de comprobar que
la autenticación funciona de verdad. No crea ni modifica nada en Google Cloud,
no ejecuta Terraform y no toca IAM. Devuelve 0 si todo pasa y 1 si algo bloquea
la corrida.

| Grupo | Qué comprueba |
| --- | --- |
| 1. Configuración | 6.000 instantes, ventana de 3.600 s, `N(mu=30, sigma=10)`, semilla 42, escenario `double_errors [35,45)` sobre `electronics`, y que el destino del CSV sea escribible (avisa si ya existe y se va a sobrescribir) |
| 2. Calidad local | `make check` en verde (omitible con `SKIP_LOCAL_TESTS=1`) |
| 3. Identidad y coste | cuenta activa, facturación del proyecto y presupuesto, con el recordatorio de que un presupuesto **solo alerta** |
| 4. La función | estado `ACTIVE`, URL, `python313`, 512Mi y tope de instancias |
| 5. Superficie pública | que **no** haya `allUsers` en la política: la corrida debe ir autenticada, no con la función abierta |
| 6. Autenticación | obtiene el token (no lo muestra) y envía la petición de sondeo: `404` es correcto, `401`/`403` bloquea |
| 7. Observabilidad | las cuatro métricas `cloudpulse_*` **ya existen**, el bucket tiene Log Analytics, la vista existe y con qué filtro, y el dashboard está presente |

El grupo 7 es el que no se puede saltar: una métrica basada en logs solo cuenta
entradas ingeridas después de crearse y **no rellena el pasado**, así que
lanzar el simulador antes de que existan obliga a repetir los 60 minutos.

Si el preflight pasa, imprime el comando exacto de la corrida con la URL ya
resuelta.

### 10.2. La corrida

```bash
uv run python simulator/simulator.py --renew-token --target-url <URL de Cloud Run>
```

Esto envía 6.000 solicitudes a lo largo de 3.600 segundos y escribe
`outputs/simulator/requests.csv` fila a fila, descargando cada una en cuanto la
solicitud termina. Si la corrida se interrumpe, el CSV conserva todo lo que ya
había medido.

Para fijar un identificador de corrida reproducible en las cabeceras:

```bash
uv run python simulator/simulator.py --target-url <URL> --run-id lab001
```

### 10.3. Después

```bash
# Filas y reparto de códigos.
wc -l outputs/simulator/requests.csv
python3 -c "
import csv, collections
rows = list(csv.DictReader(open('outputs/simulator/requests.csv')))
print('filas', len(rows))
print(collections.Counter(r['result'] for r in rows))
print(collections.Counter(r['status_code'] for r in rows))
"
```

Las consultas de `docs/log-analytics-queries.sql` se pegan en Log Analytics
sustituyendo la cláusula `FROM` por el valor de
`terraform output log_analytics_from_clause`.

La correlación entre el CSV y los logs se hace por `request_id`: la consulta 6
del archivo SQL devuelve el evento de la API para un identificador concreto del
simulador. `scheduled_min` solo existe en el CSV; no viaja a Cloud Logging.

## 11. Limpieza de recursos

> **`terraform destroy` solo se ejecuta con aprobación explícita.** No lo lances
> para «dejar limpio» sin haber exportado antes los resultados: el bucket de logs
> contiene los datos de la corrida, que son el resultado del laboratorio.

### 11.1. Exportar primero

```bash
# El CSV ya está en disco; cópialo fuera de outputs/ si vas a limpiar el árbol.
cp outputs/simulator/requests.csv ~/cloudpulse-requests-$(date +%F).csv

# Resultados de las consultas SQL: ejecútalas y guarda la salida antes de borrar.
# El dashboard se puede exportar como JSON:
gcloud monitoring dashboards describe <DASHBOARD_ID> \
  --project=cloudpulse-lab-2026 --format=json > ~/cloudpulse-dashboard.json
```

### 11.2. Destruir

```bash
# 1. Revisar exactamente qué se va a borrar.
terraform -chdir=infra plan -destroy

# 2. Solo con aprobación explícita.
terraform -chdir=infra destroy
```

### 11.3. Lo que `destroy` no deshace

| Efecto | Por qué |
| --- | --- |
| Observability Analytics en un bucket de logs | Una vez habilitado **no se puede degradar**. El bucket solo se puede borrar, no revertir. |
| Borrado del bucket de logs | Se lleva las entradas de la corrida. Un bucket borrado queda en estado de borrado lógico antes de desaparecer, pero no es una copia de seguridad. |
| APIs habilitadas | Si se declaran con `disable_on_destroy = false`, siguen habilitadas. Habilitadas no cuestan, pero conviene saberlo. |
| Imágenes de Artifact Registry y objetos de Cloud Storage | Los crea el proceso de compilación de la función, no Terraform directamente. Si quedan, ocupan almacenamiento facturable; hay que revisarlos a mano. |
| Entradas en el bucket `_Default` | El sink `_Default` sigue siendo del proyecto. Las entradas caducan por su retención, no por `destroy`. |

### 11.4. Comprobar que no queda nada facturable

```bash
gcloud logging buckets list --project=cloudpulse-lab-2026
gcloud logging metrics list --project=cloudpulse-lab-2026
gcloud logging sinks list --project=cloudpulse-lab-2026
gcloud monitoring dashboards list --project=cloudpulse-lab-2026
gcloud run services list --project=cloudpulse-lab-2026
gcloud storage buckets list --project=cloudpulse-lab-2026
gcloud artifacts repositories list --project=cloudpulse-lab-2026
gcloud iam service-accounts list --project=cloudpulse-lab-2026
```
