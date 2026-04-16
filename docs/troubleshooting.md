# Troubleshooting & FAQ

Common issues and their resolutions.

## Install

### `pip install pysdp` pulls a huge wheel stack on first run

Normal. The core dep set (`rasterio`, `rioxarray`, `xarray`, `geopandas`, `pystac`, `scipy`, etc.) is ~150 MB of wheels. All of it installs from PyPI without a system GDAL — the GDAL binary ships inside `rasterio`'s wheel.

If install is slow on a laptop or CI, try `uv pip install pysdp` (Astral's resolver is substantially faster than pip's).

### `ImportError: Cannot import name X from pysdp`

The public API is the seven functions + five constants re-exported from `pysdp/__init__.py`:

- `get_catalog`, `get_metadata`
- `open_raster`, `open_stack`
- `extract_points`, `extract_polygons`
- `download`
- `DOMAINS`, `TYPES`, `RELEASES`, `TIMESERIES_TYPES`, `SDP_CRS`

Anything else is internal and subject to change.

## Lazy reads / chunking

### `chunks='auto'` emits a warning about installing `pysdp[dask]`

`pysdp.open_raster()` defaults to `chunks="auto"` for lazy Dask-backed reads. If `dask` isn't installed, pysdp falls back to eager loads with a `UserWarning`. For lazy reads on large / time-series rasters, install the extra:

```bash
pip install "pysdp[dask]"
```

Eager mode still works fine for small rasters or small cropped regions.

## CRS and reprojection

### "Re-projecting locations to coordinate system of the raster." — is this bad?

No. `extract_points` and `extract_polygons` auto-reproject your input locations to the raster's CRS (`EPSG:32613` / UTM 13N) when they differ. The message is informational and goes to stderr; silence it with `verbose=False`.

For large point sets, pre-projecting once outside the extract call is slightly more efficient:

```python
sites_utm = sites.to_crs("EPSG:32613")
for dem_id in ["R3D009", "R5D009"]:
    out = pysdp.extract_points(pysdp.open_raster(dem_id), sites_utm)
```

### Reprojecting a full raster is slow

Reprojection touches every cell, so it's inherently expensive on cloud-hosted rasters. Two strategies:

1. **Crop first, reproject the small subset.** If you only need the raster in a small AOI, `clip_box()` before `reproject()`.
2. **Download locally first.** `pysdp.download(catalog_ids="R3D009", output_dir=...)`, then open and reproject from disk.

## Extraction

### Point extraction is slow on large cloud rasters

Known gap. `xvec.extract_points` (our `method="nearest"` path) and `xarray.interp` (our `method="linear"` path) both pull more cells than strictly necessary when backed by a remote COG — usually the full chunk containing each point rather than just the point itself. For widely-spaced points on a >1 GB raster, this can take minutes.

Workarounds today:

1. **`method="nearest"`** is usually 2–5× faster than `"linear"`.
2. **Crop first** — the bounding box of your sites, with a small buffer, often reduces the raster by orders of magnitude.
3. **Download locally** — for repeat extractions against the same raster, `pysdp.download()` + `rioxarray.open_rasterio` is the fastest path.

Dask-aware partition-and-reduce extraction is tracked in [ROADMAP §Phase 8a](https://github.com/rmbl-sdp/pySDP/blob/main/ROADMAP.md). If you're running at 10k+ points, this is the phase to watch.

### `extract_polygons(exact=True)` raises `NotImplementedError`

Tracked in [ROADMAP §Phase 8a](https://github.com/rmbl-sdp/pySDP/blob/main/ROADMAP.md). `exact=False` (centroid inclusion, matching rSDP / `terra::extract`) is the default and works today. The fractional-coverage path via `exactextract` needs a custom xarray→exactextract bridge that composes with Dask — non-trivial, budgeted for 0.2.

### Extraction output has one row per `(point, time)` — I want wide format

That's long-form. Pivot to wide:

```python
long = pysdp.extract_points(tmax, sites)
wide = long.pivot_table(
    index="site",
    columns="time",
    values="bayes_tmax_est",    # the raster's variable name
)
```

## Catalog

### `UserWarning: Packaged SDP catalog is 8 months old`

pySDP ships with a snapshot of the SDP product catalog. When it gets old, the warning nudges you to either upgrade pysdp or use `source="live"`:

```python
cat = pysdp.get_catalog(source="live")   # fetches fresh from S3
```

Threshold is configurable via `SDP_STALENESS_MONTHS` environment variable (default: 6).

### `KeyError: CatalogID 'R5D042' not found in packaged catalog (dated 2026-04-14)`

Your packaged catalog doesn't know about that ID — likely a newer product. Try:

```python
cat = pysdp.get_catalog(source="live")
cat[cat["CatalogID"] == "R5D042"]
```

If it's there, `pip install -U pysdp` gets you a fresh packaged snapshot.

## Download

### `Cannot expand Daily catalog_id 'R4D004' via catalog_ids=`

Daily products often span years of data — thousands of files. pySDP refuses to expand them implicitly to avoid surprise data-hoard downloads. Two ways forward:

**Open and process without downloading:**

```python
tmax = pysdp.open_raster("R4D004", date_start="2021-01-01", date_end="2021-12-31")
```

**Or hand-pick specific days:**

```python
# Construct the Data.URLs yourself from the catalog template
row = pysdp.get_catalog(deprecated=None).query("CatalogID == 'R4D004'").iloc[0]
urls = [row["Data.URL"].format(year=2021, day=f"{i:03d}") for i in range(1, 8)]
pysdp.download(urls=urls, output_dir="~/tmax-week")
```

### Downloads fail with `403 Forbidden` on some files

The SDP bucket is public, so this usually indicates a deprecated product URL that's been removed. Check:

```python
pysdp.get_catalog(deprecated=None).query("CatalogID == 'YOUR_ID'")[["Product", "Deprecated"]]
```

## Performance envelope

### What's a reasonable workload for pysdp 0.1?

The v0.1 release targets interactive and moderate-scale workflows — **tens to thousands** of points or polygons against SDP rasters. Specifically:

- **Point extraction**: hundreds of points × full SDP rasters → seconds–minutes (with `method="nearest"` + local download).
- **Polygon extraction**: hundreds of polygons × time-series → minutes.
- **Catalog/metadata**: <1 second, offline.
- **Lazy raster reads**: single-digit seconds to open + crop + plot a ~1 GB COG over same-region S3.

For **millions** of points or **continental-scale** workflows, see ROADMAP §Phase 8a — the Dask-aware at-scale path that'll land in 0.2.

## Still stuck?

Open an issue: <https://github.com/rmbl-sdp/pySDP/issues>. Include:

- pysdp version (`pysdp.__version__`)
- Python version (`sys.version`)
- Platform (Linux/macOS/Windows)
- A minimal reproducer
- Full error traceback if applicable
