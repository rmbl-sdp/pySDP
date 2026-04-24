"""Tests for `pysdp.browse` (visual catalog browser) and `Thumbnail.URL` column."""

from __future__ import annotations

import pysdp
from pysdp.browse import CatalogBrowser, _browser_url, _product_to_slug, browse


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

    def test_repr_html_is_data_uri_iframe(self) -> None:
        result = browse(domains=["UG"], types=["Vegetation"])
        iframe = result._repr_html_()
        assert "<iframe" in iframe
        assert "data:text/html;base64," in iframe

    def test_raw_html_contains_img_tags(self) -> None:
        result = browse(domains=["UG"], types=["Vegetation"])
        html = str(result)
        assert "<img" in html
        assert "thumbnail" in html.lower()

    def test_max_products_limits_cards(self) -> None:
        full = browse(domains=["UG"])
        limited = browse(domains=["UG"], max_products=3)
        assert str(limited).count("<img") == 3
        assert str(full).count("<img") > 3

    def test_filters_reflected_in_title(self) -> None:
        result = browse(domains=["UG"], types=["Topo"])
        html = str(result)
        assert "domains=" in html
        assert "types=" in html

    def test_columns_param_affects_grid(self) -> None:
        import re

        r3 = browse(domains=["UG"], columns=3)
        r5 = browse(domains=["UG"], columns=5)
        # Table layout: first <tr> should have `columns` <td> elements
        tds_r3 = re.findall(r"<td", str(r3).split("</tr>")[0])
        tds_r5 = re.findall(r"<td", str(r5).split("</tr>")[0])
        assert len(tds_r3) == 3
        assert len(tds_r5) == 5

    def test_browse_accessible_from_top_level(self) -> None:
        assert hasattr(pysdp, "browse")
        assert pysdp.browse is browse

    def test_cards_contain_sdp_browser_links(self) -> None:
        result = browse(domains=["UG"], types=["Vegetation"])
        html = str(result)  # raw HTML, not the base64-encoded iframe
        assert "sdpbrowser.org" in html
        assert "SDP Browser" in html

    def test_cards_contain_open_raster_snippet(self) -> None:
        result = browse(domains=["UG"], types=["Vegetation"], max_products=1)
        html = str(result)
        assert "pysdp.open_raster(" in html


class TestSlugAndBrowserUrl:
    def test_product_to_slug(self) -> None:
        assert _product_to_slug("Basic Landcover") == "basic-landcover"
        assert _product_to_slug("20th Percentile Canopy Height") == "20th-percentile-canopy-height"
        assert _product_to_slug("October 2017 NAIP NDVI") == "october-2017-naip-ndvi"

    def test_browser_url_contains_slug(self) -> None:
        url = _browser_url("Basic Landcover")
        assert "sdpbrowser.org" in url
        assert "basic-landcover" in url

    def test_browser_url_encodes_layer_param(self) -> None:
        url = _browser_url("Basic Landcover")
        assert "#layers=" in url
