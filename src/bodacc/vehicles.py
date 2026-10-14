"""Extrait marque, immatriculation, kilométrage, année et carburant d'une annonce.

Le texte vient de la description libre saisie par chaque cabinet : les formats
varient ("Immatriculé : AB-123-CD", "Immatriculation AB123CD", "174 676 kms",
"Kilométrage : 300210", "de 2016"...). Chaque champ est donc "au mieux" : None
quand on ne trouve rien de fiable, jamais une valeur inventée.
"""
import re
from datetime import date

from bodacc.actif_filter import normalize

# Marques (clé normalisée : minuscules, sans accents) -> nom affiché.
MAKES = {
    "renault": "Renault", "peugeot": "Peugeot", "citroen": "Citroën", "dacia": "Dacia",
    "ford": "Ford", "volkswagen": "Volkswagen", "vw": "Volkswagen", "mercedes": "Mercedes",
    "fiat": "Fiat", "iveco": "Iveco", "opel": "Opel", "toyota": "Toyota", "nissan": "Nissan",
    "volvo": "Volvo", "scania": "Scania", "man": "MAN", "daf": "DAF", "bmw": "BMW",
    "audi": "Audi", "seat": "Seat", "skoda": "Skoda", "hyundai": "Hyundai", "kia": "Kia",
    "mitsubishi": "Mitsubishi", "lada": "Lada", "tesla": "Tesla", "jeep": "Jeep",
    "suzuki": "Suzuki", "honda": "Honda", "yamaha": "Yamaha", "kawasaki": "Kawasaki",
    "porsche": "Porsche", "mazda": "Mazda", "smart": "Smart", "land rover": "Land Rover",
    "alfa romeo": "Alfa Romeo", "piaggio": "Piaggio", "harley": "Harley-Davidson",
    "manitou": "Manitou", "komatsu": "Komatsu", "same": "SAME", "kubota": "Kubota", "caterpillar": "Caterpillar",
    "jcb": "JCB", "bobcat": "Bobcat", "new holland": "New Holland", "john deere": "John Deere",
    "massey ferguson": "Massey Ferguson", "claas": "Claas", "fendt": "Fendt",
    "liebherr": "Liebherr", "potain": "Potain", "hitachi": "Hitachi", "doosan": "Doosan",
}

# Quand l'annonce ne cite que le modèle ("CLIO", "KANGOO"), on en déduit la marque.
MODELS = {
    "clio": "Renault", "megane": "Renault", "twingo": "Renault", "kangoo": "Renault",
    "master": "Renault", "trafic": "Renault", "zoe": "Renault", "captur": "Renault",
    "partner": "Peugeot", "expert": "Peugeot", "boxer": "Peugeot",
    "berlingo": "Citroën", "jumper": "Citroën", "jumpy": "Citroën",
    "transit": "Ford", "fiesta": "Ford", "ranger": "Ford",
    "sprinter": "Mercedes", "vito": "Mercedes",
    "sandero": "Dacia", "logan": "Dacia", "duster": "Dacia", "dokker": "Dacia",
    "ducato": "Fiat", "daily": "Iveco",
    "transporter": "Volkswagen", "caddy": "Volkswagen", "crafter": "Volkswagen",
}

_BRAND_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted({**MAKES, **MODELS}, key=len, reverse=True)) + r")\b"
)

# Plaque SIV (depuis 2009) : 2 lettres, 3 chiffres, 2 lettres. Les lettres I, O et U
# n'existent pas dans ce format, ce qui écarte pas mal de faux positifs.
_PLATE = re.compile(r"\b([A-HJ-NP-TV-Z]{2})[\s-]?(\d{3})[\s-]?([A-HJ-NP-TV-Z]{2})\b")

# Nombre avec séparateurs de milliers ("174 676", "209.309") ou sans ("300210").
_NUMBER = r"(\d{1,3}(?:[ . ]\d{3})+|\d+)"
# (?<!\d) : ne jamais commencer au milieu d'un nombre ("de 2016 209.309 km").
_KM_WITH_UNIT = re.compile(rf"(?<!\d){_NUMBER}\s*kms?\b", re.IGNORECASE)
_KM_WITH_LABEL = re.compile(rf"kilom[ée]trage\s*:?\s*{_NUMBER}", re.IGNORECASE)

