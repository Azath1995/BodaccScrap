import requests
import re
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path


class CabinetRegistry:
    """
    Registre extensible des cabinets utilisant le CMS Gemweb.

    Clé   : nom du cabinet, ou l'une de ses orthographes (alias), telle qu'elle
            apparaît dans la colonne "liquidateur"
    Valeur: domaine racine du site Gemweb du cabinet

    Plusieurs noms peuvent pointer vers le même domaine : by_domain() les
    regroupe pour qu'un site ne soit interrogé qu'une seule fois.

    Par défaut, la liste est lue dans config/cabinets.json. Pour ajouter un
    cabinet, éditez ce fichier, ou : registry.add("Nom", "https://www.domaine.fr")
    """

    DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "cabinets.json"

    def __init__(self, cabinets=None):
        """cabinets: dict {nom: domaine_racine}. Par défaut, lit DEFAULT_CONFIG."""
        if cabinets is None:
            cabinets = self._read_config(self.DEFAULT_CONFIG)
        self._cabinets = {nom: domaine.strip().rstrip("/") for nom, domaine in cabinets.items()}

    @staticmethod
    def _read_config(path):
        """Lit le JSON et développe les alias : chaque orthographe -> même domaine."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        cabinets = {}
        for entry in data["cabinets"]:
            for nom in [entry["name"], *entry.get("aliases", [])]:
                if cabinets.get(nom, entry["domain"]) != entry["domain"]:
                    raise ValueError(f"Nom en double avec deux domaines différents : {nom!r}")
                cabinets[nom] = entry["domain"]
        return cabinets

    @classmethod
    def from_json(cls, path):
        """Construit un registre depuis un fichier JSON au même format que cabinets.json."""
        return cls(cls._read_config(path))

    def add(self, nom, domaine):
        """Ajoute (ou met à jour) un cabinet dans le registre."""
        self._cabinets[nom] = domaine.rstrip("/")
        return self

    def remove(self, nom):
        """Retire un cabinet du registre s'il existe."""
        self._cabinets.pop(nom, None)
        return self

    def get(self, nom):
        """Renvoie le domaine d'un cabinet, ou None s'il n'existe pas."""
        return self._cabinets.get(nom)

    def items(self):
        """Itère sur (nom, domaine), comme un dict.items()."""
        return self._cabinets.items()

    def canonical(self, nom):
        """Nom canonique du cabinet pour un nom ou un alias, ou None s'il est inconnu."""
        domaine = self.get(nom)
        return self.by_domain()[domaine.lower()][0] if domaine else None

    def names(self):
        """Tous les noms connus, alias compris (pour cabinets.match_cabinet)."""
        return list(self._cabinets)

    def by_domain(self):
        """Regroupe les noms par domaine : {domaine: [nom canonique, alias...]}.

        Le premier nom de chaque liste est le nom canonique. Un site n'apparaît
        qu'une fois, même si plusieurs noms (ou plusieurs cabinets) y pointent.
        """
        groups = {}
        for nom, domaine in self._cabinets.items():
            groups.setdefault(domaine.lower(), []).append(nom)
        return groups

    def __len__(self):
        """Nombre de noms connus (alias compris)."""
        return len(self._cabinets)

    def __contains__(self, nom):
        return nom in self._cabinets

    def __repr__(self):
        return f"CabinetRegistry({len(self.by_domain())} site(s), {len(self)} nom(s))"


class GemwebActifScraper:
    """
    Récupère et normalise les actifs à vendre publiés sur le flux RSS
    d'un site utilisant le CMS Gemweb (Apache Tapestry) — utilisé par
    de nombreux cabinets de mandataires/liquidateurs judiciaires
    (BTSG, 4R Solutions, etc.).
    """

    RSS_PATH = "/rss/actif"

    def __init__(self, registry=None):
        """
        registry: instance de CabinetRegistry. Par défaut, un registre
        initialisé avec CabinetRegistry.DEFAULTS.
        """
        self.registry = registry or CabinetRegistry()
        self.resultats = []

    # ============================================================
    # RÉCUPÉRATION D'UN FLUX RSS
    # ============================================================

    def _fetch_rss(self, domain):
        url = domain.rstrip("/") + self.RSS_PATH

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        return response.content

    # ============================================================
    # EXTRACTION DES CHAMPS DANS LA DESCRIPTION
    # ============================================================
    # La description contient un texte libre suivi de blocs du type :
    # <h3>Type</h3> ... <h3>Estimation</h3> ... <h3>Lieu</h3> ...
    # <h3>Date limite de l'offre</h3> ...
    # ============================================================

    @staticmethod
    def _clean_description(description):
        """Texte libre du cabinet (avant les blocs <h3>), sur une seule ligne.

        "gasoil</BR>Immatriculé FX-101-AB</BR>174 676 kms"
        -> "gasoil | Immatriculé FX-101-AB | 174 676 kms"
        """
        libre = re.split(r"<h3>", description, maxsplit=1, flags=re.IGNORECASE)[0]
        libre = re.sub(r"<\s*/?\s*br\s*/?\s*>", "\n", libre, flags=re.IGNORECASE)
        libre = re.sub(r"<[^>]+>", "", libre)
        lignes = (re.sub(r"\s+", " ", ligne).strip() for ligne in libre.splitlines())
        return " | ".join(ligne for ligne in lignes if ligne) or None

    @staticmethod
    def _extract_field(description, label):
        pattern = rf"<h3>{re.escape(label)}</h3>\s*(.*?)(?:<h3>|$)"
        match = re.search(pattern, description, flags=re.IGNORECASE | re.DOTALL)

        if not match:
            return None

        valeur = match.group(1).strip()
        valeur = re.sub(r"\s+", " ", valeur)
        return valeur or None

    # ============================================================
    # PARSING D'UN FLUX RSS POUR UN CABINET
    # ============================================================

    def _parse_rss(self, cabinet, xml_content):
        root = ET.fromstring(xml_content)

        items = root.findall("./channel/item")

        lignes = []

        for item in items:
            titre = item.findtext("title", default="").strip()
            lien = item.findtext("link", default="").strip()
            pub_date = item.findtext("pubDate", default="").strip()
            guid = item.findtext("guid", default="").strip()

            description_raw = item.findtext("description", default="")
            # La description est doublement encodée en HTML (entités + balises)
            description = html.unescape(description_raw)

            ligne = {
                "cabinet": cabinet,
                "titre": titre,
                "type": self._extract_field(description, "Type"),
                "estimation": self._extract_field(description, "Estimation"),
                "lieu": self._extract_field(description, "Lieu"),
                "date_limite_offre": self._extract_field(description, "Date limite de l'offre"),
                "date_publication": pub_date,
                "url_detail": lien,
                "guid": guid,
                "description": self._clean_description(description),
            }

            lignes.append(ligne)

        return lignes

    # ============================================================
    # PIPELINE COMPLET
    # ============================================================

    def fetch_all(self):
        """Parcourt tous les cabinets du dictionnaire et agrège les résultats."""
        self.resultats = []

        for domain, noms in self.registry.by_domain().items():
            cabinet = noms[0]  # nom canonique : un site n'est interrogé qu'une fois
            print(f"→ {cabinet} ({domain})")

            try:
                xml_content = self._fetch_rss(domain)
                lignes = self._parse_rss(cabinet, xml_content)

            except requests.exceptions.RequestException as e:
                print(f"   Erreur réseau : {e}")
                continue

            except ET.ParseError as e:
                print(f"   Erreur de parsing XML : {e}")
                continue

            print(f"   {len(lignes)} actif(s) trouvé(s)")
            self.resultats.extend(lignes)

        return self.resultats