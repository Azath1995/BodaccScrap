"""Cherche le site web des sociétés d'un fichier `prospects --csv`, via OpenStreetMap.

    python -m prospects.find_sites --input data/exports/prospects_64.csv --csv data/exports/sites_64.csv

L'annuaire officiel des entreprises n'a pas de champ « site web ». OpenStreetMap (licence ODbL) en a un
pour les commerces qui l'ont renseigné : on télécharge en UNE requête Overpass les garages, concessions
et loueurs du secteur, puis on rapproche chaque société d'un commerce par la **distance** (adresse
géocodée) et par la **ressemblance du nom** (nom, marque ou exploitant OSM, et adresse du site).

Chaque ligne du résultat porte un statut :
- « trouve (osm) »    : commerce à moins de 2 km dont le nom (ou le site) ressemble à la société ;
- « a verifier (osm) » : commerce à moins de 150 m mais au nom différent (même adresse, enseigne autre) ;
- « non trouve »       : rien de convaincant (l'absence n'est pas une preuve : OSM est incomplet).

Le fichier produit (nom;siren;site;statut;commentaire) se lit directement avec
`python -m prospects.vehicle_types --input ...`.
"""
import argparse
import csv
import re
import time

import requests

from bodacc.report import write_csv_or_explain
from prospects.search import ProspectError, distance_km, geocode
from prospects.vehicle_types import fold

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "BodaccScrap (projet scolaire)"
NAME_RADIUS_KM = 2.0        # nom qui ressemble : on accepte jusqu'à 2 km
SAME_PLACE_KM = 0.15        # même adresse : on propose, à vérifier
MIN_NAME_SCORE = 0.5        # part des mots distinctifs de la société retrouvés
MIN_GEOCODE_SCORE = 0.7     # en dessous, l'adresse est mal localisée : « même adresse » n'a pas de sens
MARGIN_KM = 3.0            # marge autour des sociétés pour la zone téléchargée

COLUMNS = ["nom", "siren", "site", "statut", "commentaire"]
# Formes juridiques et mots trop courants pour distinguer deux commerces.
STOPWORDS = {"sarl", "sas", "sasu", "sa", "eurl", "snc", "scop", "selarl", "societe", "ste", "et", "de", "du",
             "des", "la", "le", "les", "l", "d", "cie", "groupe", "france", "auto", "autos", "automobile",
             "automobiles", "garage", "garages", "location", "locations", "vehicules", "vehicule", "holdings"}


def tokens(text):
    """Mots distinctifs d'un nom : sans accents, sans forme juridique ni mot générique."""
    words = re.findall(r"[a-z0-9]+", fold(text).replace("'", " "))
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def website_of(tags):
    url = (tags.get("website") or tags.get("contact:website") or "").strip()
    if url and not re.match(r"https?://", url, re.I):
        url = "https://" + url
    return url


def name_score(company_name, shop, commune=""):
    """Part des mots distinctifs de la société retrouvés dans le nom OSM, la marque ou l'adresse du site.

    Le nom de la commune n'est pas distinctif (« Montpon Automobiles » à Montpon) : il est écarté.
    """
    town = set(tokens(commune))
    wanted = [w for w in tokens(company_name) if w not in town]
    if not wanted:
        return 0.0
    haystack = " ".join(fold(shop["tags"].get(k, "")) for k in ("name", "brand", "operator", "official_name"))
    words = set(re.findall(r"[a-z0-9]+", haystack))
    host = fold(re.sub(r"^https?://(www\.)?", "", shop["site"]).split("/")[0])
    found = sum(1 for w in wanted if w in words or (len(w) >= 3 and w in host))
    return found / len(wanted)


def overpass_query(south, west, north, east):
    box = f"({south:.5f},{west:.5f},{north:.5f},{east:.5f})"
    shops = '"shop"~"^(car|car_repair|car_parts|caravan|motorcycle|truck|trailer)$"'
    selectors = [f'nwr[{shops}]["{key}"]{box};' for key in ("website", "contact:website")]
    selectors += [f'nwr["amenity"="car_rental"]["{key}"]{box};' for key in ("website", "contact:website")]
    return "[out:json][timeout:90];(" + "".join(selectors) + ");out center tags;"


def get_overpass(query, retries=3):
    for attempt in range(retries):
        try:
            response = requests.post(OVERPASS_URL, data={"data": query}, timeout=120,
                                     headers={"User-Agent": USER_AGENT})
        except requests.exceptions.RequestException as error:
            raise ProspectError(f"Connexion impossible à Overpass : {error}")
        if response.status_code in (429, 504) and attempt < retries - 1:
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code != 200:
            raise ProspectError(f"Overpass a répondu HTTP {response.status_code}.")
        return response.json()


def shops_from(data):
    """Commerces OSM ayant un site et une position : [{'lat', 'lon', 'site', 'tags'}]."""
    shops = []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        centre = element.get("center") or element
        site = website_of(tags)
        if site and "lat" in centre and "lon" in centre:
            shops.append({"lat": centre["lat"], "lon": centre["lon"], "site": site, "tags": tags})
    return shops


