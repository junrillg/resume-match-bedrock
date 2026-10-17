# Learn one concept at a time

Links and public descriptions checked **2026-10-17**. These are supplementary: no video
is required to run or rebuild the lab. Resource pages and topic fit were inspected;
video playback and subscription lessons were not watched or tested. Recording links
may preserve a start position supplied by their original page; no viewing or completion
is implied. Start with one concept, not an entire watch list.

| Topic | Resource and creator | Use here / access / differences |
| --- | --- | --- |
| Run the whole system | [Learning Docker Compose: Simplified Multi-Container Application Management](https://www.linkedin.com/learning/learning-docker-compose-simplified-multi-container-application-management), Pawel Piwosz, LinkedIn Learning, 2026 | Choose networks, volumes and startup dependencies. Full course advertised as 1h23m; account/subscription or institutional access. Public alternative: [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/). Local Compose is not HA. |
| Evidence / structured output | [Claude with Amazon Bedrock by Anthropic](https://www.linkedin.com/learning/claude-with-amazon-bedrock-by-anthropic), Anthropic, LinkedIn Learning, 2026 | Select structured data, model output and JSON-schema lessons; the full course is 7h26m and needs account/access. Model-specific examples are not universal Converse guarantees. Public alternative: [AWS structured output](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html). AWS calls stay disabled. |
| Atomic database-to-queue handoff | [Serverless Transactional Outbox Pattern on AWS](https://boristane.com/talks/serverless-transactional-outbox-pattern-on-aws/), Boris Tane, SST Conf 2022; [YouTube recording](https://youtu.be/6FzLjpMYcu8?t=1793) linked by the speaker | Understand the dual-write problem. Public older serverless talk: apply the pattern, not its AWS tooling, to this Django/PostgreSQL implementation. The recording link comes from the speaker page; playback was not verified. [AWS written pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html) is the authoritative reference. |
| Workers and delivery failures | [Conquering the Queue: Lessons from processing one billion Celery tasks](https://pycon.de/archive/2025/talks/conquering-the-queue-lessons-from-processing-one-billion-celery-tasks/), Daniel Hepper, PyCon DE 2025; [recording](https://www.youtube-nocookie.com/embed/mb7a_WErTck) | Public practitioner talk for acknowledgements, prefetch and failure diagnosis. Its deployment uses Redis; this lab uses RabbitMQ. Start with [RabbitMQ confirms and acknowledgements](https://www.rabbitmq.com/docs/confirms) for the broker contract. |
| Job-aware React | [Synchronizing with Effects](https://react.dev/learn/synchronizing-with-effects), React maintainers | Public written tutorial on lifecycle cleanup and cancelling/ignoring stale fetches. Pair it with the lab's polling and authentication-loss regressions; no framework change is required. |
| Safe diagnostics | [Getting Started with OpenTelemetry (LFS148)](https://training.linuxfoundation.org/training/getting-started-with-opentelemetry-lfs148/), Linux Foundation | Free enrollment/account; advertised full course is 8–10 hours. Choose the overview and manual instrumentation topics only. Collector, metric and trace topics extend beyond this direct-log-export lab. |
| Search and correlation | [Correlate your logs, metrics & traces with OpenObserve](https://openobserve.ai/webinars-videos/correlate-your-logs-metrics-and-traces-with-openobserve/), Manas Sharma / OpenObserve, 2026; [YouTube: Logs, Metrics, Traces: How to Correlate Them with OpenTelemetry](https://www.youtube.com/watch?v=kft86_LA-Pg) | Vendor overview, advertised five minutes. Use its public video link; no marketing registration is needed. The lab implements safe logs, not metrics/traces or every demonstrated Enterprise feature. [Public OTLP documentation](https://openobserve.ai/docs/reference/api/ingestion/logs/otlp/) supports the actual API contract. |

After a resource, predict one observable behavior in this application and verify it.
Then rebuild that small mechanism in a scratch repository using the
[implementation guide](implementation-guide.md). Keep personal answers and progress
outside the public repository.
