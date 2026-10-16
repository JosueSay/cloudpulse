#!/usr/bin/env bash
# CloudPulse — preflight de la corrida de 6.000 solicitudes.
#
# Comprueba, ANTES de lanzar los 60 minutos, todo lo que haría inútil o caro
# repetir la corrida: autenticación, métricas ya creadas, dashboard, superficie
# de Log Analytics, topes de coste, presupuesto y configuración del simulador.
#
# Es de solo lectura con UNA excepción declarada: envía una (1) petición
# autenticada a un pedido inexistente para comprobar que la autenticación
# funciona de verdad. No crea, modifica ni borra nada en Google Cloud, no
# ejecuta Terraform y no toca IAM.
#
# Uso:
#   bash scripts/preflight.sh
#   SKIP_LOCAL_TESTS=1 bash scripts/preflight.sh   # omite make check
#
# Salida: 0 si todo pasa; 1 si algo bloquea la corrida.

set -uo pipefail

PROJECT="${GCP_PROJECT_ID:-cloudpulse-lab-2026}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION="${FUNCTION_NAME:-orders-api}"
LOG_BUCKET="${LOG_BUCKET_ID:-cloudpulse-logs}"
LOG_VIEW="${LOG_VIEW_ID:-cloudpulse_requests}"
METRIC_PREFIX="${METRIC_PREFIX:-cloudpulse}"
EXPECTED_REQUESTS=6000
EXPECTED_WINDOW_S=3600

failures=0
warnings=0

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mAVISO\033[0m %s\n' "$1"; warnings=$((warnings + 1)); }
bad()  { printf '  \033[31mFALLO\033[0m %s\n' "$1"; failures=$((failures + 1)); }
head2() { printf '\n\033[1m%s\033[0m\n' "$1"; }

cd "$(dirname "$0")/.."

# --- 1. Configuración del simulador ----------------------------------------

head2 "1. Configuración del simulador (sin tráfico)"

plan="$(uv run python simulator/simulator.py --dry-run 2>&1)"
if [ $? -ne 0 ]; then
  bad "el plan no se puede generar:"$'\n'"$plan"
else
  requests="$(printf '%s\n' "$plan" | awk '/^requests /{print $2}')"
  [ "$requests" = "$EXPECTED_REQUESTS" ] \
    && ok "$EXPECTED_REQUESTS instantes planificados" \
    || bad "el plan tiene $requests solicitudes, se esperaban $EXPECTED_REQUESTS"

  printf '%s\n' "$plan" | grep -q "in $EXPECTED_WINDOW_S s of wall clock" \
    && ok "ventana de 60 min en $EXPECTED_WINDOW_S s de reloj" \
    || bad "la ventana no es de $EXPECTED_WINDOW_S s: $(printf '%s\n' "$plan" | grep '^window')"

  printf '%s\n' "$plan" | grep -q "N(mu=30, sigma=10)" \
    && ok "distribución normal N(mu=30, sigma=10)" \
    || bad "la distribución no es N(30,10)"

  printf '%s\n' "$plan" | grep -q "seed 42" \
    && ok "semilla reproducible 42" \
    || bad "la semilla no es 42"

  printf '%s\n' "$plan" | grep -q "double_errors \[35, 45) min on electronics" \
    && ok "escenario double_errors [35,45) sobre electronics" \
    || bad "falta el escenario double_errors"

  csv_path="$(printf '%s\n' "$plan" | awk '/^output /{print $2}')"
  csv_dir="$(dirname "$csv_path")"
  [ -w "$csv_dir" ] \
    && ok "destino del CSV escribible: $csv_path" \
    || bad "no se puede escribir en $csv_dir"
  [ -e "$csv_path" ] \
    && warn "$csv_path ya existe y se sobrescribirá (guárdalo antes si importa)"
fi

# --- 2. Calidad local -------------------------------------------------------

head2 "2. Pruebas y calidad local"

if [ "${SKIP_LOCAL_TESTS:-0}" = "1" ]; then
  warn "make check omitido por SKIP_LOCAL_TESTS=1"
else
  if out="$(make check 2>&1)"; then
    ok "make check: $(printf '%s\n' "$out" | grep -oE '[0-9]+ passed' | tail -1)"
  else
    bad "make check falla:"$'\n'"$(printf '%s\n' "$out" | tail -5)"
  fi
fi

# --- 3. Identidad y proyecto ------------------------------------------------

head2 "3. Identidad, proyecto y facturación"

account="$(gcloud config get-value account --quiet 2>/dev/null)"
[ -n "$account" ] && ok "cuenta activa: $account" || bad "no hay cuenta activa de gcloud"

billing="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' --quiet 2>/dev/null)"
[ "$billing" = "True" ] \
  && ok "facturación activa en $PROJECT" \
  || bad "facturación no activa en $PROJECT (billingEnabled=$billing)"

billing_account="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' --quiet 2>/dev/null)"
if [ -n "$billing_account" ]; then
  budgets="$(gcloud billing budgets list --billing-account="${billing_account#billingAccounts/}" \
    --format='value(displayName,amount.specifiedAmount.units)' --quiet 2>/dev/null)"
  if [ -n "$budgets" ]; then
    ok "presupuesto configurado: $(printf '%s' "$budgets" | tr '\n' ';')"
    warn "un presupuesto solo ALERTA: Google Cloud no suspende nada al alcanzarlo"
  else
    warn "no se pudo leer ningún presupuesto (permisos o API billingbudgets); el tope real son los límites de la función"
  fi
fi

# --- 4. La función ----------------------------------------------------------

head2 "4. La función desplegada"

read -r uri state memory maxinst runtime <<<"$(gcloud functions describe "$FUNCTION" \
  --region="$REGION" --project="$PROJECT" \
  --format='value(serviceConfig.uri,state,serviceConfig.availableMemory,serviceConfig.maxInstanceCount,buildConfig.runtime)' \
  --quiet 2>/dev/null)"

if [ -z "${uri:-}" ]; then
  bad "no se pudo describir la función $FUNCTION en $REGION"
else
  [ "$state" = "ACTIVE" ] && ok "estado ACTIVE" || bad "estado $state (se esperaba ACTIVE)"
  ok "URL: $uri"
  [ "$runtime" = "python313" ] && ok "runtime python313" || bad "runtime $runtime"
  [ "$memory" = "512Mi" ] && ok "memoria 512Mi" || warn "memoria $memory (esperada 512Mi)"
  [ "$maxinst" = "1" ] && ok "tope de instancias 1" || warn "max_instances=$maxinst: revisa el coste y los 404 entre instancias"
fi

# --- 5. Superficie pública (debe seguir privada) ----------------------------

head2 "5. La función sigue privada"

policy="$(gcloud run services get-iam-policy "$FUNCTION" --region="$REGION" --project="$PROJECT" \
  --format='value(bindings.members)' --quiet 2>/dev/null)"
if printf '%s' "$policy" | grep -q 'allUsers'; then
  bad "la función es PÚBLICA (allUsers en la política). Revócalo antes de continuar"
else
  ok "sin bindings allUsers: la invocación exige identidad"
fi

# --- 6. Autenticación (1 petición real) -------------------------------------

head2 "6. Autenticación — envía UNA petición autenticada"

if [ -z "${uri:-}" ]; then
  bad "sin URL no se puede comprobar la autenticación"
else
  token="$(gcloud auth print-identity-token --quiet 2>/dev/null)"
  if [ -z "$token" ]; then
    bad "gcloud auth print-identity-token no devolvió nada"
  else
    ok "token de identidad obtenido (${#token} caracteres, no se muestra)"
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 30 \
      -H "Authorization: Bearer $token" \
      -H "X-Request-ID: preflight-$(date -u +%Y%m%dT%H%M%SZ)" \
      "$uri/orders/ord_preflight_inexistente")"
    case "$code" in
      404) ok "petición autenticada aceptada (HTTP 404 del pedido inexistente)" ;;
      401|403) bad "HTTP $code: la autenticación NO funciona; la corrida fallaría entera" ;;
      *)   warn "HTTP $code inesperado (se esperaba 404)" ;;
    esac
  fi
  unset token
