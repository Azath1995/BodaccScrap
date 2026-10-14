"""Du texte libre du greffe au nom du cabinet, puis au cabinet du registre.

Exemple de désignation brute (colonne `liquidateur`) :
    "la Selarl BLEU SUD Représentée par Maître MARTIN Claire 8 avenue des Tilleuls 30000 Nîmes"
    -> cabinet_name      : "Selarl BLEU SUD"
    -> normalize_cabinet : "bleu sud"
"""
import re
import unicodedata

_FORMES = r"selarlu?|selafa|selasu?|scp|sasu?|sarl|eurl"

# Mots ignorés à la comparaison : formes juridiques, articles, civilités.
_MOTS_IGNORES = frozenset(
    {"selarl", "selarlu", "selafa", "selas", "selasu", "scp", "sas", "sasu",
     "sarl", "eurl", "la", "le", "les", "et", "me", "maitre"}
)

# Article devant le nom : "la Selarl X", "l'Etude Y". L'article doit être un mot
# entier : "Lambert" ne doit pas devenir "mbert".
_ARTICLE = re.compile(r"^(?:(?:la|le)\s+|l')", re.IGNORECASE)

# Débris en tête du texte du greffe : "(selarl) Etude X", "/ Selarl Y", "- Z".
_DEBUT_PARASITE = re.compile(r"^(?:\s*\([^)]*\)|[\s/,;:\-–])+")

# "Me Yann Lefort Pour La Selarl MJ Lefort ..." : la vraie structure est
# le cabinet qui suit "de la" / "pour la".
_CABINET_APRES_PREPOSITION = re.compile(
    rf"\b(?:de|pour)\s+la\s+((?:{_FORMES})\b.*)", re.IGNORECASE
)

# Premier signe qui marque la fin du nom : ponctuation, tiret, mention du
# représentant, ou début d'adresse (un nombre).
_FIN_DU_NOM = re.compile(
    rf"""
      \s*[,(/]
    | \s+-\s+
    | \s+(?:repr[ée]sent[ée]e?s?
           |pris(?:e)?\s+en\s+la\s+personne
           |en\s+la\s+personne
           |mission\s+conduite
           |agissant
           |membre\s+du)\b
    | \s+\d
    """,
    re.IGNORECASE | re.VERBOSE,
)


def cabinet_name(designation):
    """Extrait le nom du cabinet (ou du mandataire) d'une désignation brute."""
    if not designation:
        return None

    texte = _DEBUT_PARASITE.sub("", designation.strip())
    texte = _ARTICLE.sub("", texte)

    apres = _CABINET_APRES_PREPOSITION.search(texte)
    if apres:
        texte = apres.group(1)

    fin = _FIN_DU_NOM.search(texte)
    if fin:
        texte = texte[: fin.start()]

    return texte.strip() or None


def normalize_cabinet(name):
    """Forme comparable : sans accents ni ponctuation ni formes juridiques."""
    decomposed = unicodedata.normalize("NFKD", name or "")
    sans_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    # L'article élidé ("l'Etude") est retiré avant de découper en mots : sinon le
    # "l" resterait un mot à part, et on ne pourrait pas l'ignorer sans aussi
    # perdre le L des initiales ("C.L.R." deviendrait "c r").
    texte = re.sub(r"\bl['’]", " ", sans_accents.lower())
    mots = re.sub(r"[^a-z0-9]+", " ", texte).split()
    return " ".join(m for m in mots if m not in _MOTS_IGNORES)


def match_cabinet(designation, known_names):
    """Retourne le nom du registre correspondant à la désignation, sinon None.

    Un nom connu correspond si tous ses mots (normalisés) apparaissent, dans
    l'ordre et côte à côte, dans le nom du cabinet. En cas de plusieurs
    correspondances, on garde le nom connu le plus long.
    """
    cible = f" {normalize_cabinet(cabinet_name(designation))} "

    meilleur, meilleure_longueur = None, 0
    for connu in known_names:
        norme = normalize_cabinet(connu)
        if norme and f" {norme} " in cible and len(norme) > meilleure_longueur:
            meilleur, meilleure_longueur = connu, len(norme)
    return meilleur
