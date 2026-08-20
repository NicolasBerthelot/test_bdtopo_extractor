"""Interface graphique Streamlit pour bdtopo-extract.

Couche de présentation pure : toute la logique (découverte des couches,
résolution des territoires, extraction en flux) vit dans catalog.py /
territoire.py / extract.py et est réutilisée telle quelle ici.
"""
from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

from bdtopo_extract import catalog, extract, territoire

st.set_page_config(page_title="BD Topo Extract", layout="wide")
st.title("Extraction BD Topo (IGN)")


@st.cache_data(show_spinner="Chargement du catalogue de couches BD Topo...")
def _get_bdtopo_layers():
    return catalog.get_catalog("bdtopo")


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
layer_names = sorted(layers_catalog)

if "selected_layers" not in st.session_state:
    st.session_state.selected_layers = []


def _toggle_all():
    st.session_state.selected_layers = layer_names if st.session_state.select_all_cb else []


st.checkbox("Tout sélectionner", key="select_all_cb", on_change=_toggle_all)
selected_layers = st.multiselect("Couches à extraire", options=layer_names, key="selected_layers")

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
