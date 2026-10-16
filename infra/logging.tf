# Cloud Logging: analysis surface and log-based metrics for the orders API.
#
# Ordering matters for the laboratory: a log-based metric only counts entries
# ingested *after* it exists, so every resource in this file must be applied
# before the 60-minute simulator run. Re-running `apply` later does not
# backfill the metrics.
#
# The filters below reference the fields of the single structured event that
# `backend/main.py` prints on stdout for every request. Cloud Run parses that
# JSON into `jsonPayload` and lifts `severity` to the log entry, so `severity`
# is filtered at entry level and never as `jsonPayload.severity`.

locals {
  # Every log entry produced by the deployed function.
  service_filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${var.function_name}\"",
  ])

  # The one `request_completed` event that closes each request.
  request_filter = join(" AND ", [
    local.service_filter,
    "jsonPayload.message=\"request_completed\"",
  ])

  # Successful creations only. `amount` is also present on reads and cancels
  # (it is copied from the stored order), so counting every event that carries
  # the field would weigh one order as many times as it is touched.
  created_order_filter = join(" AND ", [
    local.request_filter,
    "jsonPayload.endpoint=\"POST /orders\"",
    "jsonPayload.status_code=201",
  ])
}

# --- Analysis surface -------------------------------------------------------

# Regional log bucket with Observability Analytics, which is what makes the
# entries queryable with SQL. The bucket is free until a sink routes logs into
# it; the run writes roughly 6,000 small entries, far below the free tier.
#
# WARNING: once a log bucket has been upgraded to use Observability Analytics
# it CANNOT be downgraded to remove the analytics capability.
resource "google_logging_project_bucket_config" "cloudpulse" {
  project          = var.project_id
  location         = var.region
  bucket_id        = var.log_bucket_id
  description      = "CloudPulse orders API logs, queryable with Log Analytics SQL."
  retention_days   = var.log_bucket_retention_days
  enable_analytics = true
}

# Routes the function's logs into the analytics bucket. This is additive: the
# `_Default` sink keeps writing the same entries to the `_Default` bucket, so
# the logs panel of the dashboard keeps working and the entries are ingested
# twice. At laboratory volume the duplicated ingestion is negligible.
resource "google_logging_project_sink" "cloudpulse" {
  project     = var.project_id
  name        = "${var.metric_prefix}-${var.function_name}"
  description = "Routes orders API logs to the Log Analytics bucket."
  destination = "logging.googleapis.com/${google_logging_project_bucket_config.cloudpulse.id}"
  filter      = local.service_filter

  # `true` matches what the API actually does and is the provider default.
  # Logging no longer hands out the legacy shared identity
  # (`cloud-logs@system.gserviceaccount.com`) to new sinks: it assigns a service
  # agent. Declaring `false` here left the configuration permanently out of step
  # with the created sink, and the update that would undo it is rejected by the
  # API — going from a unique writer identity back to the shared one is an
  # error.
  #
  # No extra IAM binding is needed either way: a sink whose destination is a log
  # bucket in the same project is authorised automatically.
  unique_writer_identity = true
}

# The view the SQL in `docs/log-analytics-queries.sql` reads from.
#
# --- Why the filter is this small ------------------------------------------
#
# A log view filter is NOT a log-based metric filter and NOT a Logs Explorer
# query. The REST reference for `LogView.filter` is the narrowest and most
# authoritative statement of its grammar:
#
#   "Filters must be logical conjunctions that use the AND operator, and they
#    can use any of the following qualifiers:
#      - SOURCE(), which specifies a project, folder, organization, or billing
#        account of origin.
#      - resource.type, which specifies the resource type.
#      - LOG_ID(), which identifies the log.
#    They can also use the negations of these qualifiers with the NOT
#    operator."
#
#   Example given there:
#     SOURCE("projects/myproject") AND resource.type = "gce_instance"
#     AND NOT LOG_ID("stdout")
#
# Two rejected attempts, and what each one proved:
#
#   1. `jsonPayload.message="request_completed"`
#      -> Error 400: Invalid view filter. Payload fields are not qualifiers.
#         A log-based metric accepts them; a view never does. The metrics below
#         are unaffected and still filter on jsonPayload.
#
#   2. `... AND (LOG_ID(".../stdout") OR LOG_ID(".../stderr"))`
#      -> Error 400: Filter exceeds the view filter nesting depth limit of 1.
#         The grammar has no OR at all: a filter must be a flat conjunction, so
#         any parenthesised group is already one level too deep.
#
# What is left is the smallest filter that provably exposes every entry the SQL
# needs: one qualifier, no function call, no negation, no nesting. It is also
# verbatim the example in `gcloud logging views create --help` and in the REST
# reference.
#
# Deliberately NOT added:
#
#   * `resource.labels.service_name`. The guide page lists resource labels as
#     filterable and the server's own error message mentions user-defined
#     labels, but the REST reference for this field does not list either. It is
#     redundant anyway: the bucket only receives what the sink routes, and that
#     sink is already scoped to this one service.
#   * `AND LOG_ID("run.googleapis.com/stdout")`. This would keep `varlog/system`
#     and the audit entries out of the view, and it is almost certainly the
#     right log id — this service already emits
#     `run.googleapis.com%2Fvarlog%2Fsystem`, so the naming scheme is confirmed
#     — but "almost certainly" is the problem. There is no way to validate a
#     view filter remotely without creating the view, and a wrong log id yields
#     a view that is syntactically valid and permanently EMPTY. That failure is
#     silent and would only surface after the 60-minute run, which cannot be
#     repeated cheaply. A filter that is merely noisy fails loudly in SQL
#     instead; a filter that is empty fails quietly in production.
#
# The noise this lets in is handled where the grammar does allow payload
# predicates: every consumer selects the event with
# `JSON_VALUE(json_payload.message) = 'request_completed'` — the seven queries
# in `docs/log-analytics-queries.sql` and the two SQL panels of the dashboard.
# Audit entries carry `proto_payload` and system entries `text_payload`, so that
# predicate excludes them by construction.
#
# Hardening path, once there is evidence: after the first real request, run
#   gcloud logging read 'jsonPayload.message="request_completed"' \
#     --project=<project> --limit=1 --format="value(log_name)"
# and if it returns `.../logs/run.googleapis.com%2Fstdout`, append
# `AND LOG_ID("run.googleapis.com/stdout")`. Changing a view filter is an
# in-place update — a view is a read-time window over the bucket, not an
# ingestion filter, so no stored entry is ever lost or hidden retroactively.
resource "google_logging_log_view" "cloudpulse_requests" {
  name        = var.log_view_id
  parent      = "projects/${var.project_id}"
  location    = var.region
  bucket      = google_logging_project_bucket_config.cloudpulse.id
  description = "Logs of the orders API service; the request events live here."

  filter = "resource.type=\"cloud_run_revision\""
}

