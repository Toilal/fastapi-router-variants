# Routing specs

Routing specs are small, composable predicates over a route. They are used to
classify routes — for example to decide which routes are *public* — and to build
the per-category [OpenAPI documents](openapi.md).

A `RoutingSpec` is a callable evaluated against a route's metadata: its `path`,
`methods`, `deprecated` flag, `response_model`, `response_class` and
`openapi_extra`. It returns `True`, `False`, or `None` (unset / no opinion).

## Building blocks

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

### Leaf specs

- `Yes()` / `No()` — always `True` / always `False`.
- `Unset()` — always `None` (no opinion).
- `Methods(*methods)` — true when the route's methods intersect the given set;
  `Methods(Methods.ALL)` matches any.
- `Paths(*patterns, startswith=False, endswith=False)` — match the path against
  string fragments (substring by default, or prefix/suffix with the flags) or
  compiled `re.Pattern` objects.
- `OpenapiExtra(key, value)` — true when `openapi_extra[key] == value`.
- `ApiVersion(version)` — shorthand for `OpenapiExtra("x-api-version", version)`.
- `Public()` — shorthand for `OpenapiExtra("x-public", True)`.

### Combinators

- `And(*specs)` — true unless one spec is `False`.
- `Or(*specs)` — true when any spec is `True`.
- `Not(spec)` — negates, propagating `None` unchanged.

Combinators accept booleans as well as specs; a bare `True`/`False` is coerced to
`Yes()`/`No()`.

## Evaluating a spec

`resolve(...)` evaluates specs with a route-level, router-level and default-level
precedence, against the keyword route metadata:

```python
from fastapi_router_variants import Methods, resolve

is_read = resolve(
    Or(Methods("GET"), Methods("HEAD")),
    path="/users",
    methods=["GET"],
)
```

`resolve` returns a concrete `bool`; if the resolved spec yields `None` (unset)
and no `Yes()`/`No()` default is supplied, it raises `UnsetResultError`.

## Filtering routes

`resolve_routes(routes, spec)` lazily yields the routes of an iterable that match
a spec — handy for selecting a subset of an app's routes:

```python
from fastapi_router_variants import Public, collect_app_routes, resolve_routes

public_routes = list(resolve_routes(collect_app_routes(app), Public()))
```

Internally this uses `resolve_route`, which reads a `BaseRoute`'s metadata and
evaluates the spec against it with `Yes()` as the default.

## Where the extensions come from

The `x-api-version`, `x-path-prefix`, `x-deployment` and `x-public` extensions
that `ApiVersion`, `OpenapiExtra` and `Public` match are set automatically by
`RouterWrapper` when it expands a route (from the route's version, prefix,
deployment, and the resolved `public` spec). That is what lets a spec written
against `openapi_extra` classify generated variants.
