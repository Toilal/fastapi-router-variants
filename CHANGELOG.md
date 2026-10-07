# CHANGELOG

<!-- version list -->

## v0.2.3 (2026-10-07)

### Bug Fixes

- **openapi**: Document effective include routes from FastAPI 0.137
  ([`98eb2e6`](https://github.com/Toilal/fastapi-router-variants/commit/98eb2e61a551b3bf1a8d4b2020202ba4b90c502a))

- **openapi**: Rebuild included routes from their effective context
  ([`964c508`](https://github.com/Toilal/fastapi-router-variants/commit/964c5086f9d3798b9892133c2aaee256e0c44f69))


## v0.2.2 (2026-07-25)

### Bug Fixes

- **openapi**: Clarify WebSocket route rebinding
  ([`26360ed`](https://github.com/Toilal/fastapi-router-variants/commit/26360ed181ef95353f90186bf685da3d18384a6f))

- **openapi**: Document preserved dependency overrides
  ([`ce4e7f5`](https://github.com/Toilal/fastapi-router-variants/commit/ce4e7f5a7474f4715f13b9ada9b827ecc0fd0ecc))

- **openapi**: Isolate flattened routes between apps
  ([`62b7161`](https://github.com/Toilal/fastapi-router-variants/commit/62b716185620966e583306221c2b3fae18f92b87))

- **openapi**: Preserve overrides when flattening routers
  ([`13b8175`](https://github.com/Toilal/fastapi-router-variants/commit/13b8175194804c67df9b4448ae7bb857f0abb43e))

- **openapi**: Remove project-specific changelog entry
  ([`36d8fc8`](https://github.com/Toilal/fastapi-router-variants/commit/36d8fc8f26c282bb8ce6ca306ae98e2905ed27ae))

- **openapi**: Remove project-specific implementation notes
  ([`e2150fc`](https://github.com/Toilal/fastapi-router-variants/commit/e2150fcbe4e6c4513c3807a8f3d16d39cdf52be2))


## v0.2.1 (2026-07-20)

### Bug Fixes

- Flatten lazily-mounted routers to avoid FastAPI >=0.139 memory regression
  ([#15](https://github.com/Toilal/fastapi-router-variants/pull/15),
  [`21db307`](https://github.com/Toilal/fastapi-router-variants/commit/21db307c01a0403854e3b097526f22087223807e))


## v0.2.0 (2026-07-05)

### Features

- Support Python 3.11 ([#13](https://github.com/Toilal/fastapi-router-variants/pull/13),
  [`ab9301d`](https://github.com/Toilal/fastapi-router-variants/commit/ab9301dae07480e1d8b6ae45af04e230241c65e8))


## v0.1.0 (2026-07-05)

- Initial Release

Changelog entries are generated automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/) from
[Conventional Commits](https://www.conventionalcommits.org/) on release.
