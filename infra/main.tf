# Compute infrastructure of the CloudPulse laboratory (phase 3).
#
# This file provisions everything the orders API needs to exist and to be
# observable, and nothing else:
#
#   project services -> service accounts -> IAM -> source bucket -> source
#   object -> Cloud Run function (gen 2, python313, entry point `handle`)
#
# The observability resources that consume these (log bucket, sink, view,
# four log-based metrics and the dashboard) live in `logging.tf` and
# `monitoring.tf` and are not touched here. They reference the function only by
# name (`resource.labels.service_name="${var.function_name}"`), which is why the
# Cloud Run service created below must keep that exact name.
#
# --- Laboratory decisions, with their cost ---------------------------------
#
# 1. SCALING: `max_instances` defaults to 1. The API stores orders in the
#    memory of one instance, so a read or a cancel routed to a second instance
#    would answer a legitimate 404 that looks like a defect in `requests.csv`.
#    One instance removes that noise.
#    Cost: horizontal scaling becomes unobservable — the
#    `container/instance_count` chart of the dashboard stays flat at 1, and the
#    `max_instance_request_concurrency` of the single instance becomes the only
#    throughput knob. Observing real autoscaling needs shared storage
#    (Firestore, Memorystore or Cloud SQL) instead of the in-memory dict, which
#    is out of scope for this laboratory.
#
# 2. AUTHENTICATION: `allow_unauthenticated` defaults to `false`, so NO public
#    access is granted by this configuration. See the binding at the bottom of
#    this file for what enabling it implies and how to scope it in time.
#
# 3. COST: the instance ceiling, the request concurrency, the memory, the
#    timeout and `min_instance_count = 0` are all explicit. The US$5 budget is
#    an alert, not a limit — Google Cloud does not suspend anything when it is
#    reached — so the ceilings here are the real protection.

locals {
  # APIs the compute path needs. `logging` and `monitoring` are listed too so
  # the configuration is self-contained: the observability resources must not
  # depend on an API someone happened to enable by hand.
  required_services = [
    "artifactregistry.googleapis.com", # stores the image Cloud Build produces
    "cloudbuild.googleapis.com",       # builds the source zip into that image
    "cloudfunctions.googleapis.com",   # the gen 2 function API
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com", # service accounts
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com", # gen 2 functions run on Cloud Run
    "storage.googleapis.com",
  ]

  # Bucket names are globally unique, so the project id is part of the name.
  source_bucket_name = "${var.project_id}-${var.function_name}-source"

  # Applied to the resources that support labels, so the billing report can be
  # grouped by this laboratory instead of by resource type.
  labels = {
    app   = "cloudpulse"
    lab   = "observability"
    owner = "terraform"
  }
}

# --- Project services -------------------------------------------------------

# Enabling an API is idempotent: the ones already on stay on.
#
# `disable_on_destroy = false` is deliberate. A `terraform destroy` that turned
# `run` or `logging` off would reach far beyond this laboratory — other
# resources in the project depend on those APIs, and re-enabling them is slow.
# Destroying the laboratory must remove the laboratory, not the project's
# capabilities.
resource "google_project_service" "required" {
  for_each = toset(local.required_services)

  project = var.project_id
  service = each.value

  disable_on_destroy         = false
  disable_dependent_services = false
}

# The project number is part of the name of the bucket Cloud Functions manages
# for staging source code (see `build_staging_reader` below). Reading it keeps
# that name out of the configuration as a literal.
data "google_project" "this" {
  project_id = var.project_id
}

# --- Service identities -----------------------------------------------------

# The function must NOT run as the Compute Engine default service account:
# that identity carries `roles/editor` over the whole project. Two dedicated
# accounts instead, each with the minimum its job needs.

# Runtime identity. The API talks to no other Google Cloud service, so writing
# log entries is the only permission it ever needs.
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${var.function_name}-run"
  display_name = "CloudPulse orders API runtime"
  description  = "Identity of the deployed function. Writes logs; nothing else."

  depends_on = [google_project_service.required]
}

# Build identity, used by Cloud Build to turn the source zip into a container.
resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "${var.function_name}-build"
  display_name = "CloudPulse orders API build"
  description  = "Identity Cloud Build uses to package the function source."

  depends_on = [google_project_service.required]
}

# --- IAM --------------------------------------------------------------------

