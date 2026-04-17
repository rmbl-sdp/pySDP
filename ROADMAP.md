# pySDP — Post-v0.1 Roadmap

**Status:** Scoping document. Not a commitment; not part of the v0.1 spec.
**Scope:** Two tracks of post-v0.1 work: (1) platform integrations between pySDP and the [CHESS Analysis Hub](../CHESS_Analysis_Hub/) — a RMBL-operated JupyterHub on AWS EKS (us-east-2), colocated with the SDP S3 bucket; (2) support for high-dimensional array stores (icechunk / VirtualiZarr-backed datasets) alongside the existing COG raster products.
**Companion doc:** [SPEC.md](./SPEC.md) (v0.1 — feature-parity port of rSDP v0.2).

---

## 1. Motivation

The CHESS Hub sits in the same AWS region (us-east-2) as the SDP data bucket, giving users effectively unlimited-bandwidth, zero-egress access to SDP COGs. The analysis image already ships `xarray`, `rioxarray`, `dask`, `geopandas`, `pystac`, `boto3`, `s3fs`, and (in the near future) pySDP itself.

What's missing today:
- **No distributed Dask**: the Hub has `dask` + `dask-labextension` but no Dask Gateway or other multi-pod cluster spawner. Users are limited to in-pod parallelism.
- **No Hub-aware defaults in pySDP**: users have to hand-configure GDAL env vars, S3 signing, and cluster options.
- **No distributed-extraction recipes**: community has no blessed pattern for scaling `extract_points` / `extract_polygons` across millions of geometries. Roll-your-own territory.
- **No support for high-dimensional array stores**: several critical SDP datasets (e.g., AOP imaging-spectrometer mosaics — 426 bands × 30 000 × 22 000 pixels, ~1 TB per mosaic) are stored as tiled netCDF files wrapped by [VirtualiZarr](https://virtualizarr.readthedocs.io/) into [icechunk](https://icechunk.io/) stores on S3. These don't fit the COG-per-time-slice model that v0.1's `open_raster()` targets. Users currently open them via a multi-step `icechunk.s3_storage → Repository.open → xr.open_zarr` recipe (see [`01_distributed_analysis_with_dask.ipynb`](../CHESS_Analysis_Hub/docker/tutorials/01_distributed_analysis_with_dask.ipynb) in the CHESS Hub tutorials). pySDP should collapse that into a one-liner that composes with the existing extraction and catalog functions.

These are the gaps the roadmap targets.

## 2. Design principles

These are load-bearing — violating them is what has burned other domain packages.

1. **Nothing "Hub" in the core install.** `pip install pysdp` must work on a laptop without kubernetes, dask-gateway, or boto3 plugins anywhere. Hub features live in a `pysdp.hub` submodule behind a `[hub]` extra with lazy imports.
2. **No silent behavior changes from env-var detection.** `pysdp.on_hub()` is a utility users can check. pySDP's own code paths never branch on hub detection — that's how you ship reproducibility bugs.
3. **No Dask `Client` created by pySDP.** `Client()` with no args silently registers as the default scheduler for the process. Domain packages that do this shadow user-managed clients and cause hard-to-diagnose failures. pySDP's readers return lazy Dask-backed arrays; the user brings the client.
4. **Defer to `boto3` / GDAL credential chains.** IRSA on the Hub "just works" with the default boto3 and GDAL ≥3.5 chains. Don't wrap credentials. The one exception: scope `AWS_NO_SIGN_REQUEST=YES` to SDP-bucket reads only (never global), so users mixing public-SDP reads with private-user-bucket writes don't get burned.
5. **Environment-var defaults via `setdefault`, never clobber.** If the user set `GDAL_DISABLE_READDIR_ON_OPEN=NO` for a legitimate reason, pySDP must not overwrite it. Either `os.environ.setdefault(...)` or (preferred) scope config via `rasterio.Env(...)` inside pySDP's own readers.
6. **Reuse community helpers where they exist.** odc-stac already ships `configure_rio(client=client, cloud_defaults=True)` for broadcasting GDAL env to Dask workers. pySDP's `configure()` should wrap it, not reimplement it.
7. **Backend-agnostic return types.** Whether the underlying store is a COG on VSICURL, a Zarr store via icechunk, or a future format, pySDP always returns `xarray.Dataset` with standardized coordinate names (`x`, `y`, optionally `time`) and CRS set via `rio.write_crs`. This lets `extract_points`, `extract_polygons`, `rio.clip_box`, and `.plot.imshow` work identically across backends. Backend-specific knobs (e.g., icechunk `authorize_virtual_chunk_access`) are exposed as kwargs on the opener, not baked into the Dataset.

## 3. Proposed phases

Phase numbering continues from [SPEC.md §9](./SPEC.md#9-phased-porting-plan), which ends at Phase 6.

### Phase 7 — Cloud-optimized reads & Hub submodule (~3 days)

**Target:** pySDP on the Hub is a strictly better experience than pySDP on a laptop, with no code changes from the user.

**Sequencing:** Phase 7 is blocked on §4 item 1 (Dask Gateway deployed on the CHESS Hub) for end-to-end testing. Code and docs can proceed in parallel with the Hub infra work; the `pysdp.hub.configure(client)` path needs a real gateway to validate against.

**Success criterion (aspirational):**

> A grad student opens a notebook on the CHESS Hub, runs:
>
> ```python
> from dask_gateway import GatewayCluster
> import pysdp
>
> cluster = GatewayCluster(**pysdp.hub.cluster_options(n_workers=20))
> client = cluster.get_client()
> pysdp.hub.configure(client)
>
> tmax = pysdp.open_raster("R4D004",
>                          date_start="1994-01-01",
>                          date_end="2024-12-31")
> field_sites = gpd.read_file("field_sites.gpkg")   # ~500 points
> samples = pysdp.extract_points(tmax, field_sites)
> ```
>
> and gets results in **under one minute** of wall-clock time.
>
> *Note: "under a minute" is aspirational — tight but achievable on ~20 workers at same-region bandwidth, assuming GDAL env is tuned and points localize to one domain. Worth measuring against to see whether we're within the envelope; if we can't hit it, that's useful information about where the real bottleneck lives.*

**Deliverables:**

- `pysdp.io.vsicurl.cloud_defaults()` → returns the canonical GDAL-on-S3 env dict (see [SPEC §Phase 3](./SPEC.md#phase-3--raster-access-23-days) — fold this into Phase 3 if schedule allows). Defaults derived from odc-stac's `cloud_defaults`:
  ```
  GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
  CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.TIF,.tiff
  VSI_CACHE=TRUE
  VSI_CACHE_SIZE=5000000
  GDAL_HTTP_MULTIPLEX=YES
  GDAL_HTTP_VERSION=2
  GDAL_HTTP_MAX_RETRY=4
  GDAL_HTTP_RETRY_DELAY=0.5
  AWS_REGION=us-east-2
  ```
  Applied via `rasterio.Env(**cloud_defaults())` inside `open_raster` / `open_stack` / `download` — never mutating global `os.environ`.
- `pysdp.io.vsicurl.sdp_unsigned_env()` — context manager scoping `AWS_NO_SIGN_REQUEST=YES` + anonymous-credential env vars *only* around SDP-bucket reads. Mitigates the documented rasterio #1984 gotcha where `NO_SIGN_REQUEST` alone still triggers boto3 IMDS hangs.
- `pysdp.hub` submodule (new, gated by `[hub]` extra) — **generic**, usable on any Dask-Gateway-enabled JupyterHub (CHESS, LEAP-Pangeo, CryoCloud, etc.), not CHESS-specific:
  - `on_hub() -> bool` — cheap probe via `"JUPYTERHUB_USER" in os.environ`. Does not make network calls.
  - `has_dask_gateway() -> bool` — probe via `"DASK_GATEWAY__ADDRESS" in os.environ`.
  - `cluster_options(**overrides) -> dict` — returns a dict of sensible generic defaults (worker memory, CPU count, chunk-size-aware worker sizing) that can be passed to `Gateway().new_cluster(**opts)`. Returns empty `{}` by default if no generic recommendation applies; `**overrides` lets callers set/replace keys. Hub-specific values (image tags, pool names for CHESS) live in the docs guide, not in library code.
  - `configure(client, *, cloud_defaults=True, unsigned=True)` — wraps `odc.stac.configure_rio(...)` to broadcast GDAL env and the SDP-bucket unsigned setting to every current and future Dask worker. This is the one helper users actually need.
- New `[hub]` extra: `["dask-gateway>=2024.1", "pysdp[stac]"]`. The self-reference pulls in `odc-stac` via the `[stac]` extra — avoids version-skew duplication.
- Docs page: **"Using pySDP on the CHESS Analysis Hub"** — shows the canonical `GatewayCluster()` three-liner + `pysdp.hub.configure(client)` + a real workflow (daily Tmax across UG for 30 years, extracted at field sites). CHESS-specific `cluster_options` overrides (image tag matching the user pod's image, memory sized to the CHESS worker-pool defaults) are documented here, not hardcoded in `pysdp.hub`.

**Out of scope for this phase:**
- Deploying Dask Gateway onto the CHESS Hub. That's a change in `~/code/CHESS_Analysis_Hub` (Helm values + IRSA role for the gateway controller), not a pySDP change. Phase 7 of pySDP assumes the Hub has it; see §4 below.

### Phase 8a — Distributed extraction: partition helpers & first recipe (~5 days)

**Target:** ship the first usable primitives for at-scale extraction and one working end-to-end recipe. This is genuine R&D, not a port — the community has no blessed pattern ([Pangeo's 2025 Discourse thread](https://discourse.pangeo.io/t/advice-for-scalable-raster-vector-extraction/4129) is the consensus post and its consensus is "there isn't one yet").

**Known upstream issues** we are designing around, not fixing:
- `xvec.zonal_stats` with a Dask-backed `DataArray` rasterizes the full polygon mask per call, defeating chunked reads. Reported upstream; unresolved as of April 2026.
- `xvec.extract_points` parallelizes correctly but currently loads whole chunks to extract a handful of points — inefficient for sparse point sets.
- `exactextract` streams over raster blocks with bounded memory and is the right primitive, but its Python bindings don't yet compose cleanly with Dask futures.

**Deliverables:**

- `pysdp.extract._partition_points_by_raster_tile(points, raster)` — spatial partition helper. Groups a point `GeoDataFrame` by the COG tile (block) each point falls in, producing per-tile sub-frames that can be mapped as independent Dask tasks.
- One recipe in `docs/guides/distributed-extraction.md`: "10M-point extraction against a 1000-layer daily stack" — partition → map `xvec.extract_points` per tile → concatenate. Demonstrated and timed on a real Dask Gateway cluster.
- Written design note capturing what we tried, what worked, what didn't — feeds Phase 8b.

**Explicitly out of Phase 8a:** polygon-split/recombination (harder, different shape), a polished benchmark harness, a second recipe. Those are Phase 8b.

### Phase 8b — Polygon zonal stats at scale + benchmark harness (separate release; likely 2–3 weeks calendar time)

**Target:** generalize Phase 8a's pattern to polygons with partial-cell fractional coverage, and publish reproducible benchmarks so users know what to expect.

**Deliverables:**

- `pysdp.extract._partition_polygons_by_raster_tile(polygons, raster, overlap="clip")` — analog of the point partitioner; `overlap="clip"` splits polygons at tile boundaries and the downstream recipe recombines area-weighted stats.
- Recipe: "50k-polygon zonal stats against a 30-year Tmax stack" — partition → `exactextract` per tile → area-weighted sum of per-tile partial sums.
- Benchmark harness: 3–5 canonical workloads sized to run on a single Dask Gateway cluster in < 30 min. Numbers published in the docs with timestamped notes about package versions.

Sequencing this separately because polygon-split-and-recombine is genuinely harder than point partitioning, and premature benchmarking is a trap — we want users running Phase 8a's point recipe first to validate the approach before investing in the polygon generalization.

**What we're explicitly not building across Phase 8:** a high-level `pysdp.extract_points_at_scale(...)` one-liner.

*Why not:* "at-scale extraction" isn't one problem — it's a family of problems whose optimal strategy varies along at least five axes: point density vs. tile size, temporal depth, memory per worker, network-vs-compute locality, and output shape (long/wide/aggregated). Every pick is right for some real workflow and wrong for another. Prior community attempts illustrate this: `stackstac.stack()` works for the STAC-COG happy path but users regularly fall off it on mixed-CRS / heterogeneous-nodata / sparse-time collections; `odc-stac` deliberately exposes composable primitives instead after its authors' datacube experience; `rasterstats` has been accumulating parameters for a decade without closing the gap. The failure mode is predictable: ship `do_everything(...)` → it works for early users → user #7 has a slightly different shape → add `chunk_strategy=`/`partition_size=`/`output_format=` parameters → 18 months later the signature has 22 knobs and users roll their own anyway.

*What we get by shipping partition helpers + recipes instead:* composability (partitioners pair with any extractor, not locked to xvec); transparency (user's Dask graph is visible in the notebook, not a black box); upstream evolution stays free (when xvec/exactextract fix the documented Dask issues, user code keeps working without a pysdp release); honesty (we don't ship a one-liner that pretends distributed extraction is solved when it isn't).

*When we'd reconsider:* if the community converges on a canonical pattern we import it; if pySDP users on the CHESS Hub consistently write the same 5–10 lines before our recipe, we wrap *that specific narrow shape* (e.g. `extract_daily_climate_at_sites(sites, variable, years)`) — not a general at-scale extractor. Narrow shapes can be optimized; general ones can't.

### Phase 9 — Hub-side integration polish (~1 day)

Minor ergonomic items that only make sense once Phases 7–8 are in place:

- Pre-populate a `~/pysdp-examples/` directory on first Hub login (via a Hub-side post-start hook in `docker/Dockerfile`, not in pySDP itself) with the docs recipes as runnable notebooks.
- Opt-in live-catalog on the Hub: `pysdp.hub.configure(client, catalog_source="live")` flips the default for that session. Per Principle 2, never silent; user asks for it explicitly. Low effort; ~1 hour.

### Phase 10 — Icechunk / VirtualiZarr array-store integration (~5–6 days)

**Target:** SDP's high-dimensional array stores (AOP imaging-spectrometer mosaics, future climate/LiDAR cubes) are as easy to discover and work with as COG rasters — one function call to open, full compatibility with pySDP's extraction and plotting functions, lazy Dask-backed reads out of the box.

**Context:** Several critical SDP datasets are stored as tiled netCDF files on S3, wrapped by [VirtualiZarr](https://virtualizarr.readthedocs.io/) into [icechunk](https://icechunk.io/) stores. These are fundamentally different from the COG-per-time-slice model: they're high-dimensional cubes (e.g., 426 spectral bands × 30 000 × 22 000 spatial pixels ≈ 1 TB per AOP mosaic), natively chunked in Zarr format (25 × 500 × 500), and accessed via `icechunk.s3_storage → Repository.open → xr.open_zarr`. The current access recipe is ~8 lines of boilerplate (bucket, prefix, region, auth, repo, session, open_zarr) that users have to remember or copy from tutorials.

#### Phase 10a — Catalog extension (~1 day)

Extend the SDP product catalog to include icechunk store entries alongside COG rows:

- Add a `BackendType` column: `"cog"` (existing products) or `"icechunk"` (new stores).
- Add columns for icechunk-specific metadata: `StorageBucket`, `StoragePrefix`, `StorageRegion`.
- `get_catalog()` returns both types seamlessly. Users filter via `get_catalog(backend_types=["icechunk"])` or similar; unfiltered calls return everything.
- Existing COG workflows are unaffected (the new column defaults to `"cog"` for all 156 existing products).
- Update `scripts/update_catalog.py` to handle the new schema.

#### Phase 10b — `open_store()` function (~2–3 days)

New public API function alongside `open_raster`:

```python
pysdp.open_store(
    catalog_id: str,
    *,
    wavelengths: Sequence[float] | None = None,   # band selection
    bbox: tuple[float, float, float, float] | None = None,
    chunks: dict | Literal["auto"] | None = "auto",
    standardize_coords: bool = True,
    anonymous: bool = True,
) -> xr.Dataset
```

Internally:

1. Look up catalog row; assert `BackendType == "icechunk"`.
2. Construct `icechunk.s3_storage(bucket=..., prefix=..., region=..., anonymous=...)`.
3. `Repository.open(storage, authorize_virtual_chunk_access={...})`.
4. `xr.open_zarr(repo.readonly_session(branch="main").store)`.
5. If `standardize_coords=True` (default): rename `easting` → `x`, `northing` → `y`; write CRS as `EPSG:32613` via `rio.write_crs`. This makes `extract_points`, `extract_polygons`, `rio.clip_box`, and `.plot.imshow` work without extra setup.
6. If `wavelengths` is specified: `.sel(wavelength=wavelengths, method="nearest")`.
7. If `bbox` is specified: `.sel(x=slice(xmin, xmax), y=slice(ymax, ymin))` (note: y may be decreasing).

The function collapses the current 8-line tutorial recipe into:

```python
ds = pysdp.open_store("AOP001")                    # full mosaic, lazy
ds = pysdp.open_store("AOP001", wavelengths=[660, 850])  # just red + NIR
ds = pysdp.open_store("AOP001", bbox=(325000, 4314000, 327000, 4316000))  # 2 × 2 km
```

New `[icechunk]` optional extra: `["icechunk>=0.1", "zarr>=3"]`. Calling `open_store()` without it raises `ImportError` with a helpful message (`pip install pysdp[icechunk]`).

Re-exported from `pysdp.__init__` alongside the existing seven public functions.

**Design decision: `open_store()` vs extending `open_raster()`**

A separate function rather than overloading `open_raster()` because:

- The data model is different: 3D+ cubes with a `wavelength` axis, not 2D rasters with optional `time`.
- The kwargs are different: `wavelengths=` makes no sense for COGs; `years=`/`months=`/`date_start=`/`date_end=` make no sense for single-mosaic spectrometer stores.
- The backend is different: icechunk → Zarr vs. rioxarray → GDAL VSICURL.
- Users can tell at a glance which storage model they're hitting.

The return type is the same (`xr.Dataset`), and the standardized coord names (`x`, `y`, CRS set) mean all downstream functions (`extract_*`, `rio.*`, `plot.*`) compose identically. The "one return type, multiple openers" pattern matches rioxarray's own design (`open_rasterio` for COGs, `open_zarr` for Zarr).

#### Phase 10c — Extraction compatibility verification (~1 day)

With `standardize_coords=True` (the default), `extract_points` and `extract_polygons` should work on icechunk-backed Datasets without code changes — the coord names and CRS already match what the extraction functions expect.

Verify and document:

- Point extraction on a 3D cube requires band selection first: `ds.sel(wavelength=850)` before `extract_points()`. The extraction functions operate on 2D spatial slices; passing a 3D cube without reducing the band dimension raises a descriptive error.
- Zonal stats work per-band if the band dimension is present (xvec iterates over non-spatial dims).
- Dask chunking propagates through extraction (lazy in → lazy out, `.compute()` at the end).
- Performance: same-region S3 reads at Zarr chunk granularity (25 × 500 × 500 ≈ 2 MB per chunk) should be fast; test and document latency expectations.

#### Phase 10d — Docs + user guide (~1 day)

New guide: `docs/guides/array-stores.md` — "Working with hyperspectral and high-dimensional SDP data":

- Discovery: `get_catalog(backend_types=["icechunk"])`
- Opening: `open_store()` with band selection and spatial subsetting
- NDVI recipe: `ds.sel(wavelength=[660, 850])` → normalized difference → `.compute()`
- Extraction at field sites: `.sel(wavelength=850)` → `extract_points()`
- Full-mosaic analysis with Dask: reduce-before-compute pattern, worker tuning
- Performance tips: chunk-aligned spatial slicing, when to use `open_store(bbox=...)` vs full mosaic
- Saving results: NetCDF, GeoTIFF via rioxarray, Zarr

This guide replaces the current tutorial notebook pattern (`01_distributed_analysis_with_dask.ipynb`) with a docs-site-hosted walkthrough that's discoverable alongside the COG guides.

#### Open questions (to resolve before implementation)

1. **How many icechunk stores exist today, and how many are planned?** If 3–5, extending the existing catalog CSV is clean. If dozens with rapid growth, a separate catalog or a STAC-based discovery mechanism makes more sense.
2. **Are all stores on `rmbl-chess-data` or also on `rmbl-sdp`?** Determines whether `open_store()` needs to handle multiple buckets.
3. **Auth: always anonymous?** The current tutorial uses `anonymous=True`. If some stores will require IRSA credentials (e.g., embargoed pre-publication data), `open_store()` needs an `anonymous=` flag that defaults to whatever the catalog says per-product.
4. **Coord naming convention**: is `easting`/`northing` standard across all icechunk stores, or do some use `x`/`y` natively? Determines how robust the rename logic needs to be.
5. **Time dimension**: the current AOP stores are one mosaic per domain/year (no `time` dim). Will future stores have a `time` axis (e.g., multi-year climate cubes)? If so, `open_store()` should accept `date_start`/`date_end` for those.
6. **VirtualiZarr version pinning**: the VirtualiZarr + icechunk ecosystem is moving fast (both < 1.0). Pin conservatively and document the tested version matrix.

## 4. Prerequisites on the Hub (not pySDP work)

These changes live in `~/code/CHESS_Analysis_Hub` and are required before Phase 7 becomes meaningful:

1. **Install Dask Gateway** via the [DaskHub Helm chart](https://helm.dask.org/). Adds a gateway controller + gateway proxy, configured to use JupyterHub auth. Sets `DASK_GATEWAY__*` env vars in user pods automatically.
2. **Add an IRSA role for the gateway controller** with permissions to create worker pods in the `dask-gateway` namespace. Scoped narrowly; no cross-namespace reach.
3. **Grant user-pod IRSA read access to `rmbl-sdp`** (currently only `rmbl-chess-data` is in the policy). The SDP bucket is public, so this is only needed if you ever want signed requests (higher throughput, bucket-level logging). Low priority.
4. **Bake GDAL cloud-defaults into the user image** via `ENV` lines in `docker/Dockerfile`. Duplicates what `pysdp.io.vsicurl.cloud_defaults()` would apply on import, but makes the defaults available to non-pySDP tools (rasterio scripts, QGIS sessions, etc.) in the same pod.

Rough Hub-side effort: ~2 days for an operator familiar with the Helm chart. The CHESS repo's existing Terraform + Helm structure makes this a values-file change rather than new infra.

## 5. rSDP parity note

Long-term intent is that rSDP offer comparable (but scoped-down) Hub integrations. Detailed scope is deferred to `~/code/rSDP/ROADMAP.md` and should be drafted when rSDP work actually begins — the 2026 R parallelism landscape (what the `future` ecosystem looks like, which `mirai`/`crew`-style packages have traction, what `terra` offers natively for distributed reads) is worth re-researching rather than pinning down speculatively here. Likely narrower than pySDP's story because R lacks a mature Dask-Gateway analog and most users won't get multi-node parallelism regardless.

## 6. Out of scope (explicitly)

- **A `pysdp.compute()` / `pysdp.pipeline()` DSL.** The community tried this at odc-stac and pulled it back; DSLs for geospatial Dask processing don't generalize. Users should compose `open_raster` + xarray + their own Dask graphs.
- **A pySDP-hosted catalog service.** The static STAC catalog on S3 is already zero-cost; there's no reason to add a runtime API.
- **Multi-cloud / non-AWS backends.** SDP data is on AWS us-east-2. Adding Azure Blob or GCS abstractions for a single-region dataset is speculative.
- **A `pysdp.dashboard` web UI.** Out of scope; users compose with leafmap/folium/panel on their own.
- **IPython magics (e.g. `%pysdp_hub_info`).** Avoid adding IPython-specific surface area; users can write a one-liner themselves.

## 7. Deferred (revisit with more user data)

- **xarray accessor pattern** (`ds.pysdp.extract_points(gdf)`, `ds.pysdp.to_sites(...)`, etc.). rioxarray ships `ds.rio.*`; some packages like it, some hate it. Trade-off is discoverability (users find methods on their Dataset) vs. hidden magic (methods that aren't obviously from pySDP). Not enough user data yet to decide; revisit after Phase 7 ships and we see how users actually write pySDP code.

## 9. References

- [Hub exploration notes from this doc's scoping phase](../CHESS_Analysis_Hub/SPECIFICATION.md) — Hub architecture + deployment
- [SPEC.md §9](./SPEC.md#9-phased-porting-plan) — v0.1 phases 0–6
- [2i2c: Launch a dask-gateway cluster](https://docs.2i2c.org/user/scalable-computing/launch-dask-gateway-cluster/) — the canonical user-facing pattern
- [DaskHub Helm chart](https://blog.dask.org/2020/08/31/helm_daskhub) — deployment reference for the Hub-side prerequisite
- [odc-stac: configure_rio](https://odc-stac.readthedocs.io/en/latest/_api/odc.stac.configure_rio.html) — GDAL env broadcast to Dask workers
- [opendatacube/benchmark-rio-s3 report](https://github.com/opendatacube/benchmark-rio-s3/blob/master/report.md) — same-region COG-read performance envelope
- [rasterio issue #1984](https://github.com/rasterio/rasterio/issues/1984) — `AWS_NO_SIGN_REQUEST` + boto3 IMDS hang gotcha
- [Pangeo Discourse: Advice for scalable raster-vector extraction](https://discourse.pangeo.io/t/advice-for-scalable-raster-vector-extraction/4129) — the state of the art on distributed extraction (i.e., there isn't one)
- [Planetary Computer: Scale with Dask](https://planetarycomputer.microsoft.com/docs/quickstarts/scale-with-dask/) — reference implementation for the "tell users the 3-liner" docs pattern
- [CryoCloud: Dask for Geoscientists](https://book.cryointhecloud.com/tutorials/dask_for_geoscientists.html) — another reference implementation
- [icechunk documentation](https://icechunk.io/) — cloud-native versioned data store for Zarr
- [VirtualiZarr](https://virtualizarr.readthedocs.io/) — virtual Zarr datasets referencing existing netCDF/HDF5/TIFF files
- [CHESS Hub AOP tutorial](../CHESS_Analysis_Hub/docker/tutorials/01_distributed_analysis_with_dask.ipynb) — current access pattern for icechunk-backed spectrometer mosaics
