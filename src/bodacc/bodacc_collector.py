import requests
import re
import json
from datetime import date, timedelta


class BodaccLiquidationScraper:
    """
    Fetches company liquidation announcements from the BODACC open data API,
    filters them to liquidation judgments, extracts key fields (SIREN,
    liquidateur, etc.); bodacc.update stores the result in the SQLite base.
    """

    BASE_URL = (
        "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/"
        "catalog/datasets/annonces-commerciales/records"
    )

    LIQUIDATION_NATURES = {
        "Jugement d'ouverture de liquidation judiciaire",
        "Jugement de conversion en liquidation judiciaire"
    }

    # Le texte libre du greffe varie ("désignant liquidateur", "désignant en
    # qualité de liquidateur judiciaire", "Liquidateur judiciaire : ...", et
    # même la faute "qualtié"). On ancre sur le mot "liquidateur" précédé de
    # "désignant [en qualité de]" ou d'un début de phrase, ce qui évite de
    # capter "adresser au liquidateur judiciaire" dans la phrase finale.
    # Fin de capture : la phrase standard ". Les déclarations..." ou
    # ". Les créances sont à adresser..." (espace facultatif), la clause
    # ", et mettant fin à la mission de l'administrateur X" (autre personne),
    # ou la fin du texte.
    LIQUIDATEUR_PATTERN = re.compile(
        r"(?:d[ée]signant\s+(?:en\s+qual\w+\s+de\s+)?|\.\s*)"
        r"liquidateur(?:\s+judiciaire)?\s*:?\s+"
        r"(.*?)"
        r"(?:\.\s*Les\s+(?:déclarations|créances)|,?\s+et\s+mettant\s+fin\b|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    SELECT_FIELDS = """
        id,
        publicationavis,
        parution,
        dateparution,
        numeroannonce,
        familleavis,
        familleavis_lib,
        typeavis,
        typeavis_lib,
        numerodepartement,
        departement_nom_officiel,
        region_code,
        region_nom_officiel,
        tribunal,
        commercant,
        ville,
        cp,
        registre,
        pdf_parution_subfolder,
        ispdf_unitaire,
        jugement,
        url_complete
    """

    def __init__(self, period="today", custom_start=None, custom_end=None, page_size=100):
        """
        period: "today" | "last_7_days" | "last_month" | "custom"
        custom_start / custom_end: "YYYY-MM-DD" strings, required if period == "custom"
        """
        self.period = period
        self.custom_start = custom_start
        self.custom_end = custom_end
        self.page_size = page_size

        self.start_date = None
        self.end_date = None

        self.all_results = []
        self.liquidations = []
        self.resultats = []

        self._compute_dates()

    # ============================================================
    # DATES
    # ============================================================

    def _compute_dates(self):
        today = date.today()

        if self.period == "today":
            self.start_date = today
            self.end_date = today

        elif self.period == "last_7_days":
            self.start_date = today - timedelta(days=6)
            self.end_date = today

        elif self.period == "last_month":
            first_current_month = today.replace(day=1)
            self.end_date = first_current_month - timedelta(days=1)
            self.start_date = self.end_date.replace(day=1)

        elif self.period == "custom":
            if not self.custom_start or not self.custom_end:
                raise ValueError("custom_start et custom_end sont requis pour period='custom'")
            self.start_date = date.fromisoformat(self.custom_start)
            self.end_date = date.fromisoformat(self.custom_end)

        else:
            raise ValueError(
                "period doit être : today, last_7_days, last_month ou custom"
            )

    # ============================================================
    # HELPERS DE PARSING
    # ============================================================

    @staticmethod
    def parse_jugement(jugement):
        if not jugement:
            return None

        if isinstance(jugement, dict):
            return jugement

        if isinstance(jugement, str):
            try:
                return json.loads(jugement)
            except json.JSONDecodeError:
                return None

        return None

    @staticmethod
    def extract_siren(registre):
        if not registre:
            return None

        for element in registre:
            if not element:
                continue

            value = str(element).replace(" ", "")

            if value.isdigit() and len(value) == 9:
                return value

        return None

    @classmethod
    def extract_liquidateur(cls, jugement):
        jugement = cls.parse_jugement(jugement)

        if not jugement:
            return None

        texte = jugement.get("complementJugement", "")

        if not texte:
            return None

        match = cls.LIQUIDATEUR_PATTERN.search(texte)

        if match:
            liquidateur = re.sub(r"\s+", " ", match.group(1)).strip()
            liquidateur = re.sub(r"\.$", "", liquidateur)
            return liquidateur or None

        return None

    # ============================================================
    # RÉCUPÉRATION DES DONNÉES
    # ============================================================

    def _get_page(self, offset):
        params = {
            "limit": self.page_size,
            "offset": offset,
            "select": self.SELECT_FIELDS,
            "where": f"""
                familleavis = 'collective'
                AND dateparution >= '{self.start_date}'
                AND dateparution <= '{self.end_date}'
            """,
            "order_by": "dateparution DESC"
        }

        response = requests.get(self.BASE_URL, params=params, timeout=60)
        response.raise_for_status()

        return response.json()

    def fetch_all(self):
        """Fetch all pages of results for the configured period."""
        print("=" * 100)
        print("PÉRIODE ANALYSÉE")
        print("=" * 100)
        print("Du :", self.start_date)
        print("Au :", self.end_date)

        print("\n" + "=" * 100)
        print("RÉCUPÉRATION DES ANNONCES BODACC")
        print("=" * 100)

        self.all_results = []
        offset = 0
        total_count = None

        while True:
            print(f"Récupération : offset={offset}...")

            data = self._get_page(offset)

            if total_count is None:
                total_count = data.get("total_count", 0)
                print("Nombre total d'annonces collectives :", total_count)

            results = data.get("results", [])

            if not results:
                break

            self.all_results.extend(results)
            print(f"  → {len(results)} annonces récupérées")

            offset += self.page_size

            if len(self.all_results) >= total_count:
                break

        print("\nTotal récupéré :", len(self.all_results))
        return self

    # ============================================================
    # FILTRAGE ET TRANSFORMATION
    # ============================================================

    def filter_liquidations(self):
        """Keep only announcements whose jugement.nature is a liquidation type."""
        print("\n" + "=" * 100)
        print("FILTRAGE DES LIQUIDATIONS")
        print("=" * 100)

        self.liquidations = []

        for result in self.all_results:
            jugement = self.parse_jugement(result.get("jugement"))

            if not jugement:
                continue

            if jugement.get("nature") not in self.LIQUIDATION_NATURES:
                continue

            result["jugement"] = jugement
            self.liquidations.append(result)

        print("Nombre de liquidations trouvées :", len(self.liquidations))
        return self

    def transform(self):
        """Build the flat list of dicts ready for display/export."""
        self.resultats = []

        for result in self.liquidations:
            jugement = self.parse_jugement(result.get("jugement"))

            if not jugement:
                continue

            siren = self.extract_siren(result.get("registre"))
            liquidateur = self.extract_liquidateur(jugement)

            ligne = {
                "id": result.get("id"),
                "date_publication": result.get("dateparution"),
                "numero_annonce": result.get("numeroannonce"),
                "date_jugement": jugement.get("date"),
                "nature": jugement.get("nature"),
                "entreprise": result.get("commercant"),
                "siren": siren,
                "ville": result.get("ville"),
                "cp": result.get("cp"),
                "tribunal": result.get("tribunal"),
                "liquidateur": liquidateur,
                "url_bodacc": result.get("url_complete")
            }

            self.resultats.append(ligne)

        return self