import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from copy import copy
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import (
    APIRoute,
    APIWebSocketRoute,
    get_websocket_app,
    websocket_session,
)
from openapi_spec_validator import validate
from starlette.routing import BaseRoute

from fastapi_router_variants.specs import (
    And,
    ApiVersion,
    Or,
    Public,
    RoutingSpec,
    Unset,
    resolve_routes,
)


class RouterWrapperClassProtocol(Protocol):
    """Minimal view of a ``RouterWrapper`` class needed to read its defaults."""

    defaults: Any


class RouterWrapperApp(Protocol):
    """Application exposing the router wrapper class that produced its routes."""

    router_wrapper_class: type[RouterWrapperClassProtocol]


_API_ROUTE_ACCEPTS_STRICT_CONTENT_TYPE = (
    "strict_content_type" in inspect.signature(APIRoute.__init__).parameters
)


def _serving_router(container: Any) -> Any:
    base = getattr(container, "base", None)
    target = base if base is not None else container
    return getattr(target, "router", target)


def _is_included_router(route: BaseRoute) -> bool:
    return getattr(route, "original_router", None) is not None


def _has_low_priority_routes(router: Any) -> bool:
    """Whether a router tree serves routes FastAPI only matches through includes.

    ``APIRouter.frontend()`` registers low-priority routes that the parent
    reaches through ``_IncludedRouter.effective_low_priority_routes()`` only, so
    unwrapping such an include would stop serving them.
    """
    if getattr(router, "_low_priority_routes", None):
        return True
    return any(
        _has_low_priority_routes(route.original_router)
        for route in router.routes
        if _is_included_router(route)
    )


def _materialize_api_route(
    context: Any, dependency_overrides_provider: Any
) -> APIRoute:
    original_route = context.original_route
    kwargs: dict[str, Any] = {}
    if _API_ROUTE_ACCEPTS_STRICT_CONTENT_TYPE:
        kwargs["strict_content_type"] = context.strict_content_type
    route_class = cast("type[APIRoute]", type(original_route))
    return route_class(
        context.path,
        context.endpoint,
        response_model=context.response_model,
        status_code=context.status_code,
        tags=context.tags,
        dependencies=context.dependencies,
        summary=context.summary,
        description=context.description,
        response_description=context.response_description,
        responses=context.responses,
        deprecated=context.deprecated,
        name=context.name,
        methods=context.methods,
        operation_id=context.operation_id,
        response_model_include=context.response_model_include,
        response_model_exclude=context.response_model_exclude,
        response_model_by_alias=context.response_model_by_alias,
        response_model_exclude_unset=context.response_model_exclude_unset,
        response_model_exclude_defaults=context.response_model_exclude_defaults,
        response_model_exclude_none=context.response_model_exclude_none,
        include_in_schema=context.include_in_schema,
        response_class=context.response_class,
        dependency_overrides_provider=dependency_overrides_provider,
        callbacks=context.callbacks,
        openapi_extra=context.openapi_extra,
        generate_unique_id_function=context.generate_unique_id_function,
        **kwargs,
    )


def _rebind_websocket_route(
    route: APIWebSocketRoute, dependency_overrides_provider: Any
) -> APIWebSocketRoute:
    route = copy(route)
    route.app = websocket_session(
        get_websocket_app(
            dependant=route.dependant,
            dependency_overrides_provider=dependency_overrides_provider,
            embed_body_fields=route._embed_body_fields,
        )
    )
    return route


def _materialize_route_context(
    context: Any, dependency_overrides_provider: Any
) -> BaseRoute:
    if isinstance(context.original_route, APIRoute):
        return _materialize_api_route(context, dependency_overrides_provider)
    route: BaseRoute = context.starlette_route
    if isinstance(route, APIWebSocketRoute):
        return _rebind_websocket_route(route, dependency_overrides_provider)
    return route


def materialize_included_routes(
    routes: Sequence[BaseRoute], container: Any
) -> list[BaseRoute]:
    """Replace each lazily-mounted include of ``routes`` with its effective routes.

    Since FastAPI 0.137, ``include_router`` appends a single ``_IncludedRouter``
    whose include context (prefix, tags, dependencies, responses,
    ``include_in_schema``, response class, unique id function, content-type
    strictness, …) is only applied when FastAPI resolves a route. Every route
    reachable through such an include, through nested includes too, is rebuilt
    with that effective context, the way FastAPI <= 0.136 ``include_router``
    copied routes eagerly, and bound to ``container``'s dependency override
    provider.

    Includes whose router tree holds ``APIRouter.frontend()`` routes are kept
    as-is, since FastAPI only serves those through the include. Other routes are
    returned unchanged, so on FastAPI <= 0.136 the result equals ``routes``.
    Accepts a ``FastAPI`` app, an ``APIRouter`` or a ``RouterWrapper`` as
    ``container``.
    """
    dependency_overrides_provider = getattr(
        _serving_router(container), "dependency_overrides_provider", None
    )
    materialized: list[BaseRoute] = []
    for route in routes:
        if _is_included_router(route) and not _has_low_priority_routes(
            cast("Any", route).original_router
        ):
            materialized.extend(
                _materialize_route_context(context, dependency_overrides_provider)
                for context in cast("Any", route).effective_route_contexts()
            )
        else:
            materialized.append(route)
    return materialized


