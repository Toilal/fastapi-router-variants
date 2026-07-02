from dataclasses import dataclass

import pytest

from fastapi_router_variants import (
    RouterDefaults,
    RouteRecorder,
    RouterWrapper,
    RouteType,
)
from fastapi_router_variants.versioning import DeploymentSpec, PrefixSpec, VersionSpec


@dataclass(frozen=True, kw_only=True)
class RecordedRoute:
    path: str
    type: RouteType
    methods: tuple[str, ...] | None
    version: VersionSpec | None
    prefix: PrefixSpec | None
    deployment: DeploymentSpec | None
    hidden: bool


class CollectingRecorder(RouteRecorder):
    def __init__(self) -> None:
        self.records: list[RecordedRoute] = []

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
    ) -> None:
        self.records.append(
            RecordedRoute(
                path=path,
                type=type,
                methods=methods,
                version=version,
                prefix=prefix,
                deployment=deployment,
                hidden=hidden,
            )
        )


@pytest.fixture(autouse=True)
def _reset_defaults() -> None:
    RouterWrapper.defaults = RouterDefaults()


class TestRecording:
    def test_records_single_route_without_mounting(self) -> None:
        router = RouterWrapper(version=False)
        recorder = CollectingRecorder()

        with RouterWrapper.recording(recorder):

            @router.get("/foo")
            def impl() -> None: ...

        assert len(recorder.records) == 1
        record = recorder.records[0]
        assert record.path == "/foo"
        assert record.type == "http"
        assert record.methods == ("GET",)
        # No real route was created on the underlying APIRouter.
        assert router.base.routes == []

    def test_records_websocket(self) -> None:
        router = RouterWrapper(version=False)
        recorder = CollectingRecorder()

        with RouterWrapper.recording(recorder):

            @router.websocket("/ws")
            def impl() -> None: ...

        assert len(recorder.records) == 1
        record = recorder.records[0]
        assert record.type == "websocket"
        assert record.methods is None
        assert record.path == "/ws"
        assert router.base.routes == []

    def test_records_every_version_variant(self) -> None:
        router = RouterWrapper()
        recorder = CollectingRecorder()

        with RouterWrapper.recording(recorder):

            @router.get("/items", version=(1, 3))
            def impl() -> None: ...

        paths = sorted(r.path for r in recorder.records)
        assert paths == ["/v1/items", "/v2/items", "/v3/items"]
        assert {r.version for r in recorder.records} == {1, 2, 3}
        assert router.base.routes == []

    def test_records_prefix_variants(self) -> None:
        router = RouterWrapper(version=False, prefix=["/a", "/b"])
        recorder = CollectingRecorder()

        with RouterWrapper.recording(recorder):

            @router.post("/x")
            def impl() -> None: ...

        paths = sorted(r.path for r in recorder.records)
        assert paths == ["/a/x", "/b/x"]
        assert all(r.methods == ("POST",) for r in recorder.records)
        assert router.base.routes == []

    def test_records_hidden_and_deployment(self) -> None:
        router = RouterWrapper(version=False, hidden=True, deployment="metrics")
        recorder = CollectingRecorder()

        with RouterWrapper.recording(recorder):

            @router.get("/metrics")
            def impl() -> None: ...

        record = recorder.records[0]
        assert record.hidden is True
        assert record.deployment == "metrics"

    def test_recording_restores_previous_state(self) -> None:
        router = RouterWrapper(version=False)
        recorder = CollectingRecorder()

        with RouterWrapper.recording(recorder):
            pass

        assert RouterWrapper._route_recorder is None

        # After the context, decorators mount real routes again.
        @router.get("/live")
        def impl() -> None: ...

        assert len(router.base.routes) == 1
        assert recorder.records == []

    def test_nested_recording(self) -> None:
        router = RouterWrapper(version=False)
        outer = CollectingRecorder()
        inner = CollectingRecorder()

        with RouterWrapper.recording(outer):

            @router.get("/a")
            def impl_a() -> None: ...

            with RouterWrapper.recording(inner):

                @router.get("/b")
                def impl_b() -> None: ...

            @router.get("/c")
            def impl_c() -> None: ...

        assert [r.path for r in outer.records] == ["/a", "/c"]
        assert [r.path for r in inner.records] == ["/b"]
