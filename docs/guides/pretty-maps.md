# Pretty maps

> **R counterpart:** [`pretty-maps.Rmd`](https://github.com/rmbl-sdp/rSDP/blob/main/vignettes/pretty-maps.Rmd).

`pysdp` doesn't ship its own plotting layer — it returns `xarray.Dataset` and `geopandas.GeoDataFrame` objects that compose with the rest of the PyData viz ecosystem. This guide covers the three common paths:

- **Static maps** with `matplotlib` + `xarray.plot` (for papers, reports)
- **Interactive web maps** with `folium` / `GeoDataFrame.explore()` (for exploration, notebooks)
- **Publication-quality faceted figures** with `matplotlib` subplots or `hvplot`

## Setup

```bash
pip install "pysdp[viz]"   # pulls in matplotlib + folium
```

```python
import pysdp
import geopandas as gpd
import matplotlib.pyplot as plt
```

## Loading data

```python
# Digital elevation model — the base layer for most maps
dem = pysdp.open_raster("R3D009", chunks=None)  # eager load for fast plotting

# Stream flowlines — overlay
streams = gpd.read_file(
    "https://rmbl-sdp.s3.us-east-2.amazonaws.com/data_products/released/release1/UER_streams_512k_mfd_1m_v2.tif"
)  # (in practice use a vector export for streams)
```

## Basic raster map with matplotlib

```python
fig, ax = plt.subplots(figsize=(8, 6))
dem["UG_dem_3m_v1"].plot.imshow(ax=ax, cmap="terrain", robust=True)
ax.set_aspect("equal")
ax.set_title("Upper Gunnison DEM (3 m)")
plt.tight_layout()
```

`.plot.imshow()` is xarray's matplotlib wrapper — handles colorbars, axis labels, and CRS-aware extent automatically. `robust=True` clips extreme outliers so the colormap stays useful.

## Web maps with folium

For exploration in a notebook, `GeoDataFrame.explore()` gives you a pan/zoom map with a single call:

```python
watersheds = gpd.read_file("watersheds.gpkg")
watersheds.explore(column="HYD_NAME", tiles="Esri.NatGeoWorldMap", cmap="Set2")
```

To overlay a raster on a folium map, use `folium.raster_layers.ImageOverlay` with an RGBA PNG you've rendered from the xarray data. That's more setup — for quick visual checks, `xarray.plot` + `matplotlib` is usually faster.

## Faceted multi-panel maps

Showing multiple years of a time-series product side-by-side:

```python
snow = pysdp.open_raster("R4D001", years=[2018, 2019, 2020], chunks=None)

fig = snow["UG_snow_persistence_27m_v1"].plot.imshow(
    col="time", col_wrap=3,
    cmap="Blues", robust=True,
    figsize=(14, 5),
)
```

xarray auto-creates the subplot grid from the `col="time"` faceting argument.

## Adding overlays

Combine raster + vector on one figure:

```python
fig, ax = plt.subplots(figsize=(10, 8))

# Base: DEM hillshade-style
dem["UG_dem_3m_v1"].plot.imshow(
    ax=ax, cmap="Greys_r", add_colorbar=False, alpha=0.6
)

# Overlay: watersheds in the raster's CRS
watersheds.to_crs(dem.rio.crs).boundary.plot(
    ax=ax, color="royalblue", linewidth=0.8
)

# Overlay: field sites
sites = gpd.GeoDataFrame(
    geometry=gpd.points_from_xy([-106.988934], [38.958446]),
    crs="EPSG:4326",
).to_crs(dem.rio.crs)
sites.plot(ax=ax, color="red", markersize=50, marker="^")

ax.set_title("Upper Gunnison — DEM, watersheds, and Gothic study site")
ax.set_aspect("equal")
plt.tight_layout()
```

## Zooming in

Crop to an AOI before plotting for faster rendering and sharper detail:

```python
gothic_bbox = (325000, 4310000, 330000, 4315000)   # UTM 13N coords
gothic_dem = dem.rio.clip_box(*gothic_bbox)

fig, ax = plt.subplots(figsize=(8, 6))
gothic_dem["UG_dem_3m_v1"].plot.imshow(ax=ax, cmap="terrain", robust=True)
ax.set_title("Gothic valley — 3 m DEM")
ax.set_aspect("equal")
```

## Exporting

PNG (for web, reports):

```python
plt.savefig("dem_map.png", dpi=300, bbox_inches="tight")
```

PDF (for publication):

```python
plt.savefig("dem_map.pdf", bbox_inches="tight")
```

GeoTIFF of a styled map isn't straightforward with matplotlib — if you need a georeferenced map image for GIS, write the raster directly with `rio.to_raster` and restyle downstream.

## Alternatives worth knowing

- **`hvplot`** — interactive notebook plots via holoviews: `dem.hvplot.image(x="x", y="y")`. Nice for lots of zooming.
- **`lonboard`** — GPU-accelerated map rendering for large vector datasets; excellent for 100k+ point displays.
- **`leafmap`** — folium/ipyleaflet wrapper with sensible defaults for Earth-observation workflows; supports COG display directly.

For static publication figures, matplotlib + `xarray.plot` remains the most-used path.

## Next steps

- [Field-site sampling](field-sampling.md) — generating the extracted data that your maps visualize
- [API reference](../api.md) for pySDP's full function surface
