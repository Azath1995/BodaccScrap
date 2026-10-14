"""Lots de véhicules d'eactivos.com (plateforme d'enchères judiciaires et concursales, Activos Concursales S.L.).

    python -m es.eactivos                       # lots de véhicules des 180 derniers jours du plan du site
    python -m es.eactivos --since 2026-01-01
    python -m es.eactivos --limit 20 --refresh  # relire aussi les lots déjà clos

Principes :
- On part du **plan du site** (`sitemap.liquidations.xml`), qui est fait pour les robots. On ne touche à aucun
  appel interne de la plateforme et on n'enchérit jamais.
- Le `robots.txt` est lu et **évalué avec ses règles complètes** (jokers `*`, fin de chaîne `$`) avant chaque
  requête ; une adresse interdite n'est jamais demandée. Une requête par seconde.
- On ne garde que des **faits extraits** : titre, lieu, état, valorisation, n° de procédure, tribunal, société
  concursée, plaque, et le lien vers l'annonce d'origine. Ni photos ni textes de description.
- Le nombre de procédure et le tribunal permettent de rattacher un lot à un acte du BORME (voir `es.report vinculos`).

Réserve de droits : l'avis légal d'eactivos réserve tous les droits sur son contenu et ne mentionne pas les robots ;
ce lecteur reste un usage scolaire, minimal, avec renvoi vers la source. Il n'a pas d'accord écrit de l'exploitant.
"""
import argparse
import html as html_lib
import re
import time
from datetime import date, timedelta
from urllib.parse import urlparse

import requests

from es.paths import DB_PATH
from es.storage import Storage

BASE = "https://www.eactivos.com"
SITEMAP_URL = f"{BASE}/sitemap.liquidations.xml"
USER_AGENT = "BodaccScrap (projet scolaire)"

# Mots d'une adresse de lot (« furgoneta-volkswagen-caddy ») qui désignent un véhicule.
VEHICLE_WORDS = {
    "vehiculo", "vehiculos", "furgoneta", "furgonetas", "furgon", "coche", "coches", "turismo", "turismos", "camion", "camiones",
    "camioneta", "remolque", "remolques", "semirremolque", "semirremolques", "tractor", "tractores", "motocicleta",
    "motocicletas", "moto", "motos", "autobus", "autobuses", "autocaravana", "todoterreno", "ciclomotor", "quad", "cisterna",
    "grua", "carretilla",
}


# ----------------------------------------------------------------------------------------------------------------------
# robots.txt : règles complètes (RFC 9309). urllib.robotparser ne gère ni `*` au milieu d'un motif ni `$`.
# ----------------------------------------------------------------------------------------------------------------------

def _pattern(value):
    escaped = re.escape(value).replace(r"\*", ".*")
    if escaped.endswith(r"\$"):
        escaped = escaped[:-2] + "$"
    return re.compile("^" + escaped)


class Robots:
    """Règles d'un robots.txt pour notre robot : le groupe qui le nomme s'il existe, sinon le groupe `*`."""

    def __init__(self, text, agent="bodaccscrap"):
        groups = []                                  # [(noms d'agents, [(allow/disallow, motif, longueur)])]
        after_agent_line = False
        for raw in (text or "").splitlines():
            line = raw.split("#")[0].strip()
            if ":" not in line:
                continue
            field, value = (part.strip() for part in line.split(":", 1))
            field = field.lower()
            if field == "user-agent":
                if not after_agent_line:             # plusieurs lignes User-agent de suite = un seul groupe
                    groups.append(([], []))
                groups[-1][0].append(value.lower())
                after_agent_line = True
            elif field in ("allow", "disallow"):
                after_agent_line = False
                if groups and value:
                    groups[-1][1].append((field, _pattern(value), len(value)))
        named = [rules for agents, rules in groups if agent in agents]
        general = [rules for agents, rules in groups if "*" in agents]
        self.rules = [rule for rules in (named or general) for rule in rules]

    def allowed(self, path):
        """Vrai si le chemin (avec sa requête) est autorisé. La règle la plus longue l'emporte, `allow` en cas d'égalité."""
        matching = [(length, kind == "allow") for kind, pattern, length in self.rules if pattern.match(path)]
        return True if not matching else max(matching)[1]


# ----------------------------------------------------------------------------------------------------------------------
# Lecture
# ----------------------------------------------------------------------------------------------------------------------

