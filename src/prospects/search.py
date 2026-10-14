"""Entreprises à proximité d'un lieu : des acheteurs potentiels pour un véhicule.

    python -m prospects --vehicule AB-456-EF --min-effectif 3 --max-effectif 19
    python -m prospects --near "33220 Pineuilh" --radius 25 --naf 43.22A,43.21A
    python -m prospects --vehicule AB-456-EF --csv data/exports/prospects.csv

Source : l'annuaire officiel des entreprises (API « Recherche d'entreprises », base Sirene,
Licence Ouverte) et le géocodeur de l'État. Aucune coordonnée de contact n'est fournie.

Choix de protection des données :
- les dirigeants ne sont jamais demandés à l'API (minimal=true) ni lus ;
- les entrepreneurs individuels (personnes physiques) sont exclus ;
- les entreprises à diffusion partielle sont exclues.
"""
import argparse
import math
import re
import time

import requests

from bodacc.paths import DB_PATH
from bodacc.report import format_table, write_csv_or_explain
from bodacc.storage import Storage

GEOCODER_URL = "https://api-adresse.data.gouv.fr/search/"
NEAR_URL = "https://recherche-entreprises.api.gouv.fr/near_point"
ANNUAIRE_URL = "https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"
USER_AGENT = "BodaccScrap (projet scolaire)"

# Tranches d'effectif salarié : code -> (libellé, effectif minimum, effectif maximum).
# Libellés officiels de l'INSEE ; "NN" = unité sans salarié.
TRANCHES = {
    "NN": ("sans salarié", 0, 0),
    "00": ("0 salarié", 0, 0),
    "01": ("1 ou 2 salariés", 1, 2),
    "02": ("3 à 5 salariés", 3, 5),
    "03": ("6 à 9 salariés", 6, 9),
    "11": ("10 à 19 salariés", 10, 19),
    "12": ("20 à 49 salariés", 20, 49),
    "21": ("50 à 99 salariés", 50, 99),
    "22": ("100 à 199 salariés", 100, 199),
    "31": ("200 à 249 salariés", 200, 249),
    "32": ("250 à 499 salariés", 250, 499),
    "41": ("500 à 999 salariés", 500, 999),
    "42": ("1 000 à 1 999 salariés", 1000, 1999),
    "51": ("2 000 à 4 999 salariés", 2000, 4999),
    "52": ("5 000 à 9 999 salariés", 5000, 9999),
    "53": ("10 000 salariés et plus", 10000, math.inf),
}
SOLE_TRADER = "1000"          # catégorie juridique « entrepreneur individuel »
MAX_RADIUS_KM = 50            # limite de l'API

TABLE_COLUMNS = [
    ("distance_km", "km"), ("nom", "entreprise"), ("effectif", "effectif"),
    ("naf", "NAF"), ("date_creation", "créée le"), ("commune", "commune"),
]
CSV_COLUMNS = [
    "siren", "nom", "naf", "tranche", "effectif", "annee_effectif", "date_creation",
    "nombre_etablissements_ouverts", "adresse", "code_postal", "commune", "distance_km", "lien",
]


class ProspectError(Exception):
    """Erreur attendue (lieu introuvable, API indisponible...) : message destiné à l'utilisateur."""


# ----------------------------------------------------------------------
# Réseau
# ----------------------------------------------------------------------

def get_json(url, params, retries=3):
    """GET JSON, avec quelques nouvelles tentatives si l'API demande de ralentir (HTTP 429)."""
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=30, headers={"User-Agent": USER_AGENT})
        except requests.exceptions.RequestException as error:
            raise ProspectError(f"Connexion impossible à {url.split('/')[2]} : {error}")
        if response.status_code == 429 and attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code != 200:
            raise ProspectError(f"{url.split('/')[2]} a répondu HTTP {response.status_code}.")
        return response.json()


