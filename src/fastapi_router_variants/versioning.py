import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Self, overload


class Disabled:
    pass


VersionRange = tuple[int, int]
VersionSpecNormalized = tuple[int | None, int | None]
VersionSpec = VersionSpecNormalized | int | bool | type[Disabled]

PrefixSpec = Sequence[str] | str | bool | type[Disabled]


DeploymentSpec = str | bool


class VersioningDefaultsProtocol(Protocol):
    prefix: str | bool | type[Disabled] | None = False
    """
    Default prefix to use for prefixed routes generation.
    True to force prefix declaration in routes.
    """

    version: VersionSpec | None = False
    """
    Default version to use for versioned routes generation.
    True to force version declaration in routes.
    """

    version_range: VersionRange = 1, 1
    """Default version range to use for versioned routes generation"""

    version_deprecated: int | None = None
    """From this version and below, all routes will be marked as deprecated"""


@dataclass(frozen=True, kw_only=True)
class RouteFlavor:
    path: str | None = None
    version: VersionSpec | None = None
    prefix: PrefixSpec | None = None
    deprecated: bool | None = None
    deployment: DeploymentSpec | None = None
    tags: list[str | Enum] | None = None


@dataclass(frozen=True)
class Route:
    path: str
    version: VersionSpec | None = None
    prefix: PrefixSpec | None = None
    deprecated: bool | None = None
    deployment: DeploymentSpec | None = None
    tags: list[str | Enum] | None = None

    def __add__(self, flavor: RouteFlavor) -> "RouteFlavors":
        return self.flavor(flavor)

    def flavor(
        self,
        flavor: RouteFlavor | None = None,
        *,
        path: str | None = None,
        version: VersionSpec | None = None,
        prefix: PrefixSpec | None = None,
        deprecated: bool | None = None,
        deployment: DeploymentSpec | None = None,
        tags: list[str | Enum] | None = None,
    ) -> "RouteFlavors":
        collection = RouteFlavors(self)
        if flavor is not None:
            return collection.flavor(flavor)

        return collection.flavor(
            path=path,
            version=version,
            prefix=prefix,
            deprecated=deprecated,
            deployment=deployment,
            tags=tags,
        )


class RouteFlavors:
    def __init__(self, root: Route | str):
        self.root = Route(root) if isinstance(root, str) else root
        self.flavors: list[Route] = []

    def __add__(self, flavor: RouteFlavor) -> Self:
        return self.flavor(flavor)

    @overload
    def flavor(self, flavor: RouteFlavor) -> Self: ...

    @overload
    def flavor(
        self,
        *,
        path: str | None = None,
        version: VersionSpec | None = None,
        prefix: PrefixSpec | None = None,
        deprecated: bool | None = None,
        deployment: DeploymentSpec | None = None,
        tags: list[str | Enum] | None = None,
    ) -> Self: ...

    def flavor(
        self,
        flavor: RouteFlavor | None = None,
        *,
        path: str | None = None,
        version: VersionSpec | None = None,
        prefix: PrefixSpec | None = None,
        deprecated: bool | None = None,
        deployment: DeploymentSpec | None = None,
        tags: list[str | Enum] | None = None,
    ) -> Self:
        if flavor is None:
            flavor = RouteFlavor(
                path=path,
                version=version,
                prefix=prefix,
                deprecated=deprecated,
                deployment=deployment,
                tags=tags,
            )

        new_route = Route(
            path=flavor.path if flavor.path is not None else self.root.path,
            version=flavor.version if flavor.version is not None else self.root.version,
            prefix=flavor.prefix if flavor.prefix is not None else self.root.prefix,
            deprecated=(
                flavor.deprecated
                if flavor.deprecated is not None
                else self.root.deprecated
            ),
            deployment=(
                flavor.deployment
                if flavor.deployment is not None
                else self.root.deployment
            ),
            tags=flavor.tags if flavor.tags is not None else self.root.tags,
        )

        self.flavors.append(new_route)
        return self

    def build(self) -> Sequence[Route]:
        return [self.root, *self.flavors]


class RoutePathGroup:
    path: str


PathSpecItem = str | Route

PathSpec = PathSpecItem | Sequence[PathSpecItem] | RouteFlavors

version_regex = re.compile(r"(?:\/|^)v(\d+)(?:\/|$)")


def api_version_from_path(path: str) -> int | None:
    version_path_match = version_regex.search(path)
    if version_path_match:
        return int(version_path_match.group(1))
    return None


@overload
def normalize_version_spec(spec: None) -> None: ...


@overload
def normalize_version_spec(spec: VersionSpec) -> VersionSpecNormalized: ...


