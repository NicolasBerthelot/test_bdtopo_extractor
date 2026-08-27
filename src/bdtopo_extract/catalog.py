"""Découverte des éditions et catalogues de couches sur telecharger.geoplateforme.fr.

Les pages de diffusion sont du HTML statique (pas d'API JSON séparée) qui liste,
pour l'édition courante, un fichier FlatGeobuf par couche pour la France entière.
On scrape cette page une fois par édition et on met le résultat en cache local.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://telecharger.geoplateforme.fr"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache"

DATASETS = {
    "bdtopo": "topo/BDTOPO/",
    "admin-express-cog": "admin/ADMIN-EXPRESS-COG/",
}

# Nom de couche -> URL fgb (zippé ou non)
LayerMap = dict[str, "LayerSource"]


@dataclass(frozen=True)
class LayerSource:
    name: str
    url: str
    zipped: bool  # .fgb.zip (SOZip) vs .fgb simple
    parquet_url: str | None = None  # variante GeoParquet, si publiée pour ce dataset

    @property
    def vsi_path(self) -> str:
        if self.zipped:
            return f"/vsizip/vsicurl/{self.url}"
        return f"/vsicurl/{self.url}"


def _edition_id_from_url(url: str) -> str:
    # ex: .../BDTOPO_PQT/BDTOPO_3-5_TOUSTHEMES_FLATGEOBUF-ZIP_WGS84G_FRA_2026-03-15/batiment.fgb.zip
    match = re.search(r"/([^/]+)/[^/]+\.fgb(?:\.zip)?$", url)
    if not match:
        raise ValueError(f"Impossible d'extraire l'édition depuis l'URL: {url}")
    return match.group(1)


def _scrape_layers(dataset_page_path: str) -> LayerMap:
    page_url = f"{BASE_URL}/{dataset_page_path}"
    resp = requests.get(page_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    layers: LayerMap = {}
    for a in soup.select('a[href*=".fgb"]'):
        href = a["href"]
        if href.endswith(".fgb.zip"):
            zipped = True
            layer_name = href.rsplit("/", 1)[-1][: -len(".fgb.zip")]
        elif href.endswith(".fgb"):
            zipped = False
            layer_name = href.rsplit("/", 1)[-1][: -len(".fgb")]
        else:
            continue
        # Une couche peut apparaître deux fois (zip + non-zip) ; on garde la version zippée
        # si elle existe car c'est celle mise en avant par l'IGN pour le streaming.
        if layer_name in layers and layers[layer_name].zipped and not zipped:
            continue
        layers[layer_name] = LayerSource(name=layer_name, url=href, zipped=zipped)

    if not layers:
        raise RuntimeError(
            f"Aucune couche FlatGeobuf trouvée sur {page_url} — la page a peut-être changé de structure."
        )

    # Deuxième passe : variante GeoParquet de chaque couche (utilisée pour les requêtes
    # filtrées via DuckDB — élagage par bloc, y compris sur les attributs, cf. extract.py).
    for a in soup.select('a[href$=".parquet"]'):
        href = a["href"]
        layer_name = href.rsplit("/", 1)[-1][: -len(".parquet")]
        if layer_name in layers:
            layers[layer_name] = LayerSource(
                name=layer_name, url=layers[layer_name].url, zipped=layers[layer_name].zipped, parquet_url=href
            )

    return layers


def _cache_path(dataset: str) -> Path:
    return CACHE_DIR / f"{dataset}.json"


def get_catalog(dataset: str, force_refresh: bool = False) -> LayerMap:
    """Retourne le catalogue de couches pour un dataset ('bdtopo' ou 'admin-express-cog').

    Le cache est invalidé automatiquement dès que l'édition détectée change
    (nouvelle publication trimestrielle IGN).
    """
    if dataset not in DATASETS:
        raise ValueError(f"Dataset inconnu: {dataset!r}. Attendu: {list(DATASETS)}")

    cache_file = _cache_path(dataset)
    if not force_refresh and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        layers = {
            name: LayerSource(**entry) for name, entry in cached["layers"].items()
        }
        # Vérifie que l'édition en cache est toujours la plus récente en re-scrapant
        # uniquement si l'appelant force_refresh ; sinon on fait confiance au cache
        # pour éviter une requête réseau à chaque appel dans un même run.
        return layers

    layers = _scrape_layers(DATASETS[dataset])
    edition = _edition_id_from_url(next(iter(layers.values())).url)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "edition": edition,
                "layers": {name: vars(src) for name, src in layers.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return layers


def get_edition(dataset: str) -> str:
    layers = get_catalog(dataset)
    return _edition_id_from_url(next(iter(layers.values())).url)


def refresh_if_new_edition(dataset: str) -> LayerMap:
    """Re-scrape et met à jour le cache si une nouvelle édition est disponible."""
    cache_file = _cache_path(dataset)
    if not cache_file.exists():
        return get_catalog(dataset, force_refresh=True)

    cached_edition = json.loads(cache_file.read_text(encoding="utf-8"))["edition"]
    fresh_layers = _scrape_layers(DATASETS[dataset])
    fresh_edition = _edition_id_from_url(next(iter(fresh_layers.values())).url)

    if fresh_edition != cached_edition:
        return get_catalog(dataset, force_refresh=True)
    return get_catalog(dataset)