def geocode(text, fetch=get_json):
    """Coordonnées d'un lieu ('33220 Pineuilh', '10 rue de Rivoli Paris'...) via le géocodeur officiel."""
    data = fetch(GEOCODER_URL, {"q": text, "limit": 1})
    features = data.get("features") or []
    if not features:
        raise ProspectError(f"Lieu introuvable : {text!r}")
    feature = features[0]
    longitude, latitude = feature["geometry"]["coordinates"]        # GeoJSON : longitude d'abord
    return {"lat": latitude, "lon": longitude,
            "label": feature["properties"].get("label", text),
            "score": feature["properties"].get("score")}


# ----------------------------------------------------------------------
# Logique pure
# ----------------------------------------------------------------------

def tranche_codes(min_employees=None, max_employees=None):
    """Codes des tranches qui chevauchent [min, max]. Sans borne : toutes."""
    low = 0 if min_employees is None else min_employees
    high = math.inf if max_employees is None else max_employees
    return {code for code, (_, a, b) in TRANCHES.items() if a <= high and b >= low}


def distance_km(lat1, lon1, lat2, lon2):
    """Distance à vol d'oiseau (formule de haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(a))


def _nearest_establishment(unit, lat, lon):
    """L'établissement ouvert, publiquement diffusé et géolocalisé le plus proche du point."""
    best = None
    for etab in unit.get("matching_etablissements") or []:
        if etab.get("etat_administratif") != "A" or etab.get("latitude") is None or etab.get("longitude") is None:
            continue
        if etab.get("statut_diffusion_etablissement", "O") != "O":
            continue
        d = distance_km(lat, lon, float(etab["latitude"]), float(etab["longitude"]))
        if best is None or d < best[0]:
            best = (d, etab)
    return best


def _to_row(unit, lat, lon, codes, filtering):
    if unit.get("etat_administratif") != "A" or unit.get("statut_diffusion") != "O":
        return None
    if unit.get("nature_juridique") == SOLE_TRADER:
        return None                                   # personne physique : exclue
    tranche = unit.get("tranche_effectif_salarie")
    if filtering and tranche not in codes:            # tranche inconnue = on ne peut pas dire qu'elle convient
        return None
    nearest = _nearest_establishment(unit, lat, lon)
    if nearest is None:
        return None
    distance, etab = nearest
    return {
        "siren": unit.get("siren"),
        "nom": unit.get("nom_complet"),
        "naf": unit.get("activite_principale"),
        "tranche": tranche,
        "effectif": TRANCHES[tranche][0] if tranche in TRANCHES else "inconnu",
        "annee_effectif": unit.get("annee_tranche_effectif_salarie"),
        "date_creation": unit.get("date_creation"),
        "nombre_etablissements_ouverts": unit.get("nombre_etablissements_ouverts"),
        "adresse": etab.get("adresse"),
        "code_postal": etab.get("code_postal"),
        "commune": etab.get("libelle_commune"),
        "distance_km": round(distance, 1),
        "lien": ANNUAIRE_URL.format(siren=unit.get("siren")),
    }


def find_companies(lat, lon, radius_km=15, section="F", naf=None,
                   min_employees=None, max_employees=None, max_pages=60, pause=0.25, fetch=get_json):
    """Entreprises actives autour d'un point, de la plus proche à la plus éloignée.

    Retourne {'rows', 'total' (résultats de l'API), 'pages_read', 'truncated'}.
    L'API limite chaque page à 25 résultats ; max_pages borne le nombre de requêtes.
    """
    codes = tranche_codes(min_employees, max_employees)
    filtering = min_employees is not None or max_employees is not None
    params = {"lat": lat, "long": lon, "radius": radius_km, "per_page": 25,
              "minimal": "true", "include": "matching_etablissements"}     # jamais les dirigeants
    if naf:
        params["activite_principale"] = ",".join(naf)
    else:
        params["section_activite_principale"] = section

    rows, total, total_pages, pages_read = [], 0, 0, 0
    for page in range(1, max_pages + 1):
        data = fetch(NEAR_URL, {**params, "page": page})
        pages_read = page
        total, total_pages = data.get("total_results", 0), data.get("total_pages", 0)
        for unit in data.get("results", []):
            row = _to_row(unit, lat, lon, codes, filtering)
            if row:
                rows.append(row)
        if page >= total_pages:
            break
        time.sleep(pause)

    rows.sort(key=lambda r: r["distance_km"])
    return {"rows": rows, "total": total, "pages_read": pages_read, "truncated": total_pages > max_pages}


