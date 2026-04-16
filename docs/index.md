# pySDP

Native Python interface for the [RMBL Spatial Data Platform](https://www.rmbl.org/scientists/resources/spatial-data-platform/) — curated, high-resolution geospatial datasets covering Western Colorado (USA) around [Rocky Mountain Biological Laboratory](https://rmbl.org).

pySDP gives you lazy, cloud-native access to cloud-optimized GeoTIFFs (COGs) hosted on S3, plus the ergonomics you'd expect from the modern scientific Python stack: `xarray.Dataset` returns, `geopandas.GeoDataFrame` extraction, `pystac` catalog access, and `dask` compatibility.

## Why pySDP

- **No downloads needed** — open a 1 GB COG and extract 500 point samples without ever pulling the full raster to disk. GDAL VSICURL handles the range reads.
- **Sensible types** — every function returns standard `xarray` / `geopandas` / `pandas` objects that compose with the rest of the PyData ecosystem.
- **Feature parity with [rSDP](https://github.com/rmbl-sdp/rSDP)** — the R client pySDP ports. Same catalog, same data, same vocabulary; idiomatic Python where it diverges.
- **Staleness-aware** — the packaged product catalog warns when it's older than 6 months; `source="live"` always hits fresh.

## Status

Pre-alpha. v0.1.0 is the initial feature-complete release covering catalog discovery, lazy raster access, point/polygon extraction, and bulk download. See the [changelog](changelog.md) for details.

Longer-term work (JupyterHub / Dask Gateway integration, distributed extraction recipes, benchmark harness) is tracked in the [roadmap](https://github.com/rmbl-sdp/pySDP/blob/main/ROADMAP.md).

## 30-second tour

```python
import pysdp
import geopandas as gpd

# Find datasets in the Upper Gunnison vegetation catalog
sdp_cat = pysdp.get_catalog(domains=["UG"], types=["Vegetation"])
sdp_cat[["CatalogID", "Product", "Resolution"]].head()

# Open a landcover raster lazily (no download)
landcover = pysdp.open_raster("R3D018")  # UG basic landcover, 1 m

# Extract values at three field sites
sites = gpd.GeoDataFrame(
    {"site": ["Roaring Judy", "Gothic", "Galena Lake"]},
    geometry=gpd.points_from_xy(
        [-106.853186, -106.988934, -107.072569],
        [38.716995, 38.958446, 39.021644],
    ),
    crs="EPSG:4326",
)
samples = pysdp.extract_points(landcover, sites)
samples
```

Head to [Getting started](getting-started.md) for install instructions and a deeper walkthrough, or [API reference](api.md) for the full surface.

## Citation

If pySDP supports your research, please cite the RMBL Spatial Data Platform. A formal citation for pySDP itself will be added at the 0.1.0 release.
