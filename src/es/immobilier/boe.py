"""Enchères immobilières de la zone de Torrevieja sur le Portal de Subastas du BOE (subastas.boe.es).

    python -m es.immobilier.boe                              # enchères en cours ou à venir de toute la zone
    python -m es.immobilier.boe --municipios torrevieja,orihuela
    python -m es.immobilier.boe --estados all --csv data\\es\\exports\\subastas_boe.csv

**Écart volontaire à la règle du projet.** Partout ailleurs, un `robots.txt` qui interdit tout (`Disallow: /`) arrête la
collecte. Ici, l'utilisateur a explicitement demandé de lire ce portail malgré son `robots.txt` (`Disallow: /`), en le
limitant à l'immobilier de la zone de Torrevieja. Ce module ne vérifie donc pas `robots.txt` — contrairement à `es.eactivos`
et au reste de `es.immobilier`, qui le respectent. Une requête par seconde est conservée par égard pour le serveur.

**Le débiteur, le créancier et le titulaire ne sont jamais gardés.** Sans compte, une fiche d'enchère (recherche publique
ou page de détail) ne montre déjà aucun de ces trois-là, ce qui a été vérifié avant d'écrire ce module ; `redact()` coupe
par précaution le texte dès l'un de ces mots, au cas où une fiche future en afficherait un.
**Les voisins cités dans une clause « Linda : »** (la formule notariale qui décrit les limites d'un bien, ex. « LINDA:
derecha, casa de Pedro Ejemplo Ruiz… ») sont en revanche gardés : ce sont des données de registre public sur des
tiers, pas l'identité du débiteur, et l'utilisateur a choisi explicitement (23/09/2026) de les garder après une première
version du filtre qui les coupait aussi.

**Ce que ce portail est** : une base de TOUTES les enchères publiques espagnoles (judiciaires, notariales, fiscales,
administratives), pas seulement des liquidations concursales : il n'a pas de lien avec le BORME ni avec `es.report links`.
La recherche se fait par commune (texte libre côté BOE) et par province ; on interroge chaque commune de la zone
séparément, car la recherche par texte ne repère pas toujours la bonne ville dans une fiche (l'autorité qui gère
l'enchère peut être dans une autre ville que le bien).
"""
import argparse
import re
import time
from pathlib import Path

import requests

from es.immobilier import zone
from es.paths import DB_PATH
from es.report import table, write_csv
from es.storage import Storage

BASE = "https://subastas.boe.es"
SEARCH_URL = f"{BASE}/subastas_ava.php"
USER_AGENT = "BodaccScrap (projet scolaire)"
PROVINCE_CODES = {"alicante": "03"}
# Códigos de estado du formulaire de recherche -> vocabulaire du projet (comme es.report : abierta/proxima/cerrada).
STATE_MAP = {"PU": "proxima", "EJ": "abierta", "SU": "cerrada", "CA": "cerrada", "PC": "cerrada", "FS": "cerrada"}
STATE_LABELS = {"proxima": "à venir", "abierta": "en cours", "cerrada": "clos"}
STATUSES = {"live": ("proxima", "abierta"), "open": ("abierta",), "upcoming": ("proxima",), "closed": ("cerrada",), "all": None}
MAX_PAGES = 5                                # garde-fou : au plus 250 résultats par recherche (commune + état)
# Un mot qui, s'il apparaissait, signalerait le débiteur, le créancier ou le titulaire : le texte est coupé avant lui.
# Ne couvre volontairement pas les clauses « Linda : » (limites du bien, qui nomment les voisins) : décision explicite
# de l'utilisateur (23/09/2026) — une donnée de registre public sur des tiers, à distinguer de l'identité du débiteur.
NAME_WORDS = re.compile(r"\b(?:deudor|ejecutad[oa]|demandad[oa]|titular|acreedor|propietari[oa])\b", re.IGNORECASE)
NUMBER = re.compile(r"([\d.]+),\d+\s*€|([\d.]+)\s*€")
# « Finca 12.345. URBANA.– Vivienda... » ou « URBANA. VEINTIOCHO.- Vivienda... » : formule notariale systématique,
# à retirer avant de deviner le type de bien — « urbana » n'indique qu'un usage de sol (opposé à « rústica »), pas un
# type de bien, et sinon « finca », mot-clé de es.immobilier.zone, l'emporterait toujours sur le vrai type cité juste
# après (« vivienda », « chalet »...). Un ordinal restant après (« VEINTIOCHO ») est sans risque : aucun mot-clé de
# zone.PROPERTY_WORDS ne lui correspond. « Rústica », à l'inverse, N'EST PAS retiré : c'est déjà, à lui seul, un type
# correct (« terreno/finca », comme « finca ») quand rien de plus précis n'est cité.
REGISTRY_PREFIX = re.compile(
    r"^\s*(?:finca\b\s*(?:registral)?\s*(?:n[º°oO]\.?)?\s*(?:[\d.]+\.)?\s*)?urbana\b\.?[\s.,:\-–—]*", re.IGNORECASE)

