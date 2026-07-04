# API reference

Every symbol below is importable directly from `fastapi_router_variants`.

```python
from fastapi_router_variants import RouterWrapper, RouterDefaults, Route  # etc.
```

## Router

### `RouterWrapper`

Wraps a FastAPI `APIRouter` and expands each route declaration into its
variants. The wrapped router is exposed as `router.base`.

- `defaults: RouterDefaultsProtocol` — class attribute holding the versioning /
  prefix / documentation defaults (defaults to `RouterDefaults()`).
- `require_roles`, `require_features` — optional injectable static methods; when
  set they add the matching dependencies and mention the roles/features in the
  endpoint description.
- Route decorators: `get`, `post`, `put`, `patch`, `delete`, `api_route`,
  `websocket`, plus `get_csv_export` (a CSV-download `GET` with an example
  table). Each accepts the FastAPI route arguments plus `version`, `prefix`,
  `deployment`, `public`, `require_roles`, `require_features`, `requires`,
  `exceptions`, and description helpers (`summary`, `headline`, `points`, `doc`,
  `deprecated`).
- `include_router(router, **kwargs)` — include an `APIRouter` or another
  `RouterWrapper`.
- `is_public_route(path, ...) -> bool` — resolve whether a route is public.
- `variants_decorator_wrapper(...)` — the internal combinator that expands a
  path spec into per-variant decorators.
- `reset_defaults()` (classmethod) — restore `defaults` to `RouterDefaults()`.
- `recording(recorder)` (classmethod, context manager) — activate a
  `RouteRecorder`; while active the decorators report each variant instead of
  mounting it.

### `RouterDefaults`

Frozen dataclass implementing `RouterDefaultsProtocol` — subclass it to declare
your defaults.

### `RouterDefaultsProtocol`

The full set of default fields (extends `VersioningDefaultsProtocol`):

- `public: RoutingSpec | None` — spec identifying public routes.
- `version_default: int` — version used on unversioned doc URLs (default `1`).
- `requires: list | None` — dependencies added to every route.
- `deployment: str | None` — default deployment declared on every route.
- `operation_id_settings: RouterOperationIdSettings` — OpenAPI operation-id
  generation settings.
- `autodoc_http_errors: bool` — enable automatic OpenAPI documentation of raised
  HTTP errors (off by default).
- `http_error_base: type` — base type identifying documentable error classes.
- `exception_scanner: Callable[[Callable], set[type]] | None` — hook returning
  the error types a callable may raise (wrap in `staticmethod`).
- `error_schema_builder: Callable[[set[type]], Any] | None` — hook turning error
  types into an OpenAPI `responses` mapping (wrap in `staticmethod`).

### `VersioningDefaultsProtocol`

The versioning subset of the defaults:

- `prefix: str | bool | type[Disabled] | None` — default mount prefix (`True`
  forces a prefix on every route).
- `version: VersionSpec | None` — default version behaviour (`True` forces
  versioning).
- `version_range: VersionRange` — the closed range expanded for full-range
  routes (default `(1, 1)`).
- `version_deprecated: int | None` — versions at or below are marked deprecated.

### `RouterOperationIdSettings`

Frozen, keyword-only dataclass tuning operation-id generation:
`segment_aliases`, `segment_exclusions`, `singular_mappings`,
`plural_mappings`.

### `RouterUniqueIdGenerator`

`RouterUniqueIdGenerator(router)` — the `generate_unique_id_function` FastAPI
uses to derive stable operation ids from a route's method and path, honoring the
router's `operation_id_settings` and stripping the default prefix / default
version segments.

### `RouteRecorder`

Protocol with a single `record(*, path, type, methods, version, prefix,
deployment, hidden)` method — the sink used by `RouterWrapper.recording` to
enumerate a router's variants without mounting them.

### `RouteType`

`Literal["http", "websocket"]`.

### `RouterWrapperError`

Raised when a route (or router) is missing a required `version` or `prefix`, or
when a path list is empty.

### `RequireRolesProtocol` / `RequireFeaturesProtocol`

Callable protocols for the optional `require_roles(roles)` /
`require_features(*features)` injectable hooks.

### `add_redirect_route(app, from_path, to_url)`

Register a `GET` route on `app` that returns a `RedirectResponse` to `to_url`.

## Path variants and versioning

### `Route`

Frozen dataclass describing a single path variant:
`Route(path, version=None, prefix=None, deprecated=None, deployment=None, tags=None)`.
Supports `route + RouteFlavor(...)` and `route.flavor(...)` to build a
`RouteFlavors` collection.

### `RouteFlavor`

Frozen, keyword-only dataclass carrying the same optional fields as `Route`,
representing a modification of a base route.

### `RouteFlavors`

Collection built from a root `Route` plus flavors. `.flavor(...)` appends a
flavor (returning `self` for chaining); `.build()` returns the
`[root, *flavors]` sequence.

### `VersionSpec` / `PathSpec` / `PrefixSpec` / `DeploymentSpec`

Type aliases:

- `VersionSpec = tuple[int | None, int | None] | int | bool | type[Disabled]`
- `PathSpec = str | Route | Sequence[str | Route] | RouteFlavors`
- `PrefixSpec = Sequence[str] | str | bool | type[Disabled]`
- `DeploymentSpec = str | bool`

### `Disabled`

Sentinel type used as a spec value to disable versioning or prefixing at a given
level.

