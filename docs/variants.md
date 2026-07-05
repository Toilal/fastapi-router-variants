# Path variants

A single route declaration is expanded into one *variant* per combination of
path, version and prefix. This page covers the path side of that expansion; see
[API versioning](versioning.md) for the version side.

## Several paths for one handler

Pass a list of paths to any route decorator to register the same handler under
each of them:

```python
from fastapi_router_variants import RouterDefaults, RouterWrapper


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
    ]
)
def list_vehicles(group_id: int) -> list[dict[str, int]]:
    return [{"group_id": group_id}]
```

Each entry in the list is expanded across the configured version range, so the
example above generates both paths for `v1`, `v2` and `v3`.

## Per-variant overrides with `Route`

A plain string entry inherits the router and defaults settings. To override
them for a single entry, use `Route`, whose fields pin the version window,
prefix, deprecation flag, deployment and tags for that entry only:

```python
from fastapi_router_variants import Route, RouterWrapper

router = RouterWrapper()


@router.get(
    [
        "/groups/{group_id}/vehicles",
        Route("/legacy", version=(1, 1), deprecated=False),
    ],
    version=(2, 3),
)
def list_vehicles(group_id: int) -> list[dict[str, int]]:
    return [{"group_id": group_id}]
```

`Route` is a frozen dataclass:

```python
Route(
    path: str,
    version: VersionSpec | None = None,
    prefix: PrefixSpec | None = None,
    deprecated: bool | None = None,
    deployment: DeploymentSpec | None = None,
    tags: list[str | Enum] | None = None,
)
```

Any field left as `None` falls back to the value supplied on the decorator, then
on the router, then on the defaults.

## Flavors: fluent composition

A `RouteFlavor` carries the same optional fields as `Route` but represents a
*modification* of a base route rather than a standalone one. Adding a
`RouteFlavor` to a `Route` (or to a string) produces a `RouteFlavors` collection
that expands into the base route plus one route per flavor:

```python
from fastapi_router_variants import Route, RouteFlavor, RouterWrapper

router = RouterWrapper()

variants = Route("/vehicles") + RouteFlavor(path="/vehicle_list", deprecated=True)


@router.get(variants)
def list_vehicles() -> list[dict[str, int]]:
    return []
```

`RouteFlavors` can also be built programmatically with `.flavor(...)`, which
accepts either a `RouteFlavor` or the individual keyword fields and returns the
collection so calls can be chained:

```python
variants = (
    Route("/vehicles")
    .flavor(path="/vehicle_list", deprecated=True)
    .flavor(path="/legacy", version=(1, 1))
)
```

Each flavor's fields override the corresponding fields of the root route; fields
left unset keep the root's value. `RouteFlavors.build()` returns the final
`[root, *flavors]` sequence that the decorator expands.

## Prefixes

`prefix` mounts routes under one or more path segments. It accepts:

- a string — a single mount prefix (e.g. `"/api"`);
- a sequence of strings — one variant per prefix;
- `True` — force a prefix to be declared on the route or router (raises if none is);
- `False` or `Disabled` — opt the route out of prefixing.

The default prefix is read from `defaults.prefix`. A prefix set directly on a
`Route` takes precedence over the decorator, router and defaults value. When a
prefix expands to several segments, one route variant is generated per segment.

## Deployments

`deployment` tags a route with a free-form deployment name (a string, or a
boolean). It does not change the generated path; it is recorded as the
`x-deployment` OpenAPI extension and can be matched later by a
[routing spec](specs.md). A deployment set on the decorator overrides the router
value, which overrides the defaults value.
