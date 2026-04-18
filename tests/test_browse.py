"""Tests for `pysdp.browse` (visual catalog browser) and `Thumbnail.URL` column."""

from __future__ import annotations

import pysdp
from pysdp.browse import CatalogBrowser, browse


class TestThumbnailUrl:
    def test_column_present_in_catalog(self) -> None:
        df = pysdp.get_catalog(deprecated=None)
        assert "Thumbnail.URL" in df.columns

    def test_single_product_url_ends_with_thumbnail_png(self) -> None:
        df = pysdp.get_catalog(timeseries_types=["Single"])
        for url in df["Thumbnail.URL"].head(5):
            assert url.endswith("_thumbnail.png"), url

    def test_yearly_product_has_no_placeholders(self) -> None:
        df = pysdp.get_catalog(timeseries_types=["Yearly"])
        for url in df["Thumbnail.URL"].head(5):
            assert "{" not in url, url
            assert url.endswith("_thumbnail.png"), url

    def test_all_urls_are_https(self) -> None:
        df = pysdp.get_catalog(deprecated=None)
        for url in df["Thumbnail.URL"]:
            assert url.startswith("https://"), url


class TestBrowse:
    def test_returns_catalog_browser(self) -> None:
        result = browse(domains=["UG"], types=["Vegetation"])
        assert isinstance(result, CatalogBrowser)

    def test_repr_html_contains_img_tags(self) -> None:
        result = browse(domains=["UG"], types=["Vegetation"])
        html = result._repr_html_()
        assert "<img" in html
        assert "thumbnail" in html.lower()

    def test_max_products_limits_cards(self) -> None:
        full = browse(domains=["UG"])
        limited = browse(domains=["UG"], max_products=3)
        assert limited._repr_html_().count("<img") == 3
        assert full._repr_html_().count("<img") > 3

    def test_filters_reflected_in_title(self) -> None:
        result = browse(domains=["UG"], types=["Topo"])
        html = result._repr_html_()
        assert "domains=" in html
        assert "types=" in html

    def test_columns_param_affects_grid(self) -> None:
        r3 = browse(domains=["UG"], columns=3)
        r5 = browse(domains=["UG"], columns=5)
        assert "repeat(3," in r3._repr_html_()
        assert "repeat(5," in r5._repr_html_()

    def test_browse_accessible_from_top_level(self) -> None:
        assert hasattr(pysdp, "browse")
        assert pysdp.browse is browse
