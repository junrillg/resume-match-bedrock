# Résumé Match · Evidence workbench

A Django + React architecture lab for parsing résumés and reviewing transparent,
weighted skill coverage. AWS Bedrock proposes quoted evidence; application code
validates the quotes and calculates the score. The default demo stays entirely local.

![React to Django, bounded parsing, optional Bedrock extraction, evidence validation, deterministic scoring and owner-scoped storage.](docs/assets/architecture.svg)

## Run locally

Install Docker with Compose and start your Docker runtime. From the repository root:

```sh
./scripts/lab up
```

Open <http://127.0.0.1:8088>. The script generates private, ignored `.env` credentials,
builds the images, waits for PostgreSQL and RabbitMQ health, runs migrations, and starts
Gunicorn behind nginx serving the React production build. It creates the synthetic `lab`
account once. Use `./scripts/lab credentials` in your own terminal to view its password.
Only port 8088 is exposed, on loopback; PostgreSQL and RabbitMQ stay on the Compose network.
AWS remains disabled. RabbitMQ is ready for the next milestone; matching is still synchronous.

`./scripts/lab down` stops containers while retaining database and broker volumes. Your
existing development SQLite database is separate and untouched. Keep `.env` with the named
volumes: regenerating its passwords does not change passwords already initialized in them.
Use `./scripts/lab help` for commands. The stack is a local HTTP learning environment with
synthetic data and Django debug enabled, not an internet deployment.

### Run development servers without Docker

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22.12+ and npm.
From the repository root:

```sh
cd backend
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver 127.0.0.1:8000 --noreload
```

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open <http://127.0.0.1:5173>, sign in with the account you created, load the synthetic
sample, and run a match. Vite proxies `/api` to Django; cookies and CSRF remain same-origin.
No development account or password ships with the application. These development servers bind to
loopback and are not production servers.

## What you can review

- Paste a résumé or upload a selectable-text PDF / UTF-8 TXT file up to 1 MiB.
- Define explicit weighted requirements and inspect evidence for each skill.
- Review the score, missing mentions, and your latest 100 saved results; delete a result.
- Switch explicitly from the labeled local demo to the Bedrock adapter after setup.

The score measures weighted **literal evidence coverage**, not candidate quality or a
hiring recommendation. It does not infer skill aliases or validate competence,
experience duration, negation, or document truth. Review every quote. PDF OCR and DOCX
are outside this slice. Use synthetic data: saved evidence may contain personal data.

## Verify

```sh
cd backend
uv run python manage.py test matching
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

From the repository root in another terminal:

```sh
cd frontend
npm test
npm run build
```

Verified locally: 27 backend tests pass on SQLite and Compose PostgreSQL; the existing
6 frontend tests pass and TypeScript/Vite build passes inside the production image.
The Compose smoke check covers nginx, session cookies, CSRF rejection, login, an 80% match,
saved history and deletion. PostgreSQL, RabbitMQ, API and web health checks pass.
The fictional UI sample scores 80%, confirmed through Chrome on desktop and a mobile
viewport. [See the evidence report screenshot](docs/assets/workbench.png).

Tests cover scoring and extraction boundaries, owner isolation, enforced CSRF, file
validation, and mocked provider failures. They do not establish live Bedrock access or
model accuracy. See [the architecture case study](docs/architecture.md) for decisions,
failure behavior, current official sources and production limits.

## Enable Bedrock deliberately

AWS is disabled by default. When you have chosen an approved account, region, model
and spend limit, use your AWS SDK credential chain (for example an authenticated
`AWS_PROFILE`) and restart Django with these variables set:

```sh
export MATCH_PROVIDER=bedrock
export AWS_REGION=YOUR_APPROVED_REGION
export BEDROCK_MODEL_ID=YOUR_SUPPORTED_CONVERSE_MODEL_OR_INFERENCE_PROFILE
uv run python manage.py runserver 127.0.0.1:8000 --noreload
```

This command runs from `backend/`. Credentials never belong in browser code, Git or
command arguments. The caller needs resource-scoped `bedrock:InvokeModel` permission.
The adapter has bounded timeouts, one total attempt and a token limit. Provider failures
return safe errors; they never fall back to a demo score. Model support, IAM, cross-region
inference and invocation logging must be reviewed in your own account before real calls.

## Code map

| Path | Responsibility |
| --- | --- |
| `backend/matching/services.py` | File parsing, extraction prompt, Bedrock boundary, evidence validation and score formula |
| `backend/matching/views.py` | Session API, validation, quotas and owner-scoped result access |
| `backend/matching/models.py` | Results and request counters |
| `backend/matching/tests.py` | Backend behavior and provider contract tests |
| `frontend/src/` | React forms, authenticated requests, score evidence and history |
| `docs/assets/architecture.mmd` | Editable implementation diagram |

This is an enterprise-oriented learning baseline, not a certified enterprise deployment.
Production needs an operational design for SSO/RBAC, organization isolation, storage
retention, network protections, abuse controls, observability and model evaluation.