# The structured JSON event of every request is written to stdout, which Cloud
# Run forwards to Cloud Logging under the runtime identity. Without this role
# the function answers normally and the dashboard stays empty.
resource "google_project_iam_member" "runtime_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# What the builder needs, and only that:
#   * write its build logs
#   * push the resulting image to Artifact Registry
#   * read the source zip (granted on the bucket below, not project-wide)
resource "google_project_iam_member" "build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_project_iam_member" "build_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.build.email}"
}

# Scoped to the single bucket that holds the zip. The upstream example for a
# custom builder grants `roles/storage.objectAdmin` over the whole project;
# read access to one bucket is the least privilege that can still fetch the
# source.
resource "google_storage_bucket_iam_member" "build_source_reader" {
  bucket = google_storage_bucket.source.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"
}

# Cloud Functions v2 does NOT build from the bucket above. It copies the
# uploaded object into a bucket of its own —
# `gcf-v2-sources-<project number>-<region>` — and the build reads the source
# from there. The first apply failed exactly here:
#
#   Access to bucket gcf-v2-sources-199050280954-us-central1 denied.
#   You must grant Storage Object Viewer permission to
#   orders-api-build@cloudpulse-lab-2026.iam.gserviceaccount.com.
#
# That bucket carries only the legacy project-level roles
# (`storage.legacyObjectReader` and friends, held by project viewers, editors
# and owners). The default Cloud Build identity is a project editor, so it
# reads the staged source without any extra binding; a dedicated least-
# privilege account is deliberately none of those, so it must be named
# explicitly.
#
# `..._iam_member` is additive: it adds one member to one role and leaves the
# bindings Cloud Functions put there untouched. An `..._iam_binding` or
# `..._iam_policy` would be authoritative and could strip them.
#
# The role is the one the error asks for, `roles/storage.objectViewer`, scoped
# to this single bucket — not `objectAdmin`, and not a project-level grant.
# What it does expose is every object in that bucket, which holds the staged
# sources of all gen 2 functions of the region; this project has one.
#
# Ordering caveat: the bucket is created by Cloud Functions the first time it
# stages a build, so it does not exist in a brand-new project. That is why this
# is not a `data "google_storage_bucket"` lookup — a data source would make
# `plan` itself fail before the bucket exists. In a fresh project the first
# `apply` creates the bucket and fails on the function, and the second succeeds.
resource "google_storage_bucket_iam_member" "build_staging_reader" {
  bucket = "gcf-v2-sources-${data.google_project.this.number}-${var.region}"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"

  depends_on = [google_project_service.required]
}

# Optional read access to the observability surface for the people reviewing
# the laboratory. `student_members` is empty by default, so no binding is
# created unless somebody is named in `terraform.tfvars`.
#
# Two narrow viewer roles, never a basic role: `roles/viewer` would also expose
# every other service in the project.
resource "google_project_iam_member" "reviewer_monitoring" {
  for_each = toset(var.student_members)

  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = each.value
}

resource "google_project_iam_member" "reviewer_logging" {
  for_each = toset(var.student_members)

  project = var.project_id
  role    = "roles/logging.viewer"
  member  = each.value
}

# --- Source code ------------------------------------------------------------

# Holds the zipped function source. Uniform bucket-level access and enforced
# public access prevention: the zip is reachable through IAM only, and no ACL
# or future binding can make it public.
resource "google_storage_bucket" "source" {
  project  = var.project_id
  name     = local.source_bucket_name
  location = var.region
  labels   = local.labels

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # The bucket only ever holds a few small zips. Deleting the superseded ones
  # keeps it from accumulating one object per redeployment forever.
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  # A laboratory resource must be removable: without this, `destroy` fails as
  # long as the bucket still holds a zip.
  force_destroy = true

  depends_on = [google_project_service.required]
}

# The zip is built from an explicit file list instead of from the whole
# `backend/` directory: that excludes `__pycache__` by construction and keeps
# the archive hash stable, so a redeployment happens when the code changes and
# not when a local test run leaves a `.pyc` behind.
data "archive_file" "source" {
  type        = "zip"
  output_path = "${path.module}/../outputs/terraform/${var.function_name}-source.zip"

  source {
    content  = file("${path.module}/../backend/main.py")
    filename = "main.py"
  }

  source {
    content  = file("${path.module}/../backend/requirements.txt")
    filename = "requirements.txt"
  }
}

