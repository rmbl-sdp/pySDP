"""Unit + integration tests for `pysdp.download`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import responses

import pysdp
from pysdp.download import _expand_catalog_id, _expand_catalog_ids, _is_valid_existing

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_both_urls_and_catalog_ids_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not both"):
            pysdp.download(
                urls="https://x/y.tif",
                catalog_ids="R1D001",
                output_dir=tmp_path,
            )

    def test_neither_urls_nor_catalog_ids_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must specify"):
            pysdp.download(output_dir=tmp_path)

    def test_missing_output_dir_rejected(self) -> None:
        with pytest.raises(ValueError, match="output_dir"):
            pysdp.download(urls="https://x/y.tif")

    def test_output_dir_created_if_missing(self, tmp_path: Path) -> None:
        subdir = tmp_path / "fresh" / "nested"
        assert not subdir.exists()
        # With no URLs after expansion this just returns an empty DataFrame.
        out = pysdp.download(urls=[], output_dir=subdir, return_status=True, verbose=False)
        assert subdir.is_dir()
        assert isinstance(out, pd.DataFrame)
        assert len(out) == 0


# ---------------------------------------------------------------------------
# catalog_id expansion
# ---------------------------------------------------------------------------


class TestCatalogIdExpansion:
    def test_single_product_returns_one_url(self) -> None:
        urls = _expand_catalog_id("R1D001")
        assert len(urls) == 1
        assert urls[0].endswith(".tif")
        assert "{" not in urls[0]

    def test_yearly_expands_to_all_years(self) -> None:
        # R4D001 (UG snow persistence, Yearly) spans multiple years.
        urls = _expand_catalog_id("R4D001")
        assert len(urls) > 1
        assert all("{" not in u for u in urls)
        assert all(u.endswith(".tif") for u in urls)

    def test_monthly_expands_to_all_months(self) -> None:
        # R4D006 (UG airtemp tavg, Monthly) spans many months.
        urls = _expand_catalog_id("R4D006")
        assert len(urls) > 12
        assert all("{" not in u for u in urls)

    def test_daily_rejected(self) -> None:
        # R4D004 (bayes_tmax daily) has thousands of days.
        with pytest.raises(ValueError, match="Daily catalog_id"):
            _expand_catalog_id("R4D004")

    def test_unknown_id_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="not found in packaged catalog"):
            _expand_catalog_id("ZZZZZZ")

    def test_expand_list_combines(self) -> None:
        urls = _expand_catalog_ids(["R1D001", "R1D002"])
        assert len(urls) == 2

    def test_expand_single_str_works(self) -> None:
        urls = _expand_catalog_ids("R1D001")
        assert len(urls) == 1


# ---------------------------------------------------------------------------
# _is_valid_existing
# ---------------------------------------------------------------------------


class TestIsValidExisting:
    def test_missing_file_is_not_valid(self, tmp_path: Path) -> None:
        assert not _is_valid_existing(tmp_path / "nope.tif")

    def test_tiny_file_is_not_valid(self, tmp_path: Path) -> None:
        p = tmp_path / "partial.tif"
        p.write_bytes(b"tiny")
        assert not _is_valid_existing(p)

    def test_large_file_is_valid(self, tmp_path: Path) -> None:
        p = tmp_path / "good.tif"
        p.write_bytes(b"x" * 2000)
        assert _is_valid_existing(p)


# ---------------------------------------------------------------------------
# download() end-to-end via responses-mocked HTTP
# ---------------------------------------------------------------------------


class TestDownloadMocked:
    @responses.activate
    def test_single_url_downloads(self, tmp_path: Path) -> None:
        url = "https://test.example/data/foo.tif"
        payload = b"x" * 4096  # > 1 kB so it counts as valid
        responses.add(responses.GET, url, body=payload, status=200)

        out = pysdp.download(urls=url, output_dir=tmp_path, verbose=False)
        assert isinstance(out, pd.DataFrame)
        assert len(out) == 1
        assert out.iloc[0]["success"]
        assert out.iloc[0]["status"] == 200
        assert (tmp_path / "foo.tif").exists()
        assert (tmp_path / "foo.tif").read_bytes() == payload

    @responses.activate
    def test_multiple_urls_downloaded_in_parallel(self, tmp_path: Path) -> None:
        urls = [f"https://test.example/data/{i}.tif" for i in range(3)]
        for u in urls:
            responses.add(responses.GET, u, body=b"x" * 2048, status=200)

        out = pysdp.download(urls=urls, output_dir=tmp_path, max_workers=4, verbose=False)
        assert len(out) == 3
        assert out["success"].all()
        for u in urls:
            assert (tmp_path / Path(u).name).exists()

    @responses.activate
    def test_existing_file_skipped_when_overwrite_false(self, tmp_path: Path) -> None:
        url = "https://test.example/data/existing.tif"
        # Pre-seed the destination with a "valid" file (> 1 kB).
        (tmp_path / "existing.tif").write_bytes(b"x" * 4096)
        # No responses.add() → if the download path is taken, the test fails.
        out = pysdp.download(urls=url, output_dir=tmp_path, verbose=False)
        assert len(out) == 1
        assert out.iloc[0]["status"] == "exists"
        assert out.iloc[0]["success"]

    @responses.activate
    def test_existing_file_redownloaded_when_overwrite_true(self, tmp_path: Path) -> None:
        url = "https://test.example/data/refresh.tif"
        dest = tmp_path / "refresh.tif"
        dest.write_bytes(b"old" * 1000)
        responses.add(responses.GET, url, body=b"new" * 2000, status=200)

        out = pysdp.download(urls=url, output_dir=tmp_path, overwrite=True, verbose=False)
        assert out.iloc[0]["status"] == 200
        assert dest.read_bytes() == b"new" * 2000

    @responses.activate
    def test_partial_existing_some_skipped(self, tmp_path: Path) -> None:
        urls = [f"https://test.example/data/{i}.tif" for i in range(3)]
        # Pre-seed first as valid; others missing. Only the missing ones
        # should hit HTTP.
        (tmp_path / "0.tif").write_bytes(b"x" * 4096)
        responses.add(responses.GET, urls[1], body=b"y" * 2048, status=200)
        responses.add(responses.GET, urls[2], body=b"z" * 2048, status=200)

        out = pysdp.download(urls=urls, output_dir=tmp_path, verbose=False)
        assert len(out) == 3
        statuses = sorted(out["status"].tolist(), key=str)
        assert statuses == [200, 200, "exists"]

    @responses.activate
    def test_http_error_reflected_in_status(self, tmp_path: Path) -> None:
        url = "https://test.example/data/missing.tif"
        responses.add(responses.GET, url, status=404)

        with pytest.warns(UserWarning, match="failed"):
            out = pysdp.download(urls=url, output_dir=tmp_path, verbose=False)
        assert not out.iloc[0]["success"]
        assert out.iloc[0]["status"] == 404
        assert out.iloc[0]["error"]

    @responses.activate
    def test_return_status_false_returns_none(self, tmp_path: Path) -> None:
        url = "https://test.example/data/silent.tif"
        responses.add(responses.GET, url, body=b"x" * 2048, status=200)

        out = pysdp.download(urls=url, output_dir=tmp_path, return_status=False, verbose=False)
        assert out is None
        assert (tmp_path / "silent.tif").exists()

    @responses.activate
    def test_status_dataframe_columns(self, tmp_path: Path) -> None:
        url = "https://test.example/data/shape.tif"
        responses.add(responses.GET, url, body=b"x" * 2048, status=200)

        out = pysdp.download(urls=url, output_dir=tmp_path, verbose=False)
        expected_cols = {"url", "dest", "success", "status", "size", "error"}
        assert expected_cols.issubset(set(out.columns))


# ---------------------------------------------------------------------------
# Network-gated integration test (a single small real S3 download)
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestNetwork:
    def test_download_single_real(self, tmp_path: Path) -> None:
        """Download one real Single SDP file from S3 via the catalog_id path.

        R1D001 (UER Large Stream Flowlines, Multi-flow Direction, 1 m) is
        ~4 MB — small enough to exercise the full end-to-end path in under
        a few seconds.
        """
        out = pysdp.download(
            catalog_ids="R1D001",
            output_dir=tmp_path,
            max_workers=2,
            verbose=False,
        )
        assert isinstance(out, pd.DataFrame)
        assert len(out) == 1
        assert out.iloc[0]["success"], f"failed: {out.iloc[0].to_dict()}"
        dest = Path(out.iloc[0]["dest"])
        assert dest.exists()
        # R1D001 is ~4 MB; assert > 1 MB to catch short/zero-byte failures.
        assert dest.stat().st_size > 1_000_000
