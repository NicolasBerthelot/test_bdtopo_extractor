"""Résolution des territoires (région / département / commune / bbox / France)
en géométries, via les couches Admin Express COG (petites, lues intégralement
et mises en cache localement une fois par édition)."""
from __future__ import annotations

import difflib
import unicodedata
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


def fold(s: str) -> str:
    """Casefold + suppression des accents (recherche insensible casse/accents)."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c))


@dataclass(frozen=True)
class Territoire:
    label: str
    geometry: object  # shapely geometry, en EPSG:4326
    bbox: tuple[float, float, float, float]


_ADMIN_GDF_MEMORY_CACHE: dict[str, gpd.GeoDataFrame] = {}


def _admin_gdf(kind: str) -> gpd.GeoDataFrame:
    if kind in _ADMIN_GDF_MEMORY_CACHE:
        return _ADMIN_GDF_MEMORY_CACHE[kind]

    layer_name = ADMIN_LAYER_BY_KIND[kind]
    cache_path = CACHE_DIR / f"admin_{layer_name}.gpkg"
    if cache_path.exists():
        gdf = gpd.read_file(cache_path)
        _ADMIN_GDF_MEMORY_CACHE[kind] = gdf
        return gdf

    layers = catalog.get_catalog("admin-express-cog")
    if layer_name not in layers:
        raise RuntimeError(f"Couche Admin Express '{layer_name}' introuvable dans le catalogue")
    src = layers[layer_name]
    gdf = gpd.read_file(src.vsi_path)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cache_path, driver="GPKG")
    _ADMIN_GDF_MEMORY_CACHE[kind] = gdf
    return gdf


def _match(gdf: gpd.GeoDataFrame, code_ou_nom: str) -> gpd.GeoDataFrame:
    # Les codes INSEE (région/département/commune) sont courts (2 à 5 caractères) :
    # on tente d'abord une correspondance exacte sur le code avant de chercher par nom.
    if len(code_ou_nom) <= 5:
        matches = gdf[gdf["code_insee"].str.upper() == code_ou_nom.upper()]
        if len(matches):
            return matches

    noms_folded = gdf["nom_officiel"].map(fold)
    q = fold(code_ou_nom)

    matches = gdf[noms_folded == q]
    if len(matches):
        return matches
    matches = gdf[noms_folded.str.contains(q, na=False)]
    if len(matches):
        return matches

    # Repli tolérant aux fautes de frappe (ex. "Girond" -> "Gironde").
    close = difflib.get_close_matches(q, noms_folded, n=15, cutoff=0.6)
    return gdf[noms_folded.isin(close)]


def search(kind: str, query: str | None = None, limit: int | None = None) -> gpd.GeoDataFrame:
    """Liste les territoires d'un type donné, filtrés par code ou nom (recherche partielle,
    insensible aux accents, tolérante aux fautes de frappe). `limit` plafonne le nombre de
    résultats (utile pour une autocomplétion)."""
    gdf = _admin_gdf(kind)
    if not query:
        results = gdf[["code_insee", "nom_officiel"]].sort_values("nom_officiel")
    else:
        matches = _match(gdf, query)
        results = matches[["code_insee", "nom_officiel"]].sort_values("nom_officiel")
    return results.head(limit) if limit else results


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


def union(territoires: list[Territoire]) -> Territoire | None:
    """Fusionne plusieurs territoires (sélection multiple) en un seul : géométrie unie,
    bbox englobante. Retourne None si la liste est vide."""
    if not territoires:
        return None
    if len(territoires) == 1:
        return territoires[0]

    from shapely.ops import unary_union

    geometry = unary_union([t.geometry for t in territoires])
    xs = [t.bbox[0] for t in territoires] + [t.bbox[2] for t in territoires]
    ys = [t.bbox[1] for t in territoires] + [t.bbox[3] for t in territoires]
    label = (
        ", ".join(t.label for t in territoires)
        if len(territoires) <= 3
        else f"{len(territoires)} territoires"
    )
    return Territoire(label=label, geometry=geometry, bbox=(min(xs), min(ys), max(xs), max(ys)))


def from_bbox(xmin: float, ymin: float, xmax: float, ymax: float) -> Territoire:
    from shapely.geometry import box

    geometry = box(xmin, ymin, xmax, ymax)
    return Territoire(label="bbox", geometry=geometry, bbox=(xmin, ymin, xmax, ymax))


def france() -> Territoire | None:
    """France entière : pas de filtre spatial."""
    return None