TABLE_COLUMNS = [("estado", "état"), ("municipio", "commune"), ("tipo", "type"), ("tipo_subasta", "origine"),
                 ("descripcion", "bien"), ("valor", "valor €"), ("fecha_fin", "fin")]
CSV_COLUMNS = ["id", *[c for c, _ in TABLE_COLUMNS if c != "descripcion"], "descripcion", "tasacion", "puja_minima",
              "deposito", "cantidad_reclamada", "expediente", "organo", "anuncio_boe", "url"]


def redact(text):
    """Coupe le texte avant tout mot qui désignerait une personne (débiteur, créancier...) ; None si rien à garder."""
    if not text:
        return text
    match = NAME_WORDS.search(text)
    return text[:match.start()].strip() or None if match else text


def to_int(text):
    """'52.032,62 €' -> 52032 ; 'Sin puja mínima' ou vide -> None (comme es.eactivos.to_int)."""
    match = NUMBER.search(text or "")
    if not match:
        return None
    cleaned = (match.group(1) or match.group(2)).replace(".", "")
    return int(cleaned) if cleaned.isdigit() else None


def post(url, data):
    """(code HTTP, texte). (None, '') si la connexion échoue."""
    try:
        response = requests.post(url, data=data, headers={"User-Agent": USER_AGENT}, timeout=60)
        return response.status_code, response.text
    except requests.exceptions.RequestException:
        return None, ""


def get(url):
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        return response.status_code, response.text
    except requests.exceptions.RequestException:
        return None, ""


def search_data(municipio, estado, provincia="alicante"):
    """Champs du formulaire `subastas_ava.php` : bien immobilier (I), cette commune et cette province, un seul état."""
    return {
        "campo[2]": "SUBASTA.ESTADO.CODIGO", "dato[2]": estado,
        "campo[3]": "BIEN.TIPO", "dato[3]": "I",
        "campo[7]": "BIEN.LOCALIDAD", "dato[7]": municipio,
        "campo[8]": "BIEN.COD_PROVINCIA", "dato[8]": PROVINCE_CODES[provincia.lower()],
        "accion": "Buscar",
    }


def visible(html_fragment):
    return re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), html_fragment).strip()


