from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute
from starlette.status import HTTP_204_NO_CONTENT
from starlette.testclient import TestClient

from fastapi_router_variants import (
    Route,
    RouterDefaults,
    RouterWrapper,
    RouterWrapperError,
    collect_app_routes,
)


def route_data(route: APIRoute) -> tuple[str, int | None, bool | None]:
    return (
        route.path,
        route.openapi_extra.get("x-api-version") if route.openapi_extra else None,
        route.deprecated,
    )


def router_data(router: RouterWrapper) -> list[tuple[str, int | None, bool | None]]:
    return [route_data(r) for r in router.base.routes if isinstance(r, APIRoute)]


class TestRouterWrapper:
    class TestPrefix:
        class TestWithDefaultsPre:
            @pytest.fixture(autouse=True)
            def configure_defaults_fixture(self) -> None:
                class CustomDefaults(RouterDefaults):
                    prefix = "/pre"

                RouterWrapper.defaults = CustomDefaults()
                return

            def test_empty(self) -> None:
                router = RouterWrapper(version=False)

                @router.get("/foo")
                def impl() -> None: ...

                assert router_data(router) == [("/pre/foo", None, None)]

        class TestWithDefaultsTrue:
            @pytest.fixture(autouse=True)
            def configure_defaults_fixture(self) -> None:
                class CustomDefault(RouterDefaults):
                    prefix = True

                RouterWrapper.defaults = CustomDefault()
                return

            def test_empty(self) -> None:
                router = RouterWrapper(version=False)

                with pytest.raises(RouterWrapperError):

                    @router.get("foo")
                    def impl() -> None: ...

    class TestVersion:
        class TestWithDefaults:
            @pytest.fixture(autouse=True)
            def configure_defaults_fixture(self) -> None:
                class CustomDefault(RouterDefaults):
                    prefix = False
                    version = True
                    version_range = (2, 7)
                    version_deprecated = 3

                RouterWrapper.defaults = CustomDefault()
                return

            def test_missing_version_raise_error(self) -> None:
                router = RouterWrapper()

                with pytest.raises(RouterWrapperError):

                    @router.get("foo")
                    def impl() -> None: ...

            def test_version_int(self) -> None:
                router = RouterWrapper()

                @router.get("/foo", version=4)
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/v7/foo", 7, None),
                    ("/v6/foo", 6, None),
                    ("/v5/foo", 5, None),
                    ("/v4/foo", 4, None),
                ]

            def test_version_closed(self) -> None:
                router = RouterWrapper()

                @router.get("/foo", version=(4, 6))
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/v6/foo", 6, True),
                    ("/v5/foo", 5, None),
                    ("/v4/foo", 4, None),
                ]

            def test_version_closed_many_paths(self) -> None:
                router = RouterWrapper()

                @router.get(("/foo", "/bar"), version=(4, 6))
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/v6/bar", 6, True),
                    ("/v5/bar", 5, None),
                    ("/v4/bar", 4, None),
                    ("/v6/foo", 6, True),
                    ("/v5/foo", 5, None),
                    ("/v4/foo", 4, None),
                ]

            def test_advanced_version_false(self) -> None:
                router = RouterWrapper()

                @router.get(("/foo", Route("/bar", version=False)), version=(4, 6))
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/bar", None, None),
                    ("/v6/foo", 6, True),
                    ("/v5/foo", 5, None),
                    ("/v4/foo", 4, None),
                ]

            def test_advanced_version_set(self) -> None:
                router = RouterWrapper()

                @router.get(
                    ("/foo", Route("/bar", version=(1, 1), deprecated=False)),
                    version=(4, 6),
                )
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/v1/bar", 1, None),
                    ("/v6/foo", 6, True),
                    ("/v5/foo", 5, None),
                    ("/v4/foo", 4, None),
                ]

            def test_advanced_version_range(self) -> None:
                router = RouterWrapper()

                @router.get(("/foo", Route("/bar", version=(None, 3))), version=(4, 6))
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/v3/bar", 3, True),
                    ("/v2/bar", 2, True),
                    ("/v6/foo", 6, True),
                    ("/v5/foo", 5, None),
                    ("/v4/foo", 4, None),
                ]

            def test_version_false(self) -> None:
                router = RouterWrapper()

                @router.get("/foo", version=False)
                def impl() -> None: ...

                assert router_data(router) == [("/foo", None, None)]

            def test_version_true(self) -> None:
                router = RouterWrapper()

                @router.get("/foo", version=True)
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/v7/foo", 7, None),
                    ("/v6/foo", 6, None),
                    ("/v5/foo", 5, None),
                    ("/v4/foo", 4, None),
                    ("/v3/foo", 3, True),
                    ("/v2/foo", 2, True),
                ]

        class TestWithoutDefaults:
            @pytest.fixture(autouse=True)
            def configure_defaults_fixture(self) -> None:
                class CustomDefaults(RouterDefaults): ...

                RouterWrapper.defaults = CustomDefaults()
                return

            def test_fixed_version(self) -> None:
                router = RouterWrapper()

                @router.get("/foo", version=(5, 5))
                def impl() -> None: ...

                assert router_data(router) == [("/v5/foo", 5, True)]

            def test_fixed_version_deprecated_false(self) -> None:
                router = RouterWrapper()

                @router.get("/foo", version=(5, 5), deprecated=False)
                def impl() -> None: ...

                assert router_data(router) == [("/v5/foo", 5, None)]

        class TestCombined:
            @pytest.fixture(autouse=True)
            def configure_defaults_fixture(self) -> None:
                class CustomDefaults(RouterDefaults):
                    prefix = "/api"
                    version_range = (2, 4)
                    version_deprecated = 3

                RouterWrapper.defaults = CustomDefaults()
                return

            def test_versioned_and_prefixed(self) -> None:
                router = RouterWrapper()

                @router.get("/groups/{group_id}/alerts", version=2)
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/api/v4/groups/{group_id}/alerts", 4, None),
                    ("/api/v3/groups/{group_id}/alerts", 3, True),
                    ("/api/v2/groups/{group_id}/alerts", 2, True),
                ]

            def test_multiple_paths_versioned(self) -> None:
                router = RouterWrapper()

                @router.get(
                    ["/groups/{group_id}/vehicle_list", "/groups/{group_id}/vehicles"],
                    version=(2, 3),
                )
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/api/v3/groups/{group_id}/vehicles", 3, True),
                    ("/api/v2/groups/{group_id}/vehicles", 2, True),
                    ("/api/v3/groups/{group_id}/vehicle_list", 3, True),
                    ("/api/v2/groups/{group_id}/vehicle_list", 2, True),
                ]

            def test_router_prefix_override(self) -> None:
                router = RouterWrapper(prefix="/other-api")

                @router.post(
                    [
                        Route("/devices/{device_id}/duties", version=(1, 1)),
                        "/devices/{device_id}/duties",
                    ],
                    version=3,
                )
                def impl() -> None: ...

                assert router_data(router) == [
                    ("/other-api/v4/devices/{device_id}/duties", 4, None),
                    ("/other-api/v3/devices/{device_id}/duties", 3, True),
                    ("/other-api/v1/devices/{device_id}/duties", 1, True),
                ]


class TestHidden:
    def test_default_router_keeps_routes_in_schema(self) -> None:
        router = RouterWrapper(version=False)

        @router.get("/foo")
        def impl() -> None: ...

        routes = [r for r in router.base.routes if isinstance(r, APIRoute)]
        assert router.hidden is False
        assert all(r.include_in_schema for r in routes)

    def test_hidden_router_excludes_routes_from_schema(self) -> None:
        router = RouterWrapper(version=False, hidden=True)

        @router.get("/foo")
        def impl() -> None: ...

        routes = [r for r in router.base.routes if isinstance(r, APIRoute)]
        assert router.hidden is True
        assert routes
        assert all(not r.include_in_schema for r in routes)

    def test_hidden_routes_absent_from_openapi(self) -> None:
        router = RouterWrapper(version=False, hidden=True)

        @router.get("/foo")
        def impl() -> None: ...

        schema = get_openapi(title="t", version="1", routes=router.base.routes)
        assert schema.get("paths", {}) == {}


class TestRegistrationAndDispatch:
    @pytest.fixture(autouse=True)
    def configure_defaults_fixture(self) -> None:
        class CustomDefaults(RouterDefaults):
            version = False

        RouterWrapper.defaults = CustomDefaults()
        return

    def test_all_methods_register(self) -> None:
        router = RouterWrapper()

        @router.get("/items")
        def get_items() -> list[int]:
            return [1]

        @router.post("/items")
        def create_item() -> dict[str, int]:
            return {"id": 1}

        @router.put("/items/{item_id}")
        def replace_item(item_id: int) -> dict[str, int]:
            return {"id": item_id}

        @router.patch("/items/{item_id}")
        def update_item(item_id: int) -> dict[str, int]:
            return {"id": item_id}

        @router.delete("/items/{item_id}")
        def delete_item(item_id: int) -> None: ...

        methods = {
            (r.path, next(iter(r.methods or ())))
            for r in router.base.routes
            if isinstance(r, APIRoute)
        }
        assert methods == {
            ("/items", "GET"),
            ("/items", "POST"),
            ("/items/{item_id}", "PUT"),
            ("/items/{item_id}", "PATCH"),
            ("/items/{item_id}", "DELETE"),
        }

    def test_dispatch_over_testclient(self) -> None:
        router = RouterWrapper()

        @router.get("/ping")
        def ping() -> dict[str, str]:
            return {"pong": "ok"}

        app = FastAPI()
        app.include_router(router.base)

        client = TestClient(app)
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"pong": "ok"}

    def test_none_return_yields_204(self) -> None:
        router = RouterWrapper()

        @router.delete("/thing")
        def remove() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert route.status_code == HTTP_204_NO_CONTENT

    def test_websocket_registration(self) -> None:
        router = RouterWrapper()

        @router.websocket("/ws")
        async def ws() -> None: ...

        ws_routes = [r for r in router.base.routes if isinstance(r, WebSocketRoute)]
        assert [r.path for r in ws_routes] == ["/ws"]

    def test_include_router_merges_routes(self) -> None:
        parent = RouterWrapper()
        child = RouterWrapper()

        @child.get("/child")
        def child_impl() -> None: ...

        parent.include_router(child)

        app = FastAPI()
        app.include_router(parent.base)

        paths = {r.path for r in collect_app_routes(app) if isinstance(r, APIRoute)}
        assert "/child" in paths