def get(url):
    """(code HTTP, texte). (None, '') si la connexion échoue."""
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        return response.status_code, response.text
    except requests.exceptions.RequestException:
        return None, ""


def parse_sitemap(xml_text):
    """[(url, lastmod AAAA-MM-JJ)] du plan des lots."""
    return re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", xml_text)


def is_vehicle_url(url):
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return bool(VEHICLE_WORDS & set(slug.split("-")))


def lot_code(url):
    found = re.search(r"eactivos\.com/([A-Z0-9]{8})/", url)
    return found.group(1) if found else None


def to_int(number_text):
    """'4.600' -> 4600 ; '1.234,50' -> 1234."""
    cleaned = number_text.replace(".", "").split(",")[0]
    return int(cleaned) if cleaned.isdigit() else None


def visible_text(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def parse_lot(page, url, sitemap_date=None):
    """Faits d'une fiche de lot. None si la page n'est pas une fiche lisible."""
    code = lot_code(url)
    title = re.search(r'og:title"\s+content="\s*([^"]*?)\s*"', page)
    if not code or not title:
        return None
    text = visible_text(page)
    titulo = html_lib.unescape(title.group(1)).strip()

    if re.search(r"Vaya, la (?:subasta|venta) se ha cerrado", text):
        estado = "cerrada"
    elif "Próximamente" in text:
        estado = "proxima"
    else:
        estado = "abierta"

    category =re.search(r"Portada Liquidaciones\s+(.*?)\s+" + re.escape(titulo), text) if titulo else None
    location = re.search(r"UBICACI[ÓO]N\s+(.+?)\s+VISITAS", text)
    starts = re.search(r"Empieza el (\d{2})/(\d{2})/(\d{4})", text)
    ends = re.search(r"Finaliza el (\d{2})/(\d{2})/(\d{4})", text)
    value = re.search(r"VALORACI[ÓO]N\s*([\d.]+(?:,\d+)?)\s*€", text)
    opening = re.search(r"PRECIO DE SALIDA\s*([\d.]+(?:,\d+)?)\s*€", text)
    procedure, court = parse_procedure(text)
    debtor = re.search(r"(?:procedente de|propiedad de)(?: la| el)?(?: mercantil| entidad| sociedad| empresa| concursada)?\s+"
                       r"(.+?)(?:,\s*dedicada|,\s*que\b|,\s*cuya|,\s*empresa|\s+dedicada|\s+\(|\.\s)", text)
    plate = re.search(r"matr[ií]cula\s+(\d{4}\s?[A-Za-z]{3}|[A-Za-z]{1,2}[- ]?\d{4}[- ]?[A-Za-z]{1,2})\b", text)
    liquidation = re.search(r"const liquidationId = (\d+)", page)

    def iso(found):
        return f"{found.group(3)}-{found.group(2)}-{found.group(1)}" if found else None

    concursada = debtor.group(1).strip() if debtor else None
    if concursada and re.search(r"\b(?:S\.L(?:\.[LUP])?|S\.A|S\.C|S\.L\.P)$", concursada):
        concursada += "."                  # la lecture s'arrête au point suivi d'un espace : on restaure le point d'« S.L. »

    return {
        "codigo": code, "liquidation_id": liquidation.group(1) if liquidation else None, "titulo": titulo,
        "categoria": category.group(1) if category else None, "ubicacion": location.group(1).strip() if location else None,
        "estado": estado, "inicio": iso(starts), "fin": iso(ends),
        "valoracion": to_int(value.group(1)) if value else None, "precio_salida": to_int(opening.group(1)) if opening else None,
        "procedimiento": procedure, "juzgado": court,
        "concursada": concursada, "matricula": plate.group(1).upper() if plate else None,
        "url": url, "fecha_sitemap": sitemap_date,
    }


PROCEDURE = re.compile(r"(?:Proced(?:imiento)?\.?\s+concursal|Proc\.\s*concursal|Concurso|Autos)\s*:?\s*(?:n[ºo]\.?\s*)?(\d+(?:\.\d+)?/\d{4})\s+")
COURT_ENDS = r"(?=\s+(?:Subasta|Venta|Se subasta|Se vende|Se ofrece|Lote|Vehículo|Veh[íi]culos|Ref\.)\b|$)"


def parse_procedure(text):
    """(numéro de procédure, tribunal) d'un texte de fiche, ou (None, None).

    Formats vus : « Proced. concursal 470/2025 Sección de lo Mercantil del Tribunal de Instancia de Madrid Plaza Nº 16 »,
    « Concurso: 454/2025 Juzgado Mercantil 4 de Valencia », « Autos 1192.5/2025 Juzgado de lo Mercantil Nº4 de Sevilla »,
    « Autos 74/2026 Sección de lo Mercantil du Tribunal de Instancia de Madrid. Plaza Nº 16 Land Rover, con matrícula… ».
    """
    found = PROCEDURE.search(text)
    if not found:
        return None, None
    rest = text[found.end():]
    with_plaza = re.match(r"(.{3,140}?Plaza\s*N[ºo]\.?\s*\d+)", rest)
    court = with_plaza.group(1) if with_plaza else (re.match(r"(.{3,140}?)" + COURT_ENDS, rest) or [None, rest[:80]])[1]
    return found.group(1), court.strip(" .")


def select_urls(entries, since, known_closed=(), limit=None):
    """URL de véhicules du plan du site à lire : récentes, et pas déjà connues comme closes."""
    chosen = [(url, day) for url, day in entries if is_vehicle_url(url) and day >= since and lot_code(url) not in known_closed]
    chosen.sort(key=lambda item: item[1], reverse=True)
    return chosen[:limit] if limit else chosen


def collect(since, storage, fetch=get, pause=1.0, sleep=time.sleep, limit=None, refresh=False, log=print):
    """Lit le plan du site puis les fiches ; retourne {'lus', 'nouveaux', 'interdits', 'illisibles'}."""
    status, robots_text = fetch(f"{BASE}/robots.txt")
    robots = Robots(robots_text if status == 200 else "")
    sleep(pause)
    if not robots.allowed(urlparse(SITEMAP_URL).path):
        raise SystemExit("Le robots.txt d'eactivos interdit son plan du site : arrêt.")
    status, xml_text = fetch(SITEMAP_URL)
    if status != 200:
        raise SystemExit(f"Plan du site illisible (HTTP {status}).")
    entries = parse_sitemap(xml_text)
    closed = set() if refresh else {r["codigo"] for r in storage.rows_lotes("estado = 'cerrada'")}
    todo = select_urls(entries, since, closed, limit)
    log(f"{len(entries)} lots au plan du site ; {len(todo)} véhicule(s) à lire depuis {since}.")
    result = {"lus": 0, "nouveaux": 0, "interdits": 0, "illisibles": 0, "nouveaux_lots": []}
    for url, day in todo:
        if not robots.allowed(urlparse(url).path):
            result["interdits"] += 1
            continue
        sleep(pause)
        status, page = fetch(url)
        lot = parse_lot(page, url, day) if status == 200 else None
        if lot is None:
            result["illisibles"] += 1
            continue
        if storage.upsert_lotes([lot]):
            result["nouveaux"] += 1
            result["nouveaux_lots"].append(lot)
        result["lus"] += 1
    return result


def main(argv=None, fetch=get, sleep=time.sleep, today=None):
    parser = argparse.ArgumentParser(description="Lots de véhicules d'eactivos.com (usage scolaire, robots.txt respecté).")
    parser.add_argument("--since", help="lots dont la date au plan du site est postérieure (AAAA-MM-JJ ; défaut : 180 jours)")
    parser.add_argument("--limit", type=int, help="nombre maximum de fiches lues (les plus récentes d'abord)")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes (défaut : 1)")
    parser.add_argument("--refresh", action="store_true", help="relire aussi les lots déjà connus comme clos")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args(argv)
    if args.pause < 0 or (args.limit is not None and args.limit < 1):
        parser.error("--pause ne peut pas être négatif et --limit doit valoir au moins 1")
    try:
        since = date.fromisoformat(args.since) if args.since else (today or date.today()) - timedelta(days=180)
    except ValueError:
        parser.error(f"date invalide : {args.since!r} (format AAAA-MM-JJ)")

    with Storage(args.db) as storage:
        result = collect(since.isoformat(), storage, fetch, args.pause, sleep, args.limit, args.refresh)
        counts = {row[0]: row[1] for row in storage.conn.execute("SELECT estado, COUNT(*) FROM lotes GROUP BY estado")}
        print(f"\n{result['lus']} lot(s) lu(s), {result['nouveaux']} nouveau(x), {result['illisibles']} illisible(s), "
              f"{result['interdits']} interdit(s) par robots.txt.")
        print(f"Base : {storage.count('lotes')} lot(s) — " + ", ".join(f"{n} {e}" for e, n in sorted(counts.items())))


if __name__ == "__main__":
    main()
