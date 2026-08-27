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


# La couche communes fait ~480 Mo sur disque — largement plus en GeoDataFrame Python
# (objets géométrie shapely, un par commune). La garder en mémoire pour toute la durée
# de vie du process a dépassé la limite RAM de Streamlit Community Cloud (~1 Go).
# Au lieu de ça : un index léger (code_insee, nom_officiel, SANS géométrie) reste en
# mémoire pour la recherche, et resolve() ne lit qu'UNE ligne (celle demandée) à chaque
# appel, depuis le cache disque local — jamais l'ensemble du jeu de données en mémoire.
_SEARCH_INDEX_CACHE: dict[str, "pd.DataFrame"] = {}


def _local_cache_path(kind: str) -> Path:
    """Télécharge (une seule fois par édition) et retourne le chemin du fichier
    en cache local pour cette couche admin. Le fichier reste sur disque uniquement :
    on ne le charge jamais en entier en mémoire après coup (cf. commentaire ci-dessus)."""
    layer_name = ADMIN_LAYER_BY_KIND[kind]
    cache_path = CACHE_DIR / f"admin_{layer_name}.gpkg"
    if cache_path.exists():
        return cache_path

    layers = catalog.get_catalog("admin-express-cog")
    if layer_name not in layers:
        raise RuntimeError(f"Couche Admin Express '{layer_name}' introuvable dans le catalogue")
    src = layers[layer_name]
    gdf = gpd.read_file(src.vsi_path)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cache_path, driver="GPKG")
    del gdf  # ne pas garder ce GeoDataFrame complet en mémoire au-delà de l'écriture
    return cache_path


def _search_index(kind: str) -> "pd.DataFrame":
    if kind in _SEARCH_INDEX_CACHE:
        return _SEARCH_INDEX_CACHE[kind]
    cache_path = _local_cache_path(kind)
    df = pyogrio.read_dataframe(cache_path, columns=["code_insee", "nom_officiel"], read_geometry=False)
    _SEARCH_INDEX_CACHE[kind] = df
    return df


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


def search(kind: str, query: str | None = None, limit: int | None = None) -> "pd.DataFrame":
    """Liste les territoires d'un type donné, filtrés par code ou nom (recherche partielle,
    insensible aux accents, tolérante aux fautes de frappe). `limit` plafonne le nombre de
    résultats (utile pour une autocomplétion). Ne charge jamais les géométries en mémoire."""
    index = _search_index(kind)
    if not query:
        results = index.sort_values("nom_officiel")
    else:
        results = _match(index, query).sort_values("nom_officiel")
    return results.head(limit) if limit else results


def resolve(kind: str, code_ou_nom: str) -> Territoire:
    """Résout un territoire administratif (region/departement/commune) en géométrie.

    Lève une erreur explicite si aucun résultat ou si le résultat est ambigu. Ne lit
    que la géométrie de la ligne demandée (pas toute la couche) depuis le cache disque.
    """
    index = _search_index(kind)
    matches = _match(index, code_ou_nom)

    if len(matches) == 0:
        raise ValueError(f"Aucun {kind} trouvé pour {code_ou_nom!r}")
    if len(matches) > 1:
        noms = ", ".join(f"{r.nom_officiel} ({r.code_insee})" for r in matches.itertuples())
        raise ValueError(f"Plusieurs {kind} correspondent à {code_ou_nom!r} : {noms}")

    code = matches.iloc[0]["code_insee"]
    nom = matches.iloc[0]["nom_officiel"]

    cache_path = _local_cache_path(kind)
    escaped_code = str(code).replace("'", "''")
    row_gdf = pyogrio.read_dataframe(cache_path, where=f"code_insee = '{escaped_code}'")
    if len(row_gdf) == 0:
        raise ValueError(f"{kind} {code!r} trouvé dans l'index mais introuvable dans le cache géométrique")

    geometry = row_gdf.iloc[0].geometry
    return Territoire(label=f"{nom} ({code})", geometry=geometry, bbox=geometry.bounds)


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


FRANCE_OUTLINE_FILE = Path(__file__).parent / "data" / "france_outline.geojson"

_FRANCE_GEOMETRY_CACHE: Territoire | None = None


def france_geometry() -> Territoire:
    """Contour France entière (toutes régions, y compris DROM), pour affichage carte
    uniquement — ne pas utiliser pour filtrer une extraction (voir `france()`, qui
    renvoie None pour ne pas imposer de découpage inutile sur un territoire
    "France entière").

    Chargé depuis un instantané embarqué (data/france_outline.geojson), calculé une
    fois en local à partir des régions Admin Express : union des géométries BRUTES
    (frontières exactement partagées entre régions voisines -> fusion propre), puis
    seulement ENSUITE simplifiée pour la taille du fichier. Simplifier chaque région
    avant l'union produit de petits trous aux frontières (chaque région simplifiée
    indépendamment, les bords partagés ne coïncident plus exactement) — d'où l'ordre
    important. Zéro calcul au démarrage : le fichier est chargé tel quel.
    """
    global _FRANCE_GEOMETRY_CACHE
    if _FRANCE_GEOMETRY_CACHE is None:
        import json

        from shapely.geometry import shape

        geometry = shape(json.loads(FRANCE_OUTLINE_FILE.read_text(encoding="utf-8")))
        _FRANCE_GEOMETRY_CACHE = Territoire(label="France entière", geometry=geometry, bbox=geometry.bounds)
    return _FRANCE_GEOMETRY_CACHE
