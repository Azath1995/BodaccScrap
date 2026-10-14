"""Relit la fiche des annonces de véhicules : date limite manquante, et annonces qui ne sont plus en vente.

    python -m bodacc.verify                 # aperçu : dates trouvées enregistrées, rien n'est supprimé
    python -m bodacc.verify --supprimer     # supprime aussi de la base les annonces que le cabinet dit retirées
    python -m bodacc.verify --tous          # relit toutes les fiches, pas seulement celles à vérifier

Fiches relues par défaut : les véhicules sans date limite, et ceux absents du flux RSS lors de la dernière mise à
jour (probablement vendus). robots.txt respecté, une requête par seconde.

Une annonce n'est supprimée que si sa fiche le dit (« Cet actif n'apparait plus sur le site. Il n'est plus en
vente. ») ou n'existe plus (HTTP 404/410) : une fiche injoignable ou une date limite dépassée ne suffit pas. Beaucoup
de cabinets (LGA, Fides...) ne publient aucune date limite : elle reste alors vide, il faut la demander au cabinet.
"""
import argparse
import html as html_lib
import re
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

from bodacc.actif_filter import normalize
from bodacc.paths import DB_PATH
from bodacc.report import vehicle_rows
from bodacc.storage import Storage, utc_now

USER_AGENT = "BodaccScrap (projet scolaire)"


def _text(fragment):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def get_page(url):
    try:
        response = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
        return response.status_code, response.text
    except requests.exceptions.RequestException:
        return None, ""


def allowed(url, get=get_page):
    parts = urlparse(url)
    status, body = get(f"{parts.scheme}://{parts.netloc}/robots.txt")
    parser = robotparser.RobotFileParser()
    parser.parse(body.splitlines() if status == 200 and "<html" not in body[:200].lower() else [])
    return parser.can_fetch(USER_AGENT, url)


WITHDRAWN = re.compile(r"n.est plus en vente|n.appara[iî]t plus sur le site")
MONTH = r"[a-zéû]+\.?"
DATE = rf"(\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{2,4}}|\d{{1,2}}(?:er)? {MONTH} \d{{4}})"
# Le champ Gemweb, puis les formules du texte libre (« offres à déposer avant le 12/11/2026 »).
DEADLINES = [re.compile(rf"date limite de l.offre\s+{DATE}", re.I),
             re.compile(rf"(?:avant le|au plus tard le|jusqu.au|date limite[^0-9]{{0,40}}?)\s*{DATE}", re.I)]


def parse_page(status, page):
    """('retiré' | 'en vente' | 'inaccessible', date limite ou None) d'après la fiche."""
    if status in (404, 410):
        return "retiré", None
    if status != 200:
        return "inaccessible", None
    text = _text(re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page))
    if WITHDRAWN.search(normalize(text)):
        return "retiré", None
    for pattern in DEADLINES:
        found = pattern.search(text)
        if found:
            return "en vente", found.group(1)
    return "en vente", None


def to_check(rows, everything=False):
    """Véhicules dont la fiche est à relire : sans date limite, ou absents du flux lors de la dernière mise à jour."""
    if everything or not rows:
        return list(rows)
    latest = max(r["last_seen"] for r in rows)[:10]
    return [r for r in rows if not r.get("date_limite_offre") or r["last_seen"][:10] < latest]


def check(rows, get=get_page, sleep=time.sleep, pause=1.0, log=print):
    """[(ligne, statut, date limite)] ; robots.txt lu une fois par site."""
    robots, results = {}, []
    for number, row in enumerate(rows, start=1):
        url = row.get("url_detail")
        site = urlparse(url or "").netloc
        if not url:
            results.append((row, "inaccessible", None))
            continue
        if site not in robots:
            robots[site] = allowed(url, get)
            sleep(pause)
        if not robots[site]:
            results.append((row, "interdit par robots.txt", None))
            continue
        status, page = get(url)
        sleep(pause)
        state, deadline = parse_page(status, page)
        results.append((row, state, deadline))
        log(f"  {number}/{len(rows)}  {state:12} {deadline or '':14} {(row.get('titre') or '').removeprefix('A vendre : ')[:50]}")
    return results


def main(argv=None, get=get_page, sleep=time.sleep):
    parser = argparse.ArgumentParser(description="Relit les fiches : dates limites manquantes, annonces retirées.")
    parser.add_argument("--supprimer", action="store_true", help="supprimer de la base les annonces retirées par le cabinet")
    parser.add_argument("--tous", action="store_true", help="relire toutes les fiches de véhicules")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args(argv)

    with Storage(args.db) as storage:
        rows = to_check(vehicle_rows(storage), args.tous)
        print(f"{len(rows)} fiche(s) à relire (une par seconde)")
        results = check(rows, get, sleep)
        now = utc_now()
        for row, state, deadline in results:
            if state == "en vente":
                storage.set_fiche(row["guid"], deadline, now)
        withdrawn = [row for row, state, _ in results if state == "retiré"]
        dates = sum(1 for row, _, deadline in results if deadline and not row.get("date_limite_offre"))
        still_missing = sum(1 for row, state, deadline in results if state == "en vente" and not deadline and not row.get("date_limite_offre"))
        other = [(row, state) for row, state, _ in results if state not in ("en vente", "retiré")]

        print(f"\n{dates} date(s) limite(s) retrouvée(s) sur les fiches ; {still_missing} annonce(s) en vente sans date publiée "
              "(à demander au cabinet)")
        if args.supprimer and withdrawn:
            removed = storage.delete_actifs(r["guid"] for r in withdrawn)
            print(f"{removed} annonce(s) retirée(s) par le cabinet, supprimée(s) de la base :")
        elif withdrawn:
            print(f"{len(withdrawn)} annonce(s) retirée(s) par le cabinet (relancez avec --supprimer pour les enlever) :")
        for row in withdrawn:
            print(f"   - {row['cabinet']} : {(row.get('titre') or '').removeprefix('A vendre : ')}")
        if other:
            print(f"{len(other)} fiche(s) non vérifiée(s), gardée(s) :")
            for row, state in other:
                print(f"   - {state} : {row.get('url_detail')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
