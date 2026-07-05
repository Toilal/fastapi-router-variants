# fastapi-router-variants

[![Latest Version](https://img.shields.io/pypi/v/fastapi-router-variants.svg)](https://pypi.python.org/pypi/fastapi-router-variants)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Toilal/fastapi-router-variants/blob/develop/LICENSE)
[![Build Status](https://img.shields.io/github/actions/workflow/status/Toilal/fastapi-router-variants/ci.yml?branch=develop)](https://github.com/Toilal/fastapi-router-variants/actions/workflows/ci.yml)
[![Codecov](https://img.shields.io/codecov/c/github/Toilal/fastapi-router-variants)](https://codecov.io/gh/Toilal/fastapi-router-variants)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%9A%80-semantic--release-e10079.svg)](https://github.com/relekang/python-semantic-release)

Declare a route once and get **path variants**, **API versioning** and
**per-version OpenAPI documentation** for [FastAPI](https://fastapi.tiangolo.com/)
— for free.

`fastapi-router-variants` wraps `APIRouter` with a `RouterWrapper` that expands a
single route declaration into every variant it should serve — multiple paths,
multiple version prefixes (`/v1/...`, `/v2/...`), multiple mount prefixes, with
deprecation handled automatically — then builds a separate OpenAPI schema per
version and mounts Swagger UI / ReDoc / `openapi.json` for each of them.

## Install

```bash
pip install fastapi-router-variants
# or
uv add fastapi-router-variants
```

## Usage

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

The single `get` declaration above registers `GET /api/v1/users/{user_id}`,
`GET /api/v2/users/{user_id}` and `GET /api/v3/users/{user_id}`.

Path variants and flavors, versioning helpers, routing specs, per-version
OpenAPI documents, custom categories and HTTP-error auto-documentation are
all covered in the documentation.

## Documentation

Full documentation is available at
[toilal.github.io/fastapi-router-variants](https://toilal.github.io/fastapi-router-variants/).
A preview of the in-progress `develop` branch is published at
[toilal.github.io/fastapi-router-variants/dev](https://toilal.github.io/fastapi-router-variants/dev/).

## Requirements

- Python ≥ 3.12
- FastAPI ≥ 0.115

## License

[MIT](./LICENSE) © Rémi Alvergnat
