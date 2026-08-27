# bdtopo-extract

Extraction à la demande de couches BD Topo® (IGN) par territoire, **sans téléchargement préalable de la base complète**.

S'appuie sur la diffusion cloud-native de l'IGN (FlatGeobuf) sur `telecharger.geoplateforme.fr` : chaque couche BD Topo est lue en flux HTTP avec filtrage spatial par index intégré (`pyogrio` + GDAL `/vsicurl/`), donc seule la zone demandée transite sur le réseau.

## Installation

```powershell
cd C:\Claude\bdtopo-extract
py -3.12 -m venv .venv   # ou le chemin complet vers python.exe si l'alias Windows Store interfère
.\.venv\Scripts\python.exe -m pip install -e .
```

> Note Windows : si `python`/`py` renvoie vers le Microsoft Store, utilise le chemin complet, ex.
> `& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv`

## Usage

```powershell
# Lister les couches disponibles (édition courante détectée automatiquement)
.\.venv\Scripts\bdtopo-extract.exe list-layers

# Chercher un territoire
.\.venv\Scripts\bdtopo-extract.exe list-territoires --type departement --q Gironde
.\.venv\Scripts\bdtopo-extract.exe list-territoires --type commune --q Bordeaux

# Extraire des couches sur un département, reprojeté en Lambert-93
.\.venv\Scripts\bdtopo-extract.exe extract `
    --layers batiment,troncon_de_route,cimetiere `
    --territoire departement:33 `
    --crs EPSG:2154 `
    --output .\export\

# Extraire sur une commune (code INSEE ou nom exact)
.\.venv\Scripts\bdtopo-extract.exe extract --layers batiment --territoire commune:24172 --output .\export\

# Extraire sur une bbox (WGS84 : xmin,ymin,xmax,ymax)
.\.venv\Scripts\bdtopo-extract.exe extract --layers all --territoire "bbox:-0.6,44.8,-0.5,44.9" --output .\export\

# France entière (attention : volume important selon les couches choisies)
.\.venv\Scripts\bdtopo-extract.exe extract --layers aerodrome --territoire france --output .\export\
```

`--territoire` accepte : `france`, `region:<code|nom>`, `departement:<code|nom>`, `commune:<code_insee|nom>`, `bbox:xmin,ymin,xmax,ymax`.

`--format` : `gpkg` (défaut, un seul fichier multi-couches), `shp`, `geojson`.

## Interface graphique

```powershell
.\.venv\Scripts\streamlit.exe run .\src\bdtopo_extract\app.py
```

Ouvre une page dans le navigateur avec : les 58 couches groupées par thème (section repliable par thème, couleur + puce dédiées, description complète non tronquée), recherche + choix du territoire (région/département/commune/bbox/France entière), options de format et de CRS, puis bouton "Extraire" avec téléchargement direct du résultat.

## Fonctionnement

- **`catalog.py`** : scrape la page de diffusion IGN pour découvrir l'édition en cours et l'URL FlatGeobuf de chaque couche. Résultat mis en cache dans `.cache/` et invalidé automatiquement au changement d'édition trimestrielle.
- **`territoire.py`** : résout région/département/commune via les couches Admin Express COG (mêmes principes). Les couches admin sont téléchargées intégralement une fois par édition et mises en cache localement (`.cache/admin_*.gpkg`) — la couche communes fait ~480 Mo, c'est le seul téléchargement "complet" du système, mais il ne se refait qu'au changement d'édition.
- **`extract.py`** : pour chaque couche BD Topo demandée, lecture en flux puis découpage exact (`geopandas.clip`) sur la géométrie du territoire. Deux chemins de lecture :
  - Sans filtre attributaire (cas courant) : FlatGeobuf via `pyogrio.read_dataframe(..., bbox=...)`, index spatial intégré.
  - Avec filtre attributaire (cf. `fields.py`) : GeoParquet via DuckDB (`read_parquet` + `spatial`/`httpfs`), qui exploite les statistiques par bloc de lignes (min/max, y compris sur les attributs, pas seulement la bbox `geometrie_bbox`) pour sauter les blocs ne pouvant pas correspondre. **Les valeurs du filtre doivent être injectées en littéraux SQL, pas en paramètres liés (`?`)** : les paramètres liés désactivent cet élagage côté DuckDB (~15x plus lent), constaté empiriquement. Gain mesuré sur un département entier + filtre rare : ~50s contre 5+ minutes avec l'ancienne approche (FlatGeobuf + filtre en mémoire après coup). La géométrie GeoParquet de l'IGN est encodée en "GeoArrow" natif (structs imbriqués), pas en WKB — reconstruite directement en shapely par type OGC (`_geoarrow_builder`), sans passer par les fonctions de conversion DuckDB (qui ne gèrent pas cet encodage).
- **`fields.py`** : métadonnées des attributs filtrables par couche (nom, type, valeurs possibles), scrapées sur bdtopoexplorer.ign.fr et croisées avec le schéma réel (`pyogrio.read_info`). Même principe d'instantané embarqué que `docs.py`. Dans l'UI, chaque couche cochée avec des champs filtrables propose un panneau "⚙ Filtres" (seuil min/max sur les champs quantitatifs, cases à cocher sur les champs à modalités).

## Charte visuelle DSFR

`dsfr_theme.py` habille l'interface avec la charte du Système de Design de l'État (police Marianne, bleu France `#000091`, formes de composants) via `.streamlit/config.toml` (thème natif Streamlit) et une injection CSS ciblée. C'est un **habillage visuel**, pas une conformité DSFR/RGAA complète : les composants Streamlit ne génèrent pas le HTML `.fr-*` officiel, et les composants tiers rendus dans leur propre iframe (recherche territoriale, carte) ne récupèrent pas ces styles — ils gardent l'apparence par défaut de Streamlit. Le bloc-marque officiel (logo Marianne + « RÉPUBLIQUE FRANÇAISE ») n'est volontairement pas utilisé : il est réservé aux services officiels de l'État.

## Limitations connues

- Le GDAL embarqué dans les wheels `pyogrio` ne compile pas le driver Parquet (nécessiterait Arrow) : la lecture GeoParquet passe donc par DuckDB (moteur SQL séparé), pas par `pyogrio`/geopandas directement.
- Le filtre attributaire réduit vraiment la lecture réseau uniquement quand la couche a une variante GeoParquet ET qu'au moins un filtre est actif (chemin DuckDB). Sans filtre, FlatGeobuf reste utilisé (déjà rapide, index spatial intégré) — pas de régression sur le cas courant.
- `--territoire france` sans filtre spatial peut représenter un volume important selon les couches choisies (ex. `batiment` pour la France entière) — c'est inhérent au fait de vouloir "tout" un thème sans découpage.