def vehicle_place(plate, db_path=DB_PATH):
    """Lieu (ex. '33220 PINEUILH') du véhicule portant cette plaque, lu dans la base."""
    wanted = re.sub(r"[\s-]", "", plate).upper()
    with Storage(db_path) as db:
        rows = [r for r in db.new_since("actifs", "0")
                if re.sub(r"[\s-]", "", r.get("immatriculation") or "").upper() == wanted]
    if not rows:
        raise ProspectError(f"Aucun véhicule de plaque {plate!r} dans la base.")
    places = {r["lieu"] for r in rows if r["lieu"]}
    if len(places) != 1:
        raise ProspectError(f"Lieu du véhicule {plate!r} introuvable ou ambigu : {sorted(places)}. Utilisez --near.")
    return places.pop()


# ----------------------------------------------------------------------
# Ligne de commande
# ----------------------------------------------------------------------

def main(argv=None, fetch=None):
    fetch = fetch or get_json
    parser = argparse.ArgumentParser(description="Entreprises autour d'un lieu ou d'un véhicule.")
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--near", help="lieu : ville, code postal ou adresse (ex : '33220 Pineuilh')")
    where.add_argument("--vehicule", help="plaque d'un véhicule de la base : on prend son lieu (ex : AB-456-EF)")
    parser.add_argument("--radius", type=float, default=15, help=f"rayon en km, {MAX_RADIUS_KM} au plus (défaut : 15)")
    parser.add_argument("--secteur", default="F", help="section d'activité NAF (défaut : F = construction)")
    parser.add_argument("--naf", help="codes NAF précis séparés par des virgules (ex : 43.22A,43.21A) ; remplace --secteur")
    parser.add_argument("--min-effectif", type=int, help="nombre minimum de salariés de l'entreprise")
    parser.add_argument("--max-effectif", type=int, help="nombre maximum de salariés de l'entreprise")
    parser.add_argument("--limit", type=int, default=30, help="lignes affichées (défaut : 30)")
    parser.add_argument("--csv", help="exporter tous les résultats dans ce fichier CSV")
    parser.add_argument("--max-pages", type=int, default=60, help="pages de 25 résultats lues au maximum (défaut : 60)")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args(argv)

    if not 0 < args.radius <= MAX_RADIUS_KM:
        parser.error(f"--radius doit être compris entre 0 et {MAX_RADIUS_KM} km")

    try:
        place = args.near or vehicle_place(args.vehicule, args.db)
        geo = geocode(place, fetch)
        print(f"Lieu : {geo['label']}  (demandé : {place})")
        result = find_companies(
            geo["lat"], geo["lon"], radius_km=args.radius, section=args.secteur,
            naf=[c.strip() for c in args.naf.split(",")] if args.naf else None,
            min_employees=args.min_effectif, max_employees=args.max_effectif,
            max_pages=args.max_pages, fetch=fetch)
    except ProspectError as error:
        raise SystemExit(str(error))

    rows = result["rows"]
    if args.csv:
        write_csv_or_explain(rows, args.csv, CSV_COLUMNS)
        print(f"{len(rows)} entreprise(s) exportée(s) dans {args.csv}")
    else:
        print()
        print(format_table(rows[: args.limit], TABLE_COLUMNS, link_key="lien"))
        print(f"\n{len(rows)} entreprise(s) dans un rayon de {args.radius:g} km"
              + (f", {args.limit} affichée(s)" if len(rows) > args.limit else ""))

    if result["truncated"]:
        print(f"Attention : recherche limitée aux {result['pages_read'] * 25} premières entreprises sur "
              f"{result['total']} : réduisez le rayon ou précisez --naf.")
    print("Effectif = tranche de l'entreprise entière (pas de l'établissement), à la date de référence "
          "de l'INSEE ; « inconnu » si non renseigné.")
    print("Ces données ne contiennent aucune coordonnée de contact. Avant tout démarchage, "
          "vérifiez les règles de la CNIL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
