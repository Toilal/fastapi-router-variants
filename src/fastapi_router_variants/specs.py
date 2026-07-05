import re
from collections.abc import Iterable
from typing import Any

from fastapi.routing import APIRoute
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute


class RoutingSpec:
    def __call__(
        self,
        *,
        path: str | None = None,
        methods: list[str] | None = None,
        deprecated: bool | None = None,
        response_model: Any = None,
        response_class: type[Response] | None = None,
        openapi_extra: dict[str, Any] | None = None,
    ) -> bool | None: ...


class Yes(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        return True


class No(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        return False


def from_bool(x: bool) -> RoutingSpec:
    return Yes() if x else No()


class _SpecsContainer(RoutingSpec):
    def __init__(self, *strategies: RoutingSpec | bool):
        self.specs = [
            x if isinstance(x, RoutingSpec) else from_bool(x) for x in strategies
        ]


class And(_SpecsContainer):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        for spec in self.specs:
            v = spec(*args, **kwargs)
            if v is False:
                return False
        return True


class Or(_SpecsContainer):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        for spec in self.specs:
            v = spec(*args, **kwargs)
            if v is True:
                return True
        return not self.specs


class Not(_SpecsContainer):
    def __init__(self, spec: RoutingSpec):
        super().__init__(spec)

    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        v = self.specs[0](*args, **kwargs)
        if v is None:
            return v
        return not v


class Unset(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        return None


class Methods(RoutingSpec):
    ALL = "ALL"

    def __init__(self, *methods: str):
        self.methods = set(methods)

    def __call__(
        self, *, methods: list[str] | None = None, **kwargs: Any
    ) -> bool | None:
        if Methods.ALL in self.methods:
            return True
        if not methods:
            return False
        return bool(self.methods & set(methods))


class Paths(RoutingSpec):
    def __init__(
        self,
        *path_patterns: str | re.Pattern[Any],
        startswith: bool = False,
        endswith: bool = False,
    ):
        self.path_patterns = path_patterns
        self.startswith = startswith
        self.endswith = endswith

    def __call__(self, *, path: str | None = None, **kwargs: Any) -> bool | None:
        if path:
            for path_pattern in self.path_patterns:
                if isinstance(path_pattern, str):
                    if (
                        not self.startswith
                        and not self.endswith
                        and path_pattern in path
                    ):
                        return True
                    if self.startswith and path.startswith(path_pattern):
                        return True
                    if self.endswith and path.endswith(path_pattern):
                        return True
                else:
                    if path_pattern.match(path):
                        return True
        return False


class OpenapiExtra(RoutingSpec):
    def __init__(
        self,
        key: str,
        value: Any,
    ):
        self.key = key
        self.value = value

    def __call__(
        self, *, openapi_extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> bool | None:
        openapi_extra_value = (
            openapi_extra.get(self.key) if openapi_extra is not None else None
        )
        return bool(openapi_extra_value == self.value)


class ApiVersion(OpenapiExtra):
    def __init__(self, version: int | None):
        super().__init__("x-api-version", version)


class Public(OpenapiExtra):
    def __init__(self) -> None:
        super().__init__("x-public", True)


class DefaultsReference(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        raise NotImplementedError("DefaultsReference spec should be replaced.")


class RouterReference(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        raise NotImplementedError("RouterReference spec should be replaced.")


class ChildReference(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        raise NotImplementedError("ChildReference spec should be replaced.")


class RouteReference(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        raise NotImplementedError("RouteReference spec should be replaced.")


class WithoutDefaults(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        raise NotImplementedError("WithoutDefaults spec should be replaced.")


class WithoutRouter(RoutingSpec):
    def __call__(self, *args: Any, **kwargs: Any) -> bool | None:
        raise NotImplementedError("WithoutRouter spec should be replaced.")


def _without(
    spec: RoutingSpec | bool | None, without: type[RoutingSpec]
) -> RoutingSpec | None:
    if isinstance(spec, without):
        return Unset()
    if isinstance(spec, _SpecsContainer):
        without_specs: list[RoutingSpec | bool] = []
        changed = False
        for contained_spec in spec.specs:
            without_spec = _without(contained_spec, without)
            if not isinstance(without_spec, Unset):
                without_specs.append(
                    without_spec if without_spec is not None else contained_spec
                )
            if without_spec is not None:
                changed = True
        if changed:
            return spec.__class__(*without_specs)
    return None


def _replace(
    spec: RoutingSpec | bool | None,
    replace: type[RoutingSpec],
    replacement: RoutingSpec | bool | None,
) -> RoutingSpec | bool | None:
    if isinstance(spec, replace):
        return Unset() if replacement is None else replacement
    if isinstance(spec, _SpecsContainer):
        replacement_specs: list[RoutingSpec | bool] = []
        changed = False
        for contained_spec in spec.specs:
            replacement_spec = _replace(contained_spec, replace, replacement)
            replacement_specs.append(
                replacement_spec if replacement_spec is not None else contained_spec
            )
            if replacement_spec is not None:
                changed = True
        if changed:
            return spec.__class__(*replacement_specs)
    return None


def resolve_routes[R: BaseRoute](routes: Iterable[R], spec: RoutingSpec) -> Iterable[R]:
    for route in routes:
        if resolve_route(route, spec, default_spec=Yes()):
            yield route


def resolve_route(
    route: BaseRoute,
    route_spec: RoutingSpec | bool | None = None,
    router_spec: RoutingSpec | bool | None = None,
    default_spec: RoutingSpec | bool | None = None,
) -> bool:
    return resolve(
        route_spec,
        router_spec,
        default_spec,
        path=route.path if isinstance(route, APIRoute) else None,
        methods=list(route.methods or []) if isinstance(route, APIRoute) else None,
        deprecated=route.deprecated if isinstance(route, APIRoute) else None,
        response_model=route.response_model if isinstance(route, APIRoute) else None,
        response_class=(
            route.response_class
            if isinstance(route, APIRoute) and isinstance(route.response_class, type)
            else JSONResponse
        ),
        openapi_extra=route.openapi_extra if isinstance(route, APIRoute) else None,
    )


def _none_or_unset(spec: RoutingSpec | bool | None) -> bool:
    return spec is None or isinstance(spec, Unset)


class UnsetResultError(Exception):
    def __init__(self) -> None:
        super().__init__("Resolve result is unset. Use Yes() or No() as default spec.")


def _strip_marker(
    spec: RoutingSpec | bool | None, marker: type[RoutingSpec]
) -> tuple[RoutingSpec | bool | None, bool]:
    stripped = _without(spec, marker)
    if stripped is None:
        return spec, False
    return (None if isinstance(stripped, Unset) else stripped), True


def _strip_level_markers(
    route_spec: RoutingSpec | bool | None,
    router_spec: RoutingSpec | bool | None,
) -> tuple[RoutingSpec | bool | None, RoutingSpec | bool | None, bool, bool]:
    without_defaults = False
    without_router = False

    if route_spec is not None:
        route_spec, hit = _strip_marker(route_spec, WithoutDefaults)
        without_defaults |= hit
        route_spec, hit = _strip_marker(route_spec, WithoutRouter)
        without_router |= hit

    if router_spec is not None:
        router_spec, hit = _strip_marker(router_spec, WithoutDefaults)
        without_defaults |= hit
        # A WithoutRouter carried by the router spec strips itself but, unlike on
        # the route spec, does not disable the router level.
        router_spec, _ = _strip_marker(router_spec, WithoutRouter)

    return route_spec, router_spec, without_defaults, without_router


def _select_entrypoint_spec(
    route_spec: RoutingSpec | bool | None,
    router_spec: RoutingSpec | bool | None,
    default_spec: RoutingSpec | bool | None,
    without_defaults: bool,
    without_router: bool,
) -> RoutingSpec | bool | None:
    is_router_entrypoint = (
        not _none_or_unset(_without(router_spec, RouteReference))
        or not _none_or_unset(_without(router_spec, ChildReference))
    ) and not without_router

    is_default_entrypoint = (
        (
            not _none_or_unset(_without(default_spec, RouterReference))
            and is_router_entrypoint
        )
        or not _none_or_unset(_without(default_spec, ChildReference))
    ) and not without_defaults

    if is_default_entrypoint:
        spec = default_spec
        replaced_spec = _replace(
            spec,
            ChildReference,
            (
                RouterReference()
                if router_spec
                else RouteReference()
                if route_spec
                else None
            ),
        )
        return replaced_spec if replaced_spec is not None else spec

    if is_router_entrypoint:
        spec = router_spec
        replaced_spec = _replace(
            spec, ChildReference, RouteReference() if route_spec else None
        )
        return replaced_spec if replaced_spec is not None else spec

    if not _none_or_unset(route_spec):
        return route_spec
    if not _none_or_unset(router_spec) and not without_router:
        return router_spec
    if not without_defaults:
        return default_spec
    return Unset()


def resolve(
    route_spec: RoutingSpec | bool | None = None,
    router_spec: RoutingSpec | bool | None = None,
    default_spec: RoutingSpec | bool | None = None,
    *,
    path: str | None = None,
    methods: list[str] | None = None,
    deprecated: bool | None = None,
    response_model: Any = None,
    response_class: type[Response] = JSONResponse,
    openapi_extra: dict[str, Any] | None = None,
) -> bool:
    route_spec, router_spec, without_defaults, without_router = _strip_level_markers(
        route_spec, router_spec
    )

    spec = _select_entrypoint_spec(
        route_spec, router_spec, default_spec, without_defaults, without_router
    )

    replaced_spec = _replace(spec, DefaultsReference, default_spec)
    if replaced_spec is not None:
        spec = replaced_spec

    replaced_spec = _replace(spec, RouterReference, router_spec)
    if replaced_spec is not None:
        spec = replaced_spec

    replaced_spec = _replace(spec, RouteReference, route_spec)
    if replaced_spec is not None:
        spec = replaced_spec

    if spec is None:
        return False

    if isinstance(spec, bool):
        return spec

    result = spec(
        path=path,
        methods=methods,
        deprecated=deprecated,
        response_model=response_model,
        response_class=response_class,
        openapi_extra=openapi_extra,
    )

    if result is None:
        raise UnsetResultError()

    return bool(result)
