# ADR 0002: evidence and data boundaries

Status: accepted for evidence/scoring. Source-retention decision superseded by [ADR 0006](0006-durable-document-lifecycle.md).

## Context and alternatives

An opaque model-generated suitability score cannot show a reviewer which denominator,
weights or document claims produced it. Skill mentions can be fabricated, negated or
used as embedded instructions. Background workers also need the document after HTTP ends.

## Decision

The reviewer supplies weighted requirements. The provider proposes a strict list of
verbatim quotes; application code validates schema, original-source skill boundaries
and quote existence, then calculates the score. Separate system instructions from
untrusted document data. Publish only job IDs to the broker. The original decision kept
normalized text only during queued work; ADR 0006 replaces that policy with retained
private originals, database extraction/metadata and explicit lifecycle/recovery.

## Consequences and verification

This proves provenance/coverage, not competence, positive experience, fairness or truth.
Persisted evidence remains potentially personal. The default local provider is clearly
labeled; adapter tests do not establish live Bedrock quality/access. Verify forged quotes,
SQL/MySQL boundaries, prompt-like text, malformed provider output, upload limits,
owner isolation and the source lifecycle defined by ADR 0006. Review provider account invocation logging before
real data. [Converse API](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html),
[pypdf limits](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
[Bedrock logging](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html).
