import re
import unicodedata


def normalize(text):
    """Lowercase and strip accents so 'Véhicule' and 'vehicule' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.lower()


class ActifFilter:
    """Mots-clés des actifs « véhicule » et motif qui les reconnaît par mots entiers (utilisé par bodacc.update)."""

    # Une seule forme (singulier, sans accent) par mot : le pluriel est géré
    # par le motif regex et les accents par normalize().
    VEHICULE_KEYWORDS = [
        "vehicule",
        "auto",
        "automobile",
        "voiture",
        "camion",
        "utilitaire",
        "moto",
        "deux-roues",
        "remorque",
    ]

    @staticmethod
    def build_pattern(keywords):
        r"""Compile un motif qui ne matche que des mots entiers.

        \b = frontière de mot, donc "auto" matche "auto" / "autos" mais pas
        "automate" ni "autoclave". Le "s?" accepte le pluriel.
        """
        alternatives = "|".join(re.escape(normalize(kw)) for kw in keywords)
        return re.compile(rf"\b(?:{alternatives})s?\b")
