"""Met à jour la base SQLite, puis résume ce qui est nouveau.

    python -m bodacc.update                              # liquidations du jour + actifs
    python -m bodacc.update --period last_7_days
    python -m bodacc.update --start 2026-09-01 --end 2026-09-07
    python -m bodacc.update --skip-bodacc                # seulement les actifs des cabinets
    python -m bodacc.update --db data/autre.db
"""
import argparse
import contextlib
import io
from datetime import timedelta

from bodacc.actif_filter import ActifFilter, normalize
from bodacc.bodacc_collector import BodaccLiquidationScraper
from bodacc.cabinets import match_cabinet
from bodacc.gemweb_rss import CabinetRegistry, GemwebActifScraper
from bodacc.paths import DB_PATH
from bodacc.storage import Storage, utc_now
from bodacc.vehicles import count_vehicles, parse_vehicle

_VEHICLE_PATTERN = ActifFilter.build_pattern(ActifFilter.VEHICULE_KEYWORDS)


# ----------------------------------------------------------------------
# Logique pure : prend des lignes, rend des résultats (facile à tester)
# ----------------------------------------------------------------------

def is_vehicle(actif):
    return bool(_VEHICLE_PATTERN.search(normalize(actif.get("type"))))


def tag_cabinets(rows, registry):
    """Ajoute à chaque liquidation la clé 'cabinet' : nom canonique du registre, ou None."""
    names = registry.names()
    for row in rows:
        row["cabinet"] = registry.canonical(match_cabinet(row.get("liquidateur"), names))
    return rows


def store_liquidations(storage, rows, registry, now):
    """Enregistre les liquidations et retourne un résumé."""
    tag_cabinets(rows, registry)
    new = storage.upsert_liquidations(rows, now=now)
    return {
        "seen": len(rows),
        "new": new,
        "no_cabinet": sum(1 for r in rows if not r["cabinet"]),
    }


def store_actifs(storage, rows, now):
    """Enregistre les actifs et retourne un résumé, dont les nouveaux véhicules."""
    for row in rows:                        # détails (marque, km...) pour les véhicules
        if is_vehicle(row):
            row.update(parse_vehicle(row.get("titre"), row.get("description")))
            row["nb_vehicules"] = count_vehicles(row.get("titre"), row.get("description"))

    known = storage.keys("actifs")          # avant d'écrire : ce qui existait déjà
    new_rows = {r["guid"]: r for r in rows if r["guid"] not in known}

    storage.upsert_actifs(rows, now=now)

    return {
        "seen": len(rows),
        "new": len(new_rows),
        "new_vehicles": [r for r in new_rows.values() if is_vehicle(r)],
    }


# ----------------------------------------------------------------------
# Accès réseau : deux fonctions fines, remplaçables dans les tests
# ----------------------------------------------------------------------

def fetch_liquidations(period="today", start=None, end=None, log=print):
    """Récupère les liquidations jour par jour.

    L'API BODACC refuse les décalages (offset) au-delà de 10 000 résultats :
    une seule requête sur une semaine échouerait. Un jour tient largement.
    """
    probe = BodaccLiquidationScraper(
        period="custom" if start else period, custom_start=start, custom_end=end
    )
    rows = []
    day = probe.start_date
    while day <= probe.end_date:
        scraper = BodaccLiquidationScraper(
            period="custom", custom_start=day.isoformat(), custom_end=day.isoformat()
        )
        with contextlib.redirect_stdout(io.StringIO()):   # le scraper est bavard
            scraper.fetch_all().filter_liquidations().transform()
        log(f"   {day} : {len(scraper.resultats)} liquidation(s)")
        rows.extend(scraper.resultats)
        day += timedelta(days=1)
    return rows


def fetch_actifs(registry):
    """Récupère les actifs de tous les sites. Retourne (lignes, nombre de sites en erreur)."""
    scraper = GemwebActifScraper(registry=registry)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        scraper.fetch_all()
    failures = sum(1 for line in buffer.getvalue().splitlines() if "Erreur" in line)
    return scraper.resultats, failures


# ----------------------------------------------------------------------
# Ligne de commande
# ----------------------------------------------------------------------

def describe(vehicle):
    """Une ligne lisible : 'FORD FIESTA | Ford, 174 676 km, FX-101-AB | 1 200,00 € | 91000 EVRY | url'."""
    km = vehicle.get("kilometrage")
    count = vehicle.get("nb_vehicules") or 1
    details = ", ".join(str(x) for x in [
        f"lot de {count} véhicules" if count > 1 else None,
        vehicle.get("marque"),
        vehicle.get("annee"),
        f"{km:,} km".replace(",", " ") if km else None,
        vehicle.get("immatriculation"),
        vehicle.get("carburant"),
    ] if x)
    titre = (vehicle.get("titre") or "").removeprefix("A vendre : ")
    parts = [titre, details, vehicle.get("estimation"), vehicle.get("url_detail")]
    return " | ".join(p for p in parts if p)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Met à jour la base BODACC et affiche les nouveautés.")
    parser.add_argument("--period", default="today",
                        choices=["today", "last_7_days", "last_month"],
                        help="période BODACC (défaut : today)")
    parser.add_argument("--start", help="début AAAA-MM-JJ (avec --end)")
    parser.add_argument("--end", help="fin AAAA-MM-JJ (avec --start)")
    parser.add_argument("--db", default=DB_PATH, help="fichier SQLite (défaut : data/bodacc.db)")
    parser.add_argument("--skip-bodacc", "--skip-liquidations", dest="skip_bodacc", action="store_true",
                        help="ne pas interroger le BODACC (même option que côté Espagne : --skip-liquidations)")
    parser.add_argument("--skip-actifs", action="store_true", help="ne pas interroger les cabinets")
    args = parser.parse_args(argv)

    if bool(args.start) != bool(args.end):
        parser.error("--start et --end vont ensemble")

    registry = CabinetRegistry()
    now = utc_now()

    with Storage(args.db) as storage:
        first_run = storage.count("liquidations") == 0 and storage.count("actifs") == 0

        if not args.skip_bodacc:
            print("Liquidations (BODACC)")
            rows = fetch_liquidations(args.period, args.start, args.end)
            s = store_liquidations(storage, rows, registry, now)
            print(f"→ {s['seen']} lues, {s['new']} nouvelles, "
                  f"{s['no_cabinet']} sans cabinet connu du registre")

        if not args.skip_actifs:
            print(f"\nActifs ({len(registry.by_domain())} sites)")
            rows, failures = fetch_actifs(registry)
            s = store_actifs(storage, rows, now)
            listings = len(s["new_vehicles"])
            vehicles = sum(v.get("nb_vehicules") or 1 for v in s["new_vehicles"])
            found = f"{listings} véhicule(s)" if vehicles == listings else f"{listings} annonce(s) de véhicules ({vehicles} véhicules)"
            print(f"→ {s['seen']} lus, {s['new']} nouveaux dont {found}"
                  + (f" ({failures} site(s) en erreur)" if failures else ""))
            for v in s["new_vehicles"]:
                print(f"   • {describe(v)}")

        if first_run:
            print("\nPremier passage : tout est « nouveau ». Relancez plus tard pour "
                  "ne voir que les vraies nouveautés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
