from collections.abc import Iterable
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from fastapi_router_variants import (
    RouterDefaultsProtocol,
    RouterOperationIdSettings,
    RouterUniqueIdGenerator,
    RouterWrapper,
    collect_app_routes,
)


@dataclass(frozen=True)
class SampleRouterDefaults(RouterDefaultsProtocol):
    prefix = "/api"
    version = True
    version_default = 2
    version_range = (1, 2)
    operation_id_settings = RouterOperationIdSettings(
        segment_aliases={"other-api": "other"},
        plural_mappings={"no-plural": "no-plurals"},
        segment_exclusions={"groups"},
    )


@pytest.fixture
def sample_router_type() -> Iterable[type[RouterWrapper]]:
    class SampleRouter(RouterWrapper):
        defaults: RouterDefaultsProtocol = SampleRouterDefaults()

        @classmethod
        def reset_defaults(cls) -> None:
            cls.defaults = SampleRouterDefaults()

    return SampleRouter


def _route(path: str, prefix: str, version: int) -> APIRoute:
    return APIRoute(
        path,
        endpoint=lambda x: None,
        methods=["GET"],
        openapi_extra={"x-path-prefix": prefix, "x-api-version": version},
    )


def test_segment_exclusions(sample_router_type: type[RouterWrapper]) -> None:
    router = sample_router_type(version=(1, 2))
    generator = RouterUniqueIdGenerator(router)

    assert (
        generator.generate_unique_id(
            _route("/api/v1/groups/{group_id}/config", "/api", 1)
        )
        == "getConfigV1"
    )
    assert (
        generator.generate_unique_id(
            _route("/api/v2/groups/{group_id}/config", "/api", 1)
        )
        == "getConfig"
    )
    assert (
        generator.generate_unique_id(_route("/api/v1/groups/{group_id}", "/api", 1))
        == "getGroupV1"
    )
    assert (
        generator.generate_unique_id(_route("/api/v2/groups/{group_id}", "/api", 2))
        == "getGroup"
    )
    assert (
        generator.generate_unique_id(_route("/api/v1/groups", "/api", 1))
        == "getGroupsV1"
    )
    assert (
        generator.generate_unique_id(_route("/api/v2/groups", "/api", 2)) == "getGroups"
    )


def test_suffix_behavior(sample_router_type: type[RouterWrapper]) -> None:
    router = sample_router_type(prefix=("/api", "/other-api"), version=(1, 2))
    generator = RouterUniqueIdGenerator(router)

    assert (
        generator.generate_unique_id(_route("/api/v1/users/{id}/posts", "/api", 1))
        == "getUserPostsV1"
    )
    assert (
        generator.generate_unique_id(_route("/api/v2/users/{id}/posts", "/api", 2))
        == "getUserPosts"
    )
    assert (
        generator.generate_unique_id(_route("/api/v3/users/{id}/posts", "/api", 3))
        == "getUserPostsV3"
    )
    assert (
        generator.generate_unique_id(
            _route("/other-api/v1/users/{id}/posts", "/other-api", 1)
        )
        == "getUserPostsOtherV1"
    )
    assert (
        generator.generate_unique_id(
            _route("/other-api/v2/users/{id}/posts", "/other-api", 2)
        )
        == "getUserPostsOther"
    )


def test_generated_ids_are_unique(sample_router_type: type[RouterWrapper]) -> None:
    router = sample_router_type(prefix=("/api", "/other-api"), version=(1, 2))

    @router.get("/users")
    async def get_users() -> None: ...

    @router.get("/users/{id}")
    async def get_user(id: int) -> None: ...

    @router.get("/users/{id}/posts")
    async def get_user_posts(id: int) -> None: ...

    @router.post("/users")
    async def create_user() -> None: ...

    @router.put("/posts/{id}")
    async def set_post(id: int) -> None: ...

    @router.get("/no-plural")
    async def get_no_plural() -> None: ...

    app = FastAPI()
    app.include_router(router.base)

    unique_ids = [
        r.unique_id for r in collect_app_routes(app) if isinstance(r, APIRoute)
    ]
    assert unique_ids
    assert len(unique_ids) == len(set(unique_ids))
