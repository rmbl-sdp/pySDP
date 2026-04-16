# Changelog

All notable changes to pySDP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Phase 2 — Argument validation + time-slice resolvers** (SPEC.md §9):
  - `pysdp.io.template.substitute_template()` — `{year}`/`{month}`/`{day}`
    URL-template substitution with scalar/vector recycling and
    length-consistency checks. Port of rSDP's `.substitute_template()`.
  - `pysdp._validate.validate_user_args()` — pre-catalog-lookup
    validation; zero-pads `months` to two-digit strings; rejects
    invalid combinations of `catalog_id`/`url`/`date_start`/`date_end`/
    `download_files`/`download_path`.
  - `pysdp._validate.validate_args_vs_type()` — post-lookup check for
    whether a time-arg combo is valid for a given `TimeSeriesType`
    (Single rejects all time args; Yearly rejects months + years∧dates;
    Monthly requires months with years; Daily requires dates only).
  - `pysdp._resolve.resolve_time_slices()` and per-type resolvers
    (`resolve_single`, `resolve_yearly`, `resolve_monthly`,
    `resolve_daily`) returning a `TimeSlices(paths, names)` named tuple.
    Pure functions, no network, no raster I/O.
  - Preserved behavior carry-overs from rSDP: anchor-day
    `seq(by="year"/"month")` semantics for Yearly/Monthly date-range
    branches; 30-layer default clip for Daily datasets with no date
    bounds; error-on-empty-overlap; warn-on-partial-overlap.
  - 52 new unit tests: `test_template.py` (8 tests),
    `test_validate.py` (20 tests), `test_resolve.py` (24 tests).
    Ports rSDP's 32 testthat tests across
    `test-internal_resolve.R` and `test-internal_validate.R`, plus
    additional edge-case coverage.

- **Phase 1 — Catalog + metadata** (SPEC.md §9):
  - `pysdp.get_catalog()` with three sources: `packaged` (default;
    offline, emits a `UserWarning` when the snapshot is older than
    `SDP_STALENESS_MONTHS` / default 6 months), `live` (refetches the
    CSV from S3), `stac` (returns a `pystac.Catalog` for the SDP
    static STAC v1 catalog; filter args ignored with a warning).
  - `pysdp.get_metadata(catalog_id, as_dict=True)` — fetches QGIS-style
    XML metadata; returns a `dict` via `xmltodict` or an `lxml`
    element. Descriptive `KeyError` on unknown catalog_id includes
    the snapshot date.
  - Packaged catalog CSV snapshot: `SDP_product_table_04_14_2026.csv`
    (156 products across UG/UER/GT/GMUG domains). Loaded via
    `importlib.resources` in `pysdp._catalog_data`. Handles both
    `m/d/y` and `m/d/Y` date formats mixed across rows, and
    preserves rSDP's `sysdata.rda` baking model.
  - `scripts/update_catalog.py` — mirrors rSDP's `data-raw/SDP_catalog.R`;
    downloads a fresh CSV from S3 and rotates the packaged snapshot.
  - Test suite: 48 unit tests (filter validation, date parsing,
    staleness warning, synthetic-DataFrame filter logic, responses-mocked
    HTTP) + 3 live integration tests under `@pytest.mark.network`.

- Initial Phase 0 scaffolding: `pyproject.toml` (hatchling + hatch-vcs),
  `src/pysdp/` package skeleton with public-API stubs, `constants.py`
  with real SDP catalog values (CRS, domains, types, releases, timeseries
  types), `tests/` smoke tests, CI workflows (lint, type-check, test
  matrix on Python 3.11/3.12/3.13 × linux/macOS/windows), release
  workflow with PyPI Trusted Publishing, docs workflow stub,
  `.pre-commit-config.yaml`, MIT license. See SPEC.md §9 Phase 0.
