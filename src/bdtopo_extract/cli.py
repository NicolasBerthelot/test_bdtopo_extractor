from __future__ import annotations

from pathlib import Path

import click

from . import catalog, extract, territoire


def _parse_territoire(spec: str) -> tuple[str, territoire.Territoire | None]:
    """Parse '--territoire' en (label, Territoire|None)."""
    if spec == "france":
        return "France entière", None

    if ":" not in spec:
        raise click.BadParameter(
            "Format attendu: france | region:<code|nom> | departement:<code|nom> | "
            "commune:<code|nom> | bbox:xmin,ymin,xmax,ymax"
        )
    kind, value = spec.split(":", 1)

    if kind == "bbox":
        try:
            xmin, ymin, xmax, ymax = (float(v) for v in value.split(","))
        except ValueError:
            raise click.BadParameter("bbox attendu sous la forme xmin,ymin,xmax,ymax")
        t = territoire.from_bbox(xmin, ymin, xmax, ymax)
        return t.label, t

    if kind not in territoire.ADMIN_LAYER_BY_KIND:
        raise click.BadParameter(f"Type de territoire inconnu: {kind!r}")

    t = territoire.resolve(kind, value)
    return t.label, t


@click.group()
def main():
    """Extraction à la demande de couches BD Topo (IGN) par territoire."""


@main.command("list-layers")
def list_layers():
    """Liste les couches BD Topo disponibles pour l'édition courante."""
    layers = catalog.get_catalog("bdtopo")
    edition = catalog.get_edition("bdtopo")
    click.echo(f"Édition BD Topo courante : {edition}")
    for name in sorted(layers):
        click.echo(f"  {name}")


@main.command("list-territoires")
@click.option("--type", "kind", required=True, type=click.Choice(["region", "departement", "commune"]))
@click.option("--q", "query", default=None, help="Filtre par code INSEE ou nom (recherche partielle)")
def list_territoires(kind: str, query: str | None):
    """Liste les territoires (région/département/commune) correspondant à une recherche."""
    results = territoire.search(kind, query)
    if len(results) == 0:
        click.echo("Aucun résultat.")
        return
    for row in results.itertuples():
        click.echo(f"  {row.code_insee}\t{row.nom_officiel}")


@main.command("extract")
@click.option("--layers", required=True, help="Couches séparées par des virgules, ou 'all'")
@click.option("--territoire", "territoire_spec", required=True)
@click.option("--format", "fmt", default="gpkg", type=click.Choice(["gpkg", "shp", "geojson"]))
@click.option("--crs", default=None, help="CRS de sortie, ex. EPSG:2154 (défaut : EPSG:4326 source)")
@click.option("--output", "output_dir", required=True, type=click.Path(path_type=Path))
def extract_cmd(layers: str, territoire_spec: str, fmt: str, crs: str | None, output_dir: Path):
    """Extrait une ou plusieurs couches BD Topo sur le territoire demandé."""
    catalog_layers = catalog.get_catalog("bdtopo")

    if layers == "all":
        selected = sorted(catalog_layers)
    else:
        selected = [l.strip() for l in layers.split(",") if l.strip()]
        unknown = [l for l in selected if l not in catalog_layers]
        if unknown:
            raise click.BadParameter(
                f"Couche(s) inconnue(s) : {', '.join(unknown)}. "
                f"Voir 'bdtopo-extract list-layers'."
            )

    label, terr = _parse_territoire(territoire_spec)
    click.echo(f"Territoire : {label}")

    results = {}
    for name in selected:
        click.echo(f"  extraction de '{name}'...", nl=False)
        gdf = extract.extract_layer(catalog_layers[name], terr, crs=crs)
        click.echo(f" {len(gdf)} entités ({gdf.attrs.get('extract_seconds')}s)")
        results[name] = gdf

    out_path = extract.write_layers(results, output_dir, fmt=fmt)
    click.echo(f"Écrit dans : {out_path}")


if __name__ == "__main__":
    main()
