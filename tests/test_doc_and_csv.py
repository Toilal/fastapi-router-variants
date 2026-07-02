import pytest
from fastapi.routing import APIRoute

from fastapi_router_variants import RouterDefaults, RouterWrapper
from fastapi_router_variants.doc import load_markdown


def test_load_markdown_returns_empty_without_file() -> None:
    assert load_markdown() == ""


class TestCsvExport:
    @pytest.fixture(autouse=True)
    def configure_defaults_fixture(self) -> None:
        class CustomDefaults(RouterDefaults):
            version = False

        RouterWrapper.defaults = CustomDefaults()

    def test_csv_export_route(self) -> None:
        router = RouterWrapper()

        @router.get_csv_export(
            "/export",
            csv_example=[("name", ("alice", "bob")), ("age", ("30", ""))],
        )
        def export() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert route.path == "/export"
        assert 200 in route.responses
        assert "text/csv" in route.responses[200]["content"]

        example = route.responses[200]["content"]["text/csv"]["example"]
        assert example.splitlines()[0] == "name;age"
        assert "alice;30" in example

        assert route.description is not None
        assert "**name**" in route.description
        assert "—" in route.description  # empty cell placeholder


class TestExplicitPathVariants:
    @pytest.fixture(autouse=True)
    def configure_defaults_fixture(self) -> None:
        class CustomDefaults(RouterDefaults):
            version = False

        RouterWrapper.defaults = CustomDefaults()

    def test_route_flavors_expand(self) -> None:
        from fastapi_router_variants import Route, RouteFlavor

        router = RouterWrapper()

        specs = Route("/thing") + RouteFlavor(path="/thing-alias")

        @router.get(specs)
        def impl() -> None: ...

        paths = sorted(r.path for r in router.base.routes if isinstance(r, APIRoute))
        assert paths == ["/thing", "/thing-alias"]

    def test_deployment_openapi_extra(self) -> None:
        router = RouterWrapper()

        @router.get("/svc", deployment="worker")
        def impl() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert route.openapi_extra is not None
        assert route.openapi_extra["x-deployment"] == "worker"
