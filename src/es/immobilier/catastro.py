"""Consultation ponctuelle du Catastro (cadastre espagnol) : surface, usage, année de construction, référence exacte.

    python -m es.immobilier.catastro --rc 1234567AB1234C0002XY
    python -m es.immobilier.catastro --provincia alicante --municipio "guardamar del segura" --calle "mayor" --numero 12
    python -m es.immobilier.catastro --provincia alicante --municipio "guardamar del segura" --calle "mayor" --numero 12 --detalle
    python -m es.immobilier.catastro --calles --provincia alicante --municipio torrevieja --calle mar   # rues qui contiennent « mar »
    python -m es.immobilier.catastro --adresses adresses.csv --detalle --csv sortie.csv                 # plusieurs immeubles d'un coup

Une adresse seule donne, sans `--detalle`, la simple liste des unités du bâtiment (une requête). Avec `--detalle`,
elle donne le détail complet (surface, usage, année, constructions) de **chaque** unité du bâtiment, pas seulement
d'une adresse choisie au hasard parmi elles : une requête de plus par unité, donc jusqu'à autant que le bâtiment a
d'unités (39 pour l'exemple ci-dessus).

Sert à vérifier un bien vu dans une enchère (`es.immobilier.boe`), pas à en collecter une liste : pas de base de
données, juste une consultation à la demande, imprimée à l'écran (ou dans un CSV en sortie avec `--adresses`).
Réutilisable pour n'importe quelle commune, pas seulement Torrevieja : `--provincia`/`--municipio` sont des
paramètres libres, jamais écrits en dur.

**Il n'existe pas de « tout le cadastre de Torrevieja » automatisable.** Le service donne bien la liste des rues
d'une commune (`--calles`, gratuit — Torrevieja en a 1 027, vérifié le 23 septembre 2026), mais pas celle des
numéros d'une rue : `ConsultaNumero` exige un numéro déjà connu, il ne les énumère pas. Il n'y a donc aucun moyen
gratuit de deviner tous les numéros de toutes les rues sans les essayer un par un (des dizaines de milliers d'essais
en aveugle pour une seule commune) — ce que ce module ne fait pas. **Chaque immeuble se cherche par une adresse que
vous connaissez déjà** (trouvée dans une enchère, une annonce...), un par un ou en liste avec `--adresses`.

**Ce qu'on ne peut PAS avoir ici, et pourquoi.** Le Catastro distingue deux valeurs :
- le **valor catastral** (valeur cadastrale, base de l'impôt foncier du propriétaire) est une **donnée protégée par
  la loi espagnole** : seul le propriétaire peut la consulter, avec un certificat électronique. Ce n'est pas une
  question de `robots.txt` ou de conditions d'utilisation qu'on pourrait choisir de lever : la loi la réserve au
  titulaire, quel que soit le moyen technique employé pour la demander.
- le **valor de referencia** (plancher fiscal d'une vente, pensé pour qu'un acheteur le consulte avant d'acheter)
  est, lui, public et gratuit — mais son outil de consultation est une page interactive sans API documentée comme
  celle utilisée ici, et n'a pas été automatisé (voir le README, section Catastro).

Ce module ne lit donc que les **données non protégées** (« Datos No Protegidos », DNP) : adresse, surface, usage,
année, référence cadastrale — jamais une valeur ni un nom de propriétaire, qui n'apparaissent nulle part dans ces
deux services.

**Source** : le service web libre du Catastro (`ovc.catastro.meh.es`), gratuit, sans compte, documenté par la
Direction générale du Cadastre (« Servicios web libres de la Sede Electrónica del Catastro »). Aucun `robots.txt`
n'existe sur ce domaine (vérifié le 23 septembre 2026 : réponse HTTP 404, donc aucune restriction déclarée).
"""
import argparse
import csv
import time
import unicodedata
from xml.etree import ElementTree as ET

import requests

from es.report import table, write_csv

BASE = "http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx"
USER_AGENT = "BodaccScrap (projet scolaire)"
NS = "{http://www.catastro.meh.es/}"
# Sigla officielle du type de voie, telle qu'attendue par le service ; un mot courant suffit en entrée.
VIA_TYPES = {
    "calle": "CL", "avenida": "AV", "plaza": "PZ", "paseo": "PS", "carretera": "CR", "camino": "CM",
    "urbanizacion": "UR", "travesia": "TR", "ronda": "RD", "paraje": "PJ", "poligono": "PG", "barrio": "BO",
    "lugar": "LG", "gran via": "GV",
}


