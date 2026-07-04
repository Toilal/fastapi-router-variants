# fastapi-router-variants

Declare a route once and get **path variants**, **API versioning** and
**per-version OpenAPI documentation** for [FastAPI](https://fastapi.tiangolo.com/)
— for free.

`fastapi-router-variants` wraps `APIRouter` with a `RouterWrapper` that expands a
single route declaration into every variant it should serve: multiple paths,
multiple version prefixes (`/v1/...`, `/v2/...`), multiple mount prefixes, with
deprecation handled automatically. It then builds a **separate OpenAPI schema per
version** and mounts Swagger UI / ReDoc / `openapi.json` for each of them.

## Documentation

Full documentation is published at
<https://toilal.github.io/fastapi-router-variants>. A preview of the in-progress
`develop` branch is available at
<https://toilal.github.io/fastapi-router-variants/dev/>.

## Install

```bash
pip install fastapi-router-variants
# or
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

## Path variants and flavors

A route can be declared with several paths, or with per-variant overrides via
`Route`:

```python
from fastapi_router_variants import Route, RouterDefaults, RouterWrapper


class ApiDefaults(RouterDefaults):
    prefix = "/api"
    version = True
    version_range = (1, 3)


RouterWrapper.defaults = ApiDefaults()

router = RouterWrapper()


@router.get(
    [
        "/groups/{group_id}/vehicle_list",  # legacy path
        "/groups/{group_id}/vehicles",  # new path
        Route("/legacy", version=(1, 1), deprecated=False),
    ],
    version=(2, 3),
)
def list_vehicles(group_id: int) -> list[dict[str, int]]:
    return [{"group_id": group_id}]
```

Each entry is expanded across the configured version range; a `Route` may pin its
own version window, prefix, deprecation flag, tags or deployment. Fluent
`RouteFlavor` composition is available too (`Route("/x") + RouteFlavor(...)`).

## Versioning helpers

- `version=True` — expand over `defaults.version_range`.
- `version=N` — from version `N` up to the top of the range.
- `version=(low, high)` — an explicit, closed window.
- `version=False` — opt a route out of versioning.
- `version_deprecated` on the defaults marks every version at or below it as
  deprecated; the top of a closed window is deprecated automatically.

`api_version_from_path("/api/v2/users")` extracts the version embedded in a path.

## Routing specs

Routing specs are small composable predicates over a route, used to classify
routes (e.g. which are public):

```python
from fastapi_router_variants import (
    And,
    ApiVersion,
    Methods,
    Not,
    Or,
    Paths,
    Public,
    RoutingSpec,
)

public: RoutingSpec = Not(Paths("/internal", startswith=True))
v2_public: RoutingSpec = And(ApiVersion(2), Public())
read_only: RoutingSpec = Or(Methods("GET"), Methods("HEAD"))
```

`resolve(...)` evaluates a spec against a route; `resolve_routes(routes, spec)`
filters an iterable of routes.

## Per-version OpenAPI documentation

`add_doc_routes_for_app` builds one OpenAPI document **per version and per
category** (by default `internal` and `public`) and mounts Swagger UI, ReDoc and
`openapi.json` for each, with redirects for the default version:

```python
from fastapi import FastAPI

from fastapi_router_variants import (
    RouterDefaults,
    RouterWrapper,
    add_doc_routes_for_app,
)


class ApiDefaults(RouterDefaults):
    prefix = "/api"
    version = True
    version_range = (1, 3)
    version_default = 3


RouterWrapper.defaults = ApiDefaults()

router = RouterWrapper()


@router.get("/users/{user_id}")
def get_user(user_id: int) -> dict[str, int]:
    return {"id": user_id}


class DocumentedApp(FastAPI):
    router_wrapper_class: type[RouterWrapper]


app = DocumentedApp()
app.router_wrapper_class = RouterWrapper  # expose the defaults
app.include_router(router.base)

add_doc_routes_for_app(app)
```

You get, for example:

```
/api/docs/v1/public/swagger-ui
/api/docs/v2/public/redoc
/api/docs/v3/internal/openapi.json
/api/docs           -> default version
```

Categories are configurable (`OpenapiCategory`), so you can add your own document
filtered by any routing spec. The Swagger/ReDoc CDN URLs are configurable too and
default to jsDelivr.

### Custom categories

```python
from fastapi import FastAPI

from fastapi_router_variants import (
    And,
    OpenapiCategory,
    OpenapiExtra,
    RouterWrapper,
    RoutingSpec,
    add_doc_routes_for_app,
)


class DocumentedApp(FastAPI):
    router_wrapper_class: type[RouterWrapper]


def partner_spec(version_spec: RoutingSpec) -> RoutingSpec:
    return And(version_spec, OpenapiExtra("x-partner", True))


partner = OpenapiCategory(
    name="partner",
    title="Partner API",
    spec_factory=partner_spec,
)

app = DocumentedApp()
app.router_wrapper_class = RouterWrapper

add_doc_routes_for_app(app, categories=(partner,))
```

## Optional HTTP-error auto-documentation

Auto-documentation of raised HTTP errors is **off by default** and fully
injectable — no dependency on any error base class is assumed. Enable it on the
defaults and provide the hooks:

```python
from collections.abc import Callable
from typing import Any

from fastapi_router_variants import RouterDefaults, RouterWrapper


class MyHttpError(Exception):
    pass


def my_scanner(handler: Callable[..., Any]) -> set[type]:
    return set()


def my_schema_builder(errors: set[type]) -> dict[int | str, dict[str, Any]]:
    descriptions = ", ".join(sorted(error.__name__ for error in errors))
    return {400: {"description": descriptions}}


class ApiDefaults(RouterDefaults):
    autodoc_http_errors = True
    http_error_base = MyHttpError
    exception_scanner = staticmethod(my_scanner)
    error_schema_builder = staticmethod(my_schema_builder)


RouterWrapper.defaults = ApiDefaults()
```

When left unset, the whole error-collection path is short-circuited.

## Roles and features (optional)

`require_roles` / `require_features` are optional injectable static methods on the
wrapper class. They accept arbitrary role/feature values and, when set, add the
corresponding dependencies and mention them in the endpoint description.

## Requirements

- Python ≥ 3.12
- FastAPI ≥ 0.115

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

## License

[MIT](./LICENSE) © Rémi Alvergnat
