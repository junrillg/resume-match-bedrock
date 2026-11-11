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

Django, SeaweedFS, RabbitMQ, Celery, ClamAV and Valkey use labeled function
pictograms rather than vendor logos. No reliable redistributable mark was adopted
for those nodes; in particular, RabbitMQ's [guidelines](https://www.rabbitmq.com/trademark-guidelines)
restrict logo use. The symbols represent functions, not approximations of those marks.
The local HTTP Converse fixture is not represented by a Bedrock service icon.

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