class CatastroError(Exception):
    """Erreur renvoyée par le service (adresse ou référence inconnue, etc.) : message destiné à l'utilisateur."""


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def via_code(text):
    """Sigla à deux lettres (« CL », « AV »...) à partir d'un mot courant, ou tel quel si déjà un code."""
    if not text:
        return "CL"
    if len(text) == 2 and text.isalpha():
        return text.upper()
    code = VIA_TYPES.get(fold(text).strip())
    if not code:
        raise CatastroError(f"type de voie inconnu : {text!r} (essayez calle, avenida, plaza, paseo, carretera, camino...)")
    return code


def get(url, params):
    """(code HTTP, texte). (None, '') si la connexion échoue."""
    try:
        response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        return response.status_code, response.text
    except requests.exceptions.RequestException:
        return None, ""


def _text(node, path):
    found = node.find(f"{NS}{path.replace('/', f'/{NS}')}")
    return found.text.strip() if found is not None and found.text else None


def _error(root):
    err = root.find(f"{NS}lerr/{NS}err")
    return f"{_text(err, 'des')} (code {_text(err, 'cod')})" if err is not None else None


def _rc_of(rc_node):
    return "".join(_text(rc_node, part) or "" for part in ("pc1", "pc2", "car", "cc1", "cc2"))


def _address_of(dt_node):
    dir_node = dt_node.find(f"{NS}locs/{NS}lous/{NS}lourb/{NS}dir")
    loint = dt_node.find(f"{NS}locs/{NS}lous/{NS}lourb/{NS}loint")
    calle = " ".join(p for p in (_text(dir_node, "tv"), _text(dir_node, "nv"), _text(dir_node, "pnp")) if p) if dir_node is not None else None
    return {
        "provincia": _text(dt_node, "np"), "municipio": _text(dt_node, "nm"), "calle": calle,
        "edificio": _text(dir_node, "td") if dir_node is not None else None,
        "escalera": _text(loint, "es") if loint is not None else None,
        "planta": _text(loint, "pt") if loint is not None else None, "puerta": _text(loint, "pu") if loint is not None else None,
    }


def parse_location(xml_text):
    """[unités trouvées à cette adresse] (une par escalier/étage/porte), ou lève CatastroError."""
    root = ET.fromstring(xml_text)
    error = _error(root)
    if error:
        raise CatastroError(error)
    units = []
    for node in root.findall(f"{NS}lrcdnp/{NS}rcdnp"):
        units.append({"rc": _rc_of(node.find(f"{NS}rc")), **_address_of(node.find(f"{NS}dt"))})
    return units


def parse_reference(xml_text):
    """Détails d'un bien (adresse, usage, surface, année, constructions), ou lève CatastroError."""
    root = ET.fromstring(xml_text)
    error = _error(root)
    if error:
        raise CatastroError(error)
    bi = root.find(f"{NS}bico/{NS}bi")
    debi = bi.find(f"{NS}debi")
    constructions = [{"tipo": _text(c, "lcd"), "superficie_m2": int(_text(c, "dfcons/stl") or 0) or None}
                     for c in root.findall(f"{NS}bico/{NS}lcons/{NS}cons")]
    return {
        "rc": _rc_of(bi.find(f"{NS}idbi/{NS}rc")), "direccion": _text(bi, "ldt"), **_address_of(bi.find(f"{NS}dt")),
        "uso": _text(debi, "luso"), "superficie_m2": int(_text(debi, "sfc") or 0) or None,
        "cuota_participacion": _text(debi, "cpt"), "ano_construccion": _text(debi, "ant"),
        "construcciones": constructions,
    }


def by_location(provincia, municipio, calle, numero, via="calle", bloque="", escalera="", planta="", puerta="", fetch=get):
    params = {"Provincia": provincia, "Municipio": municipio, "Sigla": via_code(via), "Calle": calle, "Numero": numero,
             "Bloque": bloque, "Escalera": escalera, "Planta": planta, "Puerta": puerta}
    status, text = fetch(f"{BASE}/Consulta_DNPLOC", params)
    if status != 200:
        raise CatastroError(f"le Catastro n'a pas répondu (HTTP {status})")
    return parse_location(text)


def by_reference(rc, fetch=get):
    status, text = fetch(f"{BASE}/Consulta_DNPRC", {"Provincia": "", "Municipio": "", "RC": rc})
    if status != 200:
        raise CatastroError(f"le Catastro n'a pas répondu (HTTP {status})")
    return parse_reference(text)


def parse_streets(xml_text):
    root = ET.fromstring(xml_text)
    error = _error(root)
    if error:
        raise CatastroError(error)
    return [{"tipo": _text(c.find(f"{NS}dir"), "tv"), "nombre": _text(c.find(f"{NS}dir"), "nv")}
            for c in root.findall(f"{NS}callejero/{NS}calle")]


