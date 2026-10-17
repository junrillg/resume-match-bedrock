# AWS architecture icon provenance

The diagrams use the official **Amazon Bedrock** service icon. Local PostgreSQL,
RabbitMQ and OpenObserve are not depicted as AWS managed services.

- Publisher and guidance: [AWS Architecture Icons](https://aws.amazon.com/architecture/icons/), checked **17 October 2026**.
- Current package linked by that page: [Icon package — 31 July 2026](https://d1.awsstatic.com/onedam/marketing-channels/website/public/shared/architecture-icon-release/Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip).
- Selected archive entry: `Architecture-Service-Icons_07312026/Arch_Artificial-Intelligence/64/Arch_Amazon-Bedrock_64.svg`.
- Retained file: [`Arch_Amazon-Bedrock_64.svg`](Arch_Amazon-Bedrock_64.svg), unchanged bytes; SHA-256 `80fa4190bb55bde5c3004ed8d2f16bf25db28d230cf46760813f2171636ea105`.

AWS's icon page permits customers and partners to use the assets in architecture
diagrams and related materials, and asks users of third-party libraries to check
for current icons. No separate license or usage-guidance document was present in
the downloaded ZIP. The icon remains an AWS asset; this repository's application
license does not relicense it. Use does not imply AWS endorsement or a deployment.

## Diagram sources

[`architecture.svg`](../architecture.svg) and
[`enterprise-context.svg`](../enterprise-context.svg) are editable native SVG
sources and the published exports. Each embeds the original icon's vector content
inside a proportionally scaled nested SVG: no external network/image load,
recoloring or redrawing. Their `.mmd` companions document the same logical flows;
they are not generators for the published layout. Preserve both representations
when changing the flow, and retain the icon's original geometry and colors.
