# Wrangling raster data

> **R counterpart:** [`wrangle-raster-data.Rmd`](https://github.com/rmbl-sdp/rSDP/blob/main/vignettes/wrangle-raster-data.Rmd).

Most real workflows need more than "open the raster" — you crop, reproject, resample, mask by an AOI, combine with other products, and eventually export. pySDP leans on `rioxarray` and `xarray` for these operations; this guide maps the common rSDP/terra idioms to their Python counterparts.

## Vector vs raster data

Same conceptual model as in R: vector data (points, lines, polygons) describes discrete features; raster data describes continuous fields on a grid. pySDP returns:

- **rasters** as `xarray.Dataset` with a `.rio` accessor for spatial operations
- **vectors** as `geopandas.GeoDataFrame` with `.geometry`, `.crs`, `.to_crs()`

Unlike terra, xarray/rioxarray treats the CRS as *attached metadata* rather than a mutable state; operations return new objects.

## Setup

```python
import pysdp
import geopandas as gpd
import rioxarray  # registers the .rio accessor on xarray objects
```

## Reading raster + vector data

### Vectors

```python
# From a local file (GeoPackage, GeoJSON, Shapefile — geopandas handles them all)
sites = gpd.read_file("field_sites.gpkg")

# Or from a remote URL (S3, HTTPS)
ug_bounds = gpd.read_file(
    "https://rmbl-sdp.s3.us-east-2.amazonaws.com/data_products/supplemental/UG_region_vect_1m.geojson"
)
```

### Rasters

```python
landcover = pysdp.open_raster("R3D018")  # UG Basic Landcover, 1 m
```

## Reprojecting vectors

```python
sites_utm = sites.to_crs(landcover.rio.crs)   # match the raster's CRS
```

pySDP's extraction functions auto-reproject for you — calling `to_crs` explicitly is only useful if you want to plot together, compute distances in meters, or chain further vector operations.

## Cropping rasters to an AOI

Two common patterns.

**Bounding-box crop** (rectangular window):

```python
minx, miny, maxx, maxy = ug_bounds.to_crs(landcover.rio.crs).total_bounds
landcover_bbox = landcover.rio.clip_box(minx, miny, maxx, maxy)
```

**Polygon clip** (masks cells outside the polygon):

```python
landcover_ug = landcover.rio.clip(
    ug_bounds.to_crs(landcover.rio.crs).geometry, from_disk=True
)
```

`from_disk=True` streams the clipped window straight from the COG — the right choice for cloud-hosted rasters. Omit it for in-memory rasters.

## Modifying raster data

xarray treats the Dataset like a labeled numpy array. Arithmetic, logical operations, reductions all work:

```python
# Identify forested cells (suppose class 4 = forest in the landcover legend)
forest = (landcover["UG_landcover_1m_v4"] == 4)

# Count forest cells
n_forest = int(forest.sum().compute())
```

Or combine multiple products:

```python
slope = pysdp.open_raster("R3D012")
dem = pysdp.open_raster("R3D009")
steep_above_3000m = (slope["UG_dem_slope_1m_v1"] > 30) & (dem["UG_dem_3m_v1"] > 3000)
```

See [the xarray docs](https://docs.xarray.dev/en/stable/user-guide/computation.html) for the full vocabulary — `.where`, `.groupby`, `.resample`, `.rolling`, `.coarsen` all work on SDP rasters.

## Resampling rasters to a different grid

`rio.reproject_match` re-grids one raster to match another:

```python
slope_on_dem_grid = slope.rio.reproject_match(dem)
```

Useful when you want to stack products that started at different resolutions.

## Reprojecting rasters to a new CRS

```python
wgs = landcover.rio.reproject("EPSG:4326")
```

Heavy operation — prefer cropping first if you only need a subset, and consider downloading locally (`pysdp.download`) before reprojecting a large raster.

## Combining rasters

If multiple products share a grid already, `open_stack()` loads them as data variables of a single Dataset:

```python
topo = pysdp.open_stack(["R3D009", "R3D012"])  # DEM + slope
sorted(topo.data_vars)
```

For products that don't share a grid, open each individually and merge after aligning with `reproject_match`:

```python
dem = pysdp.open_raster("R3D009")
landcover = pysdp.open_raster("R3D018").rio.reproject_match(dem)
stacked = dem.merge(landcover)
```

## Exporting

```python
# Write a local COG (preserves the cloud-optimized structure for future reads)
landcover_ug.rio.to_raster(
    "landcover_ug_clip.tif", driver="COG", dtype="uint8"
)
```

For vector outputs, `GeoDataFrame.to_file(...)` handles GPKG, GeoJSON, and Shapefile.

## Next steps

- [Field-site sampling](field-sampling.md) — extracting values at points/polygons
- [Pretty maps](pretty-maps.md) — making figures for papers and reports
