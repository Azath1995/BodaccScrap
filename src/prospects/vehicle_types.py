"""Classe des sites web d'entreprises selon les types de véhicules dont ils parlent.

    python -m prospects.vehicle_types --type utilitaires
    python -m prospects.vehicle_types --type citadines,electriques --min-hits 5 --csv data/exports/sites_types.csv
    python -m prospects.vehicle_types --input data/exports/mes_sites.csv

Le fichier d'entrée est un CSV avec une colonne « site » (et, si possible, « nom » et « siren »).

Méthode : on lit la page d'accueil et jusqu'à deux pages « stock / occasions / véhicules / location »
du site, puis on compte des mots-clés par type. C'est une **indication**, pas un inventaire :
- on mesure ce dont le site PARLE, pas ce qu'il a réellement en stock ;
- les sites dont le stock est chargé par JavaScript, ou écrits en anglais, sont mal vus.

Respect des sites : le robots.txt est lu, une seule requête par seconde, trois pages au plus par site.
"""
import argparse
import csv
import html as html_lib
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests

from bodacc.report import format_table, write_csv_or_explain

USER_AGENT = "BodaccScrap (projet scolaire)"
TERM_CAP = 5            # un même terme compte au plus 5 fois : un item de menu répété ne doit pas dominer
MIN_MAIN_HITS = 3       # un type est « principal » s'il a au moins 3 mentions...
MIN_MAIN_SHARE = 0.2    # ...et au moins 20 % de toutes les mentions
MIN_TEXT_CHARS = 500    # en dessous, le site est jugé « peu de contenu » (souvent du JavaScript)

_UTILITY_MODELS = (
    r"(renault\s+(kangoo|trafic|master)|peugeot\s+(partner|expert|boxer)|citroen\s+(berlingo|jumpy|jumper|nemo)"
    r"|ford\s+transit|fiat\s+(ducato|doblo|scudo|fiorino)|mercedes\s+(sprinter|vito)"
    r"|(volkswagen|vw)\s+(crafter|caddy|transporter)|opel\s+(vivaro|movano|combo)|nissan\s+(nv200|nv300|primastar))"
)
_CITY_MODELS = (
    r"(renault\s+(twingo|clio|zoe)|peugeot\s+(108|107|208|206)|citroen\s+(c1|c3)|fiat\s+(500|panda)"
    r"|toyota\s+(aygo|yaris)|dacia\s+sandero|kia\s+picanto|(volkswagen|vw)\s+(polo|up)|opel\s+(corsa|adam)"
    r"|ford\s+(fiesta|ka)|hyundai\s+i(10|20)|smart\s+for(two|four))"
)

# Mots-clés (sans accents, en minuscules). Les modèles ne comptent qu'avec leur marque :
# « trafic », « master » ou « expert » seuls sont des mots courants.
CATEGORIES = {
    "utilitaires": [r"utilitaires?", r"\bfourgons?\b", r"fourgonnettes?", r"camionnettes?", r"\bvul\b",
                    r"\bbennes?\b", r"frigorifiques?", _UTILITY_MODELS],
    "citadines": [r"citadines?", r"city\s?cars?", r"petites?\s+voitures?", _CITY_MODELS],
    "berlines": [r"berlines?", r"\bbreaks?\b", r"monospaces?", r"voitures?\s+familiales?", r"7\s+places"],
    "suv_4x4": [r"\bsuv\b", r"4x4", r"crossovers?", r"tout[- ]terrain"],
    "camping_cars": [r"camping[- ]?cars?", r"caravanes?", r"(vans?|fourgons?)\s+amenages?", r"capucines?"],
    "poids_lourds": [r"poids[- ]lourds?", r"\bcamions?\b", r"tracteurs?\s+routiers?", r"semi[- ]remorques?"],
    "electriques": [r"electriques?", r"hybrides?"],
}
LABELS = {                       # courts, pour tenir dans le tableau
    "utilitaires": "utilitaires", "citadines": "citadines", "berlines": "berlines/breaks",
    "suv_4x4": "SUV/4x4", "camping_cars": "camping-cars", "poids_lourds": "camions",
    "electriques": "électriques/hybrides",
}
_COMPILED = {cat: [re.compile(p) for p in patterns] for cat, patterns in CATEGORIES.items()}
_STOCK = re.compile(r"occasion|stock|vehicule|utilitaire|catalogue|annonce|location|flotte|voiture|camping|\bvan", re.I)
_STATIC = re.compile(r"\.(jpe?g|png|gif|svg|webp|pdf|css|js|ico|zip)(\?|$)", re.I)


