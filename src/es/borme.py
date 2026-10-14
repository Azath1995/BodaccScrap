"""Lecture du BORME par l'API ouverte du BOE, et extraction des procédures collectives (« concursos »).

Source : https://www.boe.es/datosabiertos/api/api.php (API REST, sans clé ni compte).
    /datosabiertos/api/borme/sumario/AAAAMMJJ  -> sommaire du jour (JSON) : un document par province
    /diario_borme/xml.php?id=BORME-A-...       -> le document (XML) : une entrée par société inscrite

Une entrée ressemble à :
    <p class="articulo">419092 - IMPERPAVIMENTOS EXTREMEÑOS S.L.</p>
    <p class="parrafo">... Situación concursal. Procedimiento concursal 221/2026. FIRME: SI, Fecha de resolución
    01/09/2026. Auto de conclusión del concurso. ... Juzgado: ... Juez: ... Administrador Concursal. Fecha
    27/03/2026, NIF/CIF 12345678Z. GARCIA LOPEZ ANTONIO. Datos registrales. ...</p>

Contrairement au BODACC, l'administrateur concursal (le « liquidateur ») est donné avec son NIF.
Une requête par seconde par défaut.
"""
import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import requests

API_URL = "https://www.boe.es/datosabiertos/api/borme/sumario/{day}"
USER_AGENT = "BodaccScrap (projet scolaire)"

# Ce qui rend une entrée intéressante. « liquidación » seul ne suffit pas : il désignerait toute société dissoute.
MICRO = r"micro\w*empresa"            # tolère les fautes du BOE (« microsempresas » existe dans le texte publié)
CONCURSAL = re.compile(rf"Situaci[oó]n concursal|Administrador(?:es)? Concursal|concurso|{MICRO}", re.I)
NEXT_ACT = (r"(?=Situaci[oó]n concursal|Datos registrales|Extinci[oó]n|Disoluci[oó]n|Nombramientos|Ceses/|Revocaciones|"
            r"Otros conceptos|Modificaciones|Cambio |Ampliaci[oó]n|Reducci[oó]n|Reelecciones|Constituci[oó]n|"
            r"Cierre provisional|Fusi[oó]n|Escisi[oó]n|$)")
ADMINISTRADOR = re.compile(
    r"Administrador(?:es)? Concursal(?:es)?\.\s*Fecha ([\d/]+),\s*NIF/CIF ([A-Z0-9]+)\.\s*(.+?)\.?\s*" + NEXT_ACT, re.S)
SEGMENT = re.compile(r"Situaci[oó]n concursal\.\s*")
LIQUIDATION = re.compile(r"liquidaci[oó]n|liquidativ", re.I)


def get(url, accept_json=False):
    """(code HTTP, texte). (None, '') si la connexion échoue."""
    headers = {"User-Agent": USER_AGENT}
    if accept_json:
        headers["Accept"] = "application/json"
    try:
        response = requests.get(url, headers=headers, timeout=60)
        return response.status_code, response.text
    except requests.exceptions.RequestException:
        return None, ""


