"""Carte interactive (folium) pour visualiser/dessiner la sélection territoriale,
et pour prévisualiser un résultat d'extraction avant téléchargement."""
from __future__ import annotations

import json

import folium
from folium.plugins import Draw
from shapely.geometry import mapping
from streamlit_folium import st_folium

# Palette qualitative (une couleur par couche affichée dans l'aperçu d'extraction) —
# distincte de THEME_STYLE (app.py), qui colore par thème et non par couche individuelle.
PREVIEW_PALETTE = [
    "#000091", "#e1000f", "#00a95f", "#ff9575", "#6a6af4",
    "#c9191e", "#ffca00", "#8585f6", "#1212ff", "#a94645",
]

FRANCE_CENTER = (47.0, 2.5)
FRANCE_ZOOM = 5

IGN_PLAN_TILES = (
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
    "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM"
    "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
)


def _base_map() -> folium.Map:
    m = folium.Map(location=FRANCE_CENTER, zoom_start=FRANCE_ZOOM, tiles=None)
    folium.TileLayer(
        tiles=IGN_PLAN_TILES,
        attr="IGN-F/Géoportail",
        name="Plan IGN",
        overlay=False,
        control=False,
    ).add_to(m)
    return m


def render_territoire_map(territoire, key: str, fit_bounds: bool = True):
    """Affiche la carte, avec le territoire résolu mis en surbrillance si présent.

    fit_bounds=False garde le cadrage par défaut (France métropolitaine) plutôt que
    de recadrer sur l'emprise du territoire — utile pour le contour "France entière"
    par défaut, dont la bbox englobe aussi les DROM (vue mondiale peu lisible sinon).
    """
    m = _base_map()
    if territoire is not None and territoire.geometry is not None:
        folium.GeoJson(
            mapping(territoire.geometry),
            style_function=lambda _: {"color": "#e1000f", "weight": 2, "fillColor": "#e1000f", "fillOpacity": 0.15},
        ).add_to(m)
        if fit_bounds:
            xmin, ymin, xmax, ymax = territoire.bbox
            m.fit_bounds([[ymin, xmin], [ymax, xmax]])
    return st_folium(m, height=420, use_container_width=True, key=key, returned_objects=[])


def render_bbox_map(key: str):
    """Carte avec outil de dessin (rectangle uniquement) pour définir une bbox."""
    m = _base_map()
    Draw(
        export=False,
        draw_options={
            "rectangle": True,
            "polygon": False,
            "circle": False,
            "marker": False,
            "circlemarker": False,
            "polyline": False,
        },
        edit_options={"edit": False, "remove": True},
    ).add_to(m)
    return st_folium(m, height=420, use_container_width=True, key=key, returned_objects=["last_active_drawing"])


def render_extraction_preview(preview: dict, key: str):
    """Aperçu du résultat d'extraction, une couche par groupe (bascule via la légende).

    `preview` doit déjà être plafonné en nombre d'entités et simplifié en amont (cf.
    `app.py::_build_preview`) — on affiche ici un échantillon, jamais le résultat complet :
    un gros territoire peut compter des centaines de milliers d'entités, bien trop pour
    un rendu navigateur raisonnable (et on veut éviter de reproduire le dépassement de
    mémoire déjà rencontré en gardant ça léger en session_state).
    """
    m = _base_map()
    xs, ys = [], []

    for i, (layer_name, gdf) in enumerate(preview.items()):
        if gdf is None or len(gdf) == 0:
            continue
        color = PREVIEW_PALETTE[i % len(PREVIEW_PALETTE)]
        fg = folium.FeatureGroup(name=f"{layer_name} ({len(gdf)})", show=True)
        geojson_data = json.loads(gdf.assign(couche=layer_name)[["geometry", "couche"]].to_json())
        folium.GeoJson(
            geojson_data,
            style_function=lambda _, c=color: {"color": c, "weight": 2, "fillColor": c, "fillOpacity": 0.35},
            marker=folium.CircleMarker(radius=4, color=color, fill=True, fill_color=color, fill_opacity=0.8, weight=1),
            tooltip=folium.GeoJsonTooltip(fields=["couche"], aliases=["Couche"]),
        ).add_to(fg)
        fg.add_to(m)

        xmin, ymin, xmax, ymax = gdf.total_bounds
        xs += [xmin, xmax]
        ys += [ymin, ymax]

    folium.LayerControl(collapsed=False).add_to(m)
    if xs and ys:
        m.fit_bounds([[min(ys), min(xs)], [max(ys), max(xs)]])

    return st_folium(m, height=420, use_container_width=True, key=key, returned_objects=[])
