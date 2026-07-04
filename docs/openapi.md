# Per-version OpenAPI documentation

`fastapi-router-variants` builds one OpenAPI document **per version and per
category** and mounts Swagger UI, ReDoc and `openapi.json` for each, with
redirects for the default version.

## Mounting the docs

`add_doc_routes_for_app` is the high-level entry point. It reads the router
defaults from the app, so the app must expose the `RouterWrapper` class that
produced its routes via a `router_wrapper_class` attribute:

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

You get, for the default `internal` / `public` categories:

```
/api/docs/v1/public/swagger-ui
/api/docs/v2/public/redoc
/api/docs/v3/internal/openapi.json
/api/docs           -> default version
```

The default version (`version_default`) also gets top-level shortcuts
(`/api/docs/public/...`) that redirect to its versioned URLs, and the root
redirects (`/`, `/docs`, `/swagger-ui`, `/redoc`, `/openapi.json`) point into the
docs tree.

## Categories

A category is one filtered OpenAPI document. The two defaults are `internal`
(every route of the version) and `public` (routes additionally matching
`Public()`); `public` is the `landing` category the version root redirects to.

```python
@dataclass(frozen=True)
class OpenapiCategory:
    name: str
    title: str
    spec_factory: Callable[[RoutingSpec], RoutingSpec] = lambda version_spec: version_spec
    landing: bool = False
```

`spec_factory` receives the per-version routing spec (an `ApiVersion` match) and
returns the spec used to select the routes for the category — this is how a
category narrows a version's routes further.

### Custom categories

Pass your own categories to filter by any [routing spec](specs.md):

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

## OpenAPI providers

The documents can be produced two ways, selected by `openapi_provider_factory`:

- `AppOpenapiProvider` — computes each document on the fly from the live app
  routes with FastAPI's `get_openapi`, filtering by the category spec and
  validating the result with `openapi-spec-validator`. This is the default.
- `LocalFilesOpenapiProvider` — loads pre-generated `*.openapi.json` files from a
  directory. `add_doc_routes_for_app(app, openapi_specs_dir=...)` uses this when
  the directory already contains specs, which lets you generate the specs at
  build time (via `write_specs`) and serve them without recomputation.

Both implement the `OpenapiProvider` interface (`load_openapi`,
`get_version_range`). The version range is discovered from the routes'
`x-api-version` extension, so the doc layer generates exactly the versions your
routes declare.

## CDN URLs

Swagger UI and ReDoc load their assets from jsDelivr by default. Override them
per call:

```python
add_doc_routes_for_app(
    app,
    swagger_js_url="https://example.com/swagger-ui-bundle.js",
    swagger_css_url="https://example.com/swagger-ui.css",
    redoc_js_url="https://example.com/redoc.standalone.js",
)
```

## Lower-level entry points

`add_doc_routes_for_app` delegates to functions you can also call directly for
finer control:

- `add_doc_routes_for_all_versions(app, provider, ...)` — mount every version's
  docs plus an `/all` aggregate, and the root redirects.
- `add_doc_routes_for_version(app, provider, version=..., ...)` — mount one
  version's categories.
- `add_doc_routes_for_openapi_spec(app, spec, prefix, ...)` — mount Swagger UI,
  ReDoc and `openapi.json` for a single, already-built spec dict.

All accept `skip_add_routes=True` to compute the `OpenapiSpecs` without mounting
any route, which is what you use to generate the static files.
