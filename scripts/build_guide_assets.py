#!/usr/bin/env python3
"""Generate the plots and folium maps embedded in the User Guides.

The User Guide pages (``docs/guides/*.md``) use static PNG images and
standalone HTML maps so the docs build stays fast (no notebook execution
in CI) while still showing what the code produces.

Run this script locally whenever the guides change, the SDP catalog gets
refreshed, or the visuals need an update. Output lives at
``docs/guides/assets/`` and gets committed to git.

Usage
-----
    python scripts/build_guide_assets.py              # all assets
    python scripts/build_guide_assets.py --skip-existing   # keep assets already on disk
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

warnings.simplefilter("ignore")

import folium  # noqa: E402
import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from shapely.geometry import Point  # noqa: E402

import pysdp  # noqa: E402

ASSETS_DIR = Path(__file__).resolve().parent.parent / "docs" / "guides" / "assets"
DOMAIN_GEOJSON_BASE = "https://rmbl-sdp.s3.us-east-2.amazonaws.com/data_products/supplemental/"
RMBL_FIELD_SITES = gpd.GeoDataFrame(
    {"site": ["Roaring Judy", "Gothic", "Galena Lake"]},
    geometry=[
        Point(-106.853186, 38.716995),
        Point(-106.988934, 38.958446),
        Point(-107.072569, 39.021644),
    ],
    crs="EPSG:4326",
)


def _say(msg: str) -> None:
    print(f"[build_guide_assets] {msg}", file=sys.stderr)


def _should_skip(path: Path, skip_existing: bool) -> bool:
    if skip_existing and path.exists():
        _say(f"  skip (exists): {path.name}")
        return True
    return False


# ---------------------------------------------------------------------------
# Domain boundary loader (reused across guides)
# ---------------------------------------------------------------------------


def _load_domain_bounds(simplify_tolerance_m: float | None = None) -> gpd.GeoDataFrame:
    """Load the three SDP domain boundaries as a single GeoDataFrame.

    The raw 1 m boundary polygons are huge (hundreds of thousands of
    vertices); embedding them in folium HTML produces a ~12 MB page.
    Pass ``simplify_tolerance_m`` (meters) to simplify before returning —
    100 m tolerance reduces the HTML to ~100 kB while keeping the domains
    visually indistinguishable at docs-site zoom levels.
    """
    frames = []
    for code, nice in [
        ("UG", "Upper Gunnison"),
        ("UER", "Upper East River"),
        ("GT", "Gothic Townsite"),
    ]:
        gdf = gpd.read_file(f"{DOMAIN_GEOJSON_BASE}{code}_region_vect_1m.geojson")
        gdf["Domain"] = nice
        frames.append(gdf)
    combined = pd.concat(frames, ignore_index=True).pipe(gpd.GeoDataFrame, crs=frames[0].crs)
    if simplify_tolerance_m is not None:
        # Simplify in a meter-based CRS, then reproject back.
        combined_m = combined.to_crs("EPSG:32613")
        combined_m["geometry"] = combined_m.geometry.simplify(simplify_tolerance_m)
        combined = combined_m.to_crs(combined.crs)
    return combined


# ---------------------------------------------------------------------------
# Asset generators
# ---------------------------------------------------------------------------


def make_domains_map(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (folium map of SDP domains)")
    bounds = _load_domain_bounds(simplify_tolerance_m=100)
    m = bounds.explore(
        column="Domain",
        tiles="Esri.NatGeoWorldMap",
        cmap="Set2",
        style_kwds={"fillOpacity": 0.35, "weight": 2},
        tooltip=["Domain"],
    )
    folium.LayerControl().add_to(m)
    m.save(str(out))


def make_dem_overview(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (UG DEM overview plot)")
    # Use the 9 m GMUG DEM — much smaller than the 3 m UG DEM and covers a
    # comparable footprint. Still ~500 MB to fetch fully, so downsample by
    # taking every Nth pixel before plotting.
    dem = pysdp.open_raster("R5D009", verbose=False, chunks=None)
    var = dem[next(iter(dem.data_vars))]
    # Coarsen to keep the plot snappy; the viz doesn't need full resolution.
    coarse = var.coarsen(x=20, y=20, boundary="trim").mean()
    fig, ax = plt.subplots(figsize=(9, 6))
    coarse.plot.imshow(ax=ax, cmap="terrain", robust=True, cbar_kwargs={"label": "Elevation (m)"})
    ax.set_aspect("equal")
    ax.set_title("GMUG bare-earth DEM (9 m, downsampled for docs)")
    ax.set_xlabel("UTM Easting (m)")
    ax.set_ylabel("UTM Northing (m)")
    plt.tight_layout()
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()


def make_sites_over_dem(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (field sites on DEM)")
    dem = pysdp.open_raster("R5D009", verbose=False, chunks=None)
    var = dem[next(iter(dem.data_vars))]
    coarse = var.coarsen(x=30, y=30, boundary="trim").mean()
    fig, ax = plt.subplots(figsize=(9, 7))
    coarse.plot.imshow(
        ax=ax,
        cmap="Greys_r",
        alpha=0.85,
        cbar_kwargs={"label": "Elevation (m)"},
        robust=True,
    )
    sites_utm = RMBL_FIELD_SITES.to_crs(dem.rio.crs)
    sites_utm.plot(ax=ax, color="crimson", markersize=90, marker="^", edgecolor="white")
    for _, row in sites_utm.iterrows():
        ax.annotate(
            row["site"],
            xy=(row.geometry.x, row.geometry.y),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=9,
            color="white",
            bbox={"boxstyle": "round,pad=0.25", "fc": "black", "alpha": 0.7},
        )
    ax.set_title("Three RMBL field sites on the GMUG DEM")
    ax.set_aspect("equal")
    ax.set_xlabel("UTM Easting (m)")
    ax.set_ylabel("UTM Northing (m)")
    plt.tight_layout()
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()


def make_extracted_values_plot(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (extracted-values bar chart)")
    # Use the GMUG DEM (covers Gothic only) — skip the other two sites for
    # this plot since they fall outside GMUG. Extract at just Gothic for a
    # quick asset.
    dem = pysdp.open_raster("R5D009", verbose=False, chunks=None)
    out_gdf = pysdp.extract_points(dem, RMBL_FIELD_SITES, method="nearest", verbose=False)
    var_col = [c for c in out_gdf.columns if "dem" in c.lower()][0]
    fig, ax = plt.subplots(figsize=(7, 4))
    plot_df = out_gdf[["site", var_col]].dropna().rename(columns={var_col: "Elevation (m)"})
    ax.bar(plot_df["site"], plot_df["Elevation (m)"], color="steelblue", edgecolor="black")
    ax.set_ylabel("Elevation (m)")
    ax.set_title("Elevation at RMBL field sites (GMUG 9 m DEM)")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    for i, v in enumerate(plot_df["Elevation (m)"]):
        ax.text(i, v + 20, f"{v:,.0f} m", ha="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()


def make_pretty_map_basic(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (basic matplotlib DEM plot)")
    dem = pysdp.open_raster("R5D009", verbose=False, chunks=None)
    var = dem[next(iter(dem.data_vars))]
    coarse = var.coarsen(x=20, y=20, boundary="trim").mean()
    fig, ax = plt.subplots(figsize=(9, 6))
    coarse.plot.imshow(ax=ax, cmap="terrain", robust=True)
    ax.set_aspect("equal")
    ax.set_title("GMUG bare-earth DEM, 9 m")
    plt.tight_layout()
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()


def make_pretty_map_overlay(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (DEM + domains + sites overlay)")
    dem = pysdp.open_raster("R5D009", verbose=False, chunks=None)
    var = dem[next(iter(dem.data_vars))]
    coarse = var.coarsen(x=20, y=20, boundary="trim").mean()
    bounds = _load_domain_bounds(simplify_tolerance_m=100).to_crs(dem.rio.crs)
    sites_utm = RMBL_FIELD_SITES.to_crs(dem.rio.crs)

    fig, ax = plt.subplots(figsize=(10, 7))
    coarse.plot.imshow(
        ax=ax,
        cmap="Greys_r",
        alpha=0.8,
        add_colorbar=True,
        cbar_kwargs={"label": "Elevation (m)"},
    )
    bounds.boundary.plot(
        ax=ax,
        color="royalblue",
        linewidth=1.5,
        linestyle="--",
    )
    sites_utm.plot(ax=ax, color="crimson", markersize=80, marker="^", edgecolor="white")
    ax.set_title("GMUG DEM + SDP domain boundaries + RMBL field sites")
    ax.set_aspect("equal")
    ax.set_xlabel("UTM Easting (m)")
    ax.set_ylabel("UTM Northing (m)")
    plt.tight_layout()
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()


def make_pretty_map_zoomed(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (zoomed Gothic valley DEM)")
    dem = pysdp.open_raster("R5D009", verbose=False, chunks=None)
    var = dem[next(iter(dem.data_vars))]
    # Zoom to ~5 km buffer around Gothic
    gothic_utm = RMBL_FIELD_SITES.iloc[[1]].to_crs(dem.rio.crs).geometry.iloc[0]
    cx, cy = gothic_utm.x, gothic_utm.y
    buffer_m = 5_000
    xmin, xmax = cx - buffer_m, cx + buffer_m
    ymin, ymax = cy - buffer_m, cy + buffer_m
    clipped = var.rio.clip_box(xmin, ymin, xmax, ymax)

    fig, ax = plt.subplots(figsize=(8, 7))
    clipped.plot.imshow(ax=ax, cmap="terrain", robust=True)
    # Mark Gothic
    ax.plot([cx], [cy], marker="^", color="crimson", markersize=14, markeredgecolor="white")
    ax.annotate(
        "Gothic",
        xy=(cx, cy),
        xytext=(12, 12),
        textcoords="offset points",
        fontsize=11,
        color="white",
        bbox={"boxstyle": "round,pad=0.3", "fc": "black", "alpha": 0.7},
    )
    ax.set_title("Gothic valley — 9 m DEM (±5 km)")
    ax.set_aspect("equal")
    ax.set_xlabel("UTM Easting (m)")
    ax.set_ylabel("UTM Northing (m)")
    plt.tight_layout()
    plt.savefig(out, dpi=140, bbox_inches="tight")
    plt.close()


def make_pretty_map_web(out: Path, skip_existing: bool) -> None:
    if _should_skip(out, skip_existing):
        return
    _say(f"  building {out.name} (folium interactive map)")
    bounds = _load_domain_bounds(simplify_tolerance_m=100)
    m = bounds.explore(
        column="Domain",
        tiles="Esri.WorldImagery",
        cmap="Set2",
        style_kwds={"fillOpacity": 0.35, "weight": 2},
        tooltip=["Domain"],
    )
    # Add field-site markers
    for _, row in RMBL_FIELD_SITES.iterrows():
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            popup=row["site"],
            icon=folium.Icon(color="red", icon="star"),
        ).add_to(m)
    folium.LayerControl().add_to(m)
    m.save(str(out))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--skip-existing", action="store_true", help="Skip assets that already exist on disk."
    )
    args = ap.parse_args()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    _say(f"writing to {ASSETS_DIR}")

    plans: list[tuple[Path, callable]] = [
        (ASSETS_DIR / "domains_map.html", make_domains_map),
        (ASSETS_DIR / "dem_overview.png", make_dem_overview),
        (ASSETS_DIR / "sites_over_dem.png", make_sites_over_dem),
        (ASSETS_DIR / "extracted_values.png", make_extracted_values_plot),
        (ASSETS_DIR / "pretty_basic.png", make_pretty_map_basic),
        (ASSETS_DIR / "pretty_overlay.png", make_pretty_map_overlay),
        (ASSETS_DIR / "pretty_zoomed.png", make_pretty_map_zoomed),
        (ASSETS_DIR / "pretty_web.html", make_pretty_map_web),
    ]
    for path, fn in plans:
        fn(path, args.skip_existing)

    _say(f"done: {sum(1 for p, _ in plans if p.exists())} / {len(plans)} assets on disk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