def collect_app_routes(container: Any) -> list[BaseRoute]:
    """Flatten every route reachable from an app or router.

    Lazily-mounted includes contribute their effective routes, rebuilt as
    ``materialize_included_routes`` does, so the result carries the path, tags,
    responses and schema visibility the app actually serves; mounts are
    descended into, so callers get the leaf routes regardless of how they were
    included.
    """
    return _collect_routes(getattr(container, "routes", []))


def _collect_routes(routes: Sequence[BaseRoute]) -> list[BaseRoute]:
    collected: list[BaseRoute] = []
    for route in routes:
        if _is_included_router(route):
            collected.extend(
                _collect_routes(
                    [
                        _materialize_route_context(context, None)
                        for context in cast("Any", route).effective_route_contexts()
                    ]
                )
            )
        elif isinstance(route, APIRoute):
            collected.append(route)
        elif getattr(route, "routes", None) is not None:
            collected.extend(collect_app_routes(route))
        else:
            collected.append(route)
    return collected


def flatten_included_routers(container: Any) -> None:
    """Rewrite a serving router's ``routes`` so no ``_IncludedRouter`` remains.

    Since FastAPI 0.137 each ``include_router`` call appends a single opaque
    ``_IncludedRouter`` to the parent ``routes`` instead of copying the child's
    routes. Starlette matches every ``routes`` entry on each request, and
    ``_IncludedRouter.matches()`` materialises and retains the effective
    dependency tree of every child route on first match — inflating RSS by
    hundreds of MB for a large composed app and leading to OOM under load.

    Replacing each ``_IncludedRouter`` in place with its effective routes (see
    ``materialize_included_routes``) restores the flat routing table FastAPI
    <= 0.136 built eagerly, so Starlette never calls
    ``_IncludedRouter.matches()`` on the hot path, while keeping every include
    setting: prefix, tags, dependencies, responses, ``include_in_schema``,
    response class, unique id function and content-type strictness. Flattened
    HTTP and WebSocket routes are bound to the serving container's dependency
    override provider. A no-op on FastAPI 0.115→0.136, where the table is
    already flat.

    Call it once after all ``include_router`` calls, before serving. Accepts a
    ``FastAPI`` app, an ``APIRouter`` or a ``RouterWrapper``.
    """
    router = _serving_router(container)
    routes = getattr(router, "routes", None)
    if routes is None:
        return
    routes[:] = materialize_included_routes(routes, container)
    mark_changed = getattr(router, "_mark_routes_changed", None)
    if callable(mark_changed):
        mark_changed()


INTERNAL_OPENAPI_EXTENSIONS = (
    "x-api-version",
    "x-path-prefix",
    "x-deployment",
    "x-public",
)
"""Extensions the wrapper injects into routes for filtering, never for publishing.

They are read from ``route.openapi_extra`` at filter time (``ApiVersion``,
``Public``, …) but must be removed from the emitted operations so they do not
leak into the served OpenAPI document.
"""


def _strip_internal_extensions(openapi: dict[str, Any]) -> dict[str, Any]:
    for path_item in openapi.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if isinstance(operation, dict):
                for key in INTERNAL_OPENAPI_EXTENSIONS:
                    operation.pop(key, None)
    return openapi


def get_openapi_static(
    app: FastAPI, title: str, routes: Sequence[BaseRoute]
) -> dict[str, Any]:
    openapi = get_openapi(
        title=title,
        routes=routes,
        version="3.1.0",
        servers=[],
        webhooks=[],
        openapi_version=app.openapi_version,
        summary=app.summary,
        description=app.description,
        terms_of_service=app.terms_of_service,
        contact=app.contact,
        license_info=app.license_info,
        tags=app.openapi_tags,
        separate_input_output_schemas=app.separate_input_output_schemas,
    )
    return _strip_internal_extensions(openapi)


class OpenapiSpecCategory(StrEnum):
    internal = "internal"
    public = "public"


@dataclass(frozen=True)
class OpenapiCategory:
    """A named OpenAPI document produced from a subset of routes.

    ``spec_factory`` receives the per-version routing spec and returns the spec
    used to filter the routes for this category. ``landing`` marks the category
    the version root and the top-level doc shortcuts redirect to.
    """

    name: str
    title: str
    spec_factory: Callable[[RoutingSpec], RoutingSpec] = field(
        default=lambda version_spec: version_spec
    )
    landing: bool = False


DEFAULT_CATEGORIES: tuple[OpenapiCategory, ...] = (
    OpenapiCategory(
        name=OpenapiSpecCategory.internal,
        title="Internal API",
    ),
    OpenapiCategory(
        name=OpenapiSpecCategory.public,
        title="Public API",
        spec_factory=lambda version_spec: And(version_spec, Public()),
        landing=True,
    ),
)


@dataclass(frozen=True)
class OpenapiSpecs:
    version_range: tuple[int, int] | None
    specs: dict[str, dict[str, Any]]


