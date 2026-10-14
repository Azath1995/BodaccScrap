"""Cherche le site Gemweb des cabinets absents du registre, et propose de les y ajouter.

    python -m bodacc.find_cabinets                      # les 40 cabinets les plus fréquents : rapport seulement
    python -m bodacc.find_cabinets --top 100 --csv data/exports/cabinets_trouves.csv
    python -m bodacc.find_cabinets --apply              # écrit dans config/cabinets.json ce qui est sûr

Méthode, une requête par seconde et robots.txt respecté à chaque étape :
1. les cabinets absents du registre sont lus dans la base (comme `bodacc.report unmatched`) ;
2. le nom est cherché dans le répertoire officiel des administrateurs et mandataires judiciaires (CNAJMJ),
   dont chaque fiche donne l'adresse du site du cabinet ;
3. sur ce site, `/rss/actif` doit renvoyer un flux valide : c'est ce qui prouve un site Gemweb.

Le rapprochement nom -> fiche est prudent : tous les mots du nom doivent se retrouver dans la fiche. Plusieurs
fiches possibles = « ambigu », jamais tranché. Un site déjà au registre est signalé (même cabinet, autre
orthographe). Sans `--apply`, rien n'est écrit. Avec `--apply`, seuls les sites au flux valide entrent au
registre ; les sites trouvés mais sans flux sont notés dans `pending`, avec la raison.
"""
import argparse
import csv
import json
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

from bodacc.cabinets import match_cabinet, normalize_cabinet
from bodacc.gemweb_rss import CabinetRegistry
from bodacc.paths import DB_PATH
from bodacc.report import unmatched_liquidations
from bodacc.storage import Storage

USER_AGENT = "BodaccScrap (projet scolaire)"
CNAJMJ = "https://www.cnajmj.fr"
SITEMAP = f"{CNAJMJ}/etude-sitemap.xml"
# En plus des formes juridiques déjà ignorées par normalize_cabinet : mots trop génériques pour distinguer.
GENERIC = {"associes", "associees", "etude", "mandataire", "mandataires", "judiciaire", "judiciaires", "za"}
NOISE_HOSTS = re.compile(r"cnajmj|actify|twitter|linkedin|facebook|instagram|youtube|google|goo\.gl|gmpg|jsdelivr|"
                         r"wp\.org|w3\.org|banquedesterritoires|eliott-markus|maps\.")
LEGAL_PREFIX = re.compile(r"^(?:(?:selarlu?|selafa|selasu?|scp|sasu?|sarl|eurl|me|maître|maitre)\s+)+", re.IGNORECASE)
REPORT_COLUMNS = ["cabinet", "liquidations", "statut", "site", "annonces", "fiche", "detail"]
GEMWEB = "gemweb valide"


def tokens(text):
    return [w for w in normalize_cabinet(text).split() if w not in GENERIC]


def get_page(url):
    try:
        response = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT})
        return response.status_code, response.text
    except requests.exceptions.RequestException:
        return None, ""


def robots_allows(base, path, get=get_page):
    status, body = get(f"{base}/robots.txt")
    parser = robotparser.RobotFileParser()
    parser.parse(body.splitlines() if status == 200 and "<html" not in body[:200].lower() else [])
    return parser.can_fetch(USER_AGENT, f"{base}{path}")


class Polite:
    """Enveloppe get() : une requête par seconde."""

    def __init__(self, get, pause):
        self.get, self.pause, self.last = get, pause, 0.0

    def __call__(self, url):
        wait = self.pause - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        result = self.get(url)
        self.last = time.monotonic()
        return result


def fiche_index(get):
    """{url de fiche: mots de son nom} depuis le plan du site CNAJMJ."""
    if not robots_allows(CNAJMJ, "/etude/", get):
        raise SystemExit("Le robots.txt du répertoire CNAJMJ interdit /etude/ : arrêt.")
    status, body = get(SITEMAP)
    if status != 200:
        raise SystemExit(f"Plan du site CNAJMJ illisible (HTTP {status}).")
    urls = re.findall(rf"<loc>({re.escape(CNAJMJ)}/etude/[^<]+)</loc>", body)
    return {u: tokens(u.rstrip("/").rsplit("/", 1)[1].replace("-", " ")) for u in urls}


def find_fiches(name, index):
    """Fiches dont le nom contient tous les mots de `name`. Une fiche au nom identique l'emporte."""
    wanted = tokens(name)
    if not wanted:
        return []
    found = [u for u, words in index.items() if set(wanted) <= set(words)]
    exact = [u for u in found if sorted(index[u]) == sorted(wanted)]
    return exact if len(exact) == 1 else found


