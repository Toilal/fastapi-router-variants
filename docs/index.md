# FastAPI Router Variants

[![Latest Version](https://img.shields.io/pypi/v/fastapi-router-variants.svg)](https://pypi.python.org/pypi/fastapi-router-variants)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Toilal/fastapi-router-variants/blob/develop/LICENSE)
[![Build Status](https://img.shields.io/github/actions/workflow/status/Toilal/fastapi-router-variants/ci.yml?branch=develop)](https://github.com/Toilal/fastapi-router-variants/actions/workflows/ci.yml)
[![Codecov](https://img.shields.io/codecov/c/github/Toilal/fastapi-router-variants)](https://codecov.io/gh/Toilal/fastapi-router-variants)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%9A%80-semantic--release-e10079.svg)](https://github.com/relekang/python-semantic-release)

Declare a route once and get **path variants**, **API versioning** and
**per-version OpenAPI documentation** for [FastAPI](https://fastapi.tiangolo.com/)
— for free.

`fastapi-router-variants` wraps `APIRouter` with a `RouterWrapper` that expands a
single route declaration into every variant it should serve: multiple paths,
multiple version prefixes (`/v1/...`, `/v2/...`), multiple mount prefixes, with
deprecation handled automatically. It then builds a **separate OpenAPI schema per
version** and mounts Swagger UI / ReDoc / `openapi.json` for each of them.

## Requirements

- Python ≥ 3.12
- FastAPI ≥ 0.115

## Install

Install with [pip](https://pip.pypa.io/):

```bash
pip install fastapi-router-variants
```

Or add it to your project with [uv](https://docs.astral.sh/uv/):

```bash
uv add fastapi-router-variants
```

## Quick start

```python
from fastapi import FastAPI

from fastapi_router_variants import RouterDefaults, RouterWrapper


class ApiDefaults(RouterDefaults):
    prefix = "/api"           # mount every route under /api
    version = True            # force versioning on every route
    version_range = (1, 3)    # generate v1, v2, v3
    version_default = 3       # the version served on unversioned doc URLs


RouterWrapper.defaults = ApiDefaults()

router = RouterWrapper()


@router.get("/users/{user_id}")
def get_user(user_id: int) -> dict[str, int]:
    return {"id": user_id}


app = FastAPI()
app.include_router(router.base)
```

The single `get` declaration above registers:

```
GET /api/v1/users/{user_id}
GET /api/v2/users/{user_id}
GET /api/v3/users/{user_id}
```

`RouterWrapper` mirrors the `APIRouter` decorator surface — `get`, `post`,
`put`, `patch`, `delete`, `api_route` and `websocket` — while adding the
variant-expansion parameters (`version`, `prefix`, `deployment`, `public`, …).
The underlying `APIRouter` is available as `router.base` and is what you pass to
`app.include_router(...)`.

## Where to go next

- [Path variants](variants.md) — declare one route as several paths and flavors.
- [API versioning](versioning.md) — expand a route across a range of versions.
- [Routing specs](specs.md) — composable predicates to classify routes.
- [OpenAPI documentation](openapi.md) — one documented API per version and category.
- [API reference](api.md) — every public symbol, with signatures.

## License

`fastapi-router-variants` is licensed under the
[MIT license](https://github.com/Toilal/fastapi-router-variants/blob/develop/LICENSE).
