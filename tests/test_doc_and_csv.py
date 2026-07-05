from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from fastapi_router_variants import RouterDefaults, RouterWrapper
from fastapi_router_variants.doc import load_markdown


def test_load_markdown_returns_empty_without_file() -> None:
    assert load_markdown() == ""


def test_load_markdown_relative_to_directory(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# hello")
    assert load_markdown(relative_to=tmp_path) == "# hello"


def test_load_markdown_relative_to_module_file(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("from module")
    module_file = tmp_path / "routes.py"
    assert load_markdown(relative_to=module_file) == "from module"


def test_load_markdown_custom_filename_and_absolute(tmp_path: Path) -> None:
    target = tmp_path / "custom.md"
    target.write_text("custom")
    assert load_markdown("custom.md", relative_to=tmp_path) == "custom"
    assert load_markdown(target) == "custom"


def test_load_markdown_missing_relative_file_is_empty(tmp_path: Path) -> None:
    assert load_markdown(relative_to=tmp_path) == ""


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

    def test_csv_export_unequal_columns_does_not_crash(self) -> None:
        router = RouterWrapper()

        @router.get_csv_export(
            "/export",
            csv_example=[("name", ("alice", "bob", "carol")), ("age", ("30",))],
        )
        def export() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        example = route.responses[200]["content"]["text/csv"]["example"]
        assert example.splitlines() == ["name;age", "alice;30"]
        assert route.description is not None
        assert "alice" in route.description
        assert "bob" not in route.description


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
