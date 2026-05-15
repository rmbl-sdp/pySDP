# API reference

All of pySDP's public surface. Import everything from the top-level package:

```python
import pysdp

pysdp.get_catalog(...)
pysdp.open_raster(...)
# ...
```

## Catalog discovery

::: pysdp.get_catalog
    options:
      heading_level: 3

::: pysdp.get_metadata
    options:
      heading_level: 3

::: pysdp.get_dates
    options:
      heading_level: 3

::: pysdp.browse
    options:
      heading_level: 3

## Raster access

::: pysdp.open_raster
    options:
      heading_level: 3

::: pysdp.open_stack
    options:
      heading_level: 3

## Extraction

::: pysdp.extract_points
    options:
      heading_level: 3

::: pysdp.extract_polygons
    options:
      heading_level: 3

## Download

::: pysdp.download
    options:
      heading_level: 3

## Issue tracking

Data-quality issues with SDP products are tracked in a dedicated GitHub
repo, [`rmbl-sdp/sdp-products`](https://github.com/rmbl-sdp/sdp-products),
separate from the pySDP code repo. Issues with pySDP *itself* go to
[`rmbl-sdp/pySDP/issues`](https://github.com/rmbl-sdp/pySDP/issues).

::: pysdp.report_issue
    options:
      heading_level: 3

::: pysdp.known_issues
    options:
      heading_level: 3

## Constants

::: pysdp.constants
    options:
      heading_level: 3
      members:
        - SDP_CRS
        - DOMAINS
        - TYPES
        - RELEASES
        - TIMESERIES_TYPES