# The hash is part of the object name, so changing the backend uploads a new
# object and the function picks it up. Overwriting one fixed object name would
# leave the deployed revision stale.
resource "google_storage_bucket_object" "source" {
  name   = "${var.function_name}/source-${data.archive_file.source.output_md5}.zip"
  bucket = google_storage_bucket.source.name
  source = data.archive_file.source.output_path
}

# IAM bindings are eventually consistent: a build started in the same apply
# that created the builder's permissions can fail to read the source zip. The
# upstream provider example solves it with exactly this wait.
resource "time_sleep" "build_iam_propagation" {
  create_duration = "60s"

  depends_on = [
    google_project_iam_member.build_log_writer,
    google_project_iam_member.build_artifact_writer,
    google_storage_bucket_iam_member.build_source_reader,
    google_storage_bucket_iam_member.build_staging_reader,
  ]
}

# --- The function -----------------------------------------------------------

resource "google_cloudfunctions2_function" "orders_api" {
  project     = var.project_id
  name        = var.function_name
  location    = var.region
  description = "CloudPulse orders API: three operations, structured JSON logs."
  labels      = local.labels

  build_config {
    runtime         = var.runtime
    entry_point     = "handle"
    service_account = google_service_account.build.id

    source {
      storage_source {
        bucket = google_storage_bucket.source.name
        object = google_storage_bucket_object.source.name
      }
    }
  }

  service_config {
    # Scaling and concurrency: both ceilings explicit, see decision 1 and 3.
    max_instance_count               = var.max_instances
    min_instance_count               = var.min_instances
    max_instance_request_concurrency = var.concurrency

    # One vCPU is the smallest size that allows a request concurrency above 1,
    # so raising `concurrency` later needs no change here.
    available_cpu    = "1"
    available_memory = var.function_memory

    # Upper bound per request. The simulator gives up earlier (`timeout_s` in
    # `simulator/config.json`, 10 s), so this only caps a pathological request.
    timeout_seconds = var.function_timeout_s

    # Read per request by `backend/main.py`, which validates and clamps both.
    # Strings because the function reads them from the environment.
    environment_variables = {
      FAILURE_RATE     = tostring(var.failure_rate)
      EXTRA_LATENCY_MS = tostring(var.extra_latency_ms)
    }

    service_account_email          = google_service_account.runtime.email
    all_traffic_on_latest_revision = true

    # Reachable from the internet, which is what lets the simulator run from a
    # workstation. Reachability is not authorisation: without the invoker
    # binding below, every unauthenticated request is answered with 403.
    ingress_settings = "ALLOW_ALL"
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.runtime_log_writer,
    time_sleep.build_iam_propagation,
  ]
}

# --- Who may invoke the function -------------------------------------------

# DISABLED BY DEFAULT (`allow_unauthenticated = false`).
#
# Granting `roles/run.invoker` to `allUsers` publishes an unauthenticated HTTP
# endpoint. The laboratory data is synthetic, so the data risk is nil, but the
# COST risk is not: anybody who finds the URL can generate billable
# invocations, and the US$5 budget does not stop them.
#
# `roles/run.invoker` is the narrow, documented way to do this — never a basic
# role, which would expose the rest of the project. It governs the `run.app`
# endpoint, which is the one the `function_url` output returns and the one the
# simulator must be pointed at. The legacy `cloudfunctions.net` address
# (`gcf_uri`) is gated by `roles/cloudfunctions.invoker` instead and is not
# granted here on purpose: one public surface is enough.
#
# How to enable it only for the authorised experiment:
#
#   1. `terraform apply -var allow_unauthenticated=true` right before the run.
#   2. Run the simulator against the URL in the `function_url` output.
#   3. `terraform apply -var allow_unauthenticated=false` immediately after,
#      which removes the binding and leaves the data and the logs intact.
#   4. Keep `max_instances` low throughout, and do not publish the URL.
#
# The alternative is to keep the function private and sign every request with
# an identity token. The simulator does not support that today: `_execute`
# sends only `X-Request-ID`, so a private function would answer all 6,000
# requests with 403.
resource "google_cloud_run_service_iam_member" "public_invoker" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = google_cloudfunctions2_function.orders_api.location
  service  = google_cloudfunctions2_function.orders_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
