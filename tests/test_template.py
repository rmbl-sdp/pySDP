"""Unit tests for `pysdp.io.template.substitute_template`.

Ports rSDP's `test_that(".substitute_template ...")` cases in
`tests/testthat/test-internal_resolve.R`.
"""

from __future__ import annotations

import pytest

from pysdp.io.template import substitute_template


def test_handles_vector_year() -> None:
    assert substitute_template("a/{year}/b.tif", year=range(2003, 2006)) == [
        "a/2003/b.tif",
        "a/2004/b.tif",
        "a/2005/b.tif",
    ]


def test_handles_scalar_year() -> None:
    assert substitute_template("a/{year}/b.tif", year=2003) == ["a/2003/b.tif"]


def test_handles_year_and_month_together() -> None:
    assert substitute_template(
        "a/{year}/{month}/b.tif", year=["2003", "2003"], month=["01", "02"]
    ) == ["a/2003/01/b.tif", "a/2003/02/b.tif"]


def test_recycles_scalar_against_vector() -> None:
    assert substitute_template("a/{year}/{month}/b.tif", year="2003", month=["01", "02", "03"]) == [
        "a/2003/01/b.tif",
        "a/2003/02/b.tif",
        "a/2003/03/b.tif",
    ]


def test_returns_template_unchanged_when_nothing_passed() -> None:
    assert substitute_template("a/b.tif") == ["a/b.tif"]


def test_rejects_mismatched_vector_lengths() -> None:
    with pytest.raises(ValueError, match="Mismatched placeholder vector lengths"):
        substitute_template(
            "a/{year}/{month}/b.tif", year=["2003", "2004", "2005"], month=["01", "02"]
        )


def test_accepts_scalar_and_vector_recycled_to_3() -> None:
    """Length-1 vector recycles the same way scalar does."""
    assert substitute_template("a/{year}/{day}.tif", year=[2003], day=["001", "002", "003"]) == [
        "a/2003/001.tif",
        "a/2003/002.tif",
        "a/2003/003.tif",
    ]


def test_handles_day_placeholder() -> None:
    assert substitute_template("a/{year}/{day}.tif", year=2003, day=["001", "002"]) == [
        "a/2003/001.tif",
        "a/2003/002.tif",
    ]
