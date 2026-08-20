"""Documentation des couches BD Topo, récupérée depuis bdtopoexplorer.ign.fr
(nom d'affichage FR, thème, description courte, lien vers la doc complète).

Site statique scrapable : la page racine liste l'arbre thème -> classes,
chaque page de classe contient une définition en une phrase.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import catalog

BASE_URL = "https://bdtopoexplorer.ign.fr"
CACHE_FILE = catalog.CACHE_DIR / "bdtopoexplorer_docs.json"

# bdtopoexplorer.ign.fr renvoie 403 sur le User-Agent par défaut de `requests`
# (notamment depuis des IP d'hébergeurs cloud) : on se présente comme un navigateur.
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}


def _fetch_layer_index() -> dict[str, dict]:
    """GET la page racine, retourne {layer_name: {display_name, theme}} pour chaque classe."""
    resp = requests.get(f"{BASE_URL}/", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    index: dict[str, dict] = {}
    for theme_span in soup.select("span.acacher[theme]"):
        theme = theme_span["theme"]
        theme_id = theme_span["quoi"]
        classes_div = soup.find("div", id=theme_id)
        if not classes_div:
            continue
        for a in classes_div.select("ul.liste-classes li a[href]"):
            href = a["href"]
            if not href.startswith("./") or "?" in href:
                continue  # ignore "Attributs du thème" et autres liens spéciaux
            layer_name = href[2:]
            index[layer_name] = {"display_name": a.get_text(strip=True), "theme": theme}
    return index


def _fetch_description(layer_name: str) -> str:
    """GET la page d'une classe, extrait le texte de la définition. Vide si indisponible."""
    try:
        resp = requests.get(f"{BASE_URL}/{layer_name}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        titre = soup.find("span", class_="titre_article", string=lambda s: s and "Définition" in s)
        if not titre or not titre.parent:
            return ""
        text = titre.parent.get_text(" ", strip=True)
        return text.removeprefix("Définition").lstrip(" :").strip()
    except requests.RequestException:
        return ""


def get_docs(force_refresh: bool = False) -> dict[str, dict]:
    """Retourne {layer_name: {display_name, theme, description, url}} pour les couches BD Topo.

    Mis en cache sur disque (.cache/bdtopoexplorer_docs.json) : le scraping (58 pages)
    ne se refait pas à chaque lancement.
    """
    if not force_refresh and CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))

    bdtopo_layers = set(catalog.get_catalog("bdtopo"))
    try:
        index = _fetch_layer_index()
    except requests.RequestException:
        # bdtopoexplorer.ign.fr indisponible : on continue sans documentation
        # plutôt que de faire planter l'extraction (qui n'en dépend pas).
        return {name: {"display_name": name, "theme": "", "description": "", "url": ""} for name in bdtopo_layers}

    docs: dict[str, dict] = {}
    known = [name for name in bdtopo_layers if name in index]
    with ThreadPoolExecutor(max_workers=8) as pool:
        descriptions = dict(zip(known, pool.map(_fetch_description, known)))

    for name in bdtopo_layers:
        meta = index.get(name)
        if meta:
            docs[name] = {
                "display_name": meta["display_name"],
                "theme": meta["theme"],
                "description": descriptions.get(name, ""),
                "url": f"{BASE_URL}/{name}",
            }
        else:
            # Pas de correspondance trouvée (dérive possible entre éditions) : fallback minimal.
            docs[name] = {"display_name": name, "theme": "", "description": "", "url": ""}

    catalog.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
    return docs
