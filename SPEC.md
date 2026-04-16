# pySDP — Python client for the RMBL Spatial Data Platform

**Status:** Draft specification, v0 (2026-04-16)
**Author:** Ian Breckheimer (ikb@rmbl.org)
**Source of truth for parity:** `~/code/rSDP/` v0.2

---

## 1. Goals & non-goals

### Goals

- Provide a Pythonic client for the RMBL Spatial Data Platform with feature parity to rSDP v0.2: catalog discovery, metadata retrieval, lazy cloud raster access, time-series slicing, point/polygon extraction, and bulk file download.
- Make idiomatic use of the modern scientific Python geospatial stack: `xarray` + `rioxarray` + `rasterio` for rasters, `geopandas` for vectors, `pystac` / `pystac-client` for catalog, `odc-stac` for multi-file stacks, `xvec` and `exactextract` for sampling.
- Interoperate naturally with Dask, so users can scale extractions from points to continental-scale polygon summaries without rewriting code.
- Ship on PyPI and conda-forge with sensible extras so users can install a minimal client or a full stack.

### Non-goals (v0)

- Not a port of rSDP's `terra`-specific return types. Users get `xarray.DataArray` / `xarray.Dataset` / `geopandas.GeoDataFrame`, not `SpatRaster`/`SpatVector` equivalents.
- Not a write path. pySDP is read-only against the SDP; authoring new products is out of scope.
- Not a STAC *server*. We consume the static STAC v1 catalog the R package already references.
- No GUI / map widgets in core. Users compose with `folium`, `leafmap`, `lonboard`, etc. themselves.

---

## 2. Target users & compatibility