def iso(day_text):
    """'01/09/2026' -> '2026-09-01' ; texte inchangé s'il n'a pas ce format."""
    try:
        return datetime.strptime(day_text.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return day_text.strip() or None


def fetch_summary(day, fetch=get):
    """Documents du BORME d'un jour (date) : [{'id', 'provincia', 'seccion', 'url_xml', 'url_html'}].

    Les jours sans BORME (week-ends, jours fériés) donnent une liste vide.
    """
    status, body = fetch(API_URL.format(day=day.strftime("%Y%m%d")), accept_json=True)
    if status in (404, 204):
        return []
    if status != 200:
        raise RuntimeError(f"BOE : HTTP {status} pour le sommaire du {day}")
    try:
        summary = json.loads(body)["data"]["sumario"]
    except (ValueError, KeyError, TypeError):
        return []
    diaries = summary.get("diario") or []
    diaries = diaries if isinstance(diaries, list) else [diaries]
    documents = []
    for diary in diaries:
        sections = diary.get("seccion") or []
        for section in sections if isinstance(sections, list) else [sections]:
            items = section.get("item") or []
            for item in items if isinstance(items, list) else [items]:
                documents.append({"id": item["identificador"], "provincia": item.get("titulo", ""),
                                  "seccion": section.get("codigo", ""), "url_xml": item["url_xml"],
                                  "url_html": item.get("url_html", "")})
    return documents


def parse_entries(xml_text):
    """[{'num', 'empresa', 'texto'}] : une entrée par société du document."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return []
    entries, current = [], None
    for paragraph in root.iter("p"):
        css = paragraph.get("class")
        text = html.unescape("".join(paragraph.itertext())).strip()
        if css == "articulo":
            found = re.match(r"(\d+)\s*-\s*(.*)", text, re.S)
            current = {"num": found.group(1) if found else "", "empresa": (found.group(2) if found else text).strip(" ."),
                       "texto": ""}
            entries.append(current)
        elif css == "parrafo" and current is not None:
            current["texto"] = (current["texto"] + " " + text).strip()
    return entries


def administrators(text):
    """[{'fecha', 'nif', 'nombre'}] nommés dans le texte (administrateurs concursaux)."""
    found = []
    for match in ADMINISTRADOR.finditer(text):
        name = html.unescape(re.sub(r"\s+", " ", match.group(3))).strip(" .")
        found.append({"fecha": iso(match.group(1)), "nif": match.group(2), "nombre": name})
    return found


def _segment(text):
    """Un bloc « Situación concursal. ... » -> dict des champs, ou None si ce n'est pas un bloc complet."""
    proc = re.search(r"Procedimiento concursal\s+([\w/.\-]+?)\.\s", text + " ")
    resolution = re.search(r"FIRME:\s*(\w+),\s*Fecha de resoluci[oó]n\s*([\d/]+)\.\s*", text)
    if not proc or not resolution:
        return None
    rest = text[resolution.end():]
    cut = min([i for i in (rest.find("Juzgado:"), rest.find("Resoluciones:")) if i >= 0] or [len(rest)])
    head = rest[:cut].strip()
    parts = [p.strip() for p in re.split(r"\.\s+", head.rstrip(". ")) if p.strip()]
    tipo = parts[0] if parts else ""
    detail = ". ".join(parts[1:])
    modalidad = next((m for m in ("Voluntario", "Necesario") if re.search(rf"\b{m}\b", detail)), "")
    court = re.search(r"Juzgado:\s*(.*?)\s*Juez:", text, re.S)
    judge = re.search(r"Juez:\s*(.*?)\.\s*(?:Resoluciones:|Administrador|$)", text, re.S)
    return {"procedimiento": proc.group(1), "firme": resolution.group(1).upper(),
            "fecha_resolucion": iso(resolution.group(2)), "tipo": tipo, "detalle": detail, "modalidad": modalidad,
            "juzgado": court.group(1).strip(" .") if court else "", "juez": judge.group(1).strip() if judge else ""}


def extract_acts(entry):
    """Actes de procédure collective d'une entrée : une ligne par bloc « Situación concursal ».

    Les entrées sans bloc structuré mais qui parlent d'un concours ou d'une procédure de microentreprise
    (texte libre « Otros conceptos ») donnent une ligne au type approximatif ; un simple administrateur
    nommé donne une ligne « Nombramiento de administrador concursal ».
    """
    text = entry["texto"]
    if not CONCURSAL.search(text):
        return []
    admins = administrators(text)
    admin_text = "; ".join(f"{a['nombre']} ({a['nif']})" for a in admins)
    acts = []
    blocks = SEGMENT.split(text)[1:]
    for block in blocks:
        segment = _segment(block)
        if segment:
            acts.append(segment)
    if not acts:
        free = re.search(r"Otros conceptos:\s*(.*?)(?:Datos registrales|$)", text, re.S)
        if free and re.search(rf"concurs|{MICRO}", free.group(1), re.I):
            body = free.group(1).strip()
            acts.append({"procedimiento": (re.search(rf"(?:concurso|{MICRO}s?)[^\d]{{0,30}}(\d+/\d{{4}})", body, re.I) or [None, ""])[1],
                         "firme": "", "fecha_resolucion": None, "tipo": "Otros conceptos (concurso)", "detalle": body[:300],
                         "modalidad": "", "juzgado": "", "juez": ""})
        elif admins:
            acts.append({"procedimiento": "", "firme": "", "fecha_resolucion": admins[0]["fecha"],
                         "tipo": "Nombramiento de administrador concursal", "detalle": "", "modalidad": "", "juzgado": "", "juez": ""})
    for act in acts:
        act["administradores"] = admin_text
        # « liquidation » = ouverture de la phase de liquidation (ou procédure de liquidation d'une microentreprise).
        # Une clôture « après la phase de liquidation » n'en est pas une : on ne regarde que le type et, pour les
        # microentreprises, le détail.
        opens = bool(LIQUIDATION.search(act["tipo"])) and not re.search(r"conclusi[oó]n|cese", act["tipo"], re.I)
        micro = bool(re.search(MICRO, act["tipo"] + " " + act["detalle"], re.I)) and bool(LIQUIDATION.search(act["detalle"]))
        act["liquidacion"] = 1 if opens or micro else 0
    return acts


def act_id(document_id, entry, act, index):
    """Clé stable d'un acte : relancer la collecte ne crée jamais de doublon."""
    raw = "|".join([document_id, entry["num"], act["procedimiento"], act["fecha_resolucion"] or "", act["tipo"], str(index)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


MAX_WORKERS = 8            # plafond de sécurité : l'API du BOE n'annonce pas de limite, on ne la martèle pas


def _download(document, fetch, pause, sleep):
    """Texte XML d'un document, ou None s'il reste illisible après une seconde chance."""
    sleep(pause)
    status, xml_text = fetch(document["url_xml"])
    if status != 200:
        sleep(pause * 3)                                       # un échec isolé (réseau, serveur occupé) : une seconde chance
        status, xml_text = fetch(document["url_xml"])
    return xml_text if status == 200 else None


def collect_day(day, fetch=get, pause=1.0, sleep=time.sleep, stats=None, workers=1):
    """Actes de procédure collective publiés un jour : liste de dicts prêts à stocker.

    Un document qui échoue est retenté une fois. `stats` (dict facultatif) reçoit {'documentos': nombre de documents du
    jour, 'fallidos': [identifiants des documents restés illisibles]} : un jour n'est « complet » que sans échec.
    `workers` documents sont téléchargés en parallèle (chacun avec sa pause) ; l'analyse et le résultat gardent l'ordre
    du sommaire, donc le résultat est le même qu'avec `workers=1`, seulement plus rapide.
    """
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers doit valoir entre 1 et {MAX_WORKERS}")
    rows = []
    documents = fetch_summary(day, fetch)
    if workers > 1 and len(documents) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            downloaded = list(pool.map(lambda document: _download(document, fetch, pause, sleep), documents))
    else:
        downloaded = [_download(document, fetch, pause, sleep) for document in documents]
    failed = []
    for document, xml_text in zip(documents, downloaded):
        if xml_text is None:
            failed.append(document["id"])
            continue
        for entry in parse_entries(xml_text):
            for index, act in enumerate(extract_acts(entry)):
                rows.append({"id": act_id(document["id"], entry, act, index), "fecha_publicacion": day.isoformat(),
                             "provincia": document["provincia"], "borme_id": document["id"], "empresa_num": entry["num"],
                             "empresa": entry["empresa"], "url_html": document["url_html"], **act})
    if stats is not None:
        stats.update({"documentos": len(documents), "fallidos": failed})
    return rows


def days_between(start, end):
    """Toutes les dates de start à end incluses."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def period_days(period, today=None):
    today = today or date.today()
    return {"today": (today, today), "last_7_days": (today - timedelta(days=6), today),
            "last_month": (today - timedelta(days=29), today)}[period]