fi

# --- 7. Observabilidad ------------------------------------------------------

head2 "7. Observabilidad creada ANTES del tráfico"

metrics="$(gcloud logging metrics list --project="$PROJECT" --format='value(name)' --quiet 2>/dev/null)"
for m in requests_by_outcome client_errors server_errors order_amount; do
  printf '%s\n' "$metrics" | grep -qx "${METRIC_PREFIX}_${m}" \
    && ok "métrica ${METRIC_PREFIX}_${m}" \
    || bad "falta la métrica ${METRIC_PREFIX}_${m}: no contaría el tráfico de la corrida (no hay backfill)"
done

analytics="$(gcloud logging buckets describe "$LOG_BUCKET" --location="$REGION" --project="$PROJECT" \
  --format='value(analyticsEnabled)' --quiet 2>/dev/null)"
[ "$analytics" = "True" ] \
  && ok "bucket $LOG_BUCKET con Log Analytics habilitado" \
  || bad "bucket $LOG_BUCKET sin analytics (analyticsEnabled=$analytics)"

view="$(gcloud logging views describe "$LOG_VIEW" --bucket="$LOG_BUCKET" --location="$REGION" \
  --project="$PROJECT" --format='value(filter)' --quiet 2>/dev/null)"
[ -n "$view" ] \
  && ok "vista $LOG_VIEW con filtro: $view" \
  || bad "no existe la vista $LOG_VIEW en $LOG_BUCKET"

dashboards="$(gcloud monitoring dashboards list --project="$PROJECT" \
  --format='value(displayName)' --quiet 2>/dev/null)"
printf '%s\n' "$dashboards" | grep -q 'CloudPulse' \
  && ok "dashboard presente: $(printf '%s\n' "$dashboards" | grep CloudPulse)" \
  || bad "no se encontró el dashboard de CloudPulse"

# --- Resumen ----------------------------------------------------------------

head2 "Resumen"
printf '  fallos: %s · avisos: %s\n' "$failures" "$warnings"
if [ "$failures" -eq 0 ]; then
  printf '\n  \033[32mPREFLIGHT OK\033[0m — la corrida puede lanzarse:\n\n'
  printf '    uv run python simulator/simulator.py --renew-token --target-url %s\n\n' "${uri:-<URL>}"
  exit 0
fi
printf '\n  \033[31mPREFLIGHT BLOQUEADO\033[0m — resuelve los fallos antes de lanzar los 60 minutos.\n\n'
exit 1
