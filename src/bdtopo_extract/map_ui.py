"""Carte interactive (folium) pour visualiser/dessiner la sélection territoriale."""
from __future__ import annotations

import folium
from folium.plugins import Draw
from shapely.geometry import mapping
from streamlit_folium import st_folium

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
