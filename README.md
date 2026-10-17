# Résumé Match · Evidence workbench

We designed a Django + React system that turns résumé text and weighted requirements
into a reviewable evidence report. Slow work runs through a durable queue; application
code validates each quoted skill mention and calculates the score.

![Numbered local flow: React submits a job; Django commits job and outbox; relay and RabbitMQ deliver work; the worker validates evidence and saves a score; React reads the result.](docs/assets/architecture.svg)

## One comparison, end to end

1. **Submit:** React sends the document, requirements and a retry identity.
2. **Accept:** Django commits the job and dispatch intent together in PostgreSQL, then returns `202 Accepted`.
3. **Relay:** the relay reads that intent and waits for broker confirmation before marking it sent.
4. **Queue:** RabbitMQ retains the job UUID for worker delivery.
5. **Process:** a Celery worker claims the job for a bounded time and extracts proposed evidence.
6. **Save:** code validates the quotes, computes weighted coverage and commits one result.
7. **Review:** React reads durable progress and the report. Request IDs connect safe logs across services in OpenObserve.

The database remains the source of truth when delivery repeats or the broker is unavailable.
Provider calls may repeat; the guarantee is one committed result per job.

## Run with Docker

Start Docker with Compose, then run from this repository:

```sh
./scripts/lab up
```

Open <http://127.0.0.1:8088> and use `./scripts/lab credentials` **in your private terminal**
for the generated login. Load the synthetic sample and submit it: the expected score is **80%**.
The log viewer runs at <http://127.0.0.1:5080>.

`./scripts/lab down` stops the stack and retains its volumes. Keep the ignored `.env`
with those volumes; it holds their existing passwords. `./scripts/lab help` lists commands.

## Review the design

- [Architecture and recovery](docs/architecture.md): numbered flow, trust boundaries and failure behavior.
- [Decisions](docs/decisions/0001-durable-background-work.md): why PostgreSQL, RabbitMQ and bounded workers.
- [Implementation reference](docs/implementation-guide.md): source map, API, log search, checks and observed results.

Local checks cover concurrent admission, duplicate workers, broker interruption and
log-viewer failure. [Report screenshot](docs/assets/workbench.png) · [Log search screenshot](docs/assets/log-search.png).

**Boundaries:** use synthetic data. This is a single-node local HTTP deployment with
Django debug enabled. Scores measure literal evidence coverage, not candidate quality.
PDF OCR and DOCX are unsupported. AWS calls stay disabled; Bedrock has mocked contract
tests only. Production identity, availability, security and model evaluation need further design.
