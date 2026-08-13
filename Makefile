SHELL := /bin/sh
PYTHON_QUALITY_IMAGE := aiops-x-python-quality:local
WEB_QUALITY_IMAGE := aiops-x-web-quality:local
WEB_E2E_IMAGE := aiops-x-web-e2e:local
GO_QUALITY_IMAGE := aiops-x-go-quality:local

.PHONY: setup quality-images dev test coverage lint typecheck build up down logs migrate seed-dev e2e e2e-live config helm-check performance-smoke check verify-m1 verify-m2 verify-m1-m2 test-acceptance-scripts test-deployment-scripts test-backup-scripts release clean

setup:
	@test -f .env || cp .env.example .env
	@test -f deploy/pki/agent-ca-key.pem || ./scripts/generate-agent-pki.sh deploy/pki 127.0.0.1
	find . \( -path './.git' -o -path './node_modules' -o -name '.python-deps*' \) -prune -o -name '._*' -type f -delete
	docker build --target python-quality -t $(PYTHON_QUALITY_IMAGE) -f deploy/compose/python.Dockerfile .
	docker build --target web-quality -t $(WEB_QUALITY_IMAGE) -f deploy/compose/web.Dockerfile .
	docker build --target go-quality -t $(GO_QUALITY_IMAGE) -f deploy/compose/agent.Dockerfile .

quality-images:
	find . \( -path './.git' -o -path './node_modules' -o -name '.python-deps*' \) -prune -o -name '._*' -type f -delete
	docker build --target python-quality -t $(PYTHON_QUALITY_IMAGE) -f deploy/compose/python.Dockerfile .
	docker build --target web-quality -t $(WEB_QUALITY_IMAGE) -f deploy/compose/web.Dockerfile .
	docker build --target go-quality -t $(GO_QUALITY_IMAGE) -f deploy/compose/agent.Dockerfile .

dev:
	docker compose --env-file .env up --build postgres redis nats minio api worker ai-engine web

test: quality-images
	docker run --rm $(PYTHON_QUALITY_IMAGE) pytest --cov=aiops_x_api.modules --cov-report=term-missing --cov-fail-under=80
	docker run --rm $(WEB_QUALITY_IMAGE) npm run test --workspace @aiops-x/web
	docker run --rm $(GO_QUALITY_IMAGE) /bin/sh -c 'cd agents/edge-agent && go test ./...'

coverage:
	uv run pytest --cov=aiops_x_api.modules --cov-report=term-missing --cov-fail-under=80

lint: quality-images
	docker run --rm $(PYTHON_QUALITY_IMAGE) ruff check apps scripts tests migrations
	docker run --rm $(WEB_QUALITY_IMAGE) /bin/sh -c 'npm run lint --workspace @aiops-x/web && npm run format:check --workspace @aiops-x/web'
	docker run --rm $(GO_QUALITY_IMAGE) /bin/sh -c 'cd agents/edge-agent && test -z "$$(gofmt -l .)" && go vet ./... && golangci-lint run ./...'

typecheck: quality-images
	docker run --rm $(PYTHON_QUALITY_IMAGE) mypy apps/api/src apps/worker/src apps/ai-engine/src
	docker run --rm $(WEB_QUALITY_IMAGE) npm run typecheck --workspace @aiops-x/web

build:
	docker build --target python-runtime -t aiops-x-python:local -f deploy/compose/python.Dockerfile .
	docker build --target web-build -t aiops-x-web-build:local -f deploy/compose/web.Dockerfile .
	docker build --target go-build -t aiops-x-edge-agent:local -f deploy/compose/agent.Dockerfile .

up:
	docker compose --env-file .env up -d --build

down:
	docker compose --env-file .env down

logs:
	docker compose --env-file .env logs -f --tail=200

migrate:
	docker compose --env-file .env run --rm api alembic upgrade head

seed-dev:
	docker compose --env-file .env run --rm api alembic upgrade head
	docker compose --env-file .env run --rm api python -m aiops_x_api.development.seed

e2e:
	PLAYWRIGHT_MANAGED_SERVERS=1 npm run e2e --workspace @aiops-x/web -- --reporter=list

e2e-live:
	docker build --target web-e2e -t $(WEB_E2E_IMAGE) -f deploy/compose/web.Dockerfile .
	docker run --rm --ipc=host -e PLAYWRIGHT_BASE_URL=http://host.docker.internal:8080 $(WEB_E2E_IMAGE) npm run e2e --workspace @aiops-x/web

config:
	docker compose --env-file .env.example config --quiet

helm-check:
	helm lint deploy/helm/aiops-x --set productionEnforced=false
	helm template aiops-x deploy/helm/aiops-x --set productionEnforced=false >/dev/null
	helm lint deploy/helm/aiops-x --set productionEnforced=false --set backup.enabled=true --set externalSecrets.enabled=true
	helm template aiops-x deploy/helm/aiops-x --set productionEnforced=false --set backup.enabled=true --set externalSecrets.enabled=true >/dev/null
	@! rg -n 'tag:[[:space:]]*latest|:[[:space:]]*latest' deploy/helm compose.yaml

performance-smoke:
	@test -n "$$AIOPS_BASE_URL" -a -n "$$AIOPS_ACCESS_TOKEN"
	k6 run --vus 1 --duration 15s tests/performance/k6-api.js

check: lint typecheck test build config helm-check test-acceptance-scripts test-deployment-scripts

verify-m1:
	uv run pytest -q tests/milestones/test_m1.py

verify-m2:
	uv run pytest -q tests/milestones/test_m2.py
	cd agents/edge-agent && go test -race ./...

verify-m1-m2:
	$(MAKE) verify-m1
	$(MAKE) verify-m2

test-acceptance-scripts:
	@for script in scripts/acceptance/m1_live.py scripts/acceptance/m1_persistence.py scripts/acceptance/m2_live.py scripts/acceptance/m2_supplemental_live.py scripts/acceptance/enterprise_live.py scripts/acceptance/first_e2e_live.py; do python3 "$$script" --help >/dev/null; done

test-deployment-scripts:
	@for script in scripts/release/*.sh scripts/deployment/*.sh scripts/backup/*.sh tests/deployment/*.sh; do bash -n "$$script"; done
	tests/deployment/test-release-scripts.sh
	tests/deployment/test-install-state-machine.sh
	tests/deployment/test-backup-scripts.sh

test-backup-scripts:
	tests/deployment/test-backup-scripts.sh

release:
	@scripts/release/create-release-archive.sh --release-id "$${RELEASE_ID:-$$(date -u '+%Y%m%dT%H%M%SZ')}"

clean:
	@echo "Generated artifacts are Docker images/volumes; use explicit Docker prune commands after review."
