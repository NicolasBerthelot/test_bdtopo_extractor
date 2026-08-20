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

Ouvre une page dans le navigateur avec : sélection multiple des couches, recherche + choix du territoire (région/département/commune/bbox/France entière), options de format et de CRS, puis bouton "Extraire" avec téléchargement direct du résultat.

## Fonctionnement

- **`catalog.py`** : scrape la page de diffusion IGN pour découvrir l'édition en cours et l'URL FlatGeobuf de chaque couche. Résultat mis en cache dans `.cache/` et invalidé automatiquement au changement d'édition trimestrielle.
- **`territoire.py`** : résout région/département/commune via les couches Admin Express COG (mêmes principes). Les couches admin sont téléchargées intégralement une fois par édition et mises en cache localement (`.cache/admin_*.gpkg`) — la couche communes fait ~480 Mo, c'est le seul téléchargement "complet" du système, mais il ne se refait qu'au changement d'édition.
- **`extract.py`** : pour chaque couche BD Topo demandée, lecture en flux (`pyogrio.read_dataframe(..., bbox=...)`) puis découpage exact (`geopandas.clip`) sur la géométrie du territoire.

## Limitations connues

- Seul le format **FlatGeobuf** est utilisé comme source : le GDAL embarqué dans les wheels `pyogrio` ne compile pas le driver Parquet (nécessiterait Arrow). FlatGeobuf reste de toute façon le format recommandé par l'IGN pour l'accès en flux avec filtrage spatial.
- `--territoire france` sans filtre spatial peut représenter un volume important selon les couches choisies (ex. `batiment` pour la France entière) — c'est inhérent au fait de vouloir "tout" un thème sans découpage.
