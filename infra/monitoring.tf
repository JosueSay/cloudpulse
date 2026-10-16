# Cloud Monitoring: the single dashboard required by the laboratory.
#
# The widget definitions live in `dashboards/orders-api.json.tftpl` so the JSON
# can be reviewed, diffed and validated on its own with
#   gcloud monitoring dashboards create --validate-only --config-from-file=...
# The template is rendered here with the project, service and metric names, so
# renaming the function in `terraform.tfvars` re-points every chart at once.
#
# The dashboard reads three different sources:
#   * native Cloud Run metrics (panels 1-3)
#   * the log-based metric of `logging.tf` (panel 4)
#   * Log Analytics SQL over the log view of `logging.tf` (panels 5a and 5b)
#   * a logs panel over the project's logs (panel 6)

locals {
  # FROM clause of a log view: PROJECT_ID.LOCATION.BUCKET_ID.LOG_VIEW_ID.
  log_view_path = join(".", [
    var.project_id,
    var.region,
    var.log_bucket_id,
    var.log_view_id,
  ])
}

resource "google_monitoring_dashboard" "orders_api" {
  project = var.project_id

  dashboard_json = templatefile("${path.module}/dashboards/orders-api.json.tftpl", {
    dashboard_display_name = var.dashboard_display_name
    project_id             = var.project_id
    service_name           = var.function_name
    metric_prefix          = var.metric_prefix
    log_view_path          = local.log_view_path
  })

  # The charts resolve the log-based metric by name, which is not a Terraform
  # reference, so the dependency has to be stated explicitly. Otherwise the
  # dashboard can be created before the metric descriptor exists and panel 4
  # renders empty until the next refresh.
  depends_on = [
    google_logging_metric.requests_by_outcome,
    google_logging_log_view.cloudpulse_requests,
  ]
}
