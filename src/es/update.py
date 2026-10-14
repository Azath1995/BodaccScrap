"""Met à jour la base espagnole : procédures collectives du BORME + lots de véhicules d'eactivos.

Mêmes commandes et mêmes options que côté France (`python -m bodacc.update`) :

    python -m es.update                                  # aujourd'hui
    python -m es.update --period last_7_days
    python -m es.update --start 2026-09-01 --end 2026-09-18
    python -m es.update --skip-liquidations              # seulement les annonces (lots de véhicules)
    python -m es.update --skip-actifs                    # seulement les liquidations (BORME)
    python -m es.update --start 2025-01-01 --end 2025-12-31 --pause 0.5 --workers 3   # une année, environ 3 fois plus vite

Deux sources, comme en France (liquidations d'un journal officiel + annonces d'actifs) :
- **Liquidations (BORME)** : une requête par seconde par défaut, environ 33 documents par jour de publication (une année
  prend donc quelques heures ; `--pause` et `--workers` accélèrent). Les jours sans BORME (week-ends, jours fériés) sont
  ignorés. Chaque jour lu en entier est noté : relancer ne relit que les jours manquants (`--refresh` pour tout relire).
- **Actifs (eactivos.com)** : lots de véhicules du plan du site depuis `--actifs-since` (180 jours par défaut), lus
  avec le `robots.txt` évalué en entier ; voir `es/eactivos.py`. Les lots déjà clos ne sont pas relus.
Relancer ne crée jamais de doublon.
"""
import argparse
import time
from datetime import date, timedelta

from es import borme, eactivos
from es.paths import DB_PATH
from es.report import count_vehicles
from es.storage import Storage


def parse_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"date invalide : {text!r} (format AAAA-MM-JJ)")


def collect_liquidations(storage, days, today, fetch, sleep, pause, workers, refresh):
    """Lit le BORME jour par jour ; affiche une ligne par jour et un bilan."""
    total_new = total_rows = skipped = incomplete = 0
    done = set() if refresh else storage.days_done()
    for day in days:
        if day.isoformat() in done:
            skipped += 1
            continue
        if day > today:
            skipped += 1                                       # le BORME de demain n'existe pas encore
            continue
        stats = {}
        try:
            rows = borme.collect_day(day, fetch=fetch, pause=pause, sleep=sleep, stats=stats, workers=workers)
        except RuntimeError as error:
            print(f"   {day} : ERREUR {error} (jour ignoré, à relancer)")
            incomplete += 1
            continue
        new = storage.upsert(rows) if rows else 0
        total_rows += len(rows)
        total_new += new
        failed = stats.get("fallidos", [])
        if failed:
            incomplete += 1
            note = f" — {len(failed)} document(s) illisible(s), jour à relire"
        else:
            if day < today:                                    # le jour en cours peut encore recevoir des publications
                storage.mark_day(day.isoformat(), stats.get("documentos", 0), len(rows))
            note = ""
        print(f"   {day} : {len(rows)} acte(s) de procédure collective, {new} nouveau(x){note}")
    print(f"→ {total_rows} lus, {total_new} nouveaux. Base : {storage.count()} acte(s).")
    if skipped:
        print(f"  {skipped} jour(s) ignoré(s) : déjà collectés en entier (--refresh pour les relire) ou à venir.")
    if incomplete:
        print(f"  {incomplete} jour(s) incomplet(s) : relancez la même commande, seuls les jours manquants seront relus.")


def describe(lot):
    """Une ligne par lot : titre | valorisation | lien."""
    value = f"{lot['valoracion']:,} €".replace(",", " ") if lot.get("valoracion") is not None else None
    count = count_vehicles(lot.get("titulo"))
    parts = [lot.get("titulo"), f"lot de {count} véhicules" if count > 1 else None, lot.get("ubicacion"), value, lot.get("procedimiento") and f"procédure {lot['procedimiento']}", lot.get("url")]
    return " | ".join(p for p in parts if p)


def main(argv=None, fetch=borme.get, sleep=time.sleep, today=None, actifs_fetch=eactivos.get):
    parser = argparse.ArgumentParser(description="Met à jour la base espagnole (BORME + eactivos) et affiche les nouveautés.")
    parser.add_argument("--period", choices=["today", "last_7_days", "last_month"], default="today",
                        help="période du BORME (défaut : today)")
    parser.add_argument("--start", type=parse_date, help="début AAAA-MM-JJ (avec --end)")
    parser.add_argument("--end", type=parse_date, help="fin AAAA-MM-JJ (avec --start)")
    parser.add_argument("--db", default=DB_PATH, help="fichier SQLite (défaut : data/es/borme.db)")
    parser.add_argument("--skip-liquidations", "--skip-borme", dest="skip_liquidations", action="store_true",
                        help="ne pas interroger le BORME")
    parser.add_argument("--skip-actifs", action="store_true", help="ne pas interroger eactivos")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes (défaut : 1)")
    parser.add_argument("--workers", type=int, default=1,
                        help=f"documents du BORME téléchargés en parallèle (1 à {borme.MAX_WORKERS}, défaut : 1) ; 3 divise la durée par environ 3")
    parser.add_argument("--refresh", action="store_true",
                        help="relire aussi les jours du BORME et les lots clos déjà collectés")
    parser.add_argument("--actifs-since", type=parse_date,
                        help="lots eactivos dont la date au plan du site est postérieure (défaut : 180 jours)")
    args = parser.parse_args(argv)
    if bool(args.start) != bool(args.end):
        parser.error("--start et --end vont ensemble")
    if args.pause < 0:
        parser.error("--pause ne peut pas être négatif")
    if not 1 <= args.workers <= borme.MAX_WORKERS:
        parser.error(f"--workers doit valoir entre 1 et {borme.MAX_WORKERS}")

    today = today or date.today()
    start, end = (args.start, args.end) if args.start else borme.period_days(args.period, today)
    if start > end:
        parser.error("--start doit être antérieur ou égal à --end")

    with Storage(args.db) as storage:
        if not args.skip_liquidations:
            days = borme.days_between(start, end)
            print(f"Liquidations (BORME) : {len(days)} jour(s), du {start} au {end}"
                  + (f", {args.workers} requêtes en parallèle" if args.workers > 1 else ""))
            collect_liquidations(storage, days, today, fetch, sleep, args.pause, args.workers, args.refresh)

        if not args.skip_actifs:
            since = args.actifs_since or today - timedelta(days=180)
            print("\nActifs (eactivos)")
            result = eactivos.collect(since.isoformat(), storage, actifs_fetch, args.pause, sleep, refresh=args.refresh, log=lambda m: print(f"  {m}"))
            listings = len(result["nouveaux_lots"])
            vehicles = sum(count_vehicles(lot.get("titulo")) for lot in result["nouveaux_lots"])
            found = f"{listings} véhicule(s)" if vehicles == listings else f"{listings} lot(s) de véhicules ({vehicles} véhicules)"
            print(f"→ {result['lus']} lus, {result['nouveaux']} nouveaux dont {found}"
                  + (f" ({result['illisibles']} illisible(s))" if result["illisibles"] else "")
                  + (f" ({result['interdits']} interdit(s) par robots.txt)" if result["interdits"] else ""))
            for lot in result["nouveaux_lots"]:
                print(f"   • {describe(lot)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