### `api_version_from_path(path) -> int | None`

Return the integer version embedded in a path (`"/api/v2/users"` → `2`), or
`None`.

### `normalize_version_spec(spec) -> tuple[int | None, int | None] | None`

Normalize any `VersionSpec` into a `(low, high)` tuple (or `None`).

### `version_range_from_spec(version_range, route_version) -> tuple[VersionRange | None, bool, bool]`

Resolve the effective `(low, high)` range for a route, plus whether the lower and
upper bounds were set explicitly.

### `versioned_routes(routes, defaults_version_range, route_version, version_deprecated=None)`

Expand a sequence of `Route` into their per-version variants (prepending the
`v{n}` segment and applying automatic deprecation).

### `prefixed_routes(routes, prefix)`

Expand a sequence of `Route` across a prefix spec.

### `variants_routes(routes, defaults, router_prefix, router_version, router_deployment, prefix, version, deployment)`

The top-level combinator: applies deployment, then versioning, then prefixing.
`RouterWrapper` calls it internally.

## Routing specs

### `RoutingSpec`

Base callable predicate over a route's metadata (`path`, `methods`,
`deprecated`, `response_model`, `response_class`, `openapi_extra`), returning
`bool | None`.

### Leaf specs

- `Yes()` / `No()` — constant `True` / `False`.
- `Unset()` — constant `None`.
- `Methods(*methods)` — match on HTTP methods (`Methods.ALL` matches any).
- `Paths(*patterns, startswith=False, endswith=False)` — match the path against
  strings or `re.Pattern` objects.
- `OpenapiExtra(key, value)` — match `openapi_extra[key] == value`.
- `ApiVersion(version)` — `OpenapiExtra("x-api-version", version)`.
- `Public()` — `OpenapiExtra("x-public", True)`.

### Combinators

- `And(*specs)` / `Or(*specs)` / `Not(spec)` — accept specs or booleans.

### `resolve(route_spec=None, router_spec=None, default_spec=None, *, path=None, methods=None, deprecated=None, response_model=None, response_class=JSONResponse, openapi_extra=None) -> bool`

Evaluate specs with route/router/default precedence against the route metadata.

### `resolve_routes(routes, spec)`

Lazily yield the routes of an iterable that match `spec` (using `Yes()` as the
default).

## OpenAPI documentation

### `add_doc_routes_for_app(app, *, openapi_specs_dir=None, categories=DEFAULT_CATEGORIES, title_prefix="", swagger_js_url=..., swagger_css_url=..., redoc_js_url=..., skip_add_routes=False) -> OpenapiSpecs`

High-level entry point: read the app's `router_wrapper_class.defaults` and mount
the docs for every version and category under `{prefix}/docs`.

### `add_doc_routes_for_all_versions(app, openapi_provider, doc_prefix="", prefix="", default_version=None, ...) -> OpenapiSpecs`

Mount every version's docs, plus an `/all` aggregate when a version range exists,
and the root redirects.

### `add_doc_routes_for_version(app, openapi_provider, doc_prefix="", version=None, default_version=False, skip_add_routes=False, version_prefix=None, ...) -> dict[str, dict]`

Mount one version's category docs (and default-version redirects).

### `add_doc_routes_for_openapi_spec(app, openapi_spec, prefix, redirect_prefixes=None, ...) -> None`

Mount Swagger UI, ReDoc and `openapi.json` for a single, already-built spec dict.

### `OpenapiCategory`

Frozen dataclass: `OpenapiCategory(name, title, spec_factory=identity, landing=False)`.
`spec_factory` receives the per-version spec and returns the category's route
filter; `landing` marks the category the version root redirects to.

### `OpenapiSpecCategory`

`StrEnum` with `internal` and `public` members (the default category names).

### `OpenapiSpecs`

Frozen dataclass bundling the discovered `version_range` and the built `specs`
mapping.

### `OpenapiProvider`

Abstract base with `load_openapi(version, version_prefix, category, title_suffix)`
and `get_version_range()`.

### `AppOpenapiProvider(app, routes, categories=DEFAULT_CATEGORIES, title_prefix="")`

Computes each document on the fly from the live routes with FastAPI's
`get_openapi`, filtered by the category spec and validated with
`openapi-spec-validator`. Detects duplicate route unique ids.

### `LocalFilesOpenapiProvider(path, categories=DEFAULT_CATEGORIES)`

Loads / writes pre-generated `*.openapi.json` files under `path`
(`has_specs()`, `write_specs(openapi_specs)`, `build_filename(...)`).

### `openapi_provider_factory(app, openapi_specs_dir=None, categories=DEFAULT_CATEGORIES, title_prefix="") -> OpenapiProvider`

Return a `LocalFilesOpenapiProvider` when `openapi_specs_dir` already holds
specs, otherwise an `AppOpenapiProvider`.

### `collect_app_routes(container) -> list[BaseRoute]`

Flatten every leaf route reachable from an app or router (descending into
included routers and mounts).

### `get_openapi_static(app, title, routes) -> dict`

Build an OpenAPI 3.1.0 document for a fixed set of routes, inheriting the app's
metadata.

## Docs helpers

### `load_markdown() -> str`

Read a `doc.md` file sitting next to the caller's caller module (resolved two
frames up), returning `""` when absent. Used by `get_csv_export` to attach
long-form descriptions.
