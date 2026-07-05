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
    add_redirect_route,
    collect_app_routes,
    openapi_provider_factory,
)
from fastapi_router_variants.openapi import (
    DEFAULT_CATEGORIES,
    INTERNAL_OPENAPI_EXTENSIONS,
)

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

    def test_internal_extensions_stripped_from_served_spec(self) -> None:
        app, _ = _build_app()
        provider = AppOpenapiProvider(app, collect_app_routes(app))

        spec = provider.load_openapi(1, "/v1", INTERNAL, " v1")
        operation = spec["paths"]["/api/v1/public"]["get"]

        for extension in INTERNAL_OPENAPI_EXTENSIONS:
            assert extension not in operation

    def test_get_versions_reports_only_present_versions(self) -> None:
        @dataclass(frozen=True)
        class SparseDefaults(RouterDefaults):
            prefix = "/api"
            version = True
            version_range = (1, 3)
            version_default = 1

        class SparseRouter(RouterWrapper):
            defaults = SparseDefaults()

            @classmethod
            def reset_defaults(cls) -> None:
                cls.defaults = SparseDefaults()

        router = SparseRouter()

        @router.get("/a", version=(1, 1))
        def a_ep() -> dict[str, str]:
            return {}

        @router.get("/b", version=(3, 3))
        def b_ep() -> dict[str, str]:
            return {}

        app = FastAPI()
        app.include_router(router.base)
        provider = AppOpenapiProvider(app, collect_app_routes(app))

        assert provider.get_versions() == {1, 3}
        assert provider.get_version_range() == (1, 3)

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

    @staticmethod
    def _build_sparse_app(default_version: int) -> FastAPI:
        @dataclass(frozen=True)
        class SparseDefaults(RouterDefaults):
            prefix = "/api"
            version = True
            version_range = (1, 3)
            version_default = default_version

        class SparseRouter(RouterWrapper):
            defaults = SparseDefaults()

            @classmethod
            def reset_defaults(cls) -> None:
                cls.defaults = SparseDefaults()

        router = SparseRouter()

        @router.get("/a", version=(1, 1))
        def a_ep() -> dict[str, str]:
            return {}

        @router.get("/b", version=(3, 3))
        def b_ep() -> dict[str, str]:
            return {}

        app = FastAPI()
        app.include_router(router.base)
        app.router_wrapper_class = SparseRouter  # type: ignore[attr-defined]
        return app

    def test_absent_versions_get_no_doc_routes(self) -> None:
        app = self._build_sparse_app(default_version=1)
        add_doc_routes_for_app(app)
        client = TestClient(app)

        assert client.get("/api/docs/v1/public/openapi.json").status_code == 200
        assert client.get("/api/docs/v3/public/openapi.json").status_code == 200
        assert client.get("/api/docs/v2/public/openapi.json").status_code == 404
        assert client.get("/api/docs").status_code == 200

    def test_default_version_in_gap_still_serves_landing(self) -> None:
        app = self._build_sparse_app(default_version=2)
        add_doc_routes_for_app(app)
        client = TestClient(app)

        # v2 has no routes but is the default, so its landing must resolve.
        assert client.get("/api/docs").status_code == 200
        assert client.get("/api/docs/v2/public/openapi.json").status_code == 200

    def test_redirect_routes_are_hidden_from_schema(self) -> None:
        app = FastAPI()
        add_redirect_route(app, "/from", "/to")

        route = next(r for r in app.routes if getattr(r, "path", None) == "/from")
        assert route.include_in_schema is False

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


class TestDocRedirects:
    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("/api/docs", "/api/docs/v1"),
            ("/api/docs/v1", "/api/docs/v1/public"),
            ("/api/docs/v2", "/api/docs/v2/public"),
            ("/api/docs/public", "/api/docs/v1/public"),
            ("/api/docs/swagger-ui", "/api/docs/v1/public/swagger-ui"),
            ("/api/docs/redoc", "/api/docs/v1/public/redoc"),
            ("/api/docs/openapi.json", "/api/docs/v1/public/openapi.json"),
            ("/api", "/api/docs"),
            ("/", "/api/docs"),
        ],
    )
    def test_redirect_targets(self, source: str, target: str) -> None:
        app, _ = _build_app()
        add_doc_routes_for_app(app)
        client = TestClient(app, follow_redirects=False)

        response = client.get(source)
        assert response.status_code == 307
        assert response.headers["location"] == target

    def test_root_redirect_chain_reaches_swagger(self) -> None:
        app, _ = _build_app()
        add_doc_routes_for_app(app)
        client = TestClient(app)

        response = client.get("/api/docs")
        assert response.status_code == 200
        assert str(response.url).endswith("/api/docs/v1/public/swagger-ui")
        assert "swagger-ui" in response.text.lower()


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

    def test_get_versions_is_none_without_enumeration(self, tmp_path: Path) -> None:
        assert LocalFilesOpenapiProvider(tmp_path).get_versions() is None

    def test_malformed_version_range_raises(self, tmp_path: Path) -> None:
        provider = LocalFilesOpenapiProvider(tmp_path)
        provider.write_specs(
            OpenapiSpecs(version_range=(1, 2), specs={"x.openapi.json": {}})
        )
        provider.version_range_file.write_text("[1, 2, 3]")

        with pytest.raises(ValueError, match="Malformed version range"):
            provider.get_version_range()