_YEAR_PATTERNS = [
    # "1ère mise en circulation : 31/10/2017", "Mise en circulation : 02.03.2017", "1ère MEC: 22/08/2022"
    re.compile(r"\b(?:mise en circulation|mec)\b[^\d]{0,20}\d{1,2}[/.\-]\d{1,2}[/.\-]((?:19|20)\d{2})", re.IGNORECASE),
    re.compile(r"\bann[ée]e\s*:?\s*((?:19|20)\d{2})\b", re.IGNORECASE),
    re.compile(r"\bmill[ée]sime\s*:?\s*((?:19|20)\d{2})\b", re.IGNORECASE),
    re.compile(r"\bde\s+((?:19|20)\d{2})\b", re.IGNORECASE),           # "MERCEDES VITO de 2016"
    # "PEUGEOT EXPERT DU 29/10/19 FL463DY", "RENAULT MASTER ... du 12/02/2024" (date de 1re immatriculation, Denis Hazane)
    re.compile(r"\bdu\s+\d{1,2}[/.]\d{1,2}[/.](\d{4}|\d{2})\b", re.IGNORECASE),
]

# L'ordre compte : "hybride essence" doit donner hybride.
_FUELS = [
    ("hybride", re.compile(r"\bhybride\b")),
    ("électrique", re.compile(r"\belectrique\b")),
    ("diesel", re.compile(r"\b(?:gasoil|diesel|gazole)\b")),
    ("essence", re.compile(r"\b(?:essence|sp ?9[58])\b")),
    ("gpl", re.compile(r"\bgpl\b")),
]


def _to_int(text):
    return int(re.sub(r"\D", "", text))


def find_make(text):
    match = _BRAND_PATTERN.search(normalize(text))
    if not match:
        return None
    word = match.group(1)
    return MAKES.get(word) or MODELS.get(word)


def find_plate(text):
    match = _PLATE.search(text.upper())
    return "-".join(match.groups()) if match else None


def find_mileage(text):
    for pattern in (_KM_WITH_UNIT, _KM_WITH_LABEL):
        match = pattern.search(text)
        if match:
            km = _to_int(match.group(1))
            if 1 <= km <= 2_000_000:
                return km
    return None


def find_year(text):
    for pattern in _YEAR_PATTERNS:
        match = pattern.search(text)
        if match:
            year = int(match.group(1))
            if year < 100:                  # « 29/10/19 » : 2019 ; « 12/05/98 » : 1998
                year += 2000 if year <= date.today().year % 100 + 1 else 1900
            if 1950 <= year <= date.today().year + 1:
                return year
    return None


def find_fuel(text):
    normalized = normalize(text)
    for fuel, pattern in _FUELS:
        if pattern.search(normalized):
            return fuel
    return None


_NUMBER_WORDS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
                 "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12}
_VEHICLE_NOUNS = (r"(?:vehicules?|voitures?|autos?|camions?|camionnettes?|fourgons?|fourgonnettes?|utilitaires?|"
                  r"motos?|motocyclettes?|scooters?|tracteurs?|remorques?|semi-remorques?|autocars?|bus)")
_COUNTED = re.compile(rf"\b(\d{{1,3}}|{'|'.join(_NUMBER_WORDS)})\s+{_VEHICLE_NOUNS}\b")


def find_plates(text):
    return {"-".join(m.groups()) for m in _PLATE.finditer(text.upper())}


def count_vehicles(titre, description):
    """Nombre de véhicules d'une annonce : 1 sauf si le texte en annonce plusieurs.

    Deux indices : un nombre devant un nom de véhicule (« deux véhicules », « 3 camions ») et plusieurs
    plaques distinctes. On garde le plus grand des deux et non leur somme : le titre et la description
    répètent souvent la même chose. « Des véhicules » sans nombre reste à 1 : on n'invente pas de nombre.
    """
    text = f"{titre or ''} | {description or ''}"
    numbers = [int(_NUMBER_WORDS.get(w) or w) for w in _COUNTED.findall(normalize(text))]
    return max([1, len(find_plates(text)), *numbers])


def parse_vehicle(titre, description):
    """Retourne toujours les 5 clés ; None quand l'information est absente."""
    text = f"{titre or ''} | {description or ''}"
    return {
        "marque": find_make(text),
        "immatriculation": find_plate(text),
        "kilometrage": find_mileage(text),
        "annee": find_year(text),
        "carburant": find_fuel(text),
    }
