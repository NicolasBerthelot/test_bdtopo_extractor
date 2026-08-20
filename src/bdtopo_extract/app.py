"""Interface graphique Streamlit pour bdtopo-extract.

Couche de présentation pure : toute la logique (découverte des couches,
résolution des territoires, extraction en flux) vit dans catalog.py /
territoire.py / extract.py et est réutilisée telle quelle ici.
"""
from __future__ import annotations

import io
import tempfile
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from bdtopo_extract import catalog, docs, extract, territoire


def _fold(s: str) -> str:
    """Casefold + suppression des accents, pour une recherche insensible à la casse et aux accents."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c))

st.set_page_config(page_title="BD Topo Extract", layout="wide")
st.title("Extraction BD Topo (IGN)")


@st.cache_data(show_spinner="Chargement du catalogue de couches BD Topo...")
def _get_bdtopo_layers():
    return catalog.get_catalog("bdtopo")


@st.cache_data(show_spinner="Chargement de la documentation des couches (bdtopoexplorer.ign.fr)...")
def _get_docs():
    return docs.get_docs()


@st.cache_data(show_spinner="Recherche...")
def _search_territoire(kind: str, query: str):
    df = territoire.search(kind, query)
    return df.to_dict("records")


def _zip_dir_bytes(dir_path: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in dir_path.iterdir():
            zf.write(f, arcname=f.name)
    return buf.getvalue()


layers_catalog = _get_bdtopo_layers()
st.caption(f"Édition BD Topo : {catalog.get_edition('bdtopo')}")

# --- 1. Couches ---------------------------------------------------------
st.subheader("1. Couches")
docs_map = _get_docs()


def _build_layers_df() -> pd.DataFrame:
    rows = [
        {
            "layer_id": name,
            "Sélection": False,
            "Couche": docs_map.get(name, {}).get("display_name") or name,
            "Thème": docs_map.get(name, {}).get("theme") or "",
            "Description": docs_map.get(name, {}).get("description") or "",
            "Doc": docs_map.get(name, {}).get("url") or "",
        }
        for name in sorted(layers_catalog)
    ]
    return pd.DataFrame(rows).set_index("layer_id")


if "layers_df" not in st.session_state:
    st.session_state.layers_df = _build_layers_df()

b1, b2, _spacer = st.columns([1, 1, 6])
if b1.button("Tout cocher"):
    st.session_state.layers_df["Sélection"] = True
    st.session_state.pop("layers_editor", None)
if b2.button("Tout décocher"):
    st.session_state.layers_df["Sélection"] = False
    st.session_state.pop("layers_editor", None)
filter_query = st.text_input(
    "Filtrer (nom, thème, description)", label_visibility="collapsed", placeholder="Filtrer (nom, thème, description)"
)

layers_view = st.session_state.layers_df
if filter_query:
    q = _fold(filter_query)
    mask = (
        layers_view["Couche"].map(_fold).str.contains(q, na=False)
        | layers_view["Thème"].map(_fold).str.contains(q, na=False)
        | layers_view["Description"].map(_fold).str.contains(q, na=False)
    )
    layers_view = layers_view[mask]

edited_layers = st.data_editor(
    layers_view,
    key="layers_editor",
    hide_index=True,
    height=420,
    use_container_width=True,
    column_order=["Sélection", "Couche", "Thème", "Description", "Doc"],
    column_config={
        "Sélection": st.column_config.CheckboxColumn("Sélection"),
        "Couche": st.column_config.TextColumn("Couche", disabled=True),
        "Thème": st.column_config.TextColumn("Thème", disabled=True),
        "Description": st.column_config.TextColumn("Description", disabled=True, width="large"),
        "Doc": st.column_config.LinkColumn("Doc", display_text="↗", disabled=True),
    },
)
# Ré-injecte les éditions (limitées aux lignes visibles si un filtre est actif)
# dans la source de vérité complète, sans perdre les cases cochées hors filtre.
st.session_state.layers_df.loc[edited_layers.index, "Sélection"] = edited_layers["Sélection"]

selected_layers = st.session_state.layers_df[st.session_state.layers_df["Sélection"]].index.tolist()
st.caption(f"{len(selected_layers)} couche(s) sélectionnée(s)")

# --- 2. Territoire -------------------------------------------------------
st.subheader("2. Territoire")
kind = st.radio(
    "Type de territoire",
    ["France entière", "Région", "Département", "Commune", "Bbox"],
    horizontal=True,
)

territoire_obj = None
KIND_KEY = {"Région": "region", "Département": "departement", "Commune": "commune"}

if kind == "France entière":
    st.warning("Sans filtre spatial : le volume transféré peut être important selon les couches choisies.")
elif kind in KIND_KEY:
    kind_key = KIND_KEY[kind]
    query = st.text_input(f"Rechercher ({kind.lower()}) — nom ou code INSEE")
    if query:
        results = _search_territoire(kind_key, query)
        if results:
            options = {f"{r['nom_officiel']} ({r['code_insee']})": r["code_insee"] for r in results}
            choice = st.selectbox("Résultats", options=list(options.keys()))
            if choice:
                territoire_obj = territoire.resolve(kind_key, options[choice])
        else:
            st.warning("Aucun résultat.")
elif kind == "Bbox":
    c1, c2, c3, c4 = st.columns(4)
    xmin = c1.number_input("xmin", value=0.0, format="%.6f")
    ymin = c2.number_input("ymin", value=0.0, format="%.6f")
    xmax = c3.number_input("xmax", value=0.0, format="%.6f")
    ymax = c4.number_input("ymax", value=0.0, format="%.6f")
    if xmax > xmin and ymax > ymin:
        territoire_obj = territoire.from_bbox(xmin, ymin, xmax, ymax)
    else:
        st.info("Renseigne une emprise valide (xmax > xmin et ymax > ymin).")

# --- 3. Options ------------------------------------------------------------
st.subheader("3. Options")
o1, o2 = st.columns(2)
fmt = o1.selectbox("Format de sortie", ["gpkg", "shp", "geojson"])
crs = o2.text_input("CRS de sortie (optionnel)", placeholder="EPSG:2154")

# --- 4. Extraction -----------------------------------------------------
ready = bool(selected_layers) and (kind == "France entière" or territoire_obj is not None)

st.subheader("4. Extraction")
if st.button("Extraire", disabled=not ready, type="primary"):
    progress = st.progress(0.0)
    status = st.empty()
    results = {}
    errors = []
    n = len(selected_layers)

    for i, name in enumerate(selected_layers):
        status.write(f"Extraction de **{name}**...")
        try:
            gdf = extract.extract_layer(layers_catalog[name], territoire_obj, crs=crs or None)
            results[name] = gdf
            status.write(f"{name} : {len(gdf)} entités ({gdf.attrs.get('extract_seconds')}s)")
        except Exception as exc:  # noqa: BLE001 - on affiche l'erreur, on continue les autres couches
            errors.append((name, str(exc)))
        progress.progress((i + 1) / n)

    for name, msg in errors:
        st.error(f"{name} : {msg}")

    if results:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = extract.write_layers(results, Path(tmp), fmt=fmt)
            if out_path.is_file():
                data, filename = out_path.read_bytes(), out_path.name
            else:
                data, filename = _zip_dir_bytes(out_path), "extraction.zip"

        total = sum(len(g) for g in results.values())
        st.success(f"Extraction terminée : {total} entités au total.")
        st.download_button("Télécharger le résultat", data=data, file_name=filename)
    elif not errors:
        st.warning("Aucune donnée dans le territoire demandé.")
