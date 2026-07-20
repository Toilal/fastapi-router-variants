import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
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


def collect_app_routes(container: Any) -> list[BaseRoute]:
    """Flatten every route reachable from an app or router.

    Descends into included routers (including the lazily-mounted routers used by
    recent FastAPI releases) and mounts so callers get the leaf routes
    regardless of how they were included.
    """
    collected: list[BaseRoute] = []
    for route in getattr(container, "routes", []):
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            collected.extend(collect_app_routes(original_router))
        elif isinstance(route, APIRoute):
            collected.append(route)
        elif getattr(route, "routes", None) is not None:
            collected.extend(collect_app_routes(route))
        else:
            collected.append(route)
    return collected


def _include_is_transparent(route: BaseRoute) -> bool:
    """Whether an ``_IncludedRouter`` mounts its child routes unchanged.

    FastAPI >= 0.139 stores the ``include_router`` arguments (prefix, tags,
    dependencies, …) on ``route.include_context`` and applies them lazily. When
    none of them alter the child routes, the child's own route objects already
    are the effective serving routes and can be spliced in as-is. Any transform
    means the effective route differs from the stored child route, so the
    wrapper must stay in place to keep serving correctly.
    """
    context = getattr(route, "include_context", None)
    if context is None:
        return True
    return not (
        getattr(context, "prefix", "")
        or getattr(context, "tags", None)
        or getattr(context, "dependencies", None)
        or getattr(context, "responses", None)
        or getattr(context, "callbacks", None)
        or getattr(context, "deprecated", None)
    )


def _flatten_included_routes(routes: Sequence[BaseRoute]) -> list[BaseRoute]:
    flattened: list[BaseRoute] = []
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None and _include_is_transparent(route):
            flattened.extend(_flatten_included_routes(original_router.routes))
        else:
            flattened.append(route)
    return flattened


def flatten_included_routers(container: Any) -> None:
    """Rewrite a serving router's ``routes`` so no ``_IncludedRouter`` remains.

    Since FastAPI 0.139 each ``include_router`` call appends a single opaque
    ``_IncludedRouter`` to the parent ``routes`` instead of flattening the
    child's routes. Starlette matches every ``routes`` entry on each request, and
    ``_IncludedRouter.matches()`` materialises and retains the effective
    dependency tree of every child route on first match — inflating RSS by
    hundreds of MB for a large composed app and leading to OOM under load.

    Replacing each transparent ``_IncludedRouter`` in place with the real leaf
    routes it wraps restores the flat routing table FastAPI <= 0.138 built
    eagerly, so Starlette never calls ``_IncludedRouter.matches()`` on the hot
    path. Only entries carrying ``original_router`` whose ``include_context``
    applies no transform are flattened; ``Mount``/sub-apps, ``WebSocketRoute``,
    redirect routes and prefixed/dependency-carrying includes are kept as-is. A
    no-op on FastAPI 0.115→0.138, where the table is already flat.

    Call it once after all ``include_router`` calls, before serving. Accepts a
    ``FastAPI`` app, an ``APIRouter`` or a ``RouterWrapper``.
    """
    base = getattr(container, "base", None)
    target = base if base is not None else container
    router = getattr(target, "router", target)
    routes = getattr(router, "routes", None)
    if routes is None:
        return
    routes[:] = _flatten_included_routes(routes)
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
