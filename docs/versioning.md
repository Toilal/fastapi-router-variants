# API versioning

Versioning expands a single route into one variant per version in a range, each
mounted under a `v{n}` path segment (for example `/api/v2/users`). The version
number is also recorded as the `x-api-version` OpenAPI extension, which the
[OpenAPI documentation](openapi.md) layer uses to build one document per version.

## Configuring the range

Versioning is driven by the router defaults:

```python
from fastapi_router_variants import RouterDefaults, RouterWrapper


class ApiDefaults(RouterDefaults):
    version = True            # force versioning on every route
    version_range = (1, 3)    # the closed range of versions to generate
    version_default = 3       # version served on unversioned doc URLs
    version_deprecated = 1    # this version and below are marked deprecated


RouterWrapper.defaults = ApiDefaults()
```

- `version` — the default version behaviour. `True` forces versioning on every
  route (and raises `RouterWrapperError` if a route neither sets a version nor
  inherits one). `False` disables it by default.
- `version_range` — the closed `(low, high)` range expanded when a route asks for
  the full range. Defaults to `(1, 1)`.
- `version_deprecated` — every generated version at or below this number is marked
  deprecated.
- `version_default` — the version the top-level and per-version doc shortcuts
  redirect to (see [OpenAPI documentation](openapi.md)). Defaults to `1`.

## The `version` spec

The `version` argument (a `VersionSpec`) can be given on the defaults, the
router, the decorator or an individual `Route`, and is resolved most-specific
first. Its forms:

| Value | Meaning |
|:--|:--|
| `True` | Expand over `defaults.version_range`. |
| `N` (int) | From version `N` up to the top of the range. |
| `(low, high)` | An explicit, closed window. A bare `None` in either slot falls back to the range bound. |
| `False` | Opt the route out of versioning. |
| `Disabled` | Disable versioning for this level entirely. |

```python
@router.get("/users", version=True)          # v1, v2, v3
@router.get("/users", version=2)             # v2, v3
@router.get("/users", version=(2, 3))        # v2, v3
@router.get("/users", version=False)         # no version segment
```

## Automatic deprecation

When a route does not set its own `deprecated` flag, a generated version is
marked deprecated when either:

- it is at or below `version_deprecated`, or
- it is the upper bound of an **explicitly closed** window (`version=(low, high)`
  with the high bound set) — the newest version of a closed window is assumed to
  be the last one before the next iteration.

The distinction is between **open** and **closed** windows:

- **Open** window — `version=True`, `version=N`, or `version=(low, None)`. The top
  version is *not* auto-deprecated, because the window is expected to keep growing.
- **Closed** window — `version=(low, high)` with an explicit high bound. The top
  version *is* auto-deprecated.

This is decided per route, from that route's own window. A `Route(...,
version=(2, 3))` placed inside a decorator with a broader open window (say
`version=True` over `(1, 5)`) still has its own top — `v3` — auto-deprecated,
while the open routes keep their top (`v5`) active.

An explicit `deprecated` value on the `Route` or decorator always wins over this
heuristic.

## Reading the version back from a path

`api_version_from_path` extracts the integer version embedded in a path, or
`None` when there is none:

```python
from fastapi_router_variants import api_version_from_path

api_version_from_path("/api/v2/users")  # -> 2
api_version_from_path("/api/users")     # -> None
```

## Lower-level helpers

The expansion is implemented by a small set of pure functions, exported for
advanced use:

- `normalize_version_spec(spec)` — turn any `VersionSpec` into a normalized
  `(low, high)` tuple (or `None`).
- `version_range_from_spec(version_range, route_version)` — resolve the effective
  `(low, high)` range for a route, plus flags for whether each bound was set
  explicitly.
- `versioned_routes(routes, defaults_version_range, route_version, version_deprecated=None)`
  — expand a sequence of `Route` into their per-version variants.
- `prefixed_routes(routes, prefix)` — expand routes across a prefix spec.
- `variants_routes(...)` — the top-level combinator that applies deployment,
  versioning and prefixing in order; this is what `RouterWrapper` calls
  internally.

See the [API reference](api.md) for the full signatures.
