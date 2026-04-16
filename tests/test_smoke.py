"""Smoke tests: the package imports and its public API is reachable.

These tests guard Phase 0 scaffolding. They do NOT call into any real
implementation (which lands in later phases); they only confirm that the
module graph is coherent and that the public surface matches SPEC.md §4.5.
"""

from __future__ import annotations

import pytest


def test_import_package() -> None:
    import pysdp

    assert pysdp.__version__


def test_public_api_exposed() -> None:
    import pysdp

    expected = {
        "DOMAINS",
        "RELEASES",
        "SDP_CRS",
        "TIMESERIES_TYPES",
        "TYPES",
        "__version__",
        "download",
        "extract_points",
        "extract_polygons",
        "get_catalog",
        "get_metadata",
        "open_raster",
        "open_stack",
    }
    assert expected.issubset(set(pysdp.__all__))
    for name in expected:
        assert hasattr(pysdp, name), f"pysdp is missing public name: {name}"


def test_constants_values() -> None:
    from pysdp import DOMAINS, RELEASES, SDP_CRS, TIMESERIES_TYPES, TYPES

    assert SDP_CRS == "EPSG:32613"
    assert "UG" in DOMAINS and "GMUG" in DOMAINS
    assert "Vegetation" in TYPES
    assert "Release5" in RELEASES
    assert set(TIMESERIES_TYPES) == {"Single", "Yearly", "Seasonal", "Monthly", "Daily"}


@pytest.mark.parametrize(
    ("fn_name", "args"),
    [
        # get_catalog + get_metadata implemented in Phase 1 (see test_catalog.py)
        # open_raster + open_stack implemented in Phase 3 (see test_raster.py)
        ("extract_points", (None, None)),
        ("extract_polygons", (None, None)),
        ("download", ()),
    ],
)
def test_unimplemented_stubs_raise_not_implemented(fn_name: str, args: tuple[object, ...]) -> None:
    """Stubs for not-yet-implemented phases raise NotImplementedError."""
    import pysdp

    fn = getattr(pysdp, fn_name)
    with pytest.raises(NotImplementedError):
        fn(*args)