- **Users:** researchers at RMBL and collaborators doing environmental science in Western Colorado; people already using `xarray`/`geopandas` for geospatial work. Comfort level ranges from graduate students to senior research scientists.
- **Python support:** follow [SPEC 0](https://scientific-python.org/specs/spec-0000/). At launch (2026): Python 3.11, 3.12, 3.13. Versions are dropped when they fall out of core-dep (numpy, xarray, rasterio) support windows, not proactively — supporting Python versions that still work for users is cheap, so there's no reason to push users off 3.11 until upstream forces it.
- **Platforms:** Linux, macOS (Intel + Apple Silicon), Windows. CI against all three.
- **Core deps' minimum versions (floor only, no upper caps):** `xarray >= 2024.1`, `rioxarray >= 0.15`, `rasterio >= 1.3`, `geopandas >= 1.0`, `pystac >= 1.10`, `pandas >= 2.1`, `numpy >= 1.26`, `shapely >= 2.0`.

---

## 3. Package layout

`src/`-layout, `hatchling` build backend, `pyproject.toml` only.

```
pySDP/
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CLAUDE.md                       # working-with-Claude notes
├── SPEC.md                         # this document
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/
│       ├── ci.yml                  # lint + type + test matrix
│       ├── release.yml             # PyPI trusted publishing
│       └── docs.yml                # mkdocs deploy on push to main
├── src/
│   └── sdp/                        # importable as `import sdp`
│       ├── __init__.py             # re-exports public API
│       ├── _version.py             # hatch-vcs generated
│       ├── constants.py            # SDP_CRS, VSICURL_PREFIX, DOMAINS, TYPES, RELEASES, TIMESERIES_TYPES
│       ├── catalog.py              # get_catalog(), get_metadata()
│       ├── raster.py               # open_raster(), open_stack() — lazy Dataset
│       ├── extract.py              # extract_points(), extract_polygons()
│       ├── download.py             # download()
│       ├── stac.py                 # pystac-client wrapper, static-catalog reader
│       ├── io/
│       │   ├── __init__.py
│       │   ├── vsicurl.py          # GDAL env setup, COG URL builder
│       │   └── template.py         # {year}/{month}/{day} substitution
│       ├── _resolve.py             # time-slice resolvers (Single/Yearly/Monthly/Daily)
│       ├── _validate.py            # argument validation
│       ├── _catalog_data.py        # loads packaged SDP_catalog CSV or fetches fresh
│       └── data/
│           └── SDP_product_table_<date>.csv  # snapshot shipped with package
├── tests/
│   ├── conftest.py
│   ├── fixtures/                   # tiny COGs for moto
│   ├── cassettes/                  # VCR recordings for live-S3 tests
│   ├── test_catalog.py
│   ├── test_raster.py
│   ├── test_extract.py
│   ├── test_resolve.py             # pure, no-network
│   ├── test_validate.py            # pure, no-network
│   └── test_integration.py         # pytest.mark.network
├── docs/
│   ├── index.md
│   ├── getting-started.md
│   ├── guides/
│   │   ├── cloud-data.md           # ports sdp-cloud-data.Rmd
│   │   ├── wrangle-rasters.md      # ports wrangle-raster-data.Rmd
│   │   ├── field-sampling.md       # ports field-site-sampling.Rmd
│   │   └── pretty-maps.md          # ports pretty-maps.Rmd
│   ├── api.md                      # mkdocstrings auto-API
│   └── mkdocs.yml
└── scripts/
    └── update_catalog.py           # refresh packaged CSV snapshot
```

**Rationale:**
- Distribution name and import name are both `pysdp`. The shorter `sdp` import name was considered but the PyPI `sdp` project is taken by an abandoned placeholder, and using a distribution/import split that aliases to `sdp` would create conflict risk for any user who happens to have the placeholder installed. `import pysdp` (five chars) is the idiomatic tradeoff.
- Internal module names `_resolve`, `_validate` mirror the R package's `internal_resolve.R` / `internal_validate.R` so cross-referencing between codebases stays easy during the port.
- Catalog CSV is shipped as package data (frozen snapshot, same model as `sysdata.rda`) and is also fetchable live.

---

## 4. Public API

All functions take and return standard scientific Python types.

### 4.1 Catalog discovery

```python
pysdp.get_catalog(
    domains: Sequence[str] | None = None,
    types: Sequence[str] | None = None,
    releases: Sequence[str] | None = None,
    timeseries_types: Sequence[str] | None = None,
    deprecated: bool = False,
    *,
    source: Literal["packaged", "live", "stac"] = "packaged",
) -> pd.DataFrame | pystac.Catalog
```

- `source="packaged"` (default): filters the CSV snapshot shipped with the release. Emits a `UserWarning` when the snapshot is older than `SDP_STALENESS_MONTHS` (default 6 months; env-configurable), suggesting `source="live"` or a package upgrade.
- `source="live"`: fetches the current CSV from S3.
- `source="stac"`: returns a `pystac.Catalog` object rooted at the SDP's static STAC v1 catalog. Filter arguments are ignored; user uses `pystac` traversal. (Replaces `return_stac=TRUE`.)
- `None` for any filter means "all values"; explicit sequences filter. Values validated against `constants.DOMAINS` etc.

**Unknown `catalog_id` errors** (in `get_metadata` and `open_raster`) include the packaged snapshot date and suggest remediation:

```
CatalogID 'R6D003' not found in packaged catalog (dated 2026-04-14).
Your snapshot may be outdated — try `get_catalog(source='live')` or
upgrade pysdp.
```

```python
pysdp.get_metadata(
    catalog_id: str,
    *,
    as_dict: bool = True,
) -> dict | lxml.etree._Element
```

- Fetches the QGIS-style XML metadata for one dataset via HTTP.
- `as_dict=True` → nested `dict` (via `xmltodict`); `False` → `lxml` Element.

### 4.2 Raster access

```python
pysdp.open_raster(
    catalog_id: str | None = None,
    url: str | None = None,
    *,
    years: Sequence[int] | None = None,
    months: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    chunks: dict | Literal["auto"] | None = "auto",
    download: bool = False,
    download_path: str | os.PathLike | None = None,
    overwrite: bool = False,
    verbose: bool = True,
) -> xr.Dataset
```

- Returns an `xarray.Dataset` with one data variable named after the product's canonical short name (derived from the COG filename basename minus `.tif`, e.g. `UG_dem_3m_v1`). Dims on that variable: `(y, x)` for single-layer, `(band, y, x)` for multi-band, `(time, y, x)` for time-series. CRS set to `EPSG:32613` via `rio.write_crs` on the Dataset.
- Rationale: multi-product raster stacks are routine in RMBL workflows. Returning a `Dataset` keeps `open_raster()` composable with `open_stack()` (below) and with user-side `xr.merge` — users can do `xr.merge([pysdp.open_raster(a), pysdp.open_raster(b)])` to align products on a common grid.
- Uses `rioxarray.open_rasterio(..., chunks=chunks)` under the hood for lazy Dask-backed access; `chunks=None` for eager loading (small rasters only).
- Time-series datasets use `xarray.concat` over a list of per-slice DataArrays, then `.to_dataset()`. The `time` coordinate is **always a `pandas.DatetimeIndex`** for consistency across `Yearly`/`Monthly`/`Daily`:
  - Daily → actual date
  - Monthly → first-of-month
  - Yearly → January 1st of the year
  This lets users write `ds.sel(time="2019")` uniformly and use `.resample`, `groupby("time.year")`, etc. across all TimeSeriesTypes.
- Scale factor / offset from the catalog applied as standard CF `scale_factor` / `add_offset` attrs on the data variable; `xarray` honors these on `ds.decode_cf()`.
- `download=True` downloads the COGs to `download_path` first and opens from disk.
- Mutually exclusive: `catalog_id` XOR `url`. With `url`, scale/offset are skipped (same as rSDP). The variable name in the Dataset comes from the URL basename.

```python
pysdp.open_stack(
    catalog_ids: Sequence[str],
    *,
    years: Sequence[int] | None = None,
    months: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    chunks: dict | Literal["auto"] | None = "auto",
    align: Literal["exact", "reproject"] = "exact",
    verbose: bool = True,
) -> xr.Dataset
```

- Loads multiple SDP products into a single `Dataset` with one variable per product, sharing `x`/`y` coords (and `time` if any are time-series).
- `align="exact"` (default): all products must share grid (CRS + transform + shape); otherwise raises a descriptive error listing the mismatched grids and suggesting `align="reproject"`. Chosen as default because reprojection is expensive at full resolution and should be an explicit user decision.
- `align="reproject"`: reprojects all products to the first product's grid using `odc-stac`-style resampling (requires `[stac]` extra for `odc-stac`).
- Time-series products without a matching time axis broadcast against static products naturally via xarray's alignment rules.

### 4.3 Extraction

Split into two functions for clarity (vs. rSDP's single `sdp_extract_data()`), because point sampling and polygon zonal stats have meaningfully different arguments.

```python
pysdp.extract_points(
    raster: xr.Dataset | xr.DataArray,
    locations: gpd.GeoDataFrame | pd.DataFrame,
    *,
    x: str = "x",                    # column names if locations is a DataFrame
    y: str = "y",
    crs: str | None = None,          # required if locations is a DataFrame
    method: Literal["nearest", "linear"] = "linear",
    years: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    bind: bool = True,
    verbose: bool = True,
) -> gpd.GeoDataFrame
```

```python
pysdp.extract_polygons(
    raster: xr.Dataset | xr.DataArray,
    locations: gpd.GeoDataFrame,
    *,
    stats: Sequence[str] | str = "mean",   # any exactextract-supported op
    exact: bool = False,                   # fractional cell coverage (parity with rSDP default)
    all_cells: bool = False,               # return per-cell values + fraction, skip summary
    years: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    bind: bool = True,
    verbose: bool = True,
) -> gpd.GeoDataFrame | pd.DataFrame
```

- Reprojects `locations` to raster CRS automatically if they differ; message on `verbose`.
- `extract_points` dispatches to `xvec.extract_points` (or `DataArray.xvec.extract_points`) under the hood.
- `extract_polygons` default is `exact=False` (centroid-based, matches rSDP / `terra::extract`). Setting `exact=True` dispatches to `exactextract` for fractional-coverage summaries; the docstring recommends `exact=True` for small polygons relative to cell size.
- `all_cells=True` returns a long-form `DataFrame` with `polygon_id`, `value`, `fraction` (port of `sum_fun=NULL, exact=TRUE`).
- Time-series filtering via `years` / `date_start` / `date_end` mirrors rSDP's `.filter_raster_layers_by_time` exactly.

### 4.4 Download

```python
pysdp.download(
    urls: str | Sequence[str] | None = None,
    output_dir: str | os.PathLike = ...,
    *,
    catalog_ids: str | Sequence[str] | None = None,
    overwrite: bool = False,
    resume: bool = True,
    max_workers: int = 8,
    return_status: bool = True,
) -> pd.DataFrame | None
```

- Accepts `urls` OR `catalog_ids` (mutually exclusive, exactly one required). The `catalog_ids` path resolves each ID to its `Data.URL` via the packaged catalog, then downloads — mirrors the ergonomics of `open_raster(catalog_id=...)` without forcing a `get_catalog()` round-trip.
- For time-series catalog IDs, `catalog_ids` expands to all slices by default. (Pass URLs directly if you want a hand-picked subset.)
- Uses `obstore` (preferred) with `fsspec`+`s3fs` fallback gated by import-time detection. If neither optional dep is installed, falls back to `urllib.request` single-threaded (with a `UserWarning` suggesting `pip install pysdp[download]` for throughput).
- Pre-check for existing files mirrors rSDP: skip or overwrite based on flag; returns a status `DataFrame` with columns `[url, dest, success, status, size]`.

### 4.5 Module-level re-exports

`src/pysdp/__init__.py` re-exports exactly the public API (`get_catalog`, `get_metadata`, `open_raster`, `open_stack`, `extract_points`, `extract_polygons`, `download`) plus `__version__` and the public constants (`SDP_CRS`, `DOMAINS`, `TYPES`, `RELEASES`, `TIMESERIES_TYPES`). Everything else is underscore-prefixed or nested in subpackages and is not part of the stability contract.

---

## 5. rSDP → pySDP mapping

| rSDP (R)                               | pySDP (Python)                                      | Notes                                                                  |
| -------------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------- |
| `sdp_get_catalog()`                    | `pysdp.get_catalog()`                                 | `return_stac=TRUE` → `source="stac"`                                   |
| `sdp_get_metadata()`                   | `pysdp.get_metadata()`                                | `return_list=TRUE` → `as_dict=True`                                    |
| `sdp_get_raster()`                     | `pysdp.open_raster()`, `pysdp.open_stack()`             | Returns `xr.Dataset`, not `SpatRaster`                                 |
| `sdp_extract_data()`                   | `pysdp.extract_points()` + `pysdp.extract_polygons()`   | Split for clarity                                                      |
| `download_data()`                      | `pysdp.download()`                                    | Uses `obstore` / `fsspec` (no `curl::multi_download`)                  |
| `SpatRaster`                           | `xarray.Dataset` (variable per product)             |                                                                        |
| `SpatVector` / `sf::sf`                | `geopandas.GeoDataFrame`                            |                                                                        |
| `terra::extract(fun=mean)`             | `pysdp.extract_polygons(stats="mean")`                | Centroid-based by default; `exact=True` → `exactextract`               |
| `terra::extract(method="bilinear")`    | `pysdp.extract_points(method="linear")`               |                                                                        |
| `/vsicurl/` prefix                     | `pysdp.io.vsicurl` (kept)                             | Transport swappable; may move to `obstore` in v1                       |
| STAC via `rstac::read_stac()`          | `pystac.Catalog.from_file()` / `pystac-client`      |                                                                        |
| `sysdata.rda` snapshot                 | `src/pysdp/data/SDP_product_table_*.csv`              | Refreshed via `scripts/update_catalog.py`                              |
| `R/internal_resolve.R`                 | `src/pysdp/_resolve.py`                               | Behavior-preserving port; anchor-day semantics retained                |
| `R/internal_validate.R`                | `src/pysdp/_validate.py`                              |                                                                        |
| `R/internal_load.R`                    | Folded into `raster.py` + `io/`                     |                                                                        |
| `R/constants.R`                        | `src/pysdp/constants.py`                              |                                                                        |
| `tests/testthat/test-internal_*.R`     | `tests/test_resolve.py`, `tests/test_validate.py`   | Port fixture-based unit tests, no network                              |
| vignettes                              | `docs/guides/*.md`                                  | Jupyter notebooks rendered via `mkdocs-jupyter` or inline code samples |
| `NAMESPACE` (roxygen)                  | `src/pysdp/__init__.py` `__all__`                     |                                                                        |
| pkgdown                                | MkDocs-Material + mkdocstrings                      |                                                                        |

### Behavior carry-overs (do NOT change during port)

- **Daily default clip to 30 layers** when no date bounds given (rSDP `internal_resolve.R` D2).
- **Anchor-day `seq(by="month"/"year")` semantics** for Monthly/Yearly date-range branches. Reproduce with `pd.date_range(start=first_overlap_day, end=..., freq=...)` starting from the first overlap day, NOT from calendar boundaries. See the comment block at top of `internal_resolve.R`.
- **Error-on-empty-overlap / warn-on-partial-overlap** for Monthly date ranges (rSDP fixed a silent-failure bug here; preserve the fixed behavior).
- **Single-layer URL branch** skips scale/offset application.
- All SDP raster CRS is hard-coded to `EPSG:32613`.

---

## 6. Dependencies

### Required (runtime)

```
numpy >= 1.26
pandas >= 2.1
xarray >= 2024.1
rioxarray >= 0.15
rasterio >= 1.3
geopandas >= 1.0
shapely >= 2.0
pystac >= 1.10
pyproj >= 3.6
requests >= 2.31
lxml >= 4.9
xmltodict >= 0.13
xvec >= 0.3
```

### Optional extras

```toml
[project.optional-dependencies]
stac     = ["pystac-client>=0.7", "odc-stac>=0.3"]
exact    = ["exactextract>=0.2"]
download = ["obstore>=0.3", "fsspec>=2024.1", "s3fs>=2024.1"]
viz      = ["matplotlib>=3.8", "folium>=0.15"]
dask     = ["dask[array]>=2024.1"]
all      = ["pysdp[stac,exact,download,viz,dask]"]
```

### Dev dependency groups (PEP 735)

```toml
[dependency-groups]
test = ["pytest>=8", "pytest-cov", "pytest-recording", "moto[s3]>=5"]
lint = ["ruff>=0.5", "pre-commit"]
type = ["mypy>=1.10", "pandas-stubs", "types-requests"]
docs = ["mkdocs-material", "mkdocstrings[python]", "mkdocs-jupyter"]
dev  = [
    {include-group = "test"},
    {include-group = "lint"},
    {include-group = "type"},
    {include-group = "docs"},
]
```

**Rationale:**
- `xvec` is pure-Python and small; promoting it to core means `extract_points` and `extract_polygons(exact=False)` — the common cases — work on a minimal `pip install pysdp`.
- Only the `exact=True` path (fractional coverage via `exactextract`, which wraps native code) is gated behind the `[exact]` extra.
- `odc-stac` stays optional because STAC access is opt-in via `source="stac"` and `open_stack(align="reproject")`.
- `pip install pysdp[all]` gets everything.

---

## 7. Build, tooling, release

- **Build backend:** `hatchling` with `hatch-vcs` for version-from-git-tag.
- **Lint + format:** `ruff` (lint + format, replacing black/isort/flake8). Config in `pyproject.toml`. Line length 100.
- **Type checking:** `mypy` in strict mode on `src/pysdp/`; looser on `tests/`.
- **Pre-commit:** ruff, mypy, trailing-whitespace, end-of-file-fixer, check-yaml.
- **Test runner:** `pytest`. Markers: `@pytest.mark.network` (skipped by default; run nightly). `pytest-recording` cassettes checked into `tests/cassettes/` for replay.
- **CI (`.github/workflows/ci.yml`):** matrix of (linux, macOS, windows) × (3.11, 3.12, 3.13). Lint → type-check → test → coverage upload.
- **Docs:** MkDocs-Material + mkdocstrings[python]; auto-deploy on push to `main` via `.github/workflows/docs.yml` to GitHub Pages at `rmbl-sdp.github.io/pySDP`.
- **Release:**
  - **PyPI:** Trusted Publishing via GitHub Actions OIDC on tagged releases. Prereleases (0.0.x, 0.1.0rcN) ship to PyPI only.
  - **conda-forge:** feedstock submitted to `conda-forge/staged-recipes` after the first stable `0.1.0` release (not prereleases), using `grayskull pypi pysdp` to bootstrap `meta.yaml`. Rationale: RMBL's scientist audience is disproportionately on conda environments; submitting at 0.1.0 avoids recipe churn from prerelease dep shuffling while still getting conda coverage in place for the first announced release. Once the feedstock exists, `regro-cf-autotick-bot` auto-PRs new versions.
- **Dev workflow:** `uv` first-class — `uv sync --all-groups --all-extras` for contributor setup. `pip install -e .` still works for users who don't want `uv`.

---

## 8. Testing strategy

Mirrors rSDP's two-tier approach.

**Tier 1 — pure unit tests (no network):**
- `test_validate.py`, `test_resolve.py`: port the 58 testthat unit tests one-for-one using in-memory `pd.DataFrame` fixtures mirroring `.fake_cat_line()`. These are the core correctness tests and should run in < 1 second.
- `test_catalog.py` (filter logic): construct synthetic catalog DataFrame and exercise `get_catalog` filter branches.

**Tier 2 — integration tests (network-gated):**
- `test_integration.py`, marked `@pytest.mark.network`. Runs against real S3; skipped by default in `pytest`. CI has a nightly job that runs them and alerts on failure. A failing network test could be a bug *or* a moved dataset — same caveat as the R package's `CLAUDE.md`.
- `test_raster.py`: mixed — resolver logic mocked via `moto`+tiny COGs for CI; optional live-S3 smoke test under the `network` marker.

**Regression pins:** port rSDP's `names(raster)` output pins to pinned tests for `Dataset.coords["time"]` values and data-variable names. These have already caught silent refactor regressions once.

---

## 9. Phased porting plan

### Phase 0 — Scaffolding (0.5 days)

- Initialize from `copier copy gh:scientific-python/cookie .` (adjusted for `src/pysdp/` layout).
- Set up `pyproject.toml`, ruff, mypy, pre-commit, CI skeleton.
- Write this spec into the repo (already done).

### Phase 1 — Catalog + metadata (1–2 days)

- Port `R/constants.R` → `constants.py`.
- Port `data-raw/SDP_catalog.R` → `scripts/update_catalog.py`; bake snapshot CSV into package data.
- Implement `get_catalog()` (all three sources) and `get_metadata()`.
- Unit tests + one network integration test.

### Phase 2 — Validation + time-slice resolvers (2–3 days)

- Port `_validate.py` and `_resolve.py` line-by-line; preserve anchor-day semantics documented in rSDP's `internal_resolve.R` header comment.
- Port the 58 testthat unit tests to pytest.
- No raster I/O yet.

### Phase 3 — Raster access (2–3 days)

- Implement `open_raster()` for `Single` first (simplest), then `Yearly`, `Monthly`, `Daily`. All branches return `xr.Dataset`.
- Implement `open_stack()` on top of `open_raster()` with grid-alignment checks.
- `io/vsicurl.py`: GDAL env setup helper (sets the recommended `GDAL_DISABLE_READDIR_ON_OPEN`, `CPL_VSIL_CURL_ALLOWED_EXTENSIONS`, `VSI_CACHE` env vars on import if not already set).
- `io/template.py`: port `.substitute_template`.
- Scale/offset as CF `scale_factor` / `add_offset` attrs.
- Network-gated integration tests against two representative products (one `Single`, one `Daily`).

### Phase 4 — Extraction (2–3 days)

- `extract_points()` via `xvec`.
- `extract_polygons()` via `xvec.zonal_stats` (centroid, default); `exactextract` path for `exact=True` (gated by `[exact]` extra).
- Port rSDP's bind/return-shape behavior.

### Phase 5 — Download (1 day)

- `download()` with `obstore` primary path, `fsspec`+`s3fs` fallback.
- Port existing-files pre-check behavior.

### Phase 6 — Docs + release (2 days)

- Port the four vignettes to MkDocs guides (either Markdown + code blocks or Jupyter via `mkdocs-jupyter`).
- First 0.1.0 release to PyPI via Trusted Publishing.
- conda-forge feedstock PR.

**Total rough estimate:** ~12 working days for a v0.1 with parity to rSDP v0.2.

**Post-v0.1 work** (Hub integrations, distributed extraction recipes, rSDP parity) is scoped separately in [ROADMAP.md](./ROADMAP.md).

---

## 10. Resolved design decisions (was: open questions)

1. **Return type of `open_raster()`: `xarray.Dataset`.** Multi-product raster stacks are routine in RMBL workflows; `Dataset` composes cleanly with `pysdp.open_stack()` and with user-side `xr.merge`. See §4.2.
2. **Time-coordinate dtype: `pandas.DatetimeIndex` uniformly.** Daily → actual date, Monthly → first-of-month, Yearly → January 1st. Consistent across all TimeSeriesTypes; full support for xarray datetime accessors and resampling. See §4.2.
3. **`extract_polygons` default: `exact=False`.** Preserves parity with rSDP / `terra::extract` (centroid-based). `exact=True` is available and recommended for small-polygon / coarse-cell cases; docstring calls out the tradeoff. See §4.3.
4. **Catalog source default: hybrid.** `source="packaged"` remains the default (offline, reproducible). Staleness warning emitted when the packaged snapshot is older than a configurable threshold (see Q6 resolution below). `source="live"` and `source="stac"` available explicitly. See §4.1 and Q6.
5. **Conda-forge feedstock timing: after `0.1.0` stable release.** Prereleases ship to PyPI only. First stable release gets a `staged-recipes` PR bootstrapped via `grayskull`; ongoing updates handled by `regro-cf-autotick-bot`. Rationale: most of pySDP's audience lives in conda environments because of GDAL/PROJ/GEOS dep pain with pip-only installs, so the first announced release should be installable via `conda install -c conda-forge pysdp`. See §7.

6. **Catalog staleness handling: time-based warning + helpful unknown-ID error.**
   - `get_catalog(source="packaged")` emits a `UserWarning` when the packaged snapshot is older than `SDP_STALENESS_MONTHS` (default 6, env-configurable). Uses the date parsed from the packaged CSV filename; no network call.
   - `get_metadata()` and `open_raster()` raise a descriptive error when a catalog_id isn't in the packaged snapshot, including the snapshot date and suggested remediation (`source="live"` or `pip install -U pysdp`).
   - No live ETag check (rejected: adds per-session network latency, hurts offline workflows).
   - No auto-fallback to live (rejected: same call returning different data depending on install age is hard to reason about).
   - Implementation lives in `src/pysdp/_catalog_data.py`. See §4.1.

---

## 11. References

- Scientific Python Development Guide: <https://learn.scientific-python.org/development/>
- SPEC 0 (version support): <https://scientific-python.org/specs/spec-0000/>
- PEP 735 (dependency groups): <https://peps.python.org/pep-0735/>
- odc-stac: <https://odc-stac.readthedocs.io/>
- xvec: <https://xvec.readthedocs.io/>
- exactextract: <https://github.com/isciences/exactextract>
- obstore: <https://developmentseed.org/obstore/>
- uv: <https://docs.astral.sh/uv/>
- rSDP (reference implementation): `~/code/rSDP/` — also <https://github.com/rmbl-sdp/rSDP>
