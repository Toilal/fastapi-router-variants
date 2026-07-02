import functools
from typing import TYPE_CHECKING, Literal

import inflect
from fastapi.routing import APIRoute
from pydantic.alias_generators import to_camel, to_snake

if TYPE_CHECKING:
    from fastapi_router_variants.definition import (
        RouterDefaultsProtocol,
        RouterWrapper,
    )

p = inflect.engine()


@functools.cache
def _cached_singular_noun(segment: str) -> str | Literal[False]:
    return p.singular_noun(segment)


class RouterUniqueIdGenerator:
    def __init__(self, router: "RouterWrapper"):
        self.router = router

    def __call__(self, route: APIRoute) -> str:
        return self.generate_unique_id(route)

    @property
    def defaults(self) -> "RouterDefaultsProtocol":
        return self.router.defaults

    @staticmethod
    @functools.cache
    def _sanitize(segment: str) -> str:
        return to_camel(to_snake(segment))

    def _singular(self, segment: str) -> str:
        singular = self.defaults.operation_id_settings.singular_mappings.get(segment)
        if singular is not None:
            return singular

        return _cached_singular_noun(segment) or segment

    def _plural(self, segment: str) -> str:
        plural = self.defaults.operation_id_settings.plural_mappings.get(segment)
        if plural is not None:
            return plural

        return segment

    def _enhance_segments(self, clean_segments: list[str]) -> list[str]:
        segment_exclusions = self.defaults.operation_id_settings.segment_exclusions
        if 0 < len(clean_segments) < 3 and clean_segments[0] in segment_exclusions:
            segment_exclusions = set(segment_exclusions)
            segment_exclusions.remove(clean_segments[0])

        return [
            (
                self._plural(segment)
                if i >= len(clean_segments) - 1
                else self._singular(segment)
            )
            for i, segment in enumerate(clean_segments)
            if not segment.startswith("{")
            and (i >= len(clean_segments) - 1 or segment not in segment_exclusions)
        ]

    def _build_unique_id(self, method: str, path_segments: list[str]) -> str:
        unique_id_segments = [method, *path_segments]

        unique_id_segments = [
            segment[0].upper() + segment[1:] if i > 0 else segment
            for i, segment in enumerate(unique_id_segments)
        ]

        return "".join(unique_id_segments)

    def generate_unique_id(self, route: APIRoute) -> str:
        route_prefix: str | None = None
        route_version: int | None = None
        extra_segments: list[str] | None = None

        if route.openapi_extra is not None:
            route_prefix = route.openapi_extra.get("x-path-prefix")
            route_version = route.openapi_extra.get("x-api-version")
            extra_segments = route.openapi_extra.get("x-unique-id.segments")

        main_segments: list[str] = []
        suffix_segments: list[str] = []

        if extra_segments:
            main_segments.extend(extra_segments)

        for segment in route.path_format.strip("/").split("/"):
            if segment:
                if (
                    self.defaults.prefix is not None
                    and self.defaults.prefix == f"/{segment}"
                ):
                    continue

                if (
                    self.defaults.version_default is not None
                    and f"/v{self.defaults.version_default}" == f"/{segment}"
                ):
                    continue

                if (
                    route_prefix is not None and route_prefix == segment
                ) or route_prefix == f"/{segment}":
                    if route_prefix != self.defaults.prefix:
                        suffix_segments.append(segment)
                elif route_version is not None and f"v{route_version}" == segment:
                    if route_version != self.defaults.version_default:
                        suffix_segments.append(segment)
                else:
                    main_segments.append(segment)

        main_segments = [
            self.defaults.operation_id_settings.segment_aliases.get(x, x)
            for x in main_segments
        ]
        suffix_segments = [
            self.defaults.operation_id_settings.segment_aliases.get(x, x)
            for x in suffix_segments
        ]

        main_segments = self._enhance_segments(main_segments)
        path_segments = main_segments + suffix_segments

        path_segments = [self._sanitize(x) for x in path_segments]

        method = next(iter(route.methods or ())).lower()

        return self._build_unique_id(method, path_segments)