def host(url):
    """Nom de domaine sans « www. » ni majuscules : sert à reconnaître un site déjà connu."""
    return urlparse(url).netloc.lower().removeprefix("www.")


def fiche_site(page):
    """Adresse du site du cabinet, lue dans le bloc prévu par la fiche : `<div class="right …"><h4><a href="…">`.

    Le reste de la page (pied de page, e-justice, cartes, réseaux sociaux) n'est jamais pris pour le site.
    Retourne None si la fiche n'en indique pas.
    """
    found = re.search(r'<div class="right[^"]*">\s*<h4>\s*<a href="(https?://[^"]+)"', page)
    if not found:
        return None
    host_name = urlparse(found.group(1)).netloc.lower()
    return None if NOISE_HOSTS.search(host_name) else f"https://{host_name}"


def probe(site, get):
    """('gemweb valide', nb d'annonces, détail) ou (statut d'échec, 0, détail)."""
    if not robots_allows(site, "/rss/actif", get):
        return "robots interdit", 0, "le robots.txt du site interdit /rss/actif"
    status, body = get(f"{site}/rss/actif")
    if status is None:
        return "site inaccessible", 0, "connexion impossible"
    if status != 200 or "<rss" not in body[:2000]:
        return "pas de flux", 0, f"/rss/actif : HTTP {status}, pas un flux RSS"
    return GEMWEB, len(re.findall(r"<item[ >]", body)), ""


def candidates(storage, registry, skip_keys, top, minimum):
    """[(nom lisible, clé, nombre de liquidations)] des cabinets hors registre, les plus fréquents d'abord."""
    counts, label = Counter(), {}
    for row in unmatched_liquidations(storage, registry):
        counts[row["_cle"]] += 1
        label.setdefault(row["_cle"], row["cabinet_nom"])
    ranked = [(label[k], k, n) for k, n in counts.most_common()
              if k and n >= minimum and not is_noted(k, skip_keys)]
    return ranked[:top]


def noted_keys(pending):
    """Clés (normalisées) des cabinets déjà examinés, donc à ne pas refaire."""
    return {normalize_cabinet(name) for name in pending}


def is_noted(key, noted):
    """Vrai si `key` est un cabinet déjà noté, y compris sous un nom BODACC plus long
    (« legras de grandcourt patrick » pour l'entrée « Legras de Grandcourt »). Pas dans l'autre sens : un nom
    court comme « mj » ne doit pas être écarté parce qu'« mj alpes » est noté."""
    return any(key == n or key.startswith(n + " ") for n in noted)


def investigate(name, index, registry, get):
    """{'statut', 'site', 'annonces', 'fiche', 'detail'} pour un cabinet."""
    fiches = find_fiches(name, index)
    if not fiches:
        return {"statut": "pas de fiche", "site": "", "annonces": 0, "fiche": "", "detail": "absent du répertoire CNAJMJ"}
    if len(fiches) > 1:
        return {"statut": "ambigu", "site": "", "annonces": 0, "fiche": "",
                "detail": "plusieurs fiches : " + ", ".join(u.rstrip('/').rsplit('/', 1)[1] for u in fiches[:4])}
    fiche = fiches[0]
    status, page = get(fiche)
    site = fiche_site(page) if status == 200 else None
    if not site:
        return {"statut": "fiche sans site", "site": "", "annonces": 0, "fiche": fiche, "detail": "la fiche n'indique pas de site"}
    for domain, names in registry.by_domain().items():
        if host(domain) == host(site):
            return {"statut": "deja au registre", "site": site, "annonces": 0, "fiche": fiche,
                    "detail": f"ce site est déjà celui de « {names[0]} » : ajouter ce nom en alias"}
    statut, annonces, detail = probe(site, get)
    return {"statut": statut, "site": site, "annonces": annonces, "fiche": fiche, "detail": detail}


def short_name(label):
    return LEGAL_PREFIX.sub("", label).strip() or label