class TestRolesAndFeatures:
    @pytest.fixture(autouse=True)
    def configure_defaults_fixture(self) -> None:
        class CustomDefaults(RouterDefaults):
            version = False

        RouterWrapper.defaults = CustomDefaults()
        return

    def test_require_roles_adds_dependency_and_description(self) -> None:
        def require_roles(roles: set[str]) -> Callable[[], None]:
            def dep() -> None: ...

            return dep

        RouterWrapper.require_roles = staticmethod(require_roles)

        router = RouterWrapper()

        @router.get("/secure", require_roles={"admin"})
        def secure() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert len(route.dependencies) == 1
        assert "Role needed: admin" in (route.description or "")

    def test_require_features_adds_dependency_and_description(self) -> None:
        def require_features(*features: str) -> Callable[[], None]:
            def dep() -> None: ...

            return dep

        RouterWrapper.require_features = staticmethod(require_features)

        router = RouterWrapper()

        @router.get("/flagged", require_features={"beta"})
        def flagged() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert len(route.dependencies) == 1
        assert "Feature needed: beta" in (route.description or "")


class MyError(Exception):
    pass


class TestAutodocHttpErrors:
    def test_disabled_by_default(self) -> None:
        @dataclass(frozen=True)
        class Defaults(RouterDefaults):
            version = False

        RouterWrapper.defaults = Defaults()

        router = RouterWrapper()

        @router.get("/x", exceptions={MyError})
        def impl() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert 418 not in route.responses

    def test_hooks_document_errors(self) -> None:
        @dataclass(frozen=True)
        class Defaults(RouterDefaults):
            version = False
            autodoc_http_errors = True
            http_error_base = MyError
            exception_scanner = staticmethod(lambda fn: {MyError})
            error_schema_builder = staticmethod(
                lambda excs: {418: {"description": "teapot"}}
            )

        RouterWrapper.defaults = Defaults()

        router = RouterWrapper()

        @router.get("/x")
        def impl() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert 418 in route.responses

    def test_explicit_exceptions_feed_builder(self) -> None:
        seen: dict[str, set[type]] = {}

        def builder(excs: set[type]) -> dict[int, dict[str, str]]:
            seen["excs"] = excs
            return {400: {"description": "bad"}}

        @dataclass(frozen=True)
        class Defaults(RouterDefaults):
            version = False
            autodoc_http_errors = True
            http_error_base = MyError
            error_schema_builder = staticmethod(builder)

        RouterWrapper.defaults = Defaults()

        router = RouterWrapper()

        @router.get("/x", exceptions={MyError})
        def impl() -> None: ...

        route = next(r for r in router.base.routes if isinstance(r, APIRoute))
        assert 400 in route.responses
        assert seen["excs"] == {MyError}