def list_streets(provincia, municipio, tipo=None, nombre=None, fetch=get):
    """Rues d'une commune (libre, gratuit), filtrables par type de voie et/ou un mot du nom. Torrevieja en a 1 027."""
    params = {"Provincia": provincia, "Municipio": municipio, "TipoVia": via_code(tipo) if tipo else "", "NombreVia": nombre or ""}
    status, text = fetch(f"{BASE}/ConsultaVia", params)
    if status != 200:
        raise CatastroError(f"le Catastro n'a pas répondu (HTTP {status})")
    return parse_streets(text)


def read_addresses(path):
    """Lignes d'un CSV d'adresses : colonnes provincia, municipio, calle, numero obligatoires ; via, bloque,
    escalera, planta, puerta optionnelles (défaut : voie « calle », le reste vide)."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        raise CatastroError(f"fichier introuvable : {path}")
    missing = {"provincia", "municipio", "calle", "numero"} - set(rows[0].keys() if rows else [])
    if missing:
        raise CatastroError(f"colonne(s) manquante(s) dans {path} : {', '.join(sorted(missing))}")
    return rows


def batch(addresses, detalle=False, pause=1.0, sleep=time.sleep, fetch=get, log=print):
    """Une adresse = un immeuble. Retourne une ligne par unité qui s'y trouve.

    Sans `--detalle` (défaut) : une seule requête par adresse (la liste des unités). Avec `--detalle` : une requête
    de plus par unité pour sa surface, son usage et son année (une nouvelle tentative en cas d'échec, comme pour les
    documents du BORME) — à réserver à quelques immeubles précis, un immeuble de plusieurs dizaines d'unités (un
    exemple vu : 39) coûte alors autant de requêtes.
    """
    rows = []
    for i, address in enumerate(addresses):
        if i:
            sleep(pause)
        label = f"{address.get('calle')} {address.get('numero')} ({address.get('municipio')})"
        try:
            units = by_location(address["provincia"], address["municipio"], address["calle"], address["numero"],
                                via=address.get("via") or "calle", bloque=address.get("bloque", ""),
                                escalera=address.get("escalera", ""), planta=address.get("planta", ""),
                                puerta=address.get("puerta", ""), fetch=fetch)
        except CatastroError as error:
            log(f"  {label} : {error}")
            continue
        log(f"  {label} : {len(units)} unité(s)")
        for unit in units:
            if detalle:
                unit = {**unit, **_reference_with_retry(unit["rc"], pause, sleep, fetch, log)}
            rows.append(unit)
    return rows


def _reference_with_retry(rc, pause, sleep, fetch, log):
    """Le service échoue de temps en temps sur une longue série de requêtes (connexion réinitialisée, vu en réel sur
    un immeuble de 39 unités : 12 échecs) ; une seule nouvelle tentative, comme pour les documents du BORME."""
    for attempt in range(2):
        sleep(pause if attempt == 0 else pause * 3)
        try:
            return by_reference(rc, fetch=fetch)
        except CatastroError as error:
            last_error = error
    log(f"    {rc} : {last_error}")
    return {}


def print_units(units):
    print(f"{len(units)} unité(s) à cette adresse :\n")
    for u in units:
        loc = f"Es:{u['escalera']} Pl:{u['planta']} Pt:{u['puerta']}" if u["escalera"] else ""
        print(f"  {u['rc']}  {loc}  {u['edificio'] or ''}".rstrip())
    print("\nUtilisez --rc avec l'une de ces références pour le détail (surface, usage, année).")


def print_streets(streets):
    print(f"{len(streets)} rue(s) :\n")
    for s in streets:
        print(f"  {s['tipo']}  {s['nombre']}")


BATCH_COLUMNS = ["calle", "numero", "rc", "escalera", "planta", "puerta", "edificio", "uso", "superficie_m2", "ano_construccion"]


def write_csv_of_batch(rows, path, detalle):
    """Exporte des lignes de `batch()` ; les constructions (une liste) sont aplaties en un texte pour le CSV."""
    columns = [*BATCH_COLUMNS, "construcciones"] if detalle else BATCH_COLUMNS
    flattened = [{**r, "construcciones": "; ".join(f"{c['tipo']} {c['superficie_m2'] or '?'}m2" for c in r.get("construcciones", []))}
                for r in rows]
    write_csv(flattened, path, columns)


def print_batch(rows, limit):
    print()
    print(table(rows[:limit], [(c, c) for c in BATCH_COLUMNS]) if rows else "Aucun résultat.")
    print(f"\n{len(rows)} unité(s)" + (f", {limit} affichée(s)" if len(rows) > limit else ""))


def print_detail(d):
    surface = f"{d['superficie_m2']} m2" if d["superficie_m2"] else "inconnue"
    print(f"Référence cadastrale : {d['rc']}")
    print(f"Adresse              : {d['direccion']}")
    print(f"Usage                : {d['uso'] or 'inconnu'}")
    print(f"Surface              : {surface}")
    print(f"Année de construction: {d['ano_construccion'] or 'inconnue'}")
    if d["cuota_participacion"]:
        print(f"Quote-part           : {d['cuota_participacion']} %")
    if d["construcciones"]:
        print("Constructions :")
        for c in d["construcciones"]:
            print(f"  - {c['tipo']}" + (f" ({c['superficie_m2']} m2)" if c["superficie_m2"] else ""))
    print("\nLe Catastro ne donne ici ni valeur ni nom de propriétaire (données protégées, réservées au titulaire).")


def main(argv=None, fetch=get, sleep=time.sleep):
    parser = argparse.ArgumentParser(description="Consulte le Catastro (données non protégées uniquement : pas de valeur, pas de propriétaire).")
    parser.add_argument("--rc", help="référence cadastrale (20 caractères) : donne directement le détail du bien")
    parser.add_argument("--calles", action="store_true", help="lister les rues d'une commune (avec --provincia --municipio ; --calle filtre sur un mot du nom)")
    parser.add_argument("--adresses", help="fichier CSV de plusieurs adresses (colonnes : provincia,municipio,calle,numero, "
                                          "et en option via,bloque,escalera,planta,puerta) : un immeuble par ligne")
    parser.add_argument("--detalle", action="store_true",
                        help="aussi la surface/usage/année de chaque unité du bâtiment (avec une adresse directe ou --adresses) "
                             "— coûteux : une requête de plus par unité, autant que le bâtiment a d'unités")
    parser.add_argument("--provincia", help="ex : alicante")
    parser.add_argument("--municipio", help="ex : guardamar del segura")
    parser.add_argument("--via", default="calle", help="type de voie : calle, avenida, plaza, paseo, carretera... (défaut : calle)")
    parser.add_argument("--calle", help="nom de la voie, sans le type (« mayor ») ; filtre partiel avec --calles")
    parser.add_argument("--numero", help="numéro dans la voie")
    parser.add_argument("--bloque", default="")
    parser.add_argument("--escalera", default="")
    parser.add_argument("--planta", default="")
    parser.add_argument("--puerta", default="")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes avec --detalle/--adresses (défaut : 1)")
    parser.add_argument("--limit", type=int, default=30, help="lignes affichées avec --detalle/--adresses (défaut : 30)")
    parser.add_argument("--csv", help="avec --detalle ou --adresses : exporter tous les résultats dans ce fichier CSV")
    args = parser.parse_args(argv)
    if args.pause < 0:
        parser.error("--pause ne peut pas être négatif")

    try:
        if args.rc:
            print_detail(by_reference(args.rc, fetch))
        elif args.calles:
            if not (args.provincia and args.municipio):
                parser.error("--calles a besoin de --provincia et --municipio")
            print_streets(list_streets(args.provincia, args.municipio, nombre=args.calle, fetch=fetch))
        elif args.adresses:
            addresses = read_addresses(args.adresses)
            if not addresses:
                raise SystemExit(f"{args.adresses} ne contient aucune adresse.")
            rows = batch(addresses, args.detalle, args.pause, sleep, fetch, log=print)
            if args.csv:
                write_csv_of_batch(rows, args.csv, args.detalle)
                print(f"\n{len(rows)} unité(s) exportée(s) dans {args.csv}")
            else:
                print_batch(rows, args.limit)
        elif args.provincia and args.municipio and args.calle and args.numero:
            if not args.detalle:
                print_units(by_location(args.provincia, args.municipio, args.calle, args.numero, args.via,
                                        args.bloque, args.escalera, args.planta, args.puerta, fetch))
            else:
                address = {"provincia": args.provincia, "municipio": args.municipio, "calle": args.calle, "numero": args.numero,
                          "via": args.via, "bloque": args.bloque, "escalera": args.escalera, "planta": args.planta, "puerta": args.puerta}
                rows = batch([address], detalle=True, pause=args.pause, sleep=sleep, fetch=fetch, log=print)
                if args.csv:
                    write_csv_of_batch(rows, args.csv, True)
                    print(f"\n{len(rows)} unité(s) exportée(s) dans {args.csv}")
                else:
                    print_batch(rows, args.limit)
        else:
            parser.error("donnez --rc, --calles (+ --provincia --municipio), --adresses <fichier>, "
                         "ou --provincia --municipio --calle --numero ensemble")
    except CatastroError as error:
        raise SystemExit(f"Catastro : {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
