from fastapi_router_variants.versioning import (
    Disabled,
    Route,
    api_version_from_path,
    normalize_version_spec,
    prefixed_routes,
    version_range_from_spec,
    versioned_routes,
)


class TestVersionRangeFromSpec:
    def test_simple_version(self) -> None:
        assert version_range_from_spec((2, 7), 4) == ((4, 7), True, False)

    def test_version_range(self) -> None:
        assert version_range_from_spec((2, 7), (4, 6)) == ((4, 6), True, True)

    def test_false(self) -> None:
        assert version_range_from_spec((2, 7), False) == (None, False, False)

    def test_true(self) -> None:
        assert version_range_from_spec((2, 7), True) == ((2, 7), False, False)

    def test_outside_range_upper(self) -> None:
        assert version_range_from_spec((1, 1), 3) == ((3, 3), True, False)

    def test_outside_range_lower(self) -> None:
        assert version_range_from_spec((4, 4), 2) == ((2, 4), True, False)

    def test_disabled(self) -> None:
        assert version_range_from_spec((1, 3), Disabled) == (None, False, False)


class TestNormalizeVersionSpec:
    def test_none(self) -> None:
        assert normalize_version_spec(None) is None

    def test_disabled(self) -> None:
        assert normalize_version_spec(Disabled) is None

    def test_true(self) -> None:
        assert normalize_version_spec(True) == (None, None)

    def test_false(self) -> None:
        assert normalize_version_spec(False) is None

    def test_int(self) -> None:
        assert normalize_version_spec(3) == (3, None)

    def test_tuple(self) -> None:
        assert normalize_version_spec((2, 4)) == (2, 4)


class TestApiVersionFromPath:
    def test_leading(self) -> None:
        assert api_version_from_path("/v2/users") == 2

    def test_middle(self) -> None:
        assert api_version_from_path("/api/v12/users") == 12

    def test_trailing(self) -> None:
        assert api_version_from_path("/api/v3") == 3

    def test_absent(self) -> None:
        assert api_version_from_path("/api/users") is None

    def test_not_a_version_segment(self) -> None:
        assert api_version_from_path("/vehicles") is None


class TestVersionedRoutes:
    def test_expands_open_range(self) -> None:
        result = versioned_routes([Route("/foo")], (2, 4), True)
        assert [(r.path, r.version, r.deprecated) for r in result] == [
            ("/v2/foo", 2, None),
            ("/v3/foo", 3, None),
            ("/v4/foo", 4, None),
        ]

    def test_closed_range_deprecates_top(self) -> None:
        result = versioned_routes([Route("/foo")], (1, 5), (2, 3))
        assert [(r.path, r.version, r.deprecated) for r in result] == [
            ("/v2/foo", 2, None),
            ("/v3/foo", 3, True),
        ]

    def test_version_deprecated_threshold(self) -> None:
        result = versioned_routes([Route("/foo")], (1, 3), True, version_deprecated=2)
        assert [(r.path, r.deprecated) for r in result] == [
            ("/v1/foo", True),
            ("/v2/foo", True),
            ("/v3/foo", None),
        ]

    def test_route_version_false_is_untouched(self) -> None:
        result = versioned_routes([Route("/foo", version=False)], (1, 3), True)
        assert [(r.path, r.version) for r in result] == [("/foo", False)]


class TestPrefixedRoutes:
    def test_single_prefix(self) -> None:
        result = prefixed_routes([Route("/foo")], "/api")
        assert [(r.path, r.prefix) for r in result] == [("/api/foo", "/api")]

    def test_multiple_prefixes(self) -> None:
        result = prefixed_routes([Route("/foo")], ("/api", "/admin"))
        assert [(r.path, r.prefix) for r in result] == [
            ("/api/foo", "/api"),
            ("/admin/foo", "/admin"),
        ]

    def test_prefix_false_untouched(self) -> None:
        result = prefixed_routes([Route("/foo")], False)
        assert [r.path for r in result] == ["/foo"]

    def test_route_prefix_wins(self) -> None:
        result = prefixed_routes([Route("/foo", prefix="/own")], "/api")
        assert [r.path for r in result] == ["/own/foo"]
