# Handoff — the handful of commands you actually need.
.DEFAULT_GOAL := help
PY ?= python

.PHONY: help install dev demo run serve desktop talk doctor test lint fmt docker site site-deploy clean

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Install Handoff and its dev tooling
	$(PY) -m pip install -e ".[dev,groq,desktop,web]"

demo:  ## The whole loop end to end, no keys needed
	$(PY) scripts/run_local.py --demo --offline

run:  ## Run the inbox-triage workflow once
	$(PY) -m handoff.cli run

serve:  ## Web UI on http://localhost:8000
	$(PY) -m handoff.cli serve

desktop:  ## Open Handoff in a native window, on the orb
	$(PY) -m handoff.cli desktop

talk:  ## A spoken conversation from the terminal (needs a microphone)
	$(PY) -m handoff.cli talk --mic

doctor:  ## Check which credentials actually work
	$(PY) -m handoff.cli doctor

test:  ## Run the test suite offline
	HANDOFF_FAKE_MODEL=true $(PY) -m pytest tests/ -q

lint:  ## Lint everything
	$(PY) -m ruff check src tests scripts infra

fmt:  ## Auto-fix what ruff can
	$(PY) -m ruff check --fix src tests scripts infra

docker:  ## Build the arm64 image AgentCore Runtime expects
	docker buildx build --platform linux/arm64 -t handoff:latest .

site:  ## Build the landing page and docs into site/dist
	$(PY) site/build.py --out site/dist

site-deploy: site  ## Publish site/dist to Cloudflare Pages (handoff-eya.pages.dev)
	wrangler pages deploy site/dist --project-name handoff --branch main --commit-dirty=true

clean:  ## Remove local state and caches
	rm -rf .handoff-state .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -not -path "./.venv*" -exec rm -rf {} + 2>/dev/null || true