class OpenapiProvider(ABC):
    categories: Sequence[OpenapiCategory]

    @abstractmethod
    def load_openapi(
        self,
        version: int | None,
        version_prefix: str,
        category: OpenapiCategory,
        title_suffix: str,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def get_version_range(self) -> tuple[int, int] | None: ...

    def get_versions(self) -> set[int] | None:
        """Return the exact set of versions that carry routes, or ``None``.

        ``None`` means the provider only knows the ``(min, max)`` bounds, so
        callers fall back to a dense range. Providers that can enumerate the
        actual versions override this to skip empty ones.
        """
        return None


class LocalFilesOpenapiProvider(OpenapiProvider):
    filename_suffix: ClassVar[str] = ".openapi.json"

    def __init__(
        self,
        path: Path,
        categories: Sequence[OpenapiCategory] = DEFAULT_CATEGORIES,
    ):
        self.path = path
        self.categories = categories

    @property
    def version_range_file(self) -> Path:
        return self.path / f"_version_range{self.filename_suffix}"

    def has_specs(self) -> bool:
        if not self.path.is_dir():
            return False

        return any(self.path.rglob(f"*{self.filename_suffix}"))

    def write_specs(self, openapi_specs: OpenapiSpecs) -> None:
        for file in self.path.rglob(f"*{self.filename_suffix}"):
            if file.is_file():
                file.unlink()

        for name, openapi in openapi_specs.specs.items():
            openapi_spec_file = self.path / Path(name.strip("/"))

            openapi_spec_file.parent.mkdir(parents=True, exist_ok=True)

            with open(openapi_spec_file, "w") as fp:
                json.dump(openapi, fp, indent=2)

        with open(self.version_range_file, "w") as fp:
            json.dump(openapi_specs.version_range, fp)

    @classmethod
    def build_filename(cls, version_prefix: str, category: OpenapiCategory) -> str:
        return f"{version_prefix}.{category.name}{cls.filename_suffix}".strip("/")

    def load_openapi(
        self,
        version: int | None,
        version_prefix: str,
        category: OpenapiCategory,
        title_suffix: str,
    ) -> dict[str, Any]:
        with open(self.path / self.build_filename(version_prefix, category)) as fp:
            return cast("dict[str, Any]", json.load(fp))

    def get_version_range(self) -> tuple[int, int] | None:
        with open(self.version_range_file) as fp:
            data: list[int] | None = json.load(fp)
            if data is None:
                return None

            if not isinstance(data, list) or len(data) != 2:
                raise ValueError(
                    f"Malformed version range in {self.version_range_file}: "
                    f"expected a 2-element list, got {data!r}"
                )

            return (data[0], data[1])


class AppOpenapiProvider(OpenapiProvider):
    def __init__(
        self,
        app: FastAPI,
        routes: list[BaseRoute],
        categories: Sequence[OpenapiCategory] = DEFAULT_CATEGORIES,
        title_prefix: str = "",
    ):
        self.app = app
        self.routes = routes
        self.categories = categories
        self.title_prefix = title_prefix

        route_ids: dict[str, APIRoute] = {}

        for route in routes:
            if isinstance(route, APIRoute):
                existing_route = route_ids.get(route.unique_id)

                if existing_route is not None and existing_route != route:
                    raise ValueError(
                        f"Unique ID {route.unique_id} of route {route} "
                        f"already exists for route {existing_route}"
                    )

                route_ids[route.unique_id] = route

    def load_openapi(
        self,
        version: int | None,
        version_prefix: str,
        category: OpenapiCategory,
        title_suffix: str,
    ) -> dict[str, Any]:
        version_spec: RoutingSpec = (
            Or(ApiVersion(version), ApiVersion(None))
            if version is not None
            else Unset()
        )

        openapi = get_openapi_static(
            self.app,
            f"{self.title_prefix}{category.title}{title_suffix}",
            tuple(resolve_routes(self.routes, category.spec_factory(version_spec))),
        )

        validate(cast("Mapping[str, Any]", openapi))

        return openapi

    def get_versions(self) -> set[int]:
        versions: set[int] = set()
        for route in self.routes:
            if isinstance(route, APIRoute):
                api_version = (
                    route.openapi_extra.get("x-api-version")
                    if route.openapi_extra
                    else None
                )
                if api_version is not None:
                    versions.add(api_version)
        return versions

    def get_version_range(self) -> tuple[int, int] | None:
        versions = self.get_versions()
        if not versions:
            return None
        return min(versions), max(versions)


def openapi_provider_factory(
    app: FastAPI,
    openapi_specs_dir: Path | None = None,
    categories: Sequence[OpenapiCategory] = DEFAULT_CATEGORIES,
    title_prefix: str = "",
) -> OpenapiProvider:
    if openapi_specs_dir is not None:
        local_files_provider = LocalFilesOpenapiProvider(openapi_specs_dir, categories)
        if local_files_provider.has_specs():
            return local_files_provider

    return AppOpenapiProvider(app, collect_app_routes(app), categories, title_prefix)
