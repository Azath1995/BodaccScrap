"""Filtres et tris des véhicules, pour ne pas avoir à écrire de SQL.

Le prix est stocké comme du texte (« 14 000,00 € ») : il faut le convertir en nombre
avant de le comparer.

Règle sur les valeurs inconnues : un filtre numérique (prix, km, année) ou sur le
carburant écarte les véhicules dont la valeur est inconnue, puisqu'on ne peut pas dire
qu'ils respectent le critère. `keep_unknown=True` les garde au contraire.
Les bornes sont inclusives (--max-km 50000 accepte 50 000 km).
"""
import re

from bodacc.actif_filter import normalize

_PRICE = re.compile(r"(\d[\d\s .]*?)(?:,(\d{1,2}))?\s*€")


def parse_price(text):
    """'18 000,00 €' -> 18000.0 ; 'Non renseigné', vide ou absent -> None."""
    match = _PRICE.search(text or "")
    if not match:
        return None
    euros = int(re.sub(r"\D", "", match.group(1)))
    cents = int(match.group(2).ljust(2, "0")) if match.group(2) else 0
    return euros + cents / 100


def _in_range(value, low, high, keep_unknown):
    if low is None and high is None:
        return True                          # pas de filtre sur ce champ
    if value is None:
        return keep_unknown
    return (low is None or value >= low) and (high is None or value <= high)


def _contains(value, wanted):
    return normalize(wanted) in normalize(value)


def filter_vehicles(rows, cabinet=None, carburant=None, lieu=None,
                    min_year=None, max_year=None, min_price=None, max_price=None,
                    min_km=None, max_km=None, keep_unknown=False):
    """Retourne les véhicules qui respectent tous les critères donnés, avec 'prix' (nombre).

    cabinet, carburant, lieu : recherche d'un morceau de texte, sans tenir compte de la
    casse ni des accents ('electrique' trouve 'électrique', '33220' ou 'pineuilh' trouvent le lieu).
    """
    kept = []
    for row in rows:
        price = parse_price(row.get("estimation"))

        if cabinet and not _contains(row.get("cabinet"), cabinet):
            continue
        if lieu and not _contains(row.get("lieu"), lieu):
            continue
        if carburant:
            fuel = row.get("carburant")
            if (fuel is None and not keep_unknown) or (fuel is not None and not _contains(fuel, carburant)):
                continue
        if not _in_range(row.get("annee"), min_year, max_year, keep_unknown):
            continue
        if not _in_range(price, min_price, max_price, keep_unknown):
            continue
        if not _in_range(row.get("kilometrage"), min_km, max_km, keep_unknown):
            continue

        kept.append({**row, "prix": price})
    return kept


# Clé de tri -> (colonne, sens). Les valeurs inconnues vont toujours à la fin.
SORT_KEYS = {"price": ("prix", 1), "estimation": ("prix", 1), "km": ("kilometrage", 1), "year": ("annee", -1),
             "cote": ("cote", 1)}


def sort_vehicles(rows, sort="recent"):
    """Tri sur une clé ou plusieurs, séparées par des virgules : « km,estimation,cote » trie par km, puis à km égal
    par estimation, puis par cote. recent : ordre d'arrivée (les plus récemment vus d'abord). Croissant, sauf year
    (les plus récents d'abord)."""
    rows = list(rows)
    keys = [k.strip() for k in (sort or "recent").split(",") if k.strip() and k.strip() != "recent"]
    for key in reversed(keys):              # tri stable : la dernière clé d'abord, la première décide en dernier
        column, direction = SORT_KEYS[key]
        rows.sort(key=lambda r: (r.get(column) is None, direction * (r.get(column) or 0)))
    return rows
