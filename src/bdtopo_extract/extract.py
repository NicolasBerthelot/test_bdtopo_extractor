"""Extraction en streaming d'une couche BD Topo pour un territoire donné,
sans jamais télécharger la couche France entière en local."""
from __future__ import annotations

import time
from pathlib import Path

import duckdb
import geopandas as gpd
import pyogrio
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from . import catalog
from .territoire import Territoire

FORMAT_DRIVERS = {
    "gpkg": "GPKG",
    "shp": "ESRI Shapefile",
    "geojson": "GeoJSON",
}

_DUCKDB_CON: duckdb.DuckDBPyConnection | None = None


def _duckdb_connection() -> duckdb.DuckDBPyConnection:
    global _DUCKDB_CON
    if _DUCKDB_CON is None:
        con = duckdb.connect()
        con.execute("INSTALL spatial; LOAD spatial;")
        con.execute("INSTALL httpfs; LOAD httpfs;")
        _DUCKDB_CON = con
    return _DUCKDB_CON


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(float(value))
    return "'" + str(value).replace("'", "''") + "'"


def _filter_sql_clauses(filters: list[dict]) -> list[str]:
    clauses = []
    for f in filters:
        field = f["field"]
        if not field.isidentifier():
            continue  # défense en profondeur ; les noms viennent de fields.py (fiable)
        if f["kind"] == "numeric":
            if f.get("min") is not None:
                clauses.append(f'"{field}" >= {_sql_literal(f["min"])}')
            if f.get("max") is not None:
                clauses.append(f'"{field}" <= {_sql_literal(f["max"])}')
        elif f["kind"] == "categorical" and f.get("values"):
            literals = ", ".join(_sql_literal(v) for v in f["values"])
            clauses.append(f'"{field}" IN ({literals})')
    return clauses


def _pt(p) -> tuple[float, float]:
    return (p["x"], p["y"])  # altitude (z) ignorée : découpage/filtrage restent en 2D


def _ring(ring) -> list[tuple[float, float]]:
    return [_pt(p) for p in ring]


def _polygon(rings) -> Polygon:
    return Polygon(_ring(rings[0]), [_ring(r) for r in rings[1:]])


# GeoParquet IGN encode la géométrie en "GeoArrow" natif (listes/structs imbriqués),
# pas en WKB — un constructeur shapely par type OGC, la nature du champ dépend de la
# couche (déterminée une fois via pyogrio.read_info, cf. `_geoarrow_builder`).
_GEOARROW_BUILDERS = {
    "Point": lambda v: Point(_pt(v)),
    "MultiPoint": lambda v: MultiPoint([_pt(p) for p in v]),
    "LineString": lambda v: LineString(_ring(v)),
    "MultiLineString": lambda v: MultiLineString([_ring(r) for r in v]),
    "Polygon": _polygon,
    "MultiPolygon": lambda v: MultiPolygon([_polygon(rings) for rings in v]),
}


def _geoarrow_builder(geometry_type: str):
    normalized = geometry_type.replace("3D ", "").replace(" Z", "").strip()
    builder = _GEOARROW_BUILDERS.get(normalized)
    if builder is None:
        raise ValueError(f"Type de géométrie non géré pour la lecture GeoParquet : {geometry_type!r}")
    return builder


def _read_via_duckdb(layer: catalog.LayerSource, bbox: tuple[float, float, float, float] | None, filters: list[dict]) -> gpd.GeoDataFrame:
    """Lecture filtrée (spatiale + attributaire) via DuckDB sur la variante GeoParquet.

    Contrairement à FlatGeobuf, GeoParquet stocke des statistiques par bloc de lignes
    (min/max, bbox) que DuckDB exploite pour sauter les blocs qui ne peuvent pas
    correspondre — y compris sur les colonnes d'attributs, pas seulement la géométrie.
    Important : les valeurs doivent être injectées en litéraux SQL (échappés à la main,
    cf. _sql_literal), pas via des paramètres liés (`?`) — testé, les paramètres liés
    désactivent l'élagage par bloc de DuckDB sur ce type de requête (~15x plus lent).
    """
    clauses = []
    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        clauses.append(
            f"geometrie_bbox.xmin <= {xmax!r} AND geometrie_bbox.xmax >= {xmin!r} "
            f"AND geometrie_bbox.ymin <= {ymax!r} AND geometrie_bbox.ymax >= {ymin!r}"
        )
    clauses.extend(_filter_sql_clauses(filters))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    query = f"SELECT * EXCLUDE (\"geometrie_bbox\") FROM read_parquet('{layer.parquet_url}') {where_sql}"
    df = _duckdb_connection().execute(query).fetchdf()

    geometry_type = pyogrio.read_info(layer.vsi_path)["geometry_type"]
    builder = _geoarrow_builder(geometry_type)
    geoms = df.pop("geometrie").apply(builder)
    return gpd.GeoDataFrame(df, geometry=gpd.GeoSeries(geoms, crs="EPSG:4326"))


def extract_layer(
    layer: catalog.LayerSource,
    territoire: Territoire | None,
    crs: str | None = None,
    filters: list[dict] | None = None,
) -> gpd.GeoDataFrame:
    """Lit en flux une couche BD Topo, filtrée sur le territoire demandé et, si fournis,
    des filtres attributaires (cf. fields.py / extract.apply_filters).

    territoire=None => France entière, pas de filtre spatial (peut être très volumineux).
    Si des filtres attributaires sont fournis et que la couche a une variante GeoParquet,
    la lecture passe par DuckDB (élagage par bloc y compris attributaire, beaucoup plus
    rapide sur un grand territoire + filtre sélectif) ; sinon, lecture FlatGeobuf classique
    puis filtre appliqué en mémoire après coup (apply_filters).
    """
    bbox = territoire.bbox if territoire is not None else None
    filters = filters or []

    t0 = time.time()
    if filters and layer.parquet_url:
        gdf = _read_via_duckdb(layer, bbox, filters)
    else:
        gdf = pyogrio.read_dataframe(layer.vsi_path, bbox=bbox)
        if filters:
            gdf = apply_filters(gdf, filters)
    elapsed = time.time() - t0

    if territoire is not None and len(gdf):
        # Le bbox est un préfiltre rapide (index spatial/par bloc) ; on découpe ensuite
        # exactement sur la géométrie du territoire (polygone administratif ou bbox).
        gdf = gpd.clip(gdf, territoire.geometry)

    if crs and len(gdf):
        gdf = gdf.to_crs(crs)

    gdf.attrs["extract_seconds"] = round(elapsed, 2)
    return gdf


def apply_filters(gdf: gpd.GeoDataFrame, filters: list[dict]) -> gpd.GeoDataFrame:
    """Applique des filtres attributaires (ET logique entre eux) à une couche déjà extraite.

    Chaque filtre est un dict :
      - numérique : {"field": str, "kind": "numeric", "min": float|None, "max": float|None}
      - catégoriel : {"field": str, "kind": "categorical", "values": list[str]}
    Un filtre sans borne/valeur renseignée est ignoré (pas de restriction).
    """
    for f in filters:
        if f["field"] not in gdf.columns:
            continue  # champ absent de cette édition/couche : filtre ignoré, pas d'erreur
        if f["kind"] == "numeric":
            if f.get("min") is not None:
                gdf = gdf[gdf[f["field"]] >= f["min"]]
            if f.get("max") is not None:
                gdf = gdf[gdf[f["field"]] <= f["max"]]
        elif f["kind"] == "categorical":
            values = f.get("values")
            if values:
                gdf = gdf[gdf[f["field"]].isin(values)]
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
