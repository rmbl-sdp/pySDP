# Contributing

pySDP is early-stage and we welcome contributions of all shapes — bug reports, doc fixes, new examples, API improvements. Here's how to get set up.

## Quick start

```bash
git clone https://github.com/rmbl-sdp/pySDP.git
cd pySDP

# Using uv (recommended — fast resolver)
uv sync --all-groups --all-extras

# Or using pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
pip install -r requirements-dev.txt   # if present; otherwise see pyproject.toml [dependency-groups]
```

Verify the install:

```bash
pytest -m "not network" -q      # 176 unit tests, ≈1.5s, no network
```

## Running tests

Default unit tests (no network):

```bash
pytest -m "not network"
```

Integration tests against real S3 (slower; ~1 minute):

```bash
pytest -m network
```

CI runs the default suite across Python 3.11 / 3.12 / 3.13 on Linux + macOS + Windows. Network tests run locally before significant releases.

## Code style

- **Formatter + linter:** `ruff format` + `ruff check`. Run `ruff check --fix` before committing.
- **Type checker:** `mypy src/pysdp` in strict mode.
- **Imports:** `from __future__ import annotations` at the top of every source file; imports sorted via ruff's isort rules.
- **Docstrings:** NumPy style (Parameters / Returns / Raises / Examples sections). Public APIs need full docstrings; internals need at least a one-line summary.
- **Comments:** Only when the *why* is non-obvious. Prefer well-named identifiers over inline explanations.

Pre-commit will run all of the above:

```bash
pre-commit install
git commit ...     # hooks fire automatically
```

## Project structure

```
pySDP/
├── src/pysdp/          # package source
│   ├── __init__.py     # public API re-exports
│   ├── catalog.py      # get_catalog, get_metadata
│   ├── raster.py       # open_raster, open_stack
│   ├── extract.py      # extract_points, extract_polygons
│   ├── download.py     # download
│   ├── constants.py    # SDP_CRS, DOMAINS, ...
│   ├── io/             # low-level I/O helpers (VSICURL, templates)
│   ├── _resolve.py     # time-slice resolver (internal)
│   ├── _validate.py    # argument validation (internal)
│   ├── _catalog_data.py  # packaged CSV loader
│   └── data/           # packaged catalog snapshot
├── tests/              # pytest suite
├── docs/               # MkDocs site (rendered at rmbl-sdp.github.io/pySDP)
├── scripts/            # maintainer utilities (catalog refresh etc.)
├── SPEC.md             # v0.1 specification (design doc)
├── ROADMAP.md          # post-v0.1 plans
└── pyproject.toml      # build + dep config
```

## Design principles

See [`SPEC.md`](https://github.com/rmbl-sdp/pySDP/blob/main/SPEC.md) for the full design rationale. The headline principles:

1. **Return types are standard.** `xarray.Dataset`, `geopandas.GeoDataFrame`, `pandas.DataFrame` — nothing custom.
2. **Behavior parity with rSDP where sensible.** pySDP ports the R package, so matching semantics (especially error messages and edge cases) is the default; diverging needs justification.
3. **Lazy by default.** `open_raster` returns a lazy `Dataset`; materialization is explicit.
4. **Extras gate features that need heavy deps.** The core install stays under ~150 MB of wheels; Dask, STAC tooling, exact polygon stats, etc. live behind `[dask]`, `[stac]`, `[exact]`.

## Updating the catalog snapshot

When new SDP products get published, the packaged catalog goes stale. Refresh:

```bash
python scripts/update_catalog.py         # downloads current CSV from S3
python scripts/update_catalog.py --dry-run   # preview without writing
```

Then commit the updated CSV and cut a release. Users on the stale version will see a `UserWarning` nudging them to upgrade.

## Proposing changes

1. Open an issue describing what you want to change and why.
2. Fork, branch, PR. CI runs the full test matrix + strict docs build on every PR.
3. For new features, add tests + a CHANGELOG entry under `## [Unreleased]`.
4. For behavior changes that diverge from rSDP, note the rationale in the PR description.

## Release process (maintainer-only)

1. Update `CHANGELOG.md` with the new version number + date.
2. Tag `vX.Y.Z` (e.g., `v0.1.1`) + push the tag.
3. `.github/workflows/release.yml` builds + publishes to PyPI via Trusted Publishing.
4. Docs auto-deploy to GitHub Pages on main-branch push.
5. For stable releases: bump the conda-forge feedstock via `regro-cf-autotick-bot` (auto-PR) or manual PR to `pysdp-feedstock`.

## License

MIT. See [LICENSE](https://github.com/rmbl-sdp/pySDP/blob/main/LICENSE).
