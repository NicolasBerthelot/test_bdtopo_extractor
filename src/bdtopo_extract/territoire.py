"""Résolution des territoires (région / département / commune / bbox / France)
en géométries, via les couches Admin Express COG (petites, lues intégralement
et mises en cache localement une fois par édition)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pyogrio

from . import catalog

CACHE_DIR = catalog.CACHE_DIR

ADMIN_LAYER_BY_KIND = {
    "region": "region",
    "departement": "departement",
    "commune": "commune",
}


@dataclass(frozen=True)
class Territoire:
    label: str
    geometry: object  # shapely geometry, en EPSG:4326
    bbox: tuple[float, float, float, float]


def _admin_gdf(kind: str) -> gpd.GeoDataFrame:
    layer_name = ADMIN_LAYER_BY_KIND[kind]
    cache_path = CACHE_DIR / f"admin_{layer_name}.gpkg"
    if cache_path.exists():
        return gpd.read_file(cache_path)

    layers = catalog.get_catalog("admin-express-cog")
    if layer_name not in layers:
        raise RuntimeError(f"Couche Admin Express '{layer_name}' introuvable dans le catalogue")
    src = layers[layer_name]
    gdf = gpd.read_file(src.vsi_path)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cache_path, driver="GPKG")
    return gdf


def _match(gdf: gpd.GeoDataFrame, code_ou_nom: str) -> gpd.GeoDataFrame:
    # Les codes INSEE (région/département/commune) sont courts (2 à 5 caractères) :
    # on tente d'abord une correspondance exacte sur le code avant de chercher par nom.
    if len(code_ou_nom) <= 5:
        matches = gdf[gdf["code_insee"].str.upper() == code_ou_nom.upper()]
        if len(matches):
            return matches
    matches = gdf[gdf["nom_officiel"].str.casefold() == code_ou_nom.casefold()]
    if len(matches):
        return matches
    matches = gdf[gdf["nom_officiel"].str.casefold().str.contains(code_ou_nom.casefold(), na=False)]
    return matches


def search(kind: str, query: str | None = None) -> gpd.GeoDataFrame:
    """Liste les territoires d'un type donné, filtrés par code ou nom (recherche partielle)."""
    gdf = _admin_gdf(kind)
    if not query:
        return gdf[["code_insee", "nom_officiel"]].sort_values("nom_officiel")
    matches = _match(gdf, query)
    return matches[["code_insee", "nom_officiel"]].sort_values("nom_officiel")


def resolve(kind: str, code_ou_nom: str) -> Territoire:
    """Résout un territoire administratif (region/departement/commune) en géométrie.

    Lève une erreur explicite si aucun résultat ou si le résultat est ambigu.
    """
    gdf = _admin_gdf(kind)
    matches = _match(gdf, code_ou_nom)

    if len(matches) == 0:
        raise ValueError(f"Aucun {kind} trouvé pour {code_ou_nom!r}")
    if len(matches) > 1:
        noms = ", ".join(f"{r.nom_officiel} ({r.code_insee})" for r in matches.itertuples())
        raise ValueError(f"Plusieurs {kind} correspondent à {code_ou_nom!r} : {noms}")

    row = matches.iloc[0]
    geometry = row.geometry
    return Territoire(label=f"{row.nom_officiel} ({row.code_insee})", geometry=geometry, bbox=geometry.bounds)


def from_bbox(xmin: float, ymin: float, xmax: float, ymax: float) -> Territoire:
    from shapely.geometry import box

    geometry = box(xmin, ymin, xmax, ymax)
    return Territoire(label="bbox", geometry=geometry, bbox=(xmin, ymin, xmax, ymax))


def france() -> Territoire | None:
    """France entière : pas de filtre spatial."""
    return None