# --- Log-based metrics ------------------------------------------------------

# 1. Requests broken down by outcome. `endpoint` carries the route template
#    (`GET /orders/{id}`), never a concrete order id, so the label cardinality
#    stays at three endpoints plus `unknown`.
resource "google_logging_metric" "requests_by_outcome" {
  project     = var.project_id
  name        = "${var.metric_prefix}_requests_by_outcome"
  description = "Completed requests of the orders API, labelled by outcome and endpoint."
  filter      = local.request_filter

  metric_descriptor {
    display_name = "CloudPulse requests by outcome"
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"

    labels {
      key         = "outcome"
      value_type  = "STRING"
      description = "success, client_error or server_error."
    }

    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "Route template of the operation."
    }
  }

  label_extractors = {
    outcome  = "EXTRACT(jsonPayload.outcome)"
    endpoint = "EXTRACT(jsonPayload.endpoint)"
  }
}

# 2. Client errors (400, 404, 409). `status_code` separates a validation
#    rejection from a missing order and from a double cancellation.
resource "google_logging_metric" "client_errors" {
  project     = var.project_id
  name        = "${var.metric_prefix}_client_errors"
  description = "Requests answered with 4xx by the orders API."

  filter = join(" AND ", [
    local.request_filter,
    "jsonPayload.outcome=\"client_error\"",
  ])

  metric_descriptor {
    display_name = "CloudPulse client errors"
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"

    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "Route template of the operation."
    }

    labels {
      key         = "status_code"
      value_type  = "STRING"
      description = "400 validation_error, 404 not_found or 409 conflict."
    }

    labels {
      key         = "error_type"
      value_type  = "STRING"
      description = "validation_error, not_found or conflict."
    }
  }

  label_extractors = {
    endpoint    = "EXTRACT(jsonPayload.endpoint)"
    status_code = "EXTRACT(jsonPayload.status_code)"
    error_type  = "EXTRACT(jsonPayload.error_type)"
  }
}

# 3. Server errors. `error_type` separates the injected `simulated_failure`
#    from an `unhandled_exception`, which would be a real defect.
resource "google_logging_metric" "server_errors" {
  project     = var.project_id
  name        = "${var.metric_prefix}_server_errors"
  description = "Requests answered with 5xx by the orders API."

  filter = join(" AND ", [
    local.request_filter,
    "jsonPayload.outcome=\"server_error\"",
  ])

  metric_descriptor {
    display_name = "CloudPulse server errors"
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"

    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "Route template of the operation."
    }

    labels {
      key         = "error_type"
      value_type  = "STRING"
      description = "simulated_failure (injected) or unhandled_exception (defect)."
    }
  }

  label_extractors = {
    endpoint   = "EXTRACT(jsonPayload.endpoint)"
    error_type = "EXTRACT(jsonPayload.error_type)"
  }
}

# 4. Distribution of the order amount. `amount` is a JSON number in the event,
#    so it can be extracted directly. Linear buckets of width 25 over [0, 500]
#    match the range the simulator draws from; the API accepts amounts up to
#    100,000, which land in the overflow bucket.
resource "google_logging_metric" "order_amount" {
  project     = var.project_id
  name        = "${var.metric_prefix}_order_amount"
  description = "Distribution of the amount of successfully created orders."
  filter      = local.created_order_filter

  value_extractor = "EXTRACT(jsonPayload.amount)"

  metric_descriptor {
    display_name = "CloudPulse order amount"
    metric_kind  = "DELTA"
    value_type   = "DISTRIBUTION"
    unit         = "1"

    labels {
      key         = "category"
      value_type  = "STRING"
      description = "electronics, books, grocery or apparel."
    }

    labels {
      key         = "customer_tier"
      value_type  = "STRING"
      description = "free, standard or premium."
    }
  }

  label_extractors = {
    category      = "EXTRACT(jsonPayload.category)"
    customer_tier = "EXTRACT(jsonPayload.customer_tier)"
  }

  bucket_options {
    linear_buckets {
      num_finite_buckets = var.amount_bucket_count
      width              = var.amount_bucket_width
      offset             = 0
    }
  }
}
