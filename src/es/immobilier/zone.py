"""La zone (communes de la région de Torrevieja) et ce qui reconnaît un bien immobilier dans l'adresse d'un lot eactivos.

L'adresse d'un lot est un texte du type `vivienda-duplex-b11-en-torrevieja-alicante` : on y cherche une commune (mot entier,
avec ses tirets) et un mot de bien immobilier. Limite connue : un lot dont l'adresse ne cite pas la commune n'est pas vu.
"""
import re
import unicodedata

# Mot d'adresse -> commune. L'ordre ne compte pas : les clés les plus longues sont essayées d'abord (« daya-nueva » avant « daya »).
MUNICIPALITIES = {
    "torrevieja": "Torrevieja", "la-mata": "Torrevieja",
    "orihuela": "Orihuela", "cabo-roig": "Orihuela", "playa-flamenca": "Orihuela", "la-zenia": "Orihuela",
    "punta-prima": "Orihuela", "villamartin": "Orihuela", "los-dolses": "Orihuela",
    "guardamar": "Guardamar del Segura", "pilar-de-la-horadada": "Pilar de la Horadada",
    "san-miguel-de-salinas": "San Miguel de Salinas", "rojales": "Rojales", "ciudad-quesada": "Rojales",
    "almoradi": "Almoradí", "los-montesinos": "Los Montesinos", "algorfa": "Algorfa", "benijofar": "Benijófar",
    "formentera-del-segura": "Formentera del Segura", "daya-nueva": "Daya Nueva", "daya-vieja": "Daya Vieja",
    "callosa-de-segura": "Callosa de Segura", "cox": "Cox", "redovan": "Redován", "bigastro": "Bigastro",
    "san-fulgencio": "San Fulgencio", "albatera": "Albatera", "rafal": "Rafal", "jacarilla": "Jacarilla",
    "benejuzar": "Benejúzar", "catral": "Catral", "granja-de-rocamora": "Granja de Rocamora",
}

# Mot d'adresse -> type de bien. « lote » seul est un lot mixte (peut contenir de l'immobilier) ; voir property_type.
PROPERTY_WORDS = {
    "vivienda": "vivienda", "viviendas": "vivienda", "apartamento": "vivienda", "apartamentos": "vivienda", "piso": "vivienda",
    "pisos": "vivienda", "casa": "vivienda", "chalet": "vivienda", "bungalow": "vivienda", "adosado": "vivienda", "duplex": "vivienda",
    "atico": "vivienda", "villa": "vivienda",
    "local": "local", "locales": "local", "oficina": "local", "oficinas": "local",
    "nave": "nave/edificio", "naves": "nave/edificio", "edificio": "nave/edificio", "hotel": "nave/edificio",
    "parcela": "terreno/finca", "parcelas": "terreno/finca", "solar": "terreno/finca", "terreno": "terreno/finca",
    "terrenos": "terreno/finca", "suelo": "terreno/finca", "finca": "terreno/finca", "fincas": "terreno/finca", "rustica": "terreno/finca",
    "urbana": "terreno/finca", "inmueble": "terreno/finca", "inmuebles": "terreno/finca",
    "plaza": "garaje/trastero", "garaje": "garaje/trastero", "garajes": "garaje/trastero", "trastero": "garaje/trastero",
    "trasteros": "garaje/trastero", "parking": "garaje/trastero", "aparcamiento": "garaje/trastero",
}
# Un lot qui parle de ces biens et d'aucun bien immobilier n'est pas de l'immobilier.
NOT_PROPERTY = {"maquinaria", "vehiculo", "vehiculos", "furgoneta", "camion", "semirremolque", "remolque", "tractor", "carretilla",
                "motocicleta", "coche", "coches", "turismo", "grua", "stock", "existencias", "mobiliario"}


def slug_of(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def slug_of_text(text):
    """Un texte libre (« Finca urbana en Torrevieja (Alicante) ») mis à la même forme qu'une adresse eactivos, pour
    réutiliser `municipality` et `property_type` sur du texte qui n'est pas une URL (voir `es.immobilier.boe`)."""
    return re.sub(r"[^a-z0-9]+", "-", _fold(text)).strip("-")


def municipality(slug, wanted=None):
    """Commune citée dans l'adresse (mot entier), ou None. `wanted` : les clés de commune retenues (défaut : toute la zone)."""
    for key in sorted(MUNICIPALITIES, key=len, reverse=True):
        if wanted is not None and key not in wanted:
            continue
        if re.search(rf"(?:^|-){re.escape(key)}(?:-|$)", slug):
            return MUNICIPALITIES[key]
    return None


def property_type(slug):
    """Type de bien immobilier cité dans l'adresse (« vivienda », « local »...), « lote » pour un lot mixte, None sinon."""
    words = set(slug.split("-"))
    for word in slug.split("-"):
        if word in PROPERTY_WORDS:
            return PROPERTY_WORDS[word]
    if "lote" in words and not words & NOT_PROPERTY:
        return "lote"
    return None


def keys_for(names):
    """Clés de commune pour des noms saisis (« torrevieja », « Orihuela », « pilar de la horadada »). Lève ValueError si inconnu."""
    wanted = set()
    for name in names:
        clean = re.sub(r"[^a-z]+", "-", _fold(name)).strip("-")
        found = {key for key, town in MUNICIPALITIES.items() if key == clean or _fold(town).replace(" ", "-") == clean}
        if not found:
            raise ValueError(f"commune inconnue : {name!r}")
        wanted |= found
    return wanted


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()