def parse_results_page(html):
    """([lignes brutes], url de la page suivante ou None). Une ligne = un item <li class="resultado-busqueda">."""
    rows = []
    for block in re.findall(r'<li class="resultado-busqueda">(.*?)</li>\s*(?=<li class="resultado-busqueda">|</ul>)', html, re.S):
        id_match = re.search(r"<h3>\s*SUBASTA\s+([^<]+?)\s*</h3>", block)
        detail = re.search(r'href="(\.?/?detalleSubasta\.php\?idSub=[^"]+)"', block)
        if not id_match or not detail:
            continue
        h4 = re.search(r"<h4>(.*?)</h4>", block, re.S)
        organo = visible(re.sub(r"\s+", " ", h4.group(1))).strip() if h4 else ""
        paragraphs = [visible(re.sub(r"\s+", " ", p)).strip() for p in re.findall(r"<p>(.*?)</p>", block, re.S)]
        expediente = next((p.removeprefix("Expediente:").strip() for p in paragraphs if p.startswith("Expediente:")), None)
        estado_p = next((p for p in paragraphs if p.startswith("Estado:")), "")
        others = [p for p in paragraphs if p is not estado_p and not p.startswith("Expediente:")]
        rows.append({
            "id": id_match.group(1), "organo": redact(organo), "expediente": expediente,
            "estado_texto": estado_p.removeprefix("Estado:").strip(), "descripcion": redact(" ".join(others)),
            "url": f"{BASE}/{detail.group(1).removeprefix('./').removeprefix('/').replace('&amp;', '&')}",
        })
    next_page = re.search(r'<a[^>]+href="(\./subastas_ava\.php\?accion=Mas[^"]+)"[^>]*>\s*<abbr title="P[aá]gina">', html)
    return rows, (f"{BASE}/{next_page.group(1).removeprefix('./').replace('&amp;', '&')}" if next_page else None)


def parse_detail(html):
    """Montants et dates de la fiche : jamais de nom, cette page n'en affiche aucun sans connexion (vérifié le 23/09/2026)."""
    text = visible(re.sub(r"<[^>]+>", "|", re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)))
    # La page empile beaucoup de balises vides (mise en page) : plusieurs « | » de suite ne comptent que pour une seule
    # séparation, sinon une étiquette et sa valeur, souvent dans des balises directement voisines, ne se recolleraient pas.
    text = re.sub(r"\s*(?:\|\s*)+", " | ", text).strip()

    def field(label):
        found = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([^|]+?)\s*\|", text)
        return found.group(1).strip() if found else None

    return {
        "tipo_subasta": field("Tipo de subasta"), "cantidad_reclamada": to_int(field("Cantidad reclamada")),
        "lotes": (lambda v: None if not v or "sin lotes" in v.lower() else to_int(v))(field("Lotes")),
        "anuncio_boe": field("Anuncio BOE"), "valor": to_int(field("Valor subasta")), "tasacion": to_int(field("Tasación")),
        "puja_minima": to_int(field("Puja mínima")), "deposito": to_int(field("Importe del depósito")),
    }


DETAIL_FIELDS = ("tipo_subasta", "cantidad_reclamada", "lotes", "anuncio_boe", "valor", "tasacion", "puja_minima", "deposito")


def collect(storage, municipios=None, estados=("proxima", "abierta"), fetch_post=post, fetch_get=get, pause=1.0,
           sleep=time.sleep, refresh=False, log=print):
    """Lit la zone commune par commune et état par état. Retourne {'lus', 'nouveaux', 'nouvelles_encheres'}.

    La recherche (commune × état) est toujours refaite : c'est elle qui dit si une enchère a changé d'état ou si
    une nouvelle est apparue. La fiche de détail, elle, n'est relue que pour une enchère jamais vue, ou avec
    `refresh=True` : ses montants (valeur, dépôt...) changent rarement une fois l'enchère publiée.
    """
    towns = sorted({zone.MUNICIPALITIES[k] for k in (municipios or zone.MUNICIPALITIES)})
    codes = [code for code, label in STATE_MAP.items() if label in estados]
    known = {} if refresh else {r["id"]: r for r in storage.rows_subastas_boe()}
    result = {"lus": 0, "nouveaux": 0, "nouvelles_encheres": []}
    seen_ids = set()
    for town in towns:
        for code in codes:
            sleep(pause)
            status, html = fetch_post(SEARCH_URL, search_data(town, code))
            if status != 200:
                continue
            rows, next_url = parse_results_page(html)
            pages = 1
            while next_url and pages < MAX_PAGES:
                sleep(pause)
                status, html = fetch_get(next_url)
                if status != 200:
                    break
                more, next_url = parse_results_page(html)
                rows += more
                pages += 1
            for row in rows:
                if row["id"] in seen_ids:                    # la même enchère peut ressortir pour deux communes de la zone
                    continue
                seen_ids.add(row["id"])
                municipio = zone.municipality(zone.slug_of_text(f"{row['descripcion'] or ''} {row['organo'] or ''}"), municipios)
                tipo = zone.property_type(zone.slug_of_text(REGISTRY_PREFIX.sub("", row["descripcion"] or "")))
                previous = known.get(row["id"])
                if previous is not None:
                    details = {field: previous[field] for field in DETAIL_FIELDS}
                else:
                    sleep(pause)
                    status, detail_html = fetch_get(row["url"])
                    details = parse_detail(detail_html) if status == 200 else {}
                item = {**row, **details, "municipio": municipio or town, "tipo": tipo,
                       "estado_boe": code, "estado": STATE_MAP[code],
                       "fecha_inicio": None, "fecha_fin": None, "origen": row["id"].split("-")[1] if "-" in row["id"] else None}
                fin = re.search(r"(\d{2}/\d{2}/\d{4})", item.pop("estado_texto", "") or "")
                if fin:
                    d, m, y = fin.group(1).split("/")
                    item["fecha_fin"] = f"{y}-{m}-{d}"
                result["lus"] += 1
                if storage.upsert_subastas_boe([item]):
                    result["nouveaux"] += 1
                    result["nouvelles_encheres"].append(item)
    return result


