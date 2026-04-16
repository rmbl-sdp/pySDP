# Changelog

All notable changes to pySDP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