def apply_findings(path, findings, today):
    """Ajoute les sites valides à `cabinets`, note les autres dans `pending`, retire les traités de `a_verifier`.

    Retourne ([(cabinet, texte de l'ajout)], [noms notés dans pending]). Rien n'est écrit si le fichier obtenu
    ne se recharge pas comme un registre valide (deux noms sur deux domaines, par exemple).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    by_host = {host(c["domain"]): c for c in data["cabinets"]}
    added, noted, handled = [], [], set()
    for f in findings:
        name = short_name(f["cabinet"])
        if f["statut"] == GEMWEB and host(f["site"]) not in by_host:
            entry = {"name": name, "domain": f["site"]}
            data["cabinets"].append(entry)
            by_host[host(f["site"])] = entry
            added.append((f["cabinet"], name))
        elif f["statut"] == "deja au registre" and host(f["site"]) in by_host:
            entry = by_host[host(f["site"])]
            entry.setdefault("aliases", []).append(name)
            added.append((f["cabinet"], f"{name} (alias de {entry['name']})"))
        elif f["statut"] in ("pas de flux", "robots interdit"):
            data["pending"][name] = f"CNAJMJ links {f['site']} ({today}), but {f['detail']}"
            noted.append(name)
        else:
            continue
        handled.add(normalize_cabinet(name))
    if "a_verifier" in data:
        data["a_verifier"] = {k: v for k, v in data["a_verifier"].items() if normalize_cabinet(k) not in handled}
    # Le fichier est d'abord écrit à côté, rechargé par le vrai lecteur du registre (qui refuse un même nom sur deux
    # domaines), puis seulement alors il remplace l'original.
    temporary = Path(path).with_name(Path(path).name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        CabinetRegistry.from_json(temporary)
    except Exception:
        temporary.unlink()
        raise
    temporary.replace(path)
    return added, noted


def write_report(rows, path):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        raise SystemExit(f"Impossible d'écrire {path} : le fichier est probablement ouvert dans Excel.")


def main(argv=None, get=get_page, today=None):
    parser = argparse.ArgumentParser(description="Cherche le site Gemweb des cabinets absents du registre.")
    parser.add_argument("--top", type=int, default=40, help="nombre de cabinets examinés, les plus fréquents d'abord (défaut : 40)")
    parser.add_argument("--min", type=int, default=1, help="liquidations minimum par cabinet (défaut : 1)")
    parser.add_argument("--csv", help="écrire le rapport dans ce fichier CSV")
    parser.add_argument("--apply", action="store_true", help="écrire dans config/cabinets.json (sinon : rapport seulement)")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes (défaut : 1)")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--config", default=CabinetRegistry.DEFAULT_CONFIG, help="registre à lire et à modifier")
    args = parser.parse_args(argv)
    today = today or date.today().isoformat()

    registry = CabinetRegistry.from_json(args.config)
    pending = json.loads(Path(args.config).read_text(encoding="utf-8")).get("pending", {})
    with Storage(args.db) as storage:
        todo = candidates(storage, registry, noted_keys(pending), args.top, args.min)
    if not todo:
        raise SystemExit("Aucun cabinet à examiner : tous sont au registre ou déjà notés dans pending.")

    polite = Polite(get, args.pause)
    print(f"{len(todo)} cabinet(s) à examiner. Lecture du répertoire CNAJMJ...")
    index = fiche_index(polite)
    findings = []
    for label, key, n in todo:
        result = investigate(label, index, registry, polite)
        findings.append({"cabinet": label, "liquidations": n, **result})
        print(f"  {n:>4}  {label[:36]:<36} {result['statut']:<18} {result['site']} {result['annonces'] or ''}".rstrip())

    counts = Counter(f["statut"] for f in findings)
    print("\nBilan : " + ", ".join(f"{n} {s}" for s, n in counts.most_common()))
    if args.csv:
        write_report(findings, args.csv)
        print(f"Rapport : {args.csv}")
    if not args.apply:
        usable = counts[GEMWEB]
        print(f"\nRapport seulement : rien n'a été modifié. {usable} site(s) prêt(s) à entrer au registre : "
              f"relancez avec --apply pour les ajouter.")
        return
    added, noted = apply_findings(args.config, findings, today)
    print(f"\nRegistre mis à jour ({args.config}) : {len(added)} ajout(s), {len(noted)} note(s) dans pending.")
    for _, text in added:
        print(f"  + {text}")
    names = CabinetRegistry.from_json(args.config).names()
    unresolved = [label for label, _ in added if not match_cabinet(label, names)]
    if unresolved:
        print("Attention : ces cabinets ne se rapprochent toujours pas du texte du BODACC, vérifiez-les :",
              ", ".join(unresolved))
    print("Relisez le diff (`git diff config/cabinets.json`), puis lancez `python -m bodacc.update --skip-bodacc`.")


if __name__ == "__main__":
    main()
