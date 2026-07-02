from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from fastapi.applications import FastAPI
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import HTMLResponse

from fastapi_router_variants.definition import add_redirect_route
from fastapi_router_variants.openapi import (
    DEFAULT_CATEGORIES,
    LocalFilesOpenapiProvider,
    OpenapiCategory,
    OpenapiProvider,
    OpenapiSpecs,
    RouterWrapperApp,
    openapi_provider_factory,
)

swagger_ui_path = "/swagger-ui"
redoc_path = "/redoc"
openapi_path = "/openapi.json"

redirected_paths = (swagger_ui_path, redoc_path, openapi_path)

DEFAULT_SWAGGER_JS_URL = (
    "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"
)
DEFAULT_SWAGGER_CSS_URL = (
    "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
)
DEFAULT_REDOC_JS_URL = (
    "https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js"
)


def _get_root_path(req: Request) -> str:
    return str(req.scope.get("root_path", "").rstrip("/"))


def add_doc_routes_for_app(
    app: FastAPI,
    *,
    openapi_specs_dir: Path | None = None,
    categories: Sequence[OpenapiCategory] = DEFAULT_CATEGORIES,
    title_prefix: str = "",
    swagger_js_url: str = DEFAULT_SWAGGER_JS_URL,
    swagger_css_url: str = DEFAULT_SWAGGER_CSS_URL,
    redoc_js_url: str = DEFAULT_REDOC_JS_URL,
    skip_add_routes: bool = False,
) -> OpenapiSpecs:
    defaults = cast("RouterWrapperApp", app).router_wrapper_class.defaults

    prefix_value = defaults.prefix if isinstance(defaults.prefix, str) else ""
    prefix = prefix_value or "/"

    openapi_provider = openapi_provider_factory(
        app, openapi_specs_dir, categories, title_prefix
    )

    return add_doc_routes_for_all_versions(
        app,
        openapi_provider,
        doc_prefix=f"{prefix_value}/docs",
        prefix=prefix,
        default_version=defaults.version_default,
        swagger_js_url=swagger_js_url,
        swagger_css_url=swagger_css_url,
        redoc_js_url=redoc_js_url,
        skip_add_routes=skip_add_routes,
    )


def add_doc_routes_for_all_versions(
    app: FastAPI,
    openapi_provider: OpenapiProvider,
    doc_prefix: str = "",
    prefix: str = "",
    default_version: int | None = None,
    swagger_js_url: str = DEFAULT_SWAGGER_JS_URL,
    swagger_css_url: str = DEFAULT_SWAGGER_CSS_URL,
    redoc_js_url: str = DEFAULT_REDOC_JS_URL,
    skip_add_routes: bool = False,
) -> OpenapiSpecs:
    version_range = openapi_provider.get_version_range()

    if version_range is None:
        specs = add_doc_routes_for_version(
            app,
            openapi_provider,
            doc_prefix=doc_prefix,
            default_version=True,
            swagger_js_url=swagger_js_url,
            swagger_css_url=swagger_css_url,
            redoc_js_url=redoc_js_url,
            skip_add_routes=skip_add_routes,
        )
    else:
        specs = add_doc_routes_for_version(
            app,
            openapi_provider,
            doc_prefix=doc_prefix,
            version_prefix="/all",
            swagger_js_url=swagger_js_url,
            swagger_css_url=swagger_css_url,
            redoc_js_url=redoc_js_url,
            skip_add_routes=skip_add_routes,
        )

        min_version, max_version = version_range

        for version in range(min_version, max_version + 1):
            version_specs = add_doc_routes_for_version(
                app,
                openapi_provider,
                doc_prefix=doc_prefix,
                version=version,
                default_version=version == default_version,
                swagger_js_url=swagger_js_url,
                swagger_css_url=swagger_css_url,
                redoc_js_url=redoc_js_url,
                skip_add_routes=skip_add_routes,
            )
            specs.update(version_specs)

    openapi_specs = OpenapiSpecs(version_range, specs)
    if skip_add_routes:
        return openapi_specs

    add_doc_root_redirect_routes(app, doc_prefix, prefix)
    return openapi_specs