def normalize_version_spec(
    spec: VersionSpec | None,
) -> VersionSpecNormalized | None:
    if spec is Disabled:
        return None

    result: VersionSpecNormalized | None = None

    if isinstance(spec, bool):
        result = (None, None) if spec else None

    elif isinstance(spec, int):
        result = (spec, None)

    elif isinstance(spec, tuple):
        result = spec

    return result


def version_range_from_spec(
    version_range: VersionRange, route_version: VersionSpec | None
) -> tuple[VersionRange | None, bool, bool]:
    route_version = normalize_version_spec(route_version)

    if isinstance(route_version, tuple):
        lower_version, upper_version = route_version

        lower_version_set = lower_version is not None
        upper_version_set = upper_version is not None

        if lower_version is None:
            lower_version = version_range[0]
        if upper_version is None:
            upper_version = version_range[1]

        if lower_version > upper_version:
            upper_version = lower_version

        return (lower_version, upper_version), lower_version_set, upper_version_set

    return None, False, False


def _prepend_prefix(existing: str, new_prefix: str) -> str:
    return (
        ("/" if existing.startswith("/") else "")
        + new_prefix.strip("/")
        + "/"
        + existing.lstrip("/")
    )


def versioned_routes(
    routes: Sequence[Route],
    defaults_version_range: VersionRange,
    route_version: VersionSpec | None,
    version_deprecated: int | None = None,
) -> Sequence[Route]:
    version_range, _lower_version_set, upper_version_set = version_range_from_spec(
        defaults_version_range, route_version
    )

    result: list[Route] = []

    for route in routes:
        if (version_range and route.version is True) or route.version is None:
            route_version_range = version_range
            route_upper_version_set = upper_version_set
        else:
            route_version_range, _, route_upper_version_set = version_range_from_spec(
                defaults_version_range, route.version
            )

        if route_version_range is None:
            result.append(route)
            continue

        min_version, max_version = route_version_range

        for path_version in range(min_version, max_version + 1):
            route_path_deprecated = route.deprecated

            if route_path_deprecated is None:
                if (
                    version_deprecated is not None
                    and path_version <= version_deprecated
                ) or (route_upper_version_set and path_version >= max_version):
                    route_path_deprecated = True

            result.append(
                Route(
                    _prepend_prefix(route.path, f"v{path_version}"),
                    version=path_version,
                    prefix=route.prefix,
                    deprecated=route_path_deprecated,
                    deployment=route.deployment,
                    tags=route.tags,
                )
            )

    return result


def prefixed_routes(
    routes: Sequence[Route], prefix: PrefixSpec | None
) -> Sequence[Route]:
    results: list[Route] = []

    for route_path in routes:
        route_path_prefix = route_path.prefix or prefix

        if route_path_prefix is False or isinstance(route_path_prefix, Disabled):
            results.append(route_path)
        else:
            route_path_prefix_items = (
                (route_path_prefix,)
                if isinstance(route_path_prefix, str)
                else (
                    route_path_prefix
                    if isinstance(route_path_prefix, Sequence)
                    else None
                )
            )

            if route_path_prefix_items is not None:
                for prefix_item in route_path_prefix_items:
                    results.append(
                        Route(
                            _prepend_prefix(route_path.path, prefix_item),
                            prefix=prefix_item,
                            version=route_path.version,
                            deprecated=route_path.deprecated,
                            deployment=route_path.deployment,
                            tags=route_path.tags,
                        )
                    )

    return results


def variants_routes(
    routes: Sequence[Route],
    defaults: VersioningDefaultsProtocol,
    router_prefix: PrefixSpec | None,
    router_version: VersionSpec | None,
    router_deployment: DeploymentSpec | None,
    prefix: PrefixSpec | None,
    version: VersionSpec | None,
    deployment: DeploymentSpec | None,
) -> Sequence[Route]:
    if router_deployment is not None or deployment is not None:
        routes = tuple(
            Route(
                path=x.path,
                version=x.version,
                prefix=x.prefix,
                deprecated=x.deprecated,
                deployment=router_deployment if deployment is None else deployment,
                tags=x.tags,
            )
            for x in routes
        )

    if (
        defaults.version is not Disabled
        and router_version is not Disabled
        and version is not Disabled
    ):
        if version is None:
            if router_version is None or router_version is True:
                version = defaults.version
            else:
                version = router_version

        routes = versioned_routes(
            routes,
            defaults.version_range,
            version,
            version_deprecated=defaults.version_deprecated,
        )

    if (
        defaults.prefix is not Disabled
        and router_prefix is not Disabled
        and prefix is not Disabled
    ):
        if prefix is None:
            if router_prefix is None or router_prefix is True:
                prefix = defaults.prefix
            elif isinstance(router_prefix, str | Sequence):
                prefix = router_prefix

        routes = prefixed_routes(routes, prefix)

    return routes
