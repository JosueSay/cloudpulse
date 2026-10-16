# Terraform and provider requirements.
#
# Declared in phase 4 because the observability resources (log bucket, log view,
# log-based metrics and dashboard) are the first resources in this configuration
# and they cannot be validated without a provider.
#
# Two auxiliary providers were added with the compute resources of phase 3:
#
#   * `archive` packages `backend/` into the zip the function is built from.
#     Terraform cannot create an archive on its own, and the alternative — a zip
#     built outside Terraform — would make `plan` depend on a manual step.
#   * `time` holds the apply for 60 s after the builder's IAM bindings are
#     created. IAM is eventually consistent, and a build that starts too early
#     cannot read the source zip. This is the wait the upstream provider
#     example for a custom build service account prescribes.
#
# Neither provider creates cloud resources or costs anything.

terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.7"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }

    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
