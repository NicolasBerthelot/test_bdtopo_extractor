"""Métadonnées des attributs (champs) de chaque couche BD Topo, pour construire des
filtres attributaires (quantitatif à seuil min/max, catégoriel à modalités cochables).

Récupérées depuis bdtopoexplorer.ign.fr/<couche> (même site que docs.py, structure HTML
`div.div_attribut` par champ : nom PostgreSQL, type déclaré, valeurs possibles si liste),
croisées avec le schéma réel de la couche (pyogrio.read_info, lecture d'en-tête seule) pour
ne garder que les champs effectivement présents dans l'édition courante.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyogrio
import requests
from bs4 import BeautifulSoup

from . import catalog
from .docs import BASE_URL, HEADERS

CACHE_FILE = catalog.CACHE_DIR / "bdtopo_fields.json"
BUNDLED_FILE = Path(__file__).parent / "data" / "bdtopo_fields.json"

# Préfixes de "Type :" bdtopoexplorer -> catégorie de filtre exploitable.
NUMERIC_TYPE_PREFIXES = ("Décimal", "Entier", "Réel")
CATEGORICAL_TYPE_PREFIXES = ("Liste",)


def _fetch_layer_fields(layer_name: str) -> list[dict]:
    """GET la page d'une classe, extrait pour chaque attribut : nom PostgreSQL, nom
    d'affichage, type déclaré et valeurs possibles (si liste). Vide si indisponible."""
    try:
        resp = requests.get(f"{BASE_URL}/{layer_name}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return []

    fields = []
    for attr_div in soup.select("div.div_attribut"):
        titre = attr_div.select_one(".titre_attribut_pdf")
        name_table = attr_div.select_one("table.table_nom_attr")
        type_span = attr_div.select_one('[id^="type_attr_"] .contenu_article')
        if not titre or not name_table or not type_span:
            continue

        rows = name_table.find_all("tr")
        if len(rows) < 2:
            continue
        pg_name = rows[1].find_all("td")[0].get_text(strip=True)
        if not pg_name:
            continue

        display_name = titre.get_text(strip=True)
        type_text = type_span.get_text(strip=True)

        if type_text.startswith(NUMERIC_TYPE_PREFIXES):
            kind = "numeric"
            values = []
        elif type_text.startswith(CATEGORICAL_TYPE_PREFIXES):
            kind = "categorical"
            values_span = attr_div.select_one('[id^="valeurs_possibles_attr_"] .contenu_article')
            values = [a.get_text(strip=True) for a in values_span.select("a")] if values_span else []
        else:
            continue  # texte libre, date, identifiant... non filtrable pour l'instant

        fields.append({"field": pg_name, "display_name": display_name, "kind": kind, "values": values})
    return fields


def _real_schema(vsi_path: str) -> dict[str, str]:
    """Schéma réel de la couche (lecture d'en-tête seule) : {nom_champ: type_ogr}."""
    info = pyogrio.read_info(vsi_path)
    return dict(zip(info["fields"], info["ogr_types"]))


def get_fields(force_refresh: bool = False) -> dict[str, list[dict]]:
    """Retourne {layer_name: [{field, display_name, kind, values}, ...]} pour les couches
    BD Topo dont au moins un champ est filtrable (numérique ou catégoriel).

    Par défaut, utilise le cache disque (.cache/) puis l'instantané embarqué (data/) sans
    passer par le réseau. force_refresh=True force un re-scraping (à utiliser en local pour
    régénérer l'instantané embarqué avant de le committer).
    """
    if not force_refresh:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if BUNDLED_FILE.exists():
            return json.loads(BUNDLED_FILE.read_text(encoding="utf-8"))

    layers = catalog.get_catalog("bdtopo")
    names = sorted(layers)
    with ThreadPoolExecutor(max_workers=8) as pool:
        scraped = dict(zip(names, pool.map(_fetch_layer_fields, names)))

    result: dict[str, list[dict]] = {}
    for name in names:
        try:
            schema = _real_schema(layers[name].vsi_path)
        except Exception:  # noqa: BLE001 - une couche illisible ne doit pas bloquer les autres
            schema = {}
        # Ne garde que les champs documentés ET réellement présents dans l'édition courante.
        fields = [f for f in scraped.get(name, []) if f["field"] in schema]
        if fields:
            result[name] = fields

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    catalog.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(payload, encoding="utf-8")
    if force_refresh:
        BUNDLED_FILE.parent.mkdir(parents=True, exist_ok=True)
        BUNDLED_FILE.write_text(payload, encoding="utf-8")
    return result
