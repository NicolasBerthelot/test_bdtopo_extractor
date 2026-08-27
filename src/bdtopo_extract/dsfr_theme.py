"""Habillage visuel DSFR (Système de Design de l'État) par-dessus les widgets Streamlit.

Reprend la police Marianne et les couleurs officielles (bleu France, gris texte,
gris fond alt) directement depuis la feuille de style publique @gouvfr/dsfr,
pour un rendu cohérent avec les sites publics français.

Ceci est un HABILLAGE, pas une conformité DSFR/RGAA complète : Streamlit génère
ses propres composants (pas les classes `.fr-*` officielles), donc le HTML sous-
jacent ne correspond pas à la structure DSFR réglementaire. Volontairement, le
bloc-marque officiel (logo Marianne + « RÉPUBLIQUE FRANÇAISE ») n'est pas utilisé
ici : il est réservé aux services officiels de l'État, ce qui n'est pas le cas de
cet outil (données IGN ouvertes, projet indépendant).
"""

DSFR_CDN_BASE = "https://unpkg.com/@gouvfr/dsfr@1.14.0/dist"

# Couleurs officielles DSFR (extraites de core.min.css, cf. commentaire ci-dessus).
BLUE_FRANCE = "#000091"
BLUE_FRANCE_HOVER = "#1212ff"
GREY_TEXT = "#3a3a3a"
GREY_BG_ALT = "#f6f6f6"
GREY_BORDER = "#ddd"
RED_MARIANNE = "#c9191e"

CSS = f"""
<style>
@font-face {{
    font-family: "Marianne";
    src: url("{DSFR_CDN_BASE}/fonts/Marianne-Regular.woff2") format("woff2");
    font-weight: 400; font-style: normal; font-display: swap;
}}
@font-face {{
    font-family: "Marianne";
    src: url("{DSFR_CDN_BASE}/fonts/Marianne-Medium.woff2") format("woff2");
    font-weight: 500; font-style: normal; font-display: swap;
}}
@font-face {{
    font-family: "Marianne";
    src: url("{DSFR_CDN_BASE}/fonts/Marianne-Bold.woff2") format("woff2");
    font-weight: 700; font-style: normal; font-display: swap;
}}

html, body, [class*="css"], .stApp {{
    font-family: "Marianne", "Segoe UI", Arial, sans-serif !important;
    color: {GREY_TEXT};
}}

/* Bandeau de tête sobre (pas le bloc-marque officiel Marianne/RF) */
.dsfr-topbar {{
    height: 4px;
    width: 100%;
    background: {BLUE_FRANCE};
    margin: -1rem -1rem 1.5rem -1rem;
    width: calc(100% + 2rem);
}}

h1, h2, h3, h4 {{
    font-family: "Marianne", sans-serif !important;
    font-weight: 700 !important;
    color: {GREY_TEXT} !important;
}}

/* Boutons -> style fr-btn : carrés, bleu France, texte blanc */
.stButton > button, .stDownloadButton > button {{
    background-color: {BLUE_FRANCE} !important;
    color: #fff !important;
    border: none !important;
    border-radius: 0 !important;
    font-weight: 500 !important;
    font-family: "Marianne", sans-serif !important;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    background-color: {BLUE_FRANCE_HOVER} !important;
    color: #fff !important;
}}
.stButton > button:disabled {{
    background-color: {GREY_BORDER} !important;
    color: #8b8b8b !important;
}}

/* Champs de saisie -> carrés, fond gris clair, bordure basse */
input, textarea, select,
.stTextInput input, .stNumberInput input {{
    border-radius: 0 !important;
    background-color: {GREY_BG_ALT} !important;
    border: none !important;
    border-bottom: 2px solid {GREY_TEXT} !important;
}}
input:focus, textarea:focus, select:focus {{
    outline: 2px solid {BLUE_FRANCE} !important;
    outline-offset: 2px !important;
}}

/* Radios : coche bleu France au lieu du rouge par défaut de Streamlit */
.stRadio [role="radiogroup"] label span:first-child {{
    border-color: {GREY_TEXT} !important;
}}

/* Liens */
a {{ color: {BLUE_FRANCE} !important; }}
a:hover {{ color: {BLUE_FRANCE_HOVER} !important; }}

/* Bandeaux d'alerte Streamlit -> se rapprocher des fr-alert */
div[data-testid="stAlert"] {{
    border-radius: 0 !important;
    border-left: 4px solid {BLUE_FRANCE} !important;
}}
</style>
"""


def inject():
    """À appeler une fois en tête de script (après st.set_page_config)."""
    import streamlit as st

    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="dsfr-topbar"></div>', unsafe_allow_html=True)
