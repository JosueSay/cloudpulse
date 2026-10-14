.DEFAULT_GOAL := help

.PHONY: help install extensions extensions-list check test lint format infra-fmt infra-validate

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies and VS Code extensions
	@uv sync
	@$(MAKE) --no-print-directory extensions

extensions:
	@bash scripts/extensions.sh install

extensions-list:
	@bash scripts/extensions.sh list

check: lint test infra-fmt ## Run local validation

test: ## Run Python tests
	@uv run python -m pytest tests/

lint: ## Check Python code with Ruff
	@uv run ruff check backend simulator tests

format: ## Format Python code
	@uv run ruff format backend simulator tests

infra-fmt: ## Check Terraform formatting
	@terraform -chdir=infra fmt -check -recursive

infra-validate: ## Validate initialized Terraform configuration
	@terraform -chdir=infra validate