# ----------------------------------------------------------------------
# Logique pure
# ----------------------------------------------------------------------

def fold(text):
    """Minuscules sans accents : 'Électrique' -> 'electrique'."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def page_text(html):
    """Texte visible d'une page HTML."""
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def classify(text):
    """{'hits': {type: nombre de mentions}, 'evidence': {type: [3 mots les plus fréquents]}}."""
    folded = fold(text)
    hits, evidence = {}, {}
    for category, patterns in _COMPILED.items():
        seen = Counter()
        for pattern in patterns:
            for match in pattern.finditer(folded):
                seen[re.sub(r"\s+", " ", match.group(0))] += 1
        hits[category] = sum(min(n, TERM_CAP) for n in seen.values())
        evidence[category] = [term for term, _ in seen.most_common(3)]
    return {"hits": hits, "evidence": evidence}


def main_types(hits):
    """Types qui comptent vraiment pour ce site, du plus mentionné au moins mentionné."""
    total = sum(hits.values())
    if total == 0:
        return []
    ranked = sorted(hits, key=lambda c: -hits[c])
    return [c for c in ranked if hits[c] >= MIN_MAIN_HITS and hits[c] / total >= MIN_MAIN_SHARE]


def stock_links(html, base_url, limit=2):
    """Liens internes qui ressemblent à une page de stock, d'occasions ou de véhicules."""
    if limit <= 0:
        return []
    site = urlparse(base_url).netloc
    found, seen = [], {base_url.rstrip("/")}
    for match in re.finditer(r"<a[^>]+href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", html, re.S | re.I):
        url = urljoin(base_url, match.group(1))
        if urlparse(url).netloc != site or url.rstrip("/") in seen or _STATIC.search(url):
            continue
        if _STOCK.search(fold(url)) or _STOCK.search(fold(page_text(match.group(2)))):     # « véhicules » = vehicule
            seen.add(url.rstrip("/"))
            found.append(url)
            if len(found) == limit:
                break
    return found


# ----------------------------------------------------------------------
# Réseau
# ----------------------------------------------------------------------

def get_page(url):
    """(code HTTP, URL finale, HTML) ; (None, url, '') si la connexion échoue."""
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        return response.status_code, response.url, response.text
    except requests.exceptions.RequestException:
        return None, url, ""


def _robots(base, get, pause):
    status, _, body = get(base + "/robots.txt")
    time.sleep(pause)
    parser = robotparser.RobotFileParser()
    parser.parse(body.splitlines() if status == 200 and "<html" not in body[:200].lower() else [])
    return parser


def read_site(url, max_pages=3, pause=1.0, get=get_page):
    """Lit la page d'accueil et quelques pages de stock. Retourne {'status', 'pages', 'text'}.

    status : 'ok', 'peu de contenu', 'inaccessible' ou 'interdit par robots.txt'.
    """
    parts = urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    robots = _robots(base, get, pause)

    def allowed(u):
        return robots.can_fetch("*", u)

    if not allowed(url):
        return {"status": "interdit par robots.txt", "pages": [], "text": ""}
    status, final_url, html = get(url)
    time.sleep(pause)
    if status != 200:
        return {"status": "inaccessible", "pages": [], "text": ""}

    pages, texts = [final_url], [page_text(html)]
    for link in stock_links(html, final_url, limit=max_pages - 1):
        if len(pages) >= max_pages or not allowed(link):
            continue
        link_status, link_url, link_html = get(link)
        time.sleep(pause)
        if link_status == 200:
            pages.append(link_url)
            texts.append(page_text(link_html))
    text = " ".join(texts)
    return {"status": "ok" if len(text) >= MIN_TEXT_CHARS else "peu de contenu", "pages": pages, "text": text}


# ----------------------------------------------------------------------
# Ligne de commande
# ----------------------------------------------------------------------

