# Architecture overview assets

The [editable HTML](architecture-overview.html) is authoritative; its inline SVG is
exported unchanged to [architecture-overview.svg](architecture-overview.svg).
All rendering assets are embedded. Text and function pictograms remain editable;
the official PostgreSQL mark is an embedded PNG, not a traced approximation.

| Asset | Source, retrieved 11 November 2026 | Terms |
| --- | --- | --- |
| React mark | [Official React repository](https://github.com/facebook/react/blob/5797664094c6aec19f60479523fed5d7d654dba0/fixtures/dom/public/react-logo.svg), SHA-256 `671afde83899249e6c2883b0d1592fc00886d3c0620d20bcab566cd2caa97f1a` | MIT notice below; original geometry and blue preserved, dark backing added |
| PostgreSQL mark | [Official press asset](https://www.postgresql.org/media/img/about/press/elephant.png), SHA-256 `ff92fb5d12a7fa6b23c2eb403d2edf4fbc58ced802021e1f02c3583cb70957be` | [Press-kit logo terms](https://www.postgresql.org/about/press/presskit12/ru/), [PostgreSQL License](https://www.postgresql.org/about/licence/) and [trademark policy](https://www.postgresql.org/about/policies/trademarks/) |
| Function pictograms | Original 24-unit paths in the HTML | People, document, database, queue, worker, shield, relay, terminal and deletion actions |

Postgres, PostgreSQL and the Slonik Logo are trademarks or registered trademarks of
the PostgreSQL Community Association of Canada. React marks belong to their owners.
The marks identify actual technologies; no sponsorship or endorsement is implied.
RabbitMQ is a trademark of Broadcom, Inc. in the U.S. and other countries.

Technology nodes now use their actual product marks. Relay, custom HTTP fixture,
SSE gateway and lifecycle actions retain original function pictograms. The S3
icon on explicitly **LOCAL · SeaweedFS** nodes is the user-requested notation for
S3 API compatibility; it does not identify SeaweedFS as Amazon software or claim
an AWS S3 deployment. The custom local Converse fixture is not a deployed Bedrock
model.

## Local product marks

Retrieved 11 November 2026. Vendor colors and geometry are retained; SVG metadata
is sanitized, IDs namespaced, PNG bytes embedded unchanged, and each mark is scaled
proportionately. The white Django compact mark has an added dark backing and links
to the Django project website. These marks identify the actual technologies, with
no sponsorship or endorsement. The application MIT license does not relicense
third-party marks.

| Product | Exact source | SHA-256 | Terms / attribution |
| --- | --- | --- | --- |
| Django | [Official asset](https://static.djangoproject.com/img/logo-dj.svg) | `54d88ff189e20c05a187ad88dd05c509cd9deb4b996708038860a874e74da040` | [DSF logo standards](https://www.djangoproject.com/community/logos/) and [service-identification terms](https://www.djangoproject.com/trademarks/); Django is a registered trademark of the Django Software Foundation |
| RabbitMQ | [Official asset](https://www.rabbitmq.com/assets/files/rabbitmq-logo-e91cacd38fcef5219149bc5cfa10b384.svg) | `5c83f8a9819ca280dd32eef7e79c567a071dddc6a66a120b5d1511f286766749` | [Broadcom trademark guidelines](https://www.rabbitmq.com/trademark-guidelines); official unaltered logo, requested for this technology diagram. The guidelines restrict logo use; no general redistribution permission is asserted. RabbitMQ is a trademark of Broadcom, Inc. in the U.S. and other countries |
| Celery | [Official asset](https://raw.githubusercontent.com/celery/celery/v5.5.3/docs/images/celery_512.png) | `f7bcf453ee5f27a9fabd4bcaf9cebea3459811771c043833c8a9919b45f7333a` | Logo by Ty Wilkins; [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) per the [logo record](https://commons.wikimedia.org/wiki/File:Celery_logo.png) and [documentation copyright](https://docs.celeryq.dev/en/stable/copyright.html). Original PNG unmodified, scaled for display; this logo retains CC BY-SA 4.0 |
| Valkey | [Official asset](https://raw.githubusercontent.com/valkey-io/valkey-io.github.io/2c780fc3d1f6441140f1b5c9faac0f0afd9ea09d/static/img/Valkey-logo.svg) | `36a2375e56420a570f6a0346dde019314204c05f5326c0f00d39114e63397f37` | [LF Projects trademark policy](https://lfprojects.org/policies/trademark-policy/); Valkey is a registered trademark of LF Projects, LLC |
| ClamAV | [Official asset](https://raw.githubusercontent.com/Cisco-Talos/clamav/14915a94cf00ca3a3b7d93b4da050b4dc7f7b76a/logo.png) | `f083e9c704165003f8c065964e4ccb47da48bbad8a80521d571cbf0f1d4762c6` | Official [source repository](https://github.com/Cisco-Talos/clamav); ClamAV is a registered trademark of Cisco Systems, Inc. The software GPL-2.0 license is not asserted as a trademark license |
| Docker Compose | [Official asset](https://raw.githubusercontent.com/docker/docs/75a95460ce3cc8db87a23893490ec331506d08fd/assets/icons/Compose.svg) | `b93745a2bf0aa385757e1ee37a01b9a5c6bf9d561b9aff044b8d40435e82490f` | Official Docker documentation product icon; [Docker trademark guidelines](https://www.docker.com/legal/trademark-guidelines/). Docker marks belong to Docker, Inc. |
| OpenObserve | [Official asset](https://raw.githubusercontent.com/openobserve/openobserve/0a13b5367d4f1137204c46b923a0296aeda1b8b8/web/src/assets/images/common/mini_logo.svg) | `2ffba497e2be7c99358a0d46ce6886cae024b0812154e9552eec3d409c26831a` | Official OpenObserve source mark; [source license](https://github.com/openobserve/openobserve/blob/0a13b5367d4f1137204c46b923a0296aeda1b8b8/LICENSE). OpenObserve marks retain their owners’ rights |

## AWS counterpart panel

The added panel identifies **AWS design counterparts**, not deployed services or
local product branding. It embeds these eight existing official AWS marks from
[the repository icon inventory](aws/NOTICE.md): ECS, S3, GuardDuty, RDS, MQ,
ElastiCache, Bedrock and CloudWatch. Exact archive paths and SHA-256 hashes remain
in that inventory; original paths, fills and proportions are preserved, while
inline SVG IDs are prefixed `overview-aws-` to prevent collisions. No new icon
library or remote render dependency was added.

[AWS architecture-icon guidance](https://aws.amazon.com/architecture/icons/) was
rechecked on 11 November 2026 and permits architecture diagrams and related
materials. AWS assets retain their owners’ terms; the MIT application license
does not relicense them. The same official S3 icon also appears on labeled local
SeaweedFS S3-compatible nodes at the user’s request; the visible legend identifies
that API-compatibility notation. No endorsement or cloud deployment is implied.

## React MIT notice

MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## PostgreSQL License

PostgreSQL Database Management System (also known as Postgres, formerly as Postgres95)

Portions Copyright © 1996-2026, The PostgreSQL Global Development Group

Portions Copyright © 1994, The Regents of the University of California

Permission to use, copy, modify, and distribute this software and its documentation
for any purpose, without fee, and without a written agreement is hereby granted,
provided that the above copyright notice and this paragraph and the following two
paragraphs appear in all copies.

IN NO EVENT SHALL THE UNIVERSITY OF CALIFORNIA BE LIABLE TO ANY PARTY FOR DIRECT,
INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES, INCLUDING LOST PROFITS,
ARISING OUT OF THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION, EVEN IF THE
UNIVERSITY OF CALIFORNIA HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

THE UNIVERSITY OF CALIFORNIA SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE. THE SOFTWARE PROVIDED HEREUNDER IS ON AN "AS IS" BASIS, AND THE
UNIVERSITY OF CALIFORNIA HAS NO OBLIGATIONS TO PROVIDE MAINTENANCE, SUPPORT,
UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
