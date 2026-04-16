# User guides

Longer-form walkthroughs. These port the four [rSDP vignettes](https://github.com/rmbl-sdp/rSDP/tree/main/vignettes) to Python and run against the real RMBL Spatial Data Platform.

Planned (filling in across 0.1.x releases):

- **Accessing cloud data** — catalog discovery, `open_raster` / `open_stack`, working with time-series rasters. Ports rSDP's `sdp-cloud-data.Rmd`.
- **Wrangling raster data** — masking, reprojection, cropping, resampling. Ports `wrangle-raster-data.Rmd`.
- **Field-site sampling** — point and polygon extraction workflows, rSDP's `field-site-sampling.Rmd` translated to Python.
- **Pretty maps** — visualization with `matplotlib`, `folium`, and `lonboard`. Ports `pretty-maps.Rmd`.

In the meantime, the [Getting started](../getting-started.md) page has a compact end-to-end example, and the [API reference](../api.md) has every function's full signature and docstring.
