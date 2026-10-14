"""Met à jour les lots immobiliers eactivos de la zone (par défaut : région de Torrevieja).

    python -m es.immobilier.update                          # 365 derniers jours, toute la zone
    python -m es.immobilier.update --since 2020-01-01       # plus loin dans le temps
    python -m es.immobilier.update --municipios torrevieja,guardamar
    python -m es.immobilier.update --refresh                # relire aussi les lots déjà connus comme clos

Même méthode et mêmes garde-fous que `es.update` pour les véhicules (voir `es.eactivos`) : plan du site, `robots.txt` évalué en
entier avant chaque requête, une requête par seconde, faits extraits seulement. On ne lit que les fiches dont l'adresse cite une
commune de la zone et un bien immobilier : quelques dizaines de pages, pas les 23 000 lots du site.
"""
import argparse
import re
import time
from datetime import date, timedelta
from urllib.parse import urlparse

from es import eactivos
from es.immobilier import zone
from es.paths import DB_PATH
from es.report import fold
from es.storage import Storage


def select(entries, since, wanted, known_closed=()):
    """[(url, date, commune, type)] des lots du plan du site qui sont de l'immobilier dans la zone, récents, pas déjà clos."""
    chosen = []
    for url, day in entries:
        code = eactivos.lot_code(url)
        if day < since or code is None or code in known_closed:
            continue
        slug = zone.slug_of(url)
        town, kind = zone.municipality(slug, wanted), zone.property_type(slug)
        if town and kind:
            chosen.append((url, day, town, kind))
    chosen.sort(key=lambda item: item[1], reverse=True)
    return chosen


def in_province(lot):
    """Faux si la fiche cite une autre province que celle d'Alicante : une commune peut avoir des homonymes (Guardamar de la
    Safor en Valence, Villamartín en Cadix). Une fiche close ne garde plus son lieu, mais son titre cite la province entre parenthèses.
    Sans aucune province citée, on garde le lot (le doute profite à la recherche, le rapport montre le lieu)."""
    place = fold(f"{lot.get('ubicacion') or ''} {lot.get('titulo') or ''}")
    if "alicante" in place or "alacant" in place:
        return True
    cited = re.search(r"\(([^)]+)\)", fold(f"{lot.get('ubicacion') or ''} {lot.get('titulo') or ''}"))
    return cited is None


def collect(since, storage, wanted=None, fetch=eactivos.get, pause=1.0, sleep=time.sleep, refresh=False, log=print):
    """Lit le plan du site puis les fiches ; retourne {'lus', 'nouveaux', 'ecartes', 'interdits', 'illisibles', 'nouveaux_lots'}."""
    status, robots_text = fetch(f"{eactivos.BASE}/robots.txt")
    robots = eactivos.Robots(robots_text if status == 200 else "")
    sleep(pause)
    if not robots.allowed(urlparse(eactivos.SITEMAP_URL).path):
        raise SystemExit("Le robots.txt d'eactivos interdit son plan du site : arrêt.")
    status, xml_text = fetch(eactivos.SITEMAP_URL)
    if status != 200:
        raise SystemExit(f"Plan du site illisible (HTTP {status}).")
    entries = eactivos.parse_sitemap(xml_text)
    closed = set() if refresh else {r["codigo"] for r in storage.rows_inmuebles("estado = 'cerrada'")}
    todo = select(entries, since, wanted, closed)
    log(f"{len(entries)} lots au plan du site ; {len(todo)} bien(s) immobilier(s) de la zone à lire depuis {since}.")
    result = {"lus": 0, "nouveaux": 0, "ecartes": 0, "interdits": 0, "illisibles": 0, "nouveaux_lots": []}
    for url, day, town, kind in todo:
        if not robots.allowed(urlparse(url).path):
            result["interdits"] += 1
            continue
        sleep(pause)
        status, page = fetch(url)
        lot = eactivos.parse_lot(page, url, day) if status == 200 else None
        if lot is None:
            result["illisibles"] += 1
            continue
        if not in_province(lot):
            result["ecartes"] += 1
            continue
        lot.update(municipio=town, tipo=kind)
        if storage.upsert_inmuebles([lot]):
            result["nouveaux"] += 1
            result["nouveaux_lots"].append(lot)
        result["lus"] += 1
    return result


def describe(lot):
    value = f"{lot['valoracion']:,} €".replace(",", " ") if lot.get("valoracion") is not None else None
    parts = [lot.get("titulo"), lot.get("municipio"), lot.get("tipo"), value,
             lot.get("procedimiento") and f"procédure {lot['procedimiento']}", lot.get("url")]
    return " | ".join(p for p in parts if p)


def main(argv=None, fetch=eactivos.get, sleep=time.sleep, today=None):
    parser = argparse.ArgumentParser(description="Lots immobiliers eactivos d'une zone (usage scolaire, robots.txt respecté).")
    parser.add_argument("--municipios", help="communes séparées par des virgules (défaut : toute la zone de Torrevieja)")
    parser.add_argument("--since", help="lots dont la date au plan du site est postérieure (AAAA-MM-JJ ; défaut : 365 jours)")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes (défaut : 1)")
    parser.add_argument("--refresh", action="store_true", help="relire aussi les lots déjà connus comme clos")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args(argv)
    if args.pause < 0:
        parser.error("--pause ne peut pas être négatif")
    try:
        since = date.fromisoformat(args.since) if args.since else (today or date.today()) - timedelta(days=365)
    except ValueError:
        parser.error(f"date invalide : {args.since!r} (format AAAA-MM-JJ)")
    try:
        wanted = zone.keys_for([n for n in args.municipios.split(",") if n.strip()]) if args.municipios else None
    except ValueError as error:
        parser.error(str(error))

    with Storage(args.db) as storage:
        result = collect(since.isoformat(), storage, wanted, fetch, args.pause, sleep, args.refresh, log=lambda m: print(m))
        print(f"→ {result['lus']} lus, {result['nouveaux']} nouveaux"
              + (f", {result['ecartes']} écarté(s) (hors province d'Alicante)" if result["ecartes"] else "")
              + (f", {result['illisibles']} illisible(s)" if result["illisibles"] else "")
              + (f", {result['interdits']} interdit(s) par robots.txt" if result["interdits"] else ""))
        for lot in result["nouveaux_lots"]:
            print(f"   • {describe(lot)}")
        counts = {row[0]: row[1] for row in storage.conn.execute("SELECT estado, COUNT(*) FROM inmuebles GROUP BY estado")}
        print(f"Base : {storage.count('inmuebles')} bien(s) immobilier(s) — " + ", ".join(f"{n} {e}" for e, n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
