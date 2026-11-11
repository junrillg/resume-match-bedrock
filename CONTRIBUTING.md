# Contributing

Start with the [README](README.md#run-locally) and [architecture](docs/architecture.md). Use synthetic résumé data for development and examples. The local runtime includes persistent volumes and generated credentials; preserve `.env` and avoid deleting volumes to restart it.

## Run the relevant checks

`make help` lists supported targets without Docker or network access. After `make up`:

```sh
make test           # CLI, Django/PostgreSQL, frontend, and nginx suites
make verify         # Build images, run suites, check config and Terraform mocks
```

Focused targets are `make test-cli`, `make test-backend`, `make test-frontend`, and `make test-proxy`. `test-cli` needs no Docker daemon. Run `make build` before focused backend or configuration checks after source changes; run `make up` to update the serving application. Keep Node-heavy tests/builds sequential.

`make check-config` checks Compose/Django configuration and migration drift. `make check-terraform` requires Terraform 1.15.8 and registry access; it performs credential-free format, validation, and mocked plan checks. It does not deploy AWS resources.

`make check` is the CI entry point. It runs `verify` and then fails explicitly until formatter/linter profiles, backend type checking, and dependency/secret/source/configuration/container security scans are configured. Do not describe `make verify` as a complete quality or security gate.

`make sample` exercises the running synthetic comparison and removes its own fixture data. `make down` preserves named volumes. Run `make credentials` only in your private terminal, never in shared logs or CI.

## Keep changes reviewable

Describe the user-visible change, its scope, and the checks you actually ran. Update linked documentation when behavior or commands change. Keep architecture diagrams aligned with real ownership and distinguish the local runtime from the undeployed AWS design. Include a focused regression check for changed behavior; avoid unrelated refactors and generated credentials or candidate records.

The source entry points and verification details are in the [implementation reference](docs/implementation-guide.md).

## Terms and sensitive reports

The project uses the [MIT license](LICENSE); vendor marks retain their separately documented terms. No private vulnerability-reporting channel is currently documented. Keep credentials, original candidate data, and sensitive vulnerability details out of public reports.