def add_doc_routes_for_version(
    app: FastAPI,
    openapi_provider: OpenapiProvider,
    doc_prefix: str = "",
    version: int | None = None,
    default_version: bool = False,
    skip_add_routes: bool = False,
    version_prefix: str | None = None,
    swagger_js_url: str = DEFAULT_SWAGGER_JS_URL,
    swagger_css_url: str = DEFAULT_SWAGGER_CSS_URL,
    redoc_js_url: str = DEFAULT_REDOC_JS_URL,
) -> dict[str, dict[str, Any]]:
    openapi_specs: dict[str, dict[str, Any]] = {}

    if version_prefix is None:
        version_prefix = f"/v{version}" if version is not None else ""

    title_suffix = "" if version is None else f" v{version}"

    for category in openapi_provider.categories:
        openapi_name = LocalFilesOpenapiProvider.build_filename(
            version_prefix, category
        )

        openapi_spec = openapi_provider.load_openapi(
            version, version_prefix, category, title_suffix
        )
        if openapi_spec is None:
            continue

        openapi_specs[openapi_name] = openapi_spec

    if skip_add_routes:
        return openapi_specs

    for category in openapi_provider.categories:
        openapi_name = LocalFilesOpenapiProvider.build_filename(
            version_prefix, category
        )

        maybe_openapi_spec = openapi_specs.get(openapi_name)
        if maybe_openapi_spec is None:
            continue

        openapi_spec = maybe_openapi_spec

        add_doc_routes_for_openapi_spec(
            app,
            openapi_spec,
            f"{doc_prefix}{version_prefix}/{category.name}",
            (f"{doc_prefix}/{category.name}",) if default_version else None,
            swagger_js_url=swagger_js_url,
            swagger_css_url=swagger_css_url,
            redoc_js_url=redoc_js_url,
        )

        if category.landing:
            add_redirect_route(
                app,
                f"{doc_prefix}{version_prefix}",
                f"{doc_prefix}{version_prefix}/{category.name}",
            )

            if default_version:
                for redirected_path in redirected_paths:
                    add_redirect_route(
                        app,
                        f"{doc_prefix}{redirected_path}",
                        f"{doc_prefix}{version_prefix}/{category.name}{redirected_path}",
                    )

    if default_version:
        add_redirect_route(app, f"{doc_prefix}", f"{doc_prefix}{version_prefix}")

    return openapi_specs


def add_doc_routes_for_openapi_spec(
    app: FastAPI,
    openapi_spec: dict[str, Any],
    prefix: str,
    redirect_prefixes: Sequence[str] | None = None,
    swagger_js_url: str = DEFAULT_SWAGGER_JS_URL,
    swagger_css_url: str = DEFAULT_SWAGGER_CSS_URL,
    redoc_js_url: str = DEFAULT_REDOC_JS_URL,
) -> None:
    title = openapi_spec.get("info", {}).get("title")
    if title is None:
        raise ValueError("info.title is missing in openapi spec")

    if redirect_prefixes:
        for redirect in redirect_prefixes:
            add_redirect_route(app, redirect, prefix)

    oauth2_redirect_path = f"{prefix}{swagger_ui_path}/oauth2-redirect"

    app.add_route(
        oauth2_redirect_path,
        get_swagger_ui_oauth2_redirect_html,  # type: ignore [arg-type]
        include_in_schema=False,
    )

    def openapi_path_factory(prefix: str) -> str:
        return f"{prefix}{openapi_path}"

    servers = [s for s in app.servers if s.get("url")]

    served_openapi_spec = {**openapi_spec}
    served_openapi_spec["servers"] = servers

    async def openapi(req: Request) -> JSONResponse:
        return JSONResponse(served_openapi_spec)

    app.add_route(openapi_path_factory(prefix), openapi, include_in_schema=False)
    if redirect_prefixes:
        for redirect in redirect_prefixes:
            add_redirect_route(
                app, openapi_path_factory(redirect), openapi_path_factory(prefix)
            )

    async def swagger_ui_html(req: Request) -> HTMLResponse:
        root_path = _get_root_path(req)
        return get_swagger_ui_html(
            title=f"{title} - Swagger UI",
            openapi_url=f"{root_path}{openapi_path_factory(prefix)}",
            swagger_js_url=swagger_js_url,
            swagger_css_url=swagger_css_url,
            oauth2_redirect_url=f"{root_path}{oauth2_redirect_path}",
        )

    def swagger_ui_path_factory(prefix: str) -> str:
        return f"{prefix}{swagger_ui_path}"

    app.add_route(
        swagger_ui_path_factory(prefix), swagger_ui_html, include_in_schema=False
    )

    add_redirect_route(app, prefix, swagger_ui_path_factory(prefix))

    if redirect_prefixes:
        for redirect in redirect_prefixes:
            add_redirect_route(
                app, swagger_ui_path_factory(redirect), swagger_ui_path_factory(prefix)
            )

    async def redoc_html(req: Request) -> HTMLResponse:
        root_path = _get_root_path(req)
        return get_redoc_html(
            openapi_url=f"{root_path}{openapi_path_factory(prefix)}",
            redoc_js_url=redoc_js_url,
            title=f"{title} - ReDoc",
        )

    def redoc_path_factory(prefix: str) -> str:
        return f"{prefix}{redoc_path}"

    app.add_route(redoc_path_factory(prefix), redoc_html, include_in_schema=False)
    if redirect_prefixes:
        for redirect in redirect_prefixes:
            add_redirect_route(
                app, redoc_path_factory(redirect), redoc_path_factory(prefix)
            )


def add_doc_root_redirect_routes(app: FastAPI, doc_prefix: str, prefix: str) -> None:
    for path in ("/", "/docs"):
        add_redirect_route(app, path, doc_prefix)
        add_redirect_route(app, f"{prefix}{path}".rstrip("/"), doc_prefix)

    for path in redirected_paths:
        add_redirect_route(app, path, f"{doc_prefix}{path}")
