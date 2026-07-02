from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from fastapi_router_variants import (
    And,
    AppOpenapiProvider,
    LocalFilesOpenapiProvider,
    OpenapiCategory,
    OpenapiExtra,
    OpenapiSpecs,
    RouterDefaults,
    RouterWrapper,
    add_doc_routes_for_app,
    collect_app_routes,
    openapi_provider_factory,
)
from fastapi_router_variants.openapi import DEFAULT_CATEGORIES

INTERNAL = DEFAULT_CATEGORIES[0]
PUBLIC = DEFAULT_CATEGORIES[1]


@dataclass(frozen=True)
class DocDefaults(RouterDefaults):
    prefix = "/api"
    version = True
    version_range = (1, 2)
    version_default = 1


def _build_app() -> tuple[FastAPI, type[RouterWrapper]]:
    class DocRouter(RouterWrapper):
        defaults = DocDefaults()

        @classmethod
        def reset_defaults(cls) -> None:
            cls.defaults = DocDefaults()

    router = DocRouter(version=True)

    @router.get("/public", public=True)
    def public_ep() -> dict[str, str]:
        return {}

    @router.get("/internal")
    def internal_ep() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(router.base)
    app.router_wrapper_class = DocRouter  # type: ignore[attr-defined]
    return app, DocRouter


@pytest.fixture(autouse=True)
def _use_doc_defaults() -> None:
    RouterWrapper.defaults = DocDefaults()
    return


class TestAppOpenapiProvider:
    def test_version_range_from_routes(self) -> None:
        app, _ = _build_app()
        provider = AppOpenapiProvider(app, collect_app_routes(app))
        assert provider.get_version_range() == (1, 2)

    def test_public_category_filters_by_version_and_public(self) -> None:
        app, _ = _build_app()
        provider = AppOpenapiProvider(app, collect_app_routes(app), title_prefix="X ")

        spec = provider.load_openapi(1, "/v1", PUBLIC, " v1")
        paths = spec["paths"]

        assert "/api/v1/public" in paths
        assert "/api/v1/internal" not in paths
        assert "/api/v2/public" not in paths
        assert spec["info"]["title"] == "X Public API v1"

    def test_internal_category_includes_all_of_version(self) -> None:
        app, _ = _build_app()
        provider = AppOpenapiProvider(app, collect_app_routes(app))

        spec = provider.load_openapi(1, "/v1", INTERNAL, " v1")
        paths = spec["paths"]

        assert "/api/v1/public" in paths
        assert "/api/v1/internal" in paths
        assert "/api/v2/internal" not in paths

    def test_custom_category(self) -> None:
        app, router_type = _build_app()
        router = router_type(version=True)

        @router.get("/partner", openapi_extra={"x-partner": True})
        def partner_ep() -> dict[str, str]:
            return {}

        app.include_router(router.base)

        category = OpenapiCategory(
            name="partner",
            title="Partner API",
            spec_factory=lambda version_spec: And(
                version_spec, OpenapiExtra("x-partner", True)
            ),
        )
        provider = AppOpenapiProvider(
            app, collect_app_routes(app), categories=(category,)
        )
        spec = provider.load_openapi(1, "/v1", category, " v1")

        assert "/api/v1/partner" in spec["paths"]
        assert "/api/v1/public" not in spec["paths"]


class TestDocRoutesMounting:
    def test_per_version_openapi_json(self) -> None:
        app, _ = _build_app()
        specs = add_doc_routes_for_app(app)

        assert specs.version_range == (1, 2)

        client = TestClient(app)

        public_v1 = client.get("/api/docs/v1/public/openapi.json")
        assert public_v1.status_code == 200
        assert public_v1.json()["info"]["title"] == "Public API v1"
        assert "/api/v1/public" in public_v1.json()["paths"]

        public_v2 = client.get("/api/docs/v2/public/openapi.json")
        assert public_v2.status_code == 200
        assert "/api/v2/public" in public_v2.json()["paths"]

    def test_swagger_and_redoc_html(self) -> None:
        app, _ = _build_app()
        add_doc_routes_for_app(app)
        client = TestClient(app)

        swagger = client.get("/api/docs/v1/public/swagger-ui")
        assert swagger.status_code == 200
        assert "swagger-ui" in swagger.text.lower()

        redoc = client.get("/api/docs/v1/public/redoc")
        assert redoc.status_code == 200
        assert "redoc" in redoc.text.lower()

    def test_default_version_root_redirect(self) -> None:
        app, _ = _build_app()
        add_doc_routes_for_app(app)
        client = TestClient(app)

        response = client.get("/api/docs")
        assert response.status_code == 200

    def test_configurable_cdn_urls(self) -> None:
        app, _ = _build_app()
        add_doc_routes_for_app(
            app,
            swagger_js_url="https://example.test/sw.js",
            redoc_js_url="https://example.test/redoc.js",
        )
        client = TestClient(app)

        assert (
            "https://example.test/sw.js"
            in client.get("/api/docs/v1/public/swagger-ui").text
        )
        assert (
            "https://example.test/redoc.js"
            in client.get("/api/docs/v1/public/redoc").text
        )


class TestLocalFilesProvider:
    def test_roundtrip(self, tmp_path: Path) -> None:
        provider = LocalFilesOpenapiProvider(tmp_path)
        assert provider.has_specs() is False

        specs = OpenapiSpecs(
            version_range=(1, 2),
            specs={"v1.public.openapi.json": {"info": {"title": "stored"}}},
        )
        provider.write_specs(specs)

        assert provider.has_specs() is True
        assert provider.get_version_range() == (1, 2)

        loaded = provider.load_openapi(1, "/v1", PUBLIC, " v1")
        assert loaded["info"]["title"] == "stored"

    def test_factory_prefers_populated_local_dir(self, tmp_path: Path) -> None:
        app, _ = _build_app()

        LocalFilesOpenapiProvider(tmp_path).write_specs(
            OpenapiSpecs(version_range=(1, 1), specs={"x.openapi.json": {}})
        )

        provider = openapi_provider_factory(app, tmp_path)
        assert isinstance(provider, LocalFilesOpenapiProvider)

    def test_factory_falls_back_to_app(self, tmp_path: Path) -> None:
        app, _ = _build_app()
        provider = openapi_provider_factory(app, tmp_path)
        assert isinstance(provider, AppOpenapiProvider)
