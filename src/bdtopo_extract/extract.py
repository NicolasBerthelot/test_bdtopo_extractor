"""Extraction en streaming d'une couche BD Topo pour un territoire donné,
sans jamais télécharger la couche France entière en local."""
from __future__ import annotations

import time
from pathlib import Path

import geopandas as gpd
import pyogrio

from . import catalog
from .territoire import Territoire

FORMAT_DRIVERS = {
    "gpkg": "GPKG",
    "shp": "ESRI Shapefile",
    "geojson": "GeoJSON",
}


def extract_layer(
    layer: catalog.LayerSource,
    territoire: Territoire | None,
    crs: str | None = None,
) -> gpd.GeoDataFrame:
    """Lit en flux une couche BD Topo, filtrée sur le territoire demandé.

    territoire=None => France entière, pas de filtre (attention : peut être très volumineux).
    """
    bbox = territoire.bbox if territoire is not None else None

    t0 = time.time()
    gdf = pyogrio.read_dataframe(layer.vsi_path, bbox=bbox)
    elapsed = time.time() - t0

    if territoire is not None and len(gdf):
        # Le bbox est un préfiltre rapide (index spatial) ; on découpe ensuite
        # exactement sur la géométrie du territoire (polygone administratif ou bbox).
        gdf = gpd.clip(gdf, territoire.geometry)

    if crs and len(gdf):
        gdf = gdf.to_crs(crs)

    gdf.attrs["extract_seconds"] = round(elapsed, 2)
    return gdf


def write_layers(
    layer_results: dict[str, gpd.GeoDataFrame],
    output_dir: Path,
    fmt: str = "gpkg",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    driver = FORMAT_DRIVERS[fmt]

    if fmt == "gpkg":
        out_path = output_dir / "extraction.gpkg"
        for name, gdf in layer_results.items():
            if len(gdf) == 0:
                continue
            gdf.to_file(out_path, layer=name, driver=driver)
        return out_path

    # Shapefile / GeoJSON : un fichier par couche
    for name, gdf in layer_results.items():
        if len(gdf) == 0:
            continue
        ext = "shp" if fmt == "shp" else "geojson"
        gdf.to_file(output_dir / f"{name}.{ext}", driver=driver)
    return output_dir
