import re

import pytest

from fastapi_router_variants.specs import (
    And,
    ApiVersion,
    ChildReference,
    DefaultsReference,
    Methods,
    No,
    Not,
    Or,
    Paths,
    Public,
    RouterReference,
    Unset,
    UnsetResultError,
    WithoutDefaults,
    Yes,
    resolve,
)


class TestSpecs:
    def test_methods_spec(self) -> None:
        router_spec = Methods("GET")

        assert resolve(router_spec=router_spec, path="", methods=["GET"]) is True
        assert resolve(router_spec=router_spec, path="", methods=["POST"]) is False

    def test_methods_all(self) -> None:
        assert resolve(router_spec=Methods(Methods.ALL), methods=["ANY"]) is True

    def test_paths_spec(self) -> None:
        router_spec = Paths(re.compile("/foo/.+"), re.compile("/bar/.+"))

        assert resolve(router_spec=router_spec, path="/foo/abc") is True
        assert resolve(router_spec=router_spec, path="/hello/abc") is False
        assert resolve(router_spec=router_spec, path="/bar/abc") is True

    def test_paths_startswith_endswith_contains(self) -> None:
        assert (
            resolve(router_spec=Paths("/foo", startswith=True), path="/foo/x") is True
        )
        assert resolve(router_spec=Paths("/x", endswith=True), path="/foo/x") is True
        assert resolve(router_spec=Paths("oo"), path="/foo/x") is True
        assert resolve(router_spec=Paths("/no"), path="/foo/x") is False

    def test_and_spec(self) -> None:
        router_spec = And(Methods("GET"), Methods("POST"))

        assert resolve(router_spec=router_spec, path="", methods=["GET"]) is False
        assert resolve(router_spec=router_spec, path="", methods=["POST"]) is False

    def test_or_spec(self) -> None:
        router_spec = Or(Methods("GET"), Methods("POST"))

        assert resolve(router_spec=router_spec, path="", methods=["GET"]) is True
        assert resolve(router_spec=router_spec, path="", methods=["POST"]) is True
        assert resolve(router_spec=router_spec, path="", methods=["PATCH"]) is False

    def test_not_spec(self) -> None:
        assert resolve(router_spec=Not(Methods("GET")), methods=["POST"]) is True
        assert resolve(router_spec=Not(Methods("GET")), methods=["GET"]) is False

    def test_not_unset_stays_none(self) -> None:
        with pytest.raises(UnsetResultError):
            resolve(router_spec=Not(Unset()), methods=["GET"])

    def test_bool_inside_spec_container(self) -> None:
        router_spec = Or(Methods("GET"), True)

        assert resolve(router_spec=router_spec, path="", methods=["PATCH"]) is True

    def test_api_version_and_public(self) -> None:
        spec = And(ApiVersion(2), Public())

        assert (
            resolve(
                router_spec=spec, openapi_extra={"x-api-version": 2, "x-public": True}
            )
            is True
        )
        assert resolve(router_spec=spec, openapi_extra={"x-api-version": 2}) is False

    def test_spec_defaults(self) -> None:
        default_spec = Methods("GET")

        assert resolve(default_spec=default_spec, path="", methods=["GET"]) is True
        assert resolve(default_spec=default_spec, path="", methods=["POST"]) is False

    def test_spec_defaults_without_defaults(self) -> None:
        default_spec = Methods("GET")
        router_spec = Methods("POST")

        assert (
            resolve(
                default_spec=default_spec, router_spec=router_spec, methods=["POST"]
            )
            is True
        )
        assert (
            resolve(default_spec=default_spec, router_spec=router_spec, methods=["GET"])
            is False
        )

    def test_spec_defaults_reference(self) -> None:
        default_spec = Methods("GET")
        router_spec = Or(Methods("POST"), DefaultsReference())

        assert (
            resolve(default_spec=default_spec, router_spec=router_spec, methods=["GET"])
            is True
        )
        assert (
            resolve(
                default_spec=default_spec, router_spec=router_spec, methods=["POST"]
            )
            is True
        )
        assert (
            resolve(
                default_spec=default_spec, router_spec=router_spec, methods=["PATCH"]
            )
            is False
        )

    def test_spec_child_reference(self) -> None:
        default_spec = Or(Methods("POST"), ChildReference())
        router_spec = Methods("GET")

        assert (
            resolve(default_spec=default_spec, router_spec=router_spec, methods=["GET"])
            is True
        )
        assert (
            resolve(
                default_spec=default_spec, router_spec=router_spec, methods=["POST"]
            )
            is True
        )

    def test_router_without_defaults(self) -> None:
        default_spec = Or(Methods("POST"), RouterReference())
        router_spec = WithoutDefaults()

        with pytest.raises(UnsetResultError):
            resolve(default_spec=default_spec, router_spec=router_spec, methods=["GET"])

        assert (
            resolve(
                default_spec=default_spec,
                router_spec=And(Yes(), router_spec),
                methods=["GET"],
            )
            is True
        )
        assert (
            resolve(
                default_spec=default_spec,
                router_spec=And(No(), router_spec),
                methods=["GET"],
            )
            is False
        )
        assert (
            resolve(
                default_spec=default_spec,
                router_spec=router_spec,
                methods=["PATCH"],
                route_spec=True,
            )
            is True
        )

    def test_router_without_defaults_and(self) -> None:
        default_spec = Or(Methods("POST"), RouterReference())
        router_spec = And(WithoutDefaults(), Methods("GET"))

        assert (
            resolve(default_spec=default_spec, router_spec=router_spec, methods=["GET"])
            is True
        )
        assert (
            resolve(
                default_spec=default_spec, router_spec=router_spec, methods=["POST"]
            )
            is False
        )

    def test_defaults_override_false(self) -> None:
        assert (
            resolve(default_spec=Methods("GET"), router_spec=False, methods=["GET"])
            is False
        )

    def test_defaults_override_true(self) -> None:
        assert (
            resolve(default_spec=Methods("GET"), router_spec=True, methods=["PATCH"])
            is True
        )

    def test_route_spec_override(self) -> None:
        default_spec = Methods("GET")

        assert (
            resolve(default_spec=default_spec, methods=["GET"], route_spec=False)
            is False
        )
        assert (
            resolve(default_spec=default_spec, methods=["POST"], route_spec=True)
            is True
        )

    def test_many_path_overrides(self) -> None:
        default_spec = And(Methods("GET"), ChildReference())
        router_spec = False
        public = Not(Paths("/internal", startswith=True))

        assert (
            resolve(
                default_spec=default_spec,
                router_spec=router_spec,
                path="/api",
                methods=["GET"],
                route_spec=public,
            )
            is True
        )
        assert (
            resolve(
                default_spec=default_spec,
                router_spec=router_spec,
                path="/internal",
                methods=["GET"],
                route_spec=public,
            )
            is False
        )
        assert (
            resolve(
                default_spec=default_spec,
                router_spec=router_spec,
                path="/api",
                methods=["POST"],
                route_spec=public,
            )
            is False
        )
