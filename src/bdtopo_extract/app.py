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

import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox

from bdtopo_extract import catalog, dsfr_theme, docs, extract, fields, map_ui, territoire
from bdtopo_extract.territoire import fold as _fold

# Un repère visuel par thème (couleur + puce emoji, utilisable dans un label
# d'expander qui ne rend pas de HTML) — couvre les 9 thèmes connus de la BD Topo.
THEME_STYLE = {
    "Administratif": ("#2A2A2A", "⚫"),
    "Adresses": ("#E4A11B", "🟠"),
    "Bâti": ("#8D533E", "🟤"),
    "Hydrographie": ("#417DC4", "🔵"),
    "Lieux nommés": ("#8B8B8B", "⚪"),
    "Occupation du sol": ("#68A532", "🟢"),
    "Services et activités": ("#A558A0", "🟣"),
    "Transport": ("#D4B106", "🟡"),
    "Zones réglementées": ("#CE0500", "🔴"),
}
DEFAULT_THEME_STYLE = ("#8B8B8B", "⚪")

st.set_page_config(page_title="BD Topo Extract", layout="wide")
dsfr_theme.inject()
st.title("Extraction BD Topo (IGN)")


@st.cache_data(show_spinner="Chargement du catalogue de couches BD Topo...")
def _get_bdtopo_layers():
    return catalog.get_catalog("bdtopo")


@st.cache_data(show_spinner="Chargement de la documentation des couches (bdtopoexplorer.ign.fr)...")
def _get_docs():
    return docs.get_docs()


@st.cache_data(show_spinner="Chargement des champs filtrables...")
def _get_fields():
    return fields.get_fields()


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

for _name in st.session_state.layers_df.index:
    st.session_state.setdefault(f"layer_cb_{_name}", bool(st.session_state.layers_df.loc[_name, "Sélection"]))

btn_group, _spacer = st.columns([1, 3])
b1, b2 = btn_group.columns(2)
if b1.button("Tout cocher"):
    for _name in st.session_state.layers_df.index:
        st.session_state[f"layer_cb_{_name}"] = True
if b2.button("Tout décocher"):
    for _name in st.session_state.layers_df.index:
        st.session_state[f"layer_cb_{_name}"] = False
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

# Groupé par thème (couleur + puce), plutôt qu'un tableau plat : évite le texte
# tronqué et la colonne "Sélection" disproportionnée d'un data_editor classique.
for theme, group in layers_view.groupby("Thème", sort=True):
    color, dot = THEME_STYLE.get(theme, DEFAULT_THEME_STYLE)
    n_checked = sum(st.session_state.get(f"layer_cb_{n}", False) for n in group.index)
    label = f"{dot} {theme or 'Autre'} · {len(group)} couche(s)"
    if n_checked:
        label += f" — {n_checked} sélectionnée(s)"
    with st.expander(label, expanded=bool(filter_query)):
        st.markdown(
            f'<div style="height:3px;background:{color};border-radius:2px;margin:-0.5rem 0 0.75rem 0;"></div>',
            unsafe_allow_html=True,
        )
        for name, row in group.iterrows():
            st.checkbox(row["Couche"], key=f"layer_cb_{name}")
            caption = row["Description"] or "Pas de description disponible."
            if row["Doc"]:
                caption += f" [↗ documentation complète]({row['Doc']})"
            st.caption(caption)

for _name in st.session_state.layers_df.index:
    st.session_state.layers_df.loc[_name, "Sélection"] = st.session_state.get(f"layer_cb_{_name}", False)

selected_layers = st.session_state.layers_df[st.session_state.layers_df["Sélection"]].index.tolist()
st.caption(f"{len(selected_layers)} couche(s) sélectionnée(s)")

# --- Filtres attributaires par couche cochée ----------------------------
fields_map = _get_fields()
if "layer_filters" not in st.session_state:
    st.session_state.layer_filters = {}  # {layer_name: [filter_dict, ...]}

for layer_name in selected_layers:
    layer_fields = fields_map.get(layer_name)
    if not layer_fields:
        continue  # couche sans champ filtrable connu
    display_name = st.session_state.layers_df.loc[layer_name, "Couche"]
    with st.expander(f"⚙ Filtres — {display_name}"):
        layer_filter_list = []
        for f in layer_fields:
            if f["kind"] == "numeric":
                c1, c2 = st.columns(2)
                fmin = c1.number_input(
                    f"{f['display_name']} ≥", value=None, key=f"filter_num_min_{layer_name}_{f['field']}"
                )
                fmax = c2.number_input(
                    f"{f['display_name']} ≤", value=None, key=f"filter_num_max_{layer_name}_{f['field']}"
                )
                if fmin is not None or fmax is not None:
                    layer_filter_list.append(
                        {"field": f["field"], "kind": "numeric", "min": fmin, "max": fmax}
                    )
            elif f["kind"] == "categorical":
                chosen = st.multiselect(
                    f["display_name"], options=f["values"], key=f"filter_cat_{layer_name}_{f['field']}"
                )
                if chosen:
                    layer_filter_list.append({"field": f["field"], "kind": "categorical", "values": chosen})
        st.session_state.layer_filters[layer_name] = layer_filter_list