def match(company, place, shops):
    """(site, statut, commentaire) du meilleur commerce pour cette société."""
    best = None
    for shop in shops:
        km = distance_km(place["lat"], place["lon"], shop["lat"], shop["lon"])
        score = name_score(company["nom"], shop, company.get("commune", ""))
        if km <= NAME_RADIUS_KM and score >= MIN_NAME_SCORE:
            key = (0, -score, km)
        elif km <= SAME_PLACE_KM and (place.get("score") or 1) >= MIN_GEOCODE_SCORE:
            key = (1, km, 0)
        else:
            continue
        if best is None or key < best[0]:
            best = (key, shop, km, score)
    if best is None:
        return "", "non trouve", "aucun commerce OSM avec site à proximité au nom ressemblant"
    key, shop, km, score = best
    label = shop["tags"].get("name", "?")
    if key[0] == 0:
        return shop["site"], "trouve (osm)", f"« {label} » à {km * 1000:.0f} m, nom ressemblant à {score:.0%}"
    return shop["site"], "a verifier (osm)", f"« {label} » à {km * 1000:.0f} m, mais nom différent"


def read_companies(path):
    """Lignes d'un CSV `prospects --csv` (séparateur , ou ;) ; exige les colonnes nom et adresse."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        first = f.readline()
        f.seek(0)
        reader = csv.DictReader(f, delimiter=";" if first.count(";") > first.count(",") else ",")
        missing = {"nom", "adresse"} - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Le fichier {path} doit venir de « python -m prospects --csv » : "
                             f"colonne(s) manquante(s) : {', '.join(sorted(missing))}.")
        return list(reader)


def find_sites(companies, fetch_shops=get_overpass, geo=geocode, pause=0.1):
    """Une ligne {nom, siren, site, statut, commentaire} par société."""
    located = []
    for company in companies:
        try:
            place = geo(company["adresse"])
        except ProspectError:
            place = None
        located.append(place)
        time.sleep(pause)
    points = [p for p in located if p]
    shops = []
    if points:
        margin = MARGIN_KM / 111.0
        lats, lons = [p["lat"] for p in points], [p["lon"] for p in points]
        query = overpass_query(min(lats) - margin, min(lons) - margin * 1.5, max(lats) + margin, max(lons) + margin * 1.5)
        shops = shops_from(fetch_shops(query))
    rows = []
    for company, place in zip(companies, located):
        if place is None:
            site, statut, comment = "", "non trouve", "adresse non localisée"
        else:
            site, statut, comment = match(company, place, shops)
        rows.append({"nom": company["nom"], "siren": company.get("siren", ""), "site": site,
                     "statut": statut, "commentaire": comment})
    _drop_shared_guesses(rows)
    return rows, len(shops)


def _drop_shared_guesses(rows):
    """Un commerce déjà attribué, ou proposé « à vérifier » à plusieurs sociétés, est une coïncidence d'adresse."""
    sites = [r["site"] for r in rows if r["site"]]
    for row in rows:
        if row["statut"] == "a verifier (osm)" and sites.count(row["site"]) > 1:
            row.update(site="", statut="non trouve", commentaire="plusieurs sociétés à la même adresse, aucune ne se distingue")


def main(argv=None, fetch_shops=get_overpass, geo=geocode):
    parser = argparse.ArgumentParser(description="Cherche le site web des sociétés via OpenStreetMap.")
    parser.add_argument("--input", required=True, help="CSV produit par « python -m prospects --csv »")
    parser.add_argument("--csv", required=True, help="fichier à écrire (nom;siren;site;statut;commentaire)")
    parser.add_argument("--pause", type=float, default=0.1, help="secondes entre deux géocodages (défaut : 0,1)")
    args = parser.parse_args(argv)

    companies = read_companies(args.input)
    if not companies:
        raise SystemExit(f"{args.input} ne contient aucune société.")
    try:
        rows, n_shops = find_sites(companies, fetch_shops=fetch_shops, geo=geo, pause=args.pause)
    except ProspectError as error:
        raise SystemExit(str(error))

    with_site = [r for r in rows if r["site"]]
    write_csv_or_explain(rows, args.csv, COLUMNS)
    print(f"{n_shops} commerce(s) avec site dans OpenStreetMap sur la zone.")
    for statut in ("trouve (osm)", "a verifier (osm)", "non trouve"):
        print(f"  {statut:<18}{sum(1 for r in rows if r['statut'] == statut)}")
    print(f"{len(with_site)} site(s) sur {len(rows)} société(s), écrits dans {args.csv}")
    print("« a verifier » : même adresse mais nom différent ; « non trouve » : OSM est incomplet, "
          "cela ne prouve pas que la société n'a pas de site.")
    print(f"Suite : python -m prospects.vehicle_types --input {args.csv} --csv data/exports/sites_types.csv")


if __name__ == "__main__":
    main()
