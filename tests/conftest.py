from collections.abc import Iterator

import pytest

from fastapi_router_variants import RouterWrapper


@pytest.fixture(autouse=True)
def _reset_router_wrapper() -> Iterator[None]:
    """Restore the shared ``RouterWrapper`` class state after every test."""
    yield
    RouterWrapper.reset_defaults()
