# Getting started

## Install

=== "pip"

    ```bash
    pip install pysdp                # core: catalog, raster, extract, download
    pip install "pysdp[dask]"        # + lazy chunked COG reads via Dask
    pip install "pysdp[stac]"        # + pystac-client and odc-stac for STAC
    pip install "pysdp[exact]"       # + exactextract for fractional zonal stats
    pip install "pysdp[download]"    # + obstore/fsspec for faster downloads
    pip install "pysdp[hub]"         # + dask-gateway for JupyterHub clusters
    pip install "pysdp[all]"         # everything
    ```

=== "conda / mamba"

    Conda-forge support lands alongside the first stable release. In the meantime, `pip install pysdp` inside a conda environment works well.

=== "uv"

    ```bash
    uv add pysdp                     # add to current project
    uv pip install "pysdp[all]"      # into an existing env
    ```

### Dependencies

Core runtime deps include `xarray`, `rioxarray`, `rasterio`, `geopandas`, `pystac`, `scipy`, `xvec`, and `requests`. These all have wheels on PyPI for Linux, macOS (Intel + Apple Silicon), and Windows — no GDAL system install needed.

Python 3.11, 3.12, and 3.13 are supported; pySDP follows [SPEC 0](https://scientific-python.org/specs/spec-0000/) for version windows.

## Quick start

### Discover what's in the catalog

```python
import pysdp

# All current (non-deprecated) SDP products
cat = pysdp.get_catalog()
cat.shape  # e.g. (140, 18)

# Narrow by domain, type, time-series shape
ug_climate_daily = pysdp.get_catalog(
    domains=["UG"],
    types=["Climate"],
    timeseries_types=["Daily"],
)
ug_climate_daily[["CatalogID", "Product", "Resolution"]]
```

### Open a raster

```python
# Single-layer product
dem = pysdp.open_raster("R3D009")   # UG bare-earth DEM, 3 m
dem

# Daily time-series, sliced by date range
tmax = pysdp.open_raster(
    "R4D004",
    date_start="2021-11-02",
    date_end="2021-11-04",
)
tmax.sizes   # {'time': 3, 'y': ..., 'x': ...}
```

pySDP returns an `xarray.Dataset`:

- The data variable is named from the product's canonical short name (e.g. `UG_dem_3m_v1`).
- CRS is set to `EPSG:32613` (UTM zone 13N) on every SDP raster.
- For time-series, the `time` coordinate is a `pandas.DatetimeIndex` (Daily → actual date, Monthly → first-of-month, Yearly → Jan 1).

### Extract at points and polygons

```python
import geopandas as gpd

sites = gpd.GeoDataFrame(
    {"site": ["Roaring Judy", "Gothic", "Galena Lake"]},
    geometry=gpd.points_from_xy(
        [-106.853186, -106.988934, -107.072569],
        [38.716995, 38.958446, 39.021644],
    ),
    crs="EPSG:4326",
)

# Bilinear interpolation at points (auto-reprojects to raster CRS)
elevations = pysdp.extract_points(dem, sites)

# Zonal mean over polygons (centroid-based; set exact=True for fractional coverage)
watersheds = gpd.read_file("my_watersheds.gpkg")
watershed_elev = pysdp.extract_polygons(dem, watersheds, stats="mean")
```

For time-series rasters, extraction output is **long-form**: one row per `(geometry × time)`. Pivot to wide if you want the rSDP-style layout:

```python
# tmax is the Daily time-series from above; extract at the 3 field sites
samples = pysdp.extract_points(tmax, sites)
wide = samples.pivot_table(index="site", columns="time", values="bayes_tmax_est")
```

### Download to local disk

```python
# By catalog_id (expands Yearly/Monthly to all catalog slices)
pysdp.download(
    catalog_ids=["R1D001", "R3D009"],
    output_dir="~/sdp-data",
)

# By URL (for hand-picked subsets — e.g. selective daily slices)
pysdp.download(
    urls=[
        "https://rmbl-sdp.s3.us-east-2.amazonaws.com/data_products/released/release4/bayes_tmax_year_2021_day_0305_est.tif",
        "https://rmbl-sdp.s3.us-east-2.amazonaws.com/data_products/released/release4/bayes_tmax_year_2021_day_0306_est.tif",
    ],
    output_dir="~/sdp-data",
)
```

Returns a `pandas.DataFrame` status report with `[url, dest, success, status, size, error]` columns.

## Coming from rSDP?

pySDP is a direct port of the [rSDP R package](https://github.com/rmbl-sdp/rSDP). The API mirrors rSDP closely, with Python-idiomatic adjustments:

| rSDP (R)                               | pySDP (Python)                                      |
| -------------------------------------- | --------------------------------------------------- |
| `sdp_get_catalog()`                    | `pysdp.get_catalog()`                               |
| `sdp_get_metadata()`                   | `pysdp.get_metadata()`                              |
| `sdp_get_raster()`                     | `pysdp.open_raster()` / `pysdp.open_stack()`        |
| `sdp_extract_data(points)`             | `pysdp.extract_points()`                            |
| `sdp_extract_data(polygons)`           | `pysdp.extract_polygons()`                          |
| `download_data()`                      | `pysdp.download()`                                  |
| `SpatRaster`                           | `xarray.Dataset`                                    |
| `SpatVector` / `sf::sf`                | `geopandas.GeoDataFrame`                            |

See the full behavioral mapping in [SPEC §5](https://github.com/rmbl-sdp/pySDP/blob/main/SPEC.md#5-rsdp--pysdp-mapping).

## Where to next

- [API reference](api.md) — every public function with signatures and docstrings.
- **User guides** — longer walkthroughs (porting the four rSDP vignettes to Python, one per 0.1.x release): cloud-data access, raster wrangling, field-site sampling, and pretty maps.
- [Roadmap](https://github.com/rmbl-sdp/pySDP/blob/main/ROADMAP.md) — JupyterHub / Dask Gateway integration, distributed extraction, benchmarks.
