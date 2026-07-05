import inspect
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from itertools import chain
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Protocol,
    Self,
)

from fastapi import APIRouter, Depends, FastAPI, params
from fastapi.datastructures import Default
from fastapi.routing import APIRoute
from fastapi.types import DecoratedCallable
from starlette.datastructures import URL
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import (
    BaseRoute,
)
from starlette.status import HTTP_204_NO_CONTENT
from starlette.types import ASGIApp, Lifespan
from typing_extensions import Doc, deprecated

from fastapi_router_variants.doc import load_markdown
from fastapi_router_variants.specs import (
    RoutingSpec,
    resolve,
)
from fastapi_router_variants.unique_id import RouterUniqueIdGenerator
from fastapi_router_variants.versioning import (
    DeploymentSpec,
    Disabled,
    PathSpec,
    PrefixSpec,
    Route,
    RouteFlavors,
    VersioningDefaultsProtocol,
    VersionSpec,
    api_version_from_path,
    variants_routes,
)

CSVExample = Sequence[tuple[str, tuple[str, ...]]]


def _describe_values(values: set[Any]) -> str:
    def render(value: Any) -> str:
        return str(value.value) if isinstance(value, Enum) else str(value)

    return ", ".join(sorted(render(v) for v in values))


def _csv_example_html_table(csv_example: CSVExample) -> str:
    headers = [col for col, _ in csv_example]

    num_rows = len(csv_example[0][1])
    rows = [
        [
            str(col_vals[1][i]) if col_vals[1][i] != "" else "—"
            for col_vals in csv_example
        ]
        for i in range(num_rows)
    ]

    lines = []
    lines.append("| " + " | ".join(f"**{h}**" for h in headers) + " |")
    lines.append("|" + "|".join([":--" for _ in headers]) + "|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _csv_example_return(example: CSVExample) -> str:
    headers_str = ";".join(column[0] for column in example)

    value_length = min(len(column[1]) for column in example)

    return "\n".join(
        chain(
            (headers_str,),
            (";".join(column[1][i] for column in example) for i in range(value_length)),
        )
    )


def _find_http_exceptions(handler: Any, error_base: type) -> set[type]:
    """Collect exception types declared through the dependency graph.

    Returns ``handler`` itself when it is a subclass of ``error_base``,
    otherwise walks its ``Depends()`` parameters recursively.
    """
    if inspect.isclass(handler) and issubclass(handler, error_base):
        return {handler}

    if callable(handler):
        return _find_param_http_exceptions(handler, error_base)

    return set()


def _find_param_http_exceptions(
    handler: Callable[..., Any], error_base: type
) -> set[type]:
    return {
        http_exception
        for parameter in inspect.signature(handler).parameters.values()
        if parameter.default is not None
        and parameter.default is not inspect.Parameter.empty
        and isinstance(parameter.default, params.Depends)
        for http_exception in _find_http_exceptions(
            parameter.default.dependency, error_base
        )
    }


RouteType = Literal["http", "websocket"]


class RouteRecorder(Protocol):
    """Sink for route metadata captured while a router is *recording*.

    When a recorder is active (see :meth:`RouterWrapper.recording`), the route
    decorators do not create real routes: instead they call :meth:`record`
    once for every expanded variant (versions x prefixes x flavors) with its
    generic metadata. This lets callers enumerate a router's routes without
    mounting them on an application.
    """

    def record(
        self,
        *,
        path: str,
        type: RouteType,
        methods: tuple[str, ...] | None,
        version: VersionSpec | None,
        prefix: PrefixSpec | None,
        deployment: DeploymentSpec | None,
        hidden: bool,
    ) -> None: ...


class RouterWrapperError(Exception): ...


class RequireRolesProtocol(Protocol):
    def __call__(self, roles: set[Any]) -> Any: ...


class RequireFeaturesProtocol(Protocol):
    def __call__(self, *features: Any) -> Any: ...


@dataclass(frozen=True, kw_only=True)
class RouterOperationIdSettings:
    segment_aliases: dict[str, str] = field(default_factory=dict)
    """Segment aliases"""

    segment_exclusions: set[str] = field(default_factory=set)
    """Excluded segments"""

    singular_mappings: dict[str, str] = field(default_factory=dict)
    """Segment singular mappings"""

    plural_mappings: dict[str, str] = field(default_factory=dict)
    """Segment plural mappings"""


class RouterDefaultsProtocol(VersioningDefaultsProtocol):
    public: RoutingSpec | None = None
    """Spec for public routes"""

    version_default: int = 1
    """Default version to use when accessing docs on unversioned url"""

    requires: list[Any] | None = None
    """Dependency to add on all routes"""

    deployment: str | None = None
    """default deployment to declare on all routes"""

    operation_id_settings: RouterOperationIdSettings = RouterOperationIdSettings()
    """openapi operation id generation settings"""

    autodoc_http_errors: bool = False
    """Enable automatic OpenAPI documentation of raised HTTP errors.

    Disabled by default. When enabled, ``exception_scanner`` and
    ``error_schema_builder`` are used to discover and document errors.
    """

    http_error_base: type = Exception
    """Base type identifying documentable HTTP error classes.

    Used to detect error classes reachable through the dependency graph.
    """

    exception_scanner: Callable[[Callable[..., Any]], set[type]] | None = None
    """Optional hook returning the error types a callable may raise.

    Wrap it in ``staticmethod`` when set on a defaults subclass.
    """

    error_schema_builder: Callable[[set[type]], Any] | None = None
    """Optional hook turning a set of error types into an OpenAPI ``responses``.

    Wrap it in ``staticmethod`` when set on a defaults subclass.
    """


@dataclass(frozen=True)
class RouterDefaults(RouterDefaultsProtocol): ...


@dataclass(frozen=True)
class DisabledDefaults(RouterDefaults):
    prefix = Disabled
    version = Disabled


class RouterWrapper:
    defaults: RouterDefaultsProtocol = RouterDefaults()
    require_roles: RequireRolesProtocol | None = None
    require_features: RequireFeaturesProtocol | None = None

    _route_recorder: ClassVar[RouteRecorder | None] = None

    @classmethod
    def reset_defaults(cls) -> None:
        cls.defaults = RouterDefaults()

    @classmethod
    @contextmanager
    def recording(cls, recorder: RouteRecorder) -> Iterator[RouteRecorder]:
        """Activate ``recorder`` for the duration of the context.

        While active, ``api_route``/``websocket`` (and the HTTP method
        shortcuts) report every route variant to ``recorder`` and return a
        no-op decorator instead of registering the route on ``self.base``.
        """
        previous = cls._route_recorder
        cls._route_recorder = recorder
        try:
            yield recorder
        finally:
            cls._route_recorder = previous

    def include_router(
        self,
        router: Annotated[
            "APIRouter | RouterWrapper", Doc("The `APIRouter` to include.")
        ],
        **kwargs: Any,
    ) -> None:
        self.base.include_router(
            router.base if isinstance(router, RouterWrapper) else router, **kwargs
        )

    def __init__(
        self,
        *,
        tags: Annotated[
            list[str | Enum] | None,
            Doc("""
                A list of tags to be applied to all the *path operations* in this
                router.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """),
        ] = None,
        dependencies: Annotated[
            Sequence[params.Depends] | None,
            Doc("""
                A list of dependencies (using `Depends()`) to be applied to all the
                *path operations* in this router.
                """),
        ] = None,
        default_response_class: Annotated[
            type[Response],
            Doc("""
                The default response class to be used.
                """),
        ] = Default(JSONResponse),
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc("""
                Additional responses to be shown in OpenAPI.
                """),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc("""
                OpenAPI callbacks that should apply to all *path operations* in this
                router.
                """),
        ] = None,
        routes: Annotated[
            list[BaseRoute] | None,
            Doc("""
                **Note**: you probably shouldn't use this parameter, it is inherited
                from Starlette and supported for compatibility.
                """),
            deprecated("""
                You normally wouldn't use this parameter with FastAPI, it is inherited
                from Starlette and supported for compatibility.
                """),
        ] = None,
        redirect_slashes: Annotated[
            bool,
            Doc("""
                Whether to detect and redirect slashes in URLs when the client doesn't
                use the same format.
                """),
        ] = True,
        default: Annotated[
            ASGIApp | None,
            Doc("""
                Default function handler for this router. Used to handle
                404 Not Found errors.
                """),
        ] = None,
        dependency_overrides_provider: Annotated[
            Any | None,
            Doc("""
                Only used internally by FastAPI to handle dependency overrides.
                """),
        ] = None,
        route_class: Annotated[
            type[APIRoute],
            Doc("""
                Custom route (*path operation*) class to be used by this router.
                """),
        ] = APIRoute,
        on_startup: Annotated[
            Sequence[Callable[[], Any]] | None,
            Doc("""
                A list of startup event handler functions.
                """),
        ] = None,
        on_shutdown: Annotated[
            Sequence[Callable[[], Any]] | None,
            Doc("""
                A list of shutdown event handler functions.
                """),
        ] = None,
        lifespan: Annotated[
            Lifespan[Any] | None,
            Doc("""
                A `Lifespan` context manager handler. This replaces `startup` and
                `shutdown` functions with a single context manager.
                """),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc("""
                Mark all *path operations* in this router as deprecated.
                """),
        ] = None,
        public: bool | RoutingSpec | None = None,
        deployment: DeploymentSpec | None = None,
        include_in_schema: Annotated[
            bool,
            Doc("""
                To include (or not) all the *path operations* in this router in the
                generated OpenAPI.
                """),
        ] = True,
        hidden: Annotated[
            bool,
            Doc("""
                Mark all routes of this router as internal-only: served by their
                deployment but never published in the generated OpenAPI schema.
                Forces ``include_in_schema=False``.
                """),
        ] = False,
        version: VersionSpec | None = None,
        prefix: PrefixSpec | None = None,
        parent: Self | None = None,
    ) -> None:
        self.base = APIRouter(
            tags=tags,
            dependencies=dependencies,
            default_response_class=default_response_class,
            responses=responses,
            callbacks=callbacks,
            routes=routes,
            redirect_slashes=redirect_slashes,
            default=default,
            dependency_overrides_provider=dependency_overrides_provider,
            route_class=route_class,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            lifespan=lifespan,
            deprecated=deprecated,
            include_in_schema=include_in_schema and not hidden,
            generate_unique_id_function=RouterUniqueIdGenerator(self),
        )
        self.public = public
        self.version = version
        self.prefix = prefix
        self.deployment = deployment
        self.hidden = hidden
        self.parent = parent

    def websocket(
        self,
        path_specs: PathSpec,
        *,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        deployment: DeploymentSpec | None = None,
        public: bool | RoutingSpec | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        def decorator_factory(
            route_path: Route,
        ) -> Callable[[Callable[..., Any]], Any]:
            def decorator(handler: Callable[..., Any]) -> Any:
                require_roles_http_dep: Any = (
                    self.require_roles(require_roles)
                    if require_roles and self.require_roles
                    else None
                )
                require_features_http_dep: Any = (
                    self.require_features(*require_features)
                    if require_features and self.require_features
                    else None
                )

                @wraps(handler)
                def wrapper() -> Any:
                    recorder = self._route_recorder
                    if recorder is not None:
                        recorder.record(
                            path=route_path.path,
                            type="websocket",
                            methods=None,
                            version=route_path.version,
                            prefix=route_path.prefix,
                            deployment=route_path.deployment,
                            hidden=self.hidden,
                        )
                        return handler

                    api_route = self.base.websocket(
                        route_path.path,
                        dependencies=(
                            (
                                [Depends(require_roles_http_dep)]
                                if require_roles_http_dep
                                else []
                            )
                            + (
                                [Depends(require_features_http_dep)]
                                if require_features_http_dep
                                else []
                            )
                            + ([Depends(r) for r in (requires if requires else [])])
                            + (
                                [
                                    Depends(r)
                                    for r in (
                                        self.defaults.requires
                                        if self.defaults.requires
                                        else []
                                    )
                                ]
                            )
                        ),
                    )

                    return api_route(handler)

                return wrapper()

            return decorator

        return self.variants_decorator_wrapper(
            decorator_factory, path_specs, prefix, version, deployment, public
        )

    def is_public_route(
        self,
        path: str,
        *,
        methods: list[str] | None = None,
        deprecated: bool = False,
        public: bool | RoutingSpec | None = None,
        response_model: Any = Default(None),
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
    ) -> bool:
        return resolve(
            public,
            self.public,
            self.defaults.public,
            path=path,
            methods=methods,
            deprecated=deprecated,
            response_model=response_model,
            response_class=response_class,
            openapi_extra=openapi_extra,
        )

    def api_route(
        self,
        path_specs: PathSpec,
        *,
        methods: list[str],
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        deployment: DeploymentSpec | None = None,
        public: bool | RoutingSpec | None = None,
        response_model: Any = Default(None),
        exceptions: set[Any] | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
        status_code: int | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        summary: str | None = None,
        headline: str | None = None,
        points: Sequence[str] | None = None,
        doc: str | None = None,
        deprecated: str | bool | None = None,
        response_model_exclude_none: bool = False,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_by_alias: bool = True,
        response_model_exclude: set[str] | None = None,
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        def decorator_factory(
            route_path: Route,
        ) -> Callable[[Callable[..., Any]], Any]:
            path_openapi_extra = deepcopy(openapi_extra)

            api_version = (
                route_path.version
                if isinstance(route_path.version, int)
                and not isinstance(route_path.version, bool)
                else None
            )

            if route_path.version is None:
                api_version = api_version_from_path(route_path.path)

            if api_version is not None:
                if path_openapi_extra is None:
                    path_openapi_extra = {}
                path_openapi_extra["x-api-version"] = api_version

            if route_path.prefix is not None:
                if path_openapi_extra is None:
                    path_openapi_extra = {}
                path_openapi_extra["x-path-prefix"] = route_path.prefix

            if route_path.deployment is not None:
                if path_openapi_extra is None:
                    path_openapi_extra = {}
                path_openapi_extra["x-deployment"] = route_path.deployment

            route_deprecated = (
                bool(deprecated)
                if deprecated is not None
                else bool(route_path.deprecated)
            )

            if self.is_public_route(
                route_path.path,
                methods=methods,
                deprecated=route_deprecated,
                public=public,
                response_model=response_model,
                response_class=response_class,
                openapi_extra=path_openapi_extra,
            ):
                if path_openapi_extra is None:
                    path_openapi_extra = {}
                path_openapi_extra["x-public"] = True

            if deployment is not None:
                if path_openapi_extra is None:
                    path_openapi_extra = {}
                path_openapi_extra["x-deployment"] = deployment

            def decorator(handler: Callable[..., Any]) -> Any:
                require_roles_http_dep: Any = (
                    self.require_roles(require_roles)
                    if require_roles and self.require_roles
                    else None
                )
                require_features_http_dep: Any = (
                    self.require_features(*require_features)
                    if require_features and self.require_features
                    else None
                )

                http_exceptions: set[Any] = set(exceptions) if exceptions else set()

                if self.defaults.autodoc_http_errors:
                    error_base = self.defaults.http_error_base
                    scanner = self.defaults.exception_scanner

                    http_exceptions |= _find_param_http_exceptions(handler, error_base)

                    if require_roles_http_dep:
                        http_exceptions |= _find_http_exceptions(
                            require_roles_http_dep, error_base
                        )
                    if require_features_http_dep:
                        http_exceptions |= _find_http_exceptions(
                            require_features_http_dep, error_base
                        )

                    if requires:
                        for r in requires:
                            http_exceptions |= _find_http_exceptions(r, error_base)
                            if scanner is not None:
                                http_exceptions |= scanner(r)

                    if scanner is not None:
                        http_exceptions |= scanner(handler)

                description = (
                    (
                        (
                            "<h1><b>This endpoint is deprecated"
                            + (
                                f", use <code>{deprecated}</code> instead"
                                if isinstance(deprecated, str)
                                else ""
                            )
                            + ".</b></h1>\n\n"
                        )
                        if deprecated
                        else ""
                    )
                    + ((f"**{headline}**") if headline else "")
                    + ("\n\n" if headline and points else "")
                    + ("\n".join(f"- {point}" for point in points) if points else "")
                    + ("\n\n" if (points or headline) and doc else "")
                    + (doc if doc else "")
                    + (
                        f"\n\nFeature needed: {_describe_values(require_features)}"
                        if require_features
                        else ""
                    )
                    + (
                        f"\n\nRole needed: {_describe_values(require_roles)}"
                        if require_roles
                        else ""
                    )
                )

                @wraps(handler)
                def wrapper() -> Any:
                    recorder = self._route_recorder
                    if recorder is not None:
                        recorder.record(
                            path=route_path.path,
                            type="http",
                            methods=tuple(methods),
                            version=route_path.version,
                            prefix=route_path.prefix,
                            deployment=route_path.deployment,
                            hidden=self.hidden,
                        )
                        return handler

                    error_schema_builder = self.defaults.error_schema_builder
                    error_schemas = (
                        error_schema_builder(http_exceptions)
                        if error_schema_builder and http_exceptions
                        else None
                    )

                    api_route = self.base.api_route(
                        route_path.path,
                        methods=methods,
                        tags=route_path.tags,
                        dependencies=(
                            (
                                [Depends(require_roles_http_dep)]
                                if require_roles_http_dep
                                else []
                            )
                            + (
                                [Depends(require_features_http_dep)]
                                if require_features_http_dep
                                else []
                            )
                            + ([Depends(r) for r in (requires if requires else [])])
                            + (
                                [
                                    Depends(r)
                                    for r in (
                                        self.defaults.requires
                                        if self.defaults.requires
                                        else []
                                    )
                                ]
                            )
                        ),
                        responses=(error_schemas if error_schemas else {})
                        | (responses if responses else {}),
                        status_code=(
                            HTTP_204_NO_CONTENT
                            if status_code is None
                            and inspect.signature(handler).return_annotation is None
                            else status_code
                        ),
                        deprecated=route_deprecated,
                        summary=summary,
                        description=description,
                        response_model=response_model,
                        response_model_exclude_none=response_model_exclude_none,
                        response_model_exclude_unset=response_model_exclude_unset,
                        response_model_exclude_defaults=response_model_exclude_defaults,
                        response_model_by_alias=response_model_by_alias,
                        response_model_exclude=response_model_exclude,
                        response_class=response_class,
                        openapi_extra=path_openapi_extra,
                    )

                    return api_route(handler)

                return wrapper()

            return decorator

        return self.variants_decorator_wrapper(
            decorator_factory, path_specs, prefix, version, deployment, public
        )

    def get(
        self,
        path: PathSpec,
        *,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        response_model: Any = Default(None),
        exceptions: set[Any] | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
        status_code: int | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        summary: str | None = None,
        headline: str | None = None,
        points: Sequence[str] | None = None,
        doc: str | None = None,
        deprecated: str | bool | None = None,
        public: bool | RoutingSpec | None = None,
        deployment: DeploymentSpec | None = None,
        response_model_exclude_none: bool = False,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_by_alias: bool = True,
        response_model_exclude: set[str] | None = None,
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return self.api_route(
            path,
            methods=["GET"],
            prefix=prefix,
            version=version,
            response_model=response_model,
            exceptions=exceptions,
            require_roles=require_roles,
            require_features=require_features,
            requires=requires,
            status_code=status_code,
            responses=responses,
            summary=summary,
            headline=headline,
            points=points,
            doc=doc,
            deprecated=deprecated,
            public=public,
            deployment=deployment,
            response_model_exclude_none=response_model_exclude_none,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude=response_model_exclude,
            response_class=response_class,
            openapi_extra=openapi_extra,
        )

    def get_csv_export(
        self,
        path: PathSpec,
        *,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        response_model: Any = Default(None),
        exceptions: set[Any] | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
        status_code: int | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        summary: str | None = None,
        headline: str | None = None,
        points: Sequence[str] | None = None,
        doc: str | None = None,
        deprecated: str | bool | None = None,
        public: bool | RoutingSpec | None = None,
        deployment: DeploymentSpec | None = None,
        response_model_exclude_none: bool = False,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_by_alias: bool = True,
        response_model_exclude: set[str] | None = None,
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
        csv_example: CSVExample,
    ) -> Callable[..., Any]:
        default_responses: dict[int | str, dict[str, Any]] = {
            200: {
                "description": "Successful Response",
                "content": {
                    "text/csv": {
                        "schema": {"type": "string"},
                        "example": _csv_example_return(csv_example),
                    }
                },
            }
        }
        return self.api_route(
            path,
            methods=["GET"],
            prefix=prefix,
            version=version,
            response_model=response_model,
            exceptions=exceptions,
            require_roles=require_roles,
            require_features=require_features,
            requires=requires,
            status_code=status_code,
            responses=default_responses | (responses if responses else {}),
            summary=summary,
            headline=headline,
            points=points,
            doc=(
                (load_markdown())
                + "\n\n<h2>Example : </h2>\n\n"
                + _csv_example_html_table(csv_example)
            ),
            deprecated=deprecated,
            public=public,
            deployment=deployment,
            response_model_exclude_none=response_model_exclude_none,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude=response_model_exclude,
            response_class=response_class,
            openapi_extra=openapi_extra,
        )

    def post(
        self,
        path: PathSpec,
        *,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        response_model: Any = Default(None),
        exceptions: set[Any] | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
        status_code: int | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        summary: str | None = None,
        headline: str | None = None,
        points: Sequence[str] | None = None,
        doc: str | None = None,
        deprecated: str | bool | None = None,
        public: bool | RoutingSpec | None = None,
        deployment: DeploymentSpec | None = None,
        response_model_exclude_none: bool = False,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_by_alias: bool = True,
        response_model_exclude: set[str] | None = None,
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return self.api_route(
            path,
            methods=["POST"],
            prefix=prefix,
            version=version,
            response_model=response_model,
            exceptions=exceptions,
            require_roles=require_roles,
            require_features=require_features,
            requires=requires,
            status_code=status_code,
            responses=responses,
            summary=summary,
            headline=headline,
            points=points,
            doc=doc,
            deprecated=deprecated,
            public=public,
            deployment=deployment,
            response_model_exclude_none=response_model_exclude_none,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude=response_model_exclude,
            response_class=response_class,
            openapi_extra=openapi_extra,
        )

    def patch(
        self,
        path: PathSpec,
        *,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        response_model: Any = Default(None),
        exceptions: set[Any] | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
        status_code: int | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        summary: str | None = None,
        headline: str | None = None,
        points: Sequence[str] | None = None,
        doc: str | None = None,
        deprecated: str | bool | None = None,
        public: bool | RoutingSpec | None = None,
        deployment: DeploymentSpec | None = None,
        response_model_exclude_none: bool = False,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_by_alias: bool = True,
        response_model_exclude: set[str] | None = None,
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return self.api_route(
            path,
            methods=["PATCH"],
            prefix=prefix,
            version=version,
            response_model=response_model,
            exceptions=exceptions,
            require_roles=require_roles,
            require_features=require_features,
            requires=requires,
            status_code=status_code,
            responses=responses,
            summary=summary,
            headline=headline,
            points=points,
            doc=doc,
            deprecated=deprecated,
            public=public,
            deployment=deployment,
            response_model_exclude_none=response_model_exclude_none,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude=response_model_exclude,
            response_class=response_class,
            openapi_extra=openapi_extra,
        )

    def put(
        self,
        path: PathSpec,
        *,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        response_model: Any = Default(None),
        exceptions: set[Any] | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
        status_code: int | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        summary: str | None = None,
        headline: str | None = None,
        points: Sequence[str] | None = None,
        doc: str | None = None,
        deprecated: str | bool | None = None,
        public: bool | RoutingSpec | None = None,
        deployment: DeploymentSpec | None = None,
        response_model_exclude_none: bool = False,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_by_alias: bool = True,
        response_model_exclude: set[str] | None = None,
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return self.api_route(
            path,
            prefix=prefix,
            methods=["PUT"],
            version=version,
            response_model=response_model,
            exceptions=exceptions,
            require_roles=require_roles,
            require_features=require_features,
            requires=requires,
            status_code=status_code,
            responses=responses,
            summary=summary,
            headline=headline,
            points=points,
            doc=doc,
            deprecated=deprecated,
            public=public,
            deployment=deployment,
            response_model_exclude_none=response_model_exclude_none,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude=response_model_exclude,
            response_class=response_class,
            openapi_extra=openapi_extra,
        )

    def delete(
        self,
        path: PathSpec,
        *,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        response_model: Any = Default(None),
        exceptions: set[Any] | None = None,
        require_roles: set[Any] | None = None,
        require_features: set[Any] | None = None,
        requires: Sequence[Any] | None = None,
        status_code: int | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        summary: str | None = None,
        headline: str | None = None,
        points: Sequence[str] | None = None,
        doc: str | None = None,
        deprecated: str | bool | None = None,
        public: bool | RoutingSpec | None = None,
        deployment: DeploymentSpec | None = None,
        response_model_exclude_none: bool = False,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_by_alias: bool = True,
        response_model_exclude: set[str] | None = None,
        response_class: type[Response] = Default(JSONResponse),
        openapi_extra: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        return self.api_route(
            path,
            methods=["DELETE"],
            prefix=prefix,
            version=version,
            response_model=response_model,
            exceptions=exceptions,
            require_roles=require_roles,
            require_features=require_features,
            requires=requires,
            status_code=status_code,
            responses=responses,
            summary=summary,
            headline=headline,
            points=points,
            doc=doc,
            deprecated=deprecated,
            public=public,
            deployment=deployment,
            response_model_exclude_none=response_model_exclude_none,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude=response_model_exclude,
            response_class=response_class,
            openapi_extra=openapi_extra,
        )

    def variants_decorator_wrapper(
        self,
        route_decorator_factory: Callable[[Route], Callable[[Callable[..., Any]], Any]],
        path_specs: PathSpec,
        prefix: PrefixSpec | None = None,
        version: VersionSpec | None = None,
        deployment: DeploymentSpec | None = None,
        public: bool | RoutingSpec | None = None,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        if public is None:
            public = self.public
        if deployment is None:
            deployment = self.deployment

        if version is None and self.version is None and self.defaults.version is True:
            raise RouterWrapperError("version must be defined on route or router")

        if prefix is None and self.prefix is None and self.defaults.prefix is True:
            raise RouterWrapperError("prefix must be defined on route or router")

        if isinstance(path_specs, RouteFlavors):
            path_specs = path_specs.build()

        if not isinstance(path_specs, Sequence) or isinstance(path_specs, str):
            path_specs = (path_specs,)

        route_paths: Sequence[Route] = deepcopy(
            tuple(Route(x) if isinstance(x, str) else x for x in path_specs)
        )

        route_paths = variants_routes(
            route_paths,
            self.defaults,
            self.prefix,
            self.version,
            self.deployment,
            prefix,
            version,
            deployment,
        )

        if len(route_paths) == 1:
            route_path = route_paths[0]
            return route_decorator_factory(route_path)

        if len(route_paths) < 1:
            raise RouterWrapperError(
                "Path should have at least one item when declared as a list."
            )

        decorators: list[Callable[[Callable[..., Any]], Any]] = []
        for route_path in route_paths:
            decorators.append(route_decorator_factory(route_path))

        def composed_decorator_factory(
            decorators: list[Callable[[Callable[..., Any]], Any]],
        ) -> Callable[..., Any]:
            def compose(f: Any) -> Any:
                for decorator in reversed(decorators):
                    f = decorator(f)
                return f

            return compose

        return composed_decorator_factory(decorators)


def add_redirect_route(app: FastAPI, from_path: str, to_url: str | URL) -> None:
    @app.get(from_path)
    def redirect() -> RedirectResponse:
        return RedirectResponse(url=to_url)
