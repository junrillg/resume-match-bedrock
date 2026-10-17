# Evidence before scoring

This fictional recruiting workbench demonstrates a trust boundary: an AI provider can
propose résumé evidence, but application code validates it and calculates the score.
It is an architecture lab with enterprise-oriented controls, not a production hiring platform.

![Architecture: React sends bounded input to an authenticated Django API; validated demo or Bedrock evidence is scored and stored per owner.](assets/architecture.svg)

![Conceptual illustration: documents pass through a sieve and selected evidence is weighed. This is a nonliteral analogy.](assets/evidence-concept.png)

The illustration is a nonliteral analogy: evidence is filtered before weights are counted.

## One execution

A reviewer signs in, supplies a synthetic résumé, and defines weighted job requirements.
Django validates the request before extraction. The default demo runs locally; the
Bedrock path uses a separate system instruction and treats the submitted document as
untrusted data. The provider cannot supply weights or the final score. A strict result
validator rejects unknown skills and evidence absent from the source. The server computes
`100 × matched requirement weight / total requirement weight`, stores an owner-scoped
result, and returns the score with quotes and gaps. React renders quotes as text.

## Decisions and limits

- Explicit, reviewer-controlled requirements keep the denominator inspectable. This is
  not automatic job-description interpretation. Weights can still encode human bias.
- Quoted skill mentions provide provenance, not proof of competence, years of experience,
  positive context, or suitability. Negations and instruction-like text can contain real
  skill names. Human review remains necessary; prompt separation is not an injection guarantee.
- Bedrock is opt-in. A timeout, access error, truncated response, or invalid extraction
  fails the request; it must never silently become a successful demo result.
- Local SQLite keeps the slice runnable. Session authentication, CSRF, owner-scoped
  access, bounded requests and provider budgets are implemented controls. SSO,
  organizational tenancy/RBAC, PostgreSQL operations, asynchronous queues, malware
  scanning, distributed quotas, retention automation, HA and operational alerting are
  production follow-up work, not boxes in the implemented diagram.
- Source documents are not deliberately persisted. Evidence quotes are persisted and
  can still contain personal data. Local database files are ignored by Git. Use synthetic
  records here; deletion removes a result, not backups or operator logs.

## Failure boundary

An unauthenticated request is rejected. CSRF applies to login and mutations. A result
belongs to its creator; another user cannot list or delete it. Bad file types, empty
extraction, oversized input and invalid requirements stop before a model call. Per-user
attempt limits bound provider use; credentials stay in the AWS SDK credential chain.
The application must not log résumé bodies, credentials or raw provider exceptions.
Request IDs connect safe client errors with operational events.

## Bedrock operations

Before enabling real calls, choose an approved AWS account/profile, region and supported
Converse model or inference profile; review IAM, cost and data handling. The necessary
inference permission is `bedrock:InvokeModel`; an inference profile may require access
to its underlying regional models. Scope permissions to the chosen resources. Never
use wildcard administrative access as a setup shortcut.

Bedrock model invocation logging is account/region configuration and can capture full
requests/responses to CloudWatch or S3 when enabled. Review that setting and retention
before using personal documents. No real AWS invocation was authorized for this lab.
Mocked adapter tests establish request and failure behavior, not live model access,
model quality, fairness or accuracy.

## Sources

Official sources accessed 2026-10-17. Installed dependency versions are pinned in the
backend lockfile and frontend package lock; these docs describe the relevant API families.

| Source | Version / decision |
| --- | --- |
| [Django release support](https://www.djangoproject.com/download/) | Django 5.2 LTS line; use a supported patched release available from the registry. |
| [Django CSRF](https://docs.djangoproject.com/en/5.2/howto/csrf/) | Bootstrap a CSRF token, send it on same-origin requests, and test with CSRF enforcement. |
| [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) | Local development is distinct from hardened production deployment. |
| [Boto3 Converse](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html) | Separate system instructions, bounded inference configuration, validate response content and stop reason. |
| [Botocore Config](https://docs.aws.amazon.com/botocore/latest/reference/config.html) | Explicit connection/read timeouts and total attempt bound. |
| [Boto3 retries](https://docs.aws.amazon.com/boto3/latest/guide/retries.html) | `total_max_attempts` includes the initial attempt. |
| [Bedrock invocation logging](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html) | Account logging can retain request and response content. |
| [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | Text PDFs only; compressed size alone does not bound decompressed processing. |
| [React versions](https://react.dev/versions) | React 19 browser interface; no server components needed. |

The score formula and evidence validator are design choices. The local demo is a learning
simplification, not research evidence of model performance.