def read_sites_csv(path):
    """Lignes d'un CSV (séparateur ; ou ,) ayant une colonne « site »."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        first = f.readline()
        f.seek(0)
        reader = csv.DictReader(f, delimiter=";" if first.count(";") > first.count(",") else ",")
        if "site" not in (reader.fieldnames or []):
            raise SystemExit(f"Le fichier {path} doit avoir une colonne « site ».")
        return list(reader)


def main(argv=None, get=get_page):
    parser = argparse.ArgumentParser(description="Classe des sites web selon les types de véhicules dont ils parlent.")
    parser.add_argument("--input", default="data/exports/prospects_vehicules_sites.csv", help="CSV avec une colonne « site »")
    parser.add_argument("--type", help="type(s) recherché(s), séparés par des virgules : " + ", ".join(CATEGORIES))
    parser.add_argument("--min-hits", type=int, default=MIN_MAIN_HITS, help="mentions minimum du type demandé (défaut : 3)")
    parser.add_argument("--main-only", action="store_true",
                        help="ne garder que les sites dont le type demandé est un type PRINCIPAL (au moins 3 mentions "
                             "et 20 %% de toutes les mentions), pas une simple mention")
    parser.add_argument("--max-pages", type=int, default=3, help="pages lues par site, accueil comprise (défaut : 3)")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes (défaut : 1)")
    parser.add_argument("--limit", type=int, default=30, help="lignes affichées (défaut : 30)")
    parser.add_argument("--csv", help="exporter tous les résultats dans ce fichier CSV")
    args = parser.parse_args(argv)

    wanted = [t.strip() for t in args.type.split(",")] if args.type else []
    unknown = [t for t in wanted if t not in CATEGORIES]
    if unknown:
        parser.error(f"type inconnu : {', '.join(unknown)}. Types possibles : {', '.join(CATEGORIES)}")

    entries = read_sites_csv(args.input)
    with_site = [e for e in entries if (e.get("site") or "").strip()]
    if len(with_site) < len(entries):
        print(f"{len(entries) - len(with_site)} société(s) sans site ignorée(s).")

    rows = []
    for entry in with_site:
        site = entry["site"].strip()
        result = read_site(site, max_pages=args.max_pages, pause=args.pause, get=get)
        scored = classify(result["text"]) if result["text"] else {"hits": {c: 0 for c in CATEGORIES}, "evidence": {c: [] for c in CATEGORIES}}
        hits = scored["hits"]
        selected = wanted or list(CATEGORIES)
        score = sum(hits[c] for c in selected)
        top = max(selected, key=lambda c: hits[c])
        rows.append({
            "nom": entry.get("nom") or site, "siren": entry.get("siren", ""), "site": site,
            "statut": result["status"], "pages_lues": len(result["pages"]),
            "types_principaux": ", ".join(LABELS[c] for c in main_types(hits)),
            "score": score, "mots_cles": ", ".join(scored["evidence"][top]),
            **{f"mentions_{c}": hits[c] for c in CATEGORIES},
            "_principaux": main_types(hits),                      # non exporté
        })

    if wanted:
        rows = [r for r in rows if r["score"] >= args.min_hits]
        if args.main_only:
            rows = [r for r in rows if set(wanted) & set(r["_principaux"])]
    rows.sort(key=lambda r: (-r["score"], r["nom"]))

    if args.csv:
        columns = ["nom", "siren", "site", "statut", "pages_lues", "types_principaux", "score", "mots_cles",
                   *[f"mentions_{c}" for c in CATEGORIES]]
        write_csv_or_explain(rows, args.csv, columns)
        print(f"{len(rows)} site(s) exporté(s) dans {args.csv}")
    else:
        print()
        columns = [("nom", "société"), ("types_principaux", "types principaux"), ("score", "mentions"), ("statut", "statut")]
        print(format_table(rows[: args.limit], columns, width=42, link_key="site"))
        title = f"pour « {args.type} » (au moins {args.min_hits} mentions)" if wanted else "classés"
        print(f"\n{len(rows)} site(s) {title}")
    print("Ces comptes mesurent ce dont le site PARLE, pas son stock réel. Les sites en JavaScript ou en anglais "
          "sont mal vus ; « peu de contenu » signale une page presque vide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
