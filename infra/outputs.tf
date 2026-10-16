# --- Cloud Run function (phase 3) -------------------------------------------

output "function_name" {
  description = "Name of the deployed function. Also the `resource.labels.service_name` every log filter, metric and dashboard chart matches on."
  value       = google_cloudfunctions2_function.orders_api.name
}

output "function_url" {
  description = "HTTPS endpoint of the function. This is the value to pass to the simulator as `--target-url`."
  value       = google_cloudfunctions2_function.orders_api.service_config[0].uri
}

output "simulator_command" {
  description = "Ready-to-run command for the official 60-minute experiment."
  value       = "uv run python simulator/simulator.py --target-url ${google_cloudfunctions2_function.orders_api.service_config[0].uri}"
}

output "function_public" {
  description = "Whether this configuration granted `roles/run.invoker` to `allUsers`. When false the function answers 403 to an unauthenticated caller, including the simulator."
  value       = var.allow_unauthenticated
}

output "runtime_service_account" {
  description = "Identity the function runs as. Holds `roles/logging.logWriter` and nothing else."
  value       = google_service_account.runtime.email
}

output "build_service_account" {
  description = "Identity Cloud Build uses to package the source."
  value       = google_service_account.build.email
}

output "source_bucket" {
  description = "Bucket that holds the zipped function source."
  value       = google_storage_bucket.source.name
}

output "scaling" {
  description = "Scaling and cost ceilings actually applied to the function."
  value = {
    max_instances = var.max_instances
    min_instances = var.min_instances
    concurrency   = var.concurrency
    memory        = var.function_memory
    timeout_s     = var.function_timeout_s
  }
}

# --- Observability (phase 4) ------------------------------------------------

output "log_bucket" {
  description = "Resource name of the regional log bucket with Log Analytics enabled."
  value       = google_logging_project_bucket_config.cloudpulse.id
}

output "log_view" {
  description = "Resource name of the log view queried by the SQL in docs/log-analytics-queries.sql."
  value       = google_logging_log_view.cloudpulse_requests.id
}

output "log_analytics_from_clause" {
  description = "Value to paste into the FROM clause of a Log Analytics SQL query."
  value       = local.log_view_path
}

output "log_based_metrics" {
  description = "Log-based metric ids, in the order the dashboard consumes them."
  value = [
    google_logging_metric.requests_by_outcome.name,
    google_logging_metric.client_errors.name,
    google_logging_metric.server_errors.name,
    google_logging_metric.order_amount.name,
  ]
}

output "dashboard_url" {
  description = "Console URL of the dashboard. The resource id is the last path segment of the dashboard name."
  value       = "https://console.cloud.google.com/monitoring/dashboards/builder/${basename(google_monitoring_dashboard.orders_api.id)}?project=${var.project_id}"
}
