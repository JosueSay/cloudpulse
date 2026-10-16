# AGENTS.md — GCP Observable API Lab

## Project objective

Build a serverless Python API deployed to Google Cloud using Terraform, simulate 6,000 HTTP requests over 60 minutes, and analyze traffic, latency, errors, and scaling in one Cloud Monitoring dashboard.

## Architecture

- **Backend:** Python 3.13, Cloud Run functions, Functions Framework.
- **Infrastructure:** Terraform, Google Cloud IAM, Cloud Storage.
- **Traffic simulation:** Python, HTTPX, NumPy.
- **Observability:** Cloud Logging, Cloud Monitoring, Log Analytics SQL.

## Specialized agents

### Backend Architect

Responsible for `backend/`.

- Implement at least three API operations.
- Handle HTTP 400, 404, 409 and simulated 500 errors.
- Generate structured JSON logs.
- Propagate `X-Request-ID`.
- Include business attributes and latency measurements.

### DevOps Automator

Responsible for `infra/`.

- Provision infrastructure using Terraform.
- Configure IAM and service accounts.
- Deploy Cloud Run functions.
- Configure logging and monitoring.
- Avoid unnecessary cloud resources and costs.
- Never execute `terraform destroy` without approval.

### SRE Engineer

Responsible for observability.

- Configure native Cloud Monitoring metrics.
- Define log-based metrics before running the simulator.
- Analyze request throughput, p50/p95 latency, errors and active instances.
- Create Log Analytics SQL queries.
- Consolidate results in one dashboard.

### Code Reviewer

Responsible for validation.

- Review API behavior and HTTP responses.
- Verify structured logging fields.
- Check simulator configuration and concurrency.
- Validate Terraform configuration.
- Confirm compliance with laboratory requirements.

## Skills

Use these skills when applicable.

### Engineering practice

- `test-driven-development`: before implementing API behavior.
- `systematic-debugging`: when deployment, API or monitoring failures occur.
- `verification-before-completion`: before declaring a task complete.

### Google Cloud

- `gcloud`: before proposing or running any `gcloud` command.
- `cloud-run-basics`: when deploying or configuring the Cloud Run function.
- `google-cloud-storage-basics`: when provisioning the bucket that holds the function source.
- `iam-helper-for-policy-management`: when creating service accounts or granting roles.

### Observability

- `cloud-logging-configuration-basics`: when defining log buckets, log views and log-based metrics.
- `cloud-logging-query-generation`: when writing Logging Query Language filters over the structured events.
- `cloud-monitoring-metric-selection`: when identifying native Cloud Run metric descriptors.
- `cloud-monitoring-promql-query`: when writing PromQL for dashboard charts.
- `cloud-monitoring-chart-generation`: when generating dashboard widget definitions.

## Constraints

- Follow the laboratory specification.
- Preserve the required project structure.
- Do not hardcode credentials.
- Do not expose secrets in logs.
- Do not modify infrastructure without explaining the changes.
- Do not invent monitoring results or test outcomes.
- Ask for approval before destructive cloud operations.

## Definition of done

- API deployed and responding correctly.
- Simulator generates the configured traffic.
- `requests.csv` contains one record per request.
- Structured logs are available in Cloud Logging.
- Dashboard combines native metrics, log-based metrics, SQL charts and logs.
- Results can be traced using request identifiers.
