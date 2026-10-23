.DEFAULT_GOAL := help
.NOTPARALLEL:

.PHONY: help up down restart logs status credentials sample build test test-cli \
	test-backend test-frontend test-proxy verify check-config check-terraform check check-standards

help:
	@printf '%s\n' \
	  'Usage: make <target> (default: help)' \
	  '  up             Build/start the complete local lab; wait for readiness' \
	  '  down           Remove lab containers/networks; preserve named volumes' \
	  '  restart        Restart services and wait; preserve data and credentials' \
	  '  logs           Follow container logs (Ctrl-C stops following)' \
	  '  status         Show Compose service health' \
	  '  credentials    Show generated logins; use only in a private terminal' \
	  '  sample         Run a disposable synthetic journey; report result and IDs' \
	  '  build          Validate Compose and build application images' \
	  '  test           Run CLI, PostgreSQL, frontend and nginx tests sequentially' \
	  '  test-cli       Run side-effect/failure boundary tests without Docker' \
	  '  test-backend   Run Django in a disposable container and test database' \
	  '  test-frontend  Build the locked Node environment and run Vitest' \
	  '  test-proxy     Build nginx and run isolated proxy tests' \
	  '  check-config   Check Django configuration and migration drift' \
	  '  check-terraform  Run credential-free format/validate/mock-plan checks' \
	  '  verify         Run existing build, test, config and Terraform checks' \
	  '  check          Run verify, then fail on missing quality/security gates' \
	  '  check-standards  Report the unconfigured quality/security gates (fails)' \
	  'Requires: GNU Make 3.81+, POSIX sh, Docker/Compose with --wait, Python 3.12+.' \
	  'First startup also needs openssl, internet and at least 8 GiB Docker memory.' \
	  'Run make up before build/test/sample/check-config/verify/check.' \
	  'Terraform checks require Terraform 1.15.8 and registry access; no AWS calls.' \
	  'Variables: no Make-specific overrides; Compose environment selection is inherited.' \
	  'Help performs no configuration reads, Docker calls, network calls or writes.'

up down restart logs status credentials sample build:
	@./scripts/lab $@

test: test-cli test-backend test-frontend test-proxy

test-cli:
	python3 -m unittest discover -s scripts -p 'test_*.py'

test-backend:
	@./scripts/lab test

test-frontend:
	docker build --target build --tag resume-match-frontend-test:local --file frontend/Dockerfile .
	docker run --rm --network none resume-match-frontend-test:local npm test

test-proxy:
	docker build --tag resume-match-web-test:local --file frontend/Dockerfile .
	NGINX_TEST_IMAGE=resume-match-web-test:local python3 frontend/test_proxy.py

check-config:
	docker compose config --quiet
	docker compose run --rm --no-deps -T api python manage.py check
	docker compose run --rm --no-deps -T api python manage.py makemigrations --check --dry-run

check-terraform:
	terraform -chdir=infra/terraform fmt -check -recursive
	terraform -chdir=infra/terraform init -backend=false -input=false -lockfile=readonly
	terraform -chdir=infra/terraform validate
	terraform -chdir=infra/terraform test -no-color

verify:
	$(MAKE) build
	$(MAKE) test
	$(MAKE) check-config
	$(MAKE) check-terraform

check: verify check-standards

check-standards:
	@printf '%s\n' \
	  'BLOCKED: formatter/linter profiles, backend type checking and security scans are not configured.' \
	  'Missing scans: dependency advisories, secrets, source/configuration and container images.' \
	  'make verify covers existing checks only. Configure and wire these gates before making check pass.' >&2
	@exit 1
