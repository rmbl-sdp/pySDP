"""Tests for `pysdp.issues` and the `with_issue_counts=` integrations.

Ports rSDP's ``tests/testthat/test-sdp_issues.R``. Covers:

- ``report_issue()`` URL building, type validation, unknown-CatalogID warning
- ``_issues_to_dataframe()`` label parsing + PR filtering
- ``known_issues()`` cache hit / miss / expiration / offline fallback
- ``open_issue_counts()`` aggregation
- ``get_catalog(with_issue_counts=True)`` attaches ``OpenIssues``
- ``browse(with_issue_counts=True)`` renders the "⚠ N open issue" badge
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pandas as pd
import pytest
import responses

import pysdp
from pysdp import issues as issues_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect XDG_CACHE_HOME so tests never touch the real user cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)


def _make_issue(
    number: int,
    *,
    cat: str | None = "R4D004",
    type_: str | None = "incorrect-values",
    severity: str | None = "high",
    status: str | None = "investigating",
    title: str = "Bad pixels in 2019",
    is_pr: bool = False,
) -> dict[str, object]:
    labels: list[dict[str, str]] = []
    if cat is not None:
        labels.append({"name": f"product:{cat}"})
    if type_ is not None:
        labels.append({"name": f"type:{type_}"})
    if severity is not None:
        labels.append({"name": f"severity:{severity}"})
    if status is not None:
        labels.append({"name": f"status:{status}"})
    issue: dict[str, object] = {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/rmbl-sdp/sdp-products/issues/{number}",
        "created_at": "2026-05-15T00:00:00Z",
        "updated_at": "2026-05-16T00:00:00Z",
        "labels": labels,
    }
    if is_pr:
        issue["pull_request"] = {"url": "https://example.com/pr"}
    return issue


# ---------------------------------------------------------------------------
# report_issue: URL building + validation
# ---------------------------------------------------------------------------


class TestReportIssueUrl:
    def test_builds_prefilled_url(self) -> None:
        url = pysdp.report_issue("R4D001", open=False)
        assert "github.com/rmbl-sdp/sdp-products/issues/new" in url
        assert "template=dataset-issue.yml" in url
        assert "catalog_id=R4D001" in url

    def test_appends_type(self) -> None:
        url = pysdp.report_issue("R4D001", type="metadata-error", open=False)
        assert "issue_type=metadata-error" in url

    def test_rejects_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="must be one of"):
            pysdp.report_issue("R4D001", type="not-a-type", open=False)

    def test_rejects_wrong_length_catalog_id(self) -> None:
        with pytest.raises(ValueError, match="6-char"):
            pysdp.report_issue("short", open=False)

    def test_warns_on_unknown_catalog_id(self) -> None:
        with pytest.warns(UserWarning, match="not in the bundled catalog"):
            url = pysdp.report_issue("ZZZ999", open=False)
        assert "catalog_id=ZZZ999" in url

    def test_open_true_invokes_webbrowser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(issues_mod.webbrowser, "open", lambda u: calls.append(u))
        url = pysdp.report_issue("R3D009")
        assert calls == [url]


# ---------------------------------------------------------------------------
# _issues_to_dataframe: label parsing + PR filtering
# ---------------------------------------------------------------------------


class TestIssuesToDataframe:
    def test_empty_input_returns_empty_frame_with_columns(self) -> None:
        df = issues_mod._issues_to_dataframe([])
        assert df.empty
        assert set(df.columns) == {
            "CatalogID",
            "number",
            "title",
            "type",
            "severity",
            "status",
            "created",
            "updated",
            "url",
        }

    def test_extracts_product_type_severity_status(self) -> None:
        df = issues_mod._issues_to_dataframe([_make_issue(7)])
        assert df.iloc[0]["CatalogID"] == "R4D004"
        assert df.iloc[0]["type"] == "incorrect-values"
        assert df.iloc[0]["severity"] == "high"
        assert df.iloc[0]["status"] == "investigating"
        assert df.iloc[0]["number"] == 7

    def test_filters_out_pull_requests(self) -> None:
        df = issues_mod._issues_to_dataframe([_make_issue(1, is_pr=True), _make_issue(2)])
        assert len(df) == 1
        assert df.iloc[0]["number"] == 2

    def test_handles_missing_labels(self) -> None:
        bare = {
            "number": 99,
            "title": "Bare",
            "html_url": "https://example.com/99",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "labels": [],
        }
        df = issues_mod._issues_to_dataframe([bare])
        assert pd.isna(df.iloc[0]["CatalogID"])
        assert pd.isna(df.iloc[0]["type"])


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


class TestCache:
    @responses.activate
    def test_first_call_hits_api_and_writes_cache(self) -> None:
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[_make_issue(1)],
            status=200,
        )
        df = pysdp.known_issues()
        assert len(df) == 1
        assert issues_mod._cache_path().exists()
        # Cache payload is JSON and contains the expected schema.
        with issues_mod._cache_path().open() as fh:
            payload = json.load(fh)
        assert "fetched_at" in payload
        assert payload["issues"][0]["CatalogID"] == "R4D004"

    @responses.activate
    def test_second_call_within_ttl_uses_cache(self) -> None:
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[_make_issue(1)],
            status=200,
        )
        pysdp.known_issues()  # warm
        api_calls_after_warm = len(responses.calls)
        pysdp.known_issues()  # should be cached
        assert len(responses.calls) == api_calls_after_warm

    @responses.activate
    def test_refresh_true_bypasses_cache(self) -> None:
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[_make_issue(1)],
            status=200,
        )
        pysdp.known_issues()  # warm
        warmed = len(responses.calls)
        # Add another response to satisfy the bypass call.
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[_make_issue(1)],
            status=200,
        )
        pysdp.known_issues(refresh=True)
        assert len(responses.calls) > warmed

    def test_expired_cache_falls_back_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Seed cache with stale fetched_at.
        cache_path = issues_mod._cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        stale = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
        with cache_path.open("w") as fh:
            json.dump(
                {
                    "fetched_at": stale.isoformat(),
                    "issues": [
                        {
                            "CatalogID": "OLD001",
                            "number": 1,
                            "title": "stale",
                            "type": None,
                            "severity": None,
                            "status": None,
                            "created": "2026-01-01T00:00:00+00:00",
                            "updated": "2026-01-01T00:00:00+00:00",
                            "url": "https://example.com",
                        }
                    ],
                },
                fh,
            )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{issues_mod.ISSUES_API_BASE}/issues",
                json=[_make_issue(42)],
                status=200,
            )
            df = pysdp.known_issues()
        assert "R4D004" in df["CatalogID"].tolist()  # fresh API result
        assert "OLD001" not in df["CatalogID"].tolist()

    def test_offline_no_cache_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No HTTP mocks installed → requests will hit a connection error.
        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("offline")

        monkeypatch.setattr(issues_mod, "_gh_fetch_issues_paginated", _boom)
        with pytest.warns(UserWarning, match="Could not fetch"):
            df = pysdp.known_issues()
        assert df.empty
        assert set(df.columns) >= {"CatalogID", "number", "title", "url"}

    def test_offline_with_stale_cache_returns_stale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cache_path = issues_mod._cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        stale = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
        with cache_path.open("w") as fh:
            json.dump(
                {
                    "fetched_at": stale.isoformat(),
                    "issues": [
                        {
                            "CatalogID": "STALE1",
                            "number": 1,
                            "title": "from cache",
                            "type": None,
                            "severity": None,
                            "status": None,
                            "created": "2026-01-01T00:00:00+00:00",
                            "updated": "2026-01-01T00:00:00+00:00",
                            "url": "https://example.com",
                        }
                    ],
                },
                fh,
            )

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("offline")

        monkeypatch.setattr(issues_mod, "_gh_fetch_issues_paginated", _boom)
        with pytest.warns(UserWarning, match="Could not fetch"):
            df = pysdp.known_issues()
        assert "STALE1" in df["CatalogID"].tolist()


# ---------------------------------------------------------------------------
# known_issues() filter behavior
# ---------------------------------------------------------------------------


class TestKnownIssuesFilter:
    @responses.activate
    def test_filter_by_catalog_id(self) -> None:
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[_make_issue(1, cat="R4D004"), _make_issue(2, cat="R3D009")],
            status=200,
        )
        df = pysdp.known_issues("R4D004")
        assert len(df) == 1
        assert df.iloc[0]["CatalogID"] == "R4D004"


# ---------------------------------------------------------------------------
# open_issue_counts aggregator
# ---------------------------------------------------------------------------


class TestOpenIssueCounts:
    @responses.activate
    def test_groups_by_catalog_id(self) -> None:
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[
                _make_issue(1, cat="R4D004"),
                _make_issue(2, cat="R4D004"),
                _make_issue(3, cat="R3D009"),
            ],
            status=200,
        )
        counts = issues_mod.open_issue_counts()
        d = dict(zip(counts["CatalogID"], counts["OpenIssues"], strict=True))
        assert d["R4D004"] == 2
        assert d["R3D009"] == 1

    def test_offline_empty_returns_empty_frame(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("offline")

        monkeypatch.setattr(issues_mod, "_gh_fetch_issues_paginated", _boom)
        with pytest.warns(UserWarning):
            counts = issues_mod.open_issue_counts()
        assert counts.empty
        assert set(counts.columns) == {"CatalogID", "OpenIssues"}


# ---------------------------------------------------------------------------
# get_catalog(with_issue_counts=True) + browse(with_issue_counts=True)
# ---------------------------------------------------------------------------


class TestGetCatalogWithIssueCounts:
    @responses.activate
    def test_attaches_openissues_column(self) -> None:
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[_make_issue(1, cat="R3D009"), _make_issue(2, cat="R3D009")],
            status=200,
        )
        df = pysdp.get_catalog(with_issue_counts=True)
        assert "OpenIssues" in df.columns
        row = df[df["CatalogID"] == "R3D009"]
        if not row.empty:
            assert int(row.iloc[0]["OpenIssues"]) == 2
        # CatalogIDs with no issues get 0, not NaN.
        assert df["OpenIssues"].notna().all()

    def test_default_no_column(self) -> None:
        df = pysdp.get_catalog()
        assert "OpenIssues" not in df.columns


class TestBrowseWithIssueCounts:
    @responses.activate
    def test_badge_renders(self) -> None:
        responses.add(
            responses.GET,
            f"{issues_mod.ISSUES_API_BASE}/issues",
            json=[
                _make_issue(1, cat="R3D009"),
                _make_issue(2, cat="R3D009"),
            ],
            status=200,
        )
        html = str(pysdp.browse(domains=["UG"], types=["Topo"], with_issue_counts=True))
        # Badge text appears when a UG/Topo product matches R3D009.
        if "R3D009" in html:
            assert "⚠ 2 open issues" in html

    def test_default_no_badge(self) -> None:
        # Without with_issue_counts=True, no network call is made and no badge appears.
        html = str(pysdp.browse(domains=["UG"], types=["Topo"], max_products=2))
        assert "open issue" not in html