def describe(row):
    value = f"{row['valor']:,} €".replace(",", " ") if row.get("valor") is not None else None
    parts = [row.get("descripcion") or row.get("id"), row.get("municipio"), value, row.get("fecha_fin") and f"fin le {row['fecha_fin']}",
            row.get("url")]
    return " | ".join(p for p in parts if p)


def main(argv=None, fetch_post=post, fetch_get=get):
    parser = argparse.ArgumentParser(description="Enchères immobilières de la zone de Torrevieja (Portal de Subastas du BOE).")
    parser.add_argument("--municipios", help="communes séparées par des virgules (défaut : toute la zone de Torrevieja)")
    parser.add_argument("--estados", choices=list(STATUSES), default="live", help="live (défaut), open, upcoming, closed, all")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes (défaut : 1)")
    parser.add_argument("--refresh", action="store_true",
                        help="relire aussi la fiche de détail des enchères déjà connues (valeur, dépôt...)")
    parser.add_argument("--limit", type=int, default=30, help="lignes affichées (défaut : 30)")
    parser.add_argument("--csv", help="exporter tous les résultats dans ce fichier CSV")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args(argv)
    if args.pause < 0:
        parser.error("--pause ne peut pas être négatif")
    try:
        wanted = zone.keys_for([n for n in args.municipios.split(",") if n.strip()]) if args.municipios else None
    except ValueError as error:
        parser.error(str(error))

    with Storage(args.db) as storage:
        result = collect(storage, wanted, STATUSES[args.estados] or ("proxima", "abierta", "cerrada"),
                         fetch_post, fetch_get, args.pause, refresh=args.refresh, log=lambda m: print(m))
        print(f"→ {result['lus']} lu(e)s, {result['nouveaux']} nouvelle(s) enchère(s)")
        for row in result["nouvelles_encheres"]:
            print(f"   • {describe(row)}")

        statuses = STATUSES[args.estados]
        rows = [r for r in storage.rows_subastas_boe() if statuses is None or r["estado"] in statuses]
        rows = [{**r, "etat": STATE_LABELS.get(r["estado"], r["estado"])} for r in rows]
        columns = [("etat", "état"), *TABLE_COLUMNS[1:]]
        if args.csv:
            write_csv(rows, args.csv, CSV_COLUMNS)
            print(f"\n{len(rows)} enchère(s) exportée(s) dans {args.csv}")
        else:
            print()
            print(table(rows[:args.limit], columns, width=44, link_key="url") if rows else "Aucune enchère.")
            print(f"\n{len(rows)} enchère(s)" + (f", {args.limit} affichée(s)" if len(rows) > args.limit else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
