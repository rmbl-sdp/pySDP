# Changelog

All notable changes to pySDP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial Phase 0 scaffolding: `pyproject.toml` (hatchling + hatch-vcs),
  `src/pysdp/` package skeleton with public-API stubs, `constants.py`
  with real SDP catalog values (CRS, domains, types, releases, timeseries
  types), `tests/` smoke tests, CI workflows (lint, type-check, test
  matrix on Python 3.11/3.12/3.13 × linux/macOS/windows), release
  workflow with PyPI Trusted Publishing, docs workflow stub,
  `.pre-commit-config.yaml`, MIT license. See SPEC.md §9 Phase 0.