# --- 2. Territoire -------------------------------------------------------
st.subheader("2. Territoire")
kind = st.radio(
    "Type de territoire",
    ["France entière", "Territoires", "Bbox"],
    horizontal=True,
)

territoire_obj = None
TERRITOIRE_KIND_LABEL = {"region": "région", "departement": "département", "commune": "commune"}

if "selected_territoires" not in st.session_state:
    st.session_state.selected_territoires = []  # list[(kind_key, code_insee, label)]


def _multi_kind_search(searchterm: str):
    if len(searchterm) < 3:
        return []
    options = []
    for kind_key, kind_label in TERRITOIRE_KIND_LABEL.items():
        for r in territoire.search(kind_key, searchterm, limit=8).itertuples():
            options.append((f"{r.nom_officiel} ({r.code_insee}) — {kind_label}", (kind_key, r.code_insee)))
    return options


if kind == "France entière":
    st.warning("Sans filtre spatial : le volume transféré peut être important selon les couches choisies.")
elif kind == "Territoires":
    col_form, col_map = st.columns([1, 2])
    with col_form:
        picked = st_searchbox(
            _multi_kind_search,
            key="territoire_searchbox",
            placeholder="Région, département ou commune (3+ caractères)...",
            clear_on_submit=True,
        )
        if picked:
            picked_kind, picked_code = picked
            already = any(
                k == picked_kind and c == picked_code for k, c, _ in st.session_state.selected_territoires
            )
            if not already:
                t = territoire.resolve(picked_kind, picked_code)
                st.session_state.selected_territoires.append((picked_kind, picked_code, t.label))

        for i, (k, c, label) in enumerate(st.session_state.selected_territoires):
            row_label, row_btn = st.columns([5, 1])
            row_label.write(f"• {label} ({TERRITOIRE_KIND_LABEL[k]})")
            if row_btn.button("✕", key=f"remove_terr_{k}_{c}"):
                st.session_state.selected_territoires.pop(i)
                st.rerun()

    resolved = [territoire.resolve(k, c) for k, c, _ in st.session_state.selected_territoires]
    territoire_obj = territoire.union(resolved)

    with col_map:
        map_ui.render_territoire_map(territoire_obj, key="map_multi")
elif kind == "Bbox":
    for bbox_key in ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax"):
        st.session_state.setdefault(bbox_key, 0.0)

    col_form, col_map = st.columns([1, 2])
    with col_map:
        draw_result = map_ui.render_bbox_map(key="bbox_map")
    drawing = draw_result.get("last_active_drawing") if draw_result else None
    if drawing:
        ring = drawing["geometry"]["coordinates"][0]
        lngs, lats = [c[0] for c in ring], [c[1] for c in ring]
        st.session_state["bbox_xmin"] = min(lngs)
        st.session_state["bbox_ymin"] = min(lats)
        st.session_state["bbox_xmax"] = max(lngs)
        st.session_state["bbox_ymax"] = max(lats)

    with col_form:
        st.caption("Dessine un rectangle sur la carte, ou saisis les coordonnées (EPSG:4326).")
        c1, c2 = st.columns(2)
        xmin = c1.number_input("xmin", key="bbox_xmin", format="%.6f")
        ymin = c2.number_input("ymin", key="bbox_ymin", format="%.6f")
        xmax = c1.number_input("xmax", key="bbox_xmax", format="%.6f")
        ymax = c2.number_input("ymax", key="bbox_ymax", format="%.6f")
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
# Le résultat est stocké dans session_state (pas juste affiché dans le bloc du bouton) :
# des composants comme la carte peuvent déclencher des reruns en arrière-plan qui,
# sinon, effaceraient le résultat avant que l'utilisateur ait pu le voir.
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
            layer_filters = st.session_state.layer_filters.get(name, [])
            gdf = extract.extract_layer(
                layers_catalog[name], territoire_obj, crs=crs or None, filters=layer_filters
            )
            results[name] = gdf
            status.write(f"{name} : {len(gdf)} entités ({gdf.attrs.get('extract_seconds')}s)")
        except Exception as exc:  # noqa: BLE001 - on affiche l'erreur, on continue les autres couches
            errors.append((name, str(exc)))
        progress.progress((i + 1) / n)

    st.session_state["extraction_errors"] = errors
    if results:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = extract.write_layers(results, Path(tmp), fmt=fmt)
            if out_path.is_file():
                data, filename = out_path.read_bytes(), out_path.name
            else:
                data, filename = _zip_dir_bytes(out_path), "extraction.zip"
        st.session_state["extraction_result"] = {
            "data": data,
            "filename": filename,
            "total": sum(len(g) for g in results.values()),
        }
    else:
        st.session_state["extraction_result"] = None

for name, msg in st.session_state.get("extraction_errors", []):
    st.error(f"{name} : {msg}")

result = st.session_state.get("extraction_result")
if result:
    st.success(f"Extraction terminée : {result['total']} entités au total.")
    st.download_button("Télécharger le résultat", data=result["data"], file_name=result["filename"])
elif "extraction_result" in st.session_state and not st.session_state.get("extraction_errors"):
    st.warning("Aucune donnée dans le territoire demandé.")
