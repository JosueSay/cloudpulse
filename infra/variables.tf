# --- Project and location ---------------------------------------------------

variable "project_id" {
  description = "Google Cloud project that owns every resource."
  type        = string
}

variable "region" {
  description = "Region of the Cloud Run function and of the regional log bucket. Log Analytics requires a regional bucket, so this must not be `global`."
  type        = string
  default     = "us-central1"

  validation {
    condition     = var.region != "global"
    error_message = "Log Analytics requires a regional log bucket; `global` is not accepted."
  }
}

# --- Cloud Run function (phase 3) -------------------------------------------

variable "function_name" {
  description = "Name of the Cloud Run function. Used as `resource.labels.service_name` in every log filter and dashboard query."
  type        = string
  default     = "orders-api"
}

variable "runtime" {
  description = "Functions Framework runtime of the deployed function."
  type        = string
  default     = "python313"
}

variable "failure_rate" {
  description = "`FAILURE_RATE` environment variable of the function: probability of answering 500."
  type        = number
  default     = 0.02

  validation {
    condition     = var.failure_rate >= 0 && var.failure_rate <= 1
    error_message = "failure_rate must be between 0 and 1."
  }
}

variable "extra_latency_ms" {
  description = "`EXTRA_LATENCY_MS` environment variable of the function: artificial delay added to every request."
  type        = number
  default     = 0

  validation {
    condition     = var.extra_latency_ms >= 0 && var.extra_latency_ms <= 60000
    error_message = "extra_latency_ms must be between 0 and 60000."
  }
}

variable "max_instances" {
  description = "Upper bound on concurrent Cloud Run instances. Defaults to 1 because the API keeps its orders in the memory of one instance: a read routed elsewhere would answer a legitimate 404 that looks like a defect. The cost of this choice is that horizontal scaling becomes unobservable; see the header of `main.tf`."
  type        = number
  default     = 1

  validation {
    condition     = var.max_instances >= 1 && var.max_instances <= 100
    error_message = "max_instances must be between 1 and 100; the ceiling is what protects the budget."
  }
}

variable "min_instances" {
  description = "Instances kept warm. 0 scales to zero, so nothing is billed between runs at the price of a cold start on the first requests."
  type        = number
  default     = 0

  validation {
    condition     = var.min_instances >= 0
    error_message = "min_instances must not be negative."
  }
}

variable "concurrency" {
  description = "Requests served concurrently by one instance. The in-memory store is guarded by a lock, so a value above 1 is safe within a single instance and is the only throughput knob left when `max_instances` is 1."
  type        = number
  default     = 1

  validation {
    condition     = var.concurrency >= 1 && var.concurrency <= 1000
    error_message = "concurrency must be between 1 and 1000."
  }
}

variable "function_memory" {
  description = "Memory per instance, in the units the Cloud Functions API accepts (k, M, G, Mi, Gi). 512Mi leaves headroom over the measured footprint of the python313 runtime plus Functions Framework, so a cold start cannot fail the health check; 256Mi (the platform default) was too tight to rely on for a run that cannot be repeated cheaply."
  type        = string
  default     = "512Mi"
}

variable "function_timeout_s" {
  description = "Per-request timeout of the function. The simulator gives up earlier (10 s), so this only caps a pathological request."
  type        = number
  default     = 60

  validation {
    condition     = var.function_timeout_s >= 1 && var.function_timeout_s <= 3600
    error_message = "function_timeout_s must be between 1 and 3600."
  }
}

variable "allow_unauthenticated" {
  description = "Whether to grant `roles/run.invoker` to `allUsers`, which publishes an unauthenticated HTTP endpoint. `false` by default: the binding is prepared but not applied, because a public endpoint is a cost risk that the US$5 budget does not stop. See the end of `main.tf` for how to enable it only during the authorised run."
  type        = bool
  default     = false
}

variable "student_members" {
  description = "Extra IAM members granted read access to the observability resources. Empty by default so no binding is created."
  type        = list(string)
  default     = []
}

# --- Observability (phase 4) ------------------------------------------------

variable "log_bucket_id" {
  description = "ID of the regional log bucket that backs Log Analytics."
  type        = string
  default     = "cloudpulse-logs"
}

variable "log_bucket_retention_days" {
  description = "Retention of the log bucket. 30 days is the free tier; the laboratory only needs the 60 minutes of the run."
  type        = number
  default     = 30
}

variable "log_view_id" {
  description = "ID of the log view queried by the Log Analytics SQL in `docs/log-analytics-queries.sql`."
  type        = string
  default     = "cloudpulse_requests"
}

variable "metric_prefix" {
  description = "Prefix shared by every log-based metric, so they sort together in Cloud Monitoring."
  type        = string
  default     = "cloudpulse"
}

variable "dashboard_display_name" {
  description = "Display name of the single Cloud Monitoring dashboard."
  type        = string
  default     = "CloudPulse — orders API"
}

variable "amount_bucket_width" {
  description = "Width of the linear buckets of the `amount` distribution metric."
  type        = number
  default     = 25
}

variable "amount_bucket_count" {
  description = "Number of finite linear buckets of the `amount` distribution metric. 20 buckets of width 25 cover [0, 500], the range the simulator draws from; larger amounts land in the overflow bucket."
  type        = number
  default     = 20
}
