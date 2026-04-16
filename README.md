# pySDP

Native Python interface for the [RMBL Spatial Data Platform](https://www.rmbl.org/scientists/resources/spatial-data-platform/) — curated, high-resolution geospatial datasets for the Western Colorado (USA) region around Rocky Mountain Biological Laboratory.

**Status:** Pre-alpha. Phase 0 scaffolding only; real functionality lands phase-by-phase per [SPEC.md](./SPEC.md) §9.

## Installation

```bash
pip install pysdp                # core: catalog, raster, extraction
pip install "pysdp[stac]"        # STAC catalog access via pystac-client + odc-stac
pip install "pysdp[exact]"       # fractional-coverage polygon stats via exactextract
pip install "pysdp[download]"    # faster downloads via obstore / fsspec
pip install "pysdp[hub]"         # JupyterHub / Dask Gateway integration
pip install "pysdp[all]"         # everything
```

## Quick look

```python
import pysdp

# Discover datasets
catalog = pysdp.get_catalog(domains=["UG"], types=["Vegetation"])

# Open a raster lazily
landcover = pysdp.open_raster("R3D018")

# Extract at points
import geopandas as gpd
sites = gpd.read_file("sites.gpkg")
samples = pysdp.extract_points(landcover, sites)
```

## Documentation

Full docs: <https://rmbl-sdp.github.io/pySDP> *(published after Phase 6)*

Design documents:
- [SPEC.md](./SPEC.md) — v0.1 specification (feature-parity port of the [rSDP](https://github.com/rmbl-sdp/rSDP) R package)
- [ROADMAP.md](./ROADMAP.md) — post-v0.1 JupyterHub / Dask integrations

## License

MIT. See [LICENSE](./LICENSE).

## Citation

If pySDP supports your research, please cite the RMBL Spatial Data Platform. A formal citation for pySDP itself will be added at the 0.1.0 release.
