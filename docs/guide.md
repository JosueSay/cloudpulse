# CloudPulse — Guía de instalación y configuración

Documentación del proceso de preparación, desarrollo y despliegue de una API serverless observable en Google Cloud Platform (GCP).

## 1. Descripción del proyecto

**CloudPulse** es un laboratorio de observabilidad que consiste en desarrollar y desplegar una API HTTP serverless en Google Cloud, generar tráfico simulado y analizar su comportamiento mediante métricas, registros estructurados y dashboards.

### Tecnologías

| Tecnología | Propósito |
| --- | --- |
| Python 3.12 | Desarrollo de API y simulador |
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
├── README.md
├── backend/
│   ├── main.py
│   └── requirements.txt
├── docs/
│   └── guide.md
├── infra/
│   ├── main.tf
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
├── simulator/
│   ├── config.json
│   └── simulator.py
├── skills-lock.json
├── tests/
└── uv.lock
```

*Nota:* Se omiten del árbol algunos archivos ocultos, directorios temporales y contenidos internos de los agentes para mantener la representación legible.

### 2.1. Organización de directorios

| Directorio | Propósito |
| --- | --- |
| `.agents/agents/` | Agentes especializados para desarrollo, infraestructura, observabilidad y revisión. |
| `.agents/skills/` | Skills locales reutilizables para pruebas, depuración y verificación. |
| `backend/` | Implementación de la API HTTP serverless. |
| `docs/` | Documentación técnica y guía de configuración. |
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

### 3.1. Seleccionar Python 3.12

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
gcloud rojects get-iam-policy cloudpulse-lab-2026 \
  --format="table(bindings.role)"
```

Esto permite revisar los roles asignados al proyecto, aunque no muestra todos los permisos efectivos heredados.
