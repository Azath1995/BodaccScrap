"""Estimation du coût de transport d'un véhicule vers une destination, en fourchette.

    python -m bodacc.report vehicles --destination "87000 Limoges"

**Ce n'est pas l'algorithme d'un transporteur** (les leurs sont propriétaires, dynamiques, et Hiflow interdit à ses robots ses pages de
simulation) : c'est une fourchette calée sur des prix publiés (convoyage par chauffeur, voiture standard qui roule, tout compris) :

- Hiflow : Lyon-Marseille (environ 420 km) 355 € TTC, minimum 104 € TTC ;
- guides de tarifs : Lyon-Clermont (300 km) 380 €, Paris-Marseille (775 km) 735 €, bandes 200-300 km : 180 à 280 €, 300-500 km : 280 à 450 €.

Le prix suit une courbe dégressive : les frais fixes (chargement, assurance, retour du chauffeur) se diluent sur les longs trajets.
La distance est routière estimée = distance à vol d'oiseau × 1,3. Non pris en compte : véhicule non roulant (plateau, 1,2 à 2 €/km), SUV
ou utilitaire (+10 à 25 %), urgence (+20 à 40 %), lots de plusieurs véhicules. À remplacer par de vrais devis dès que vous en avez.
"""
import json
import math
import time
from pathlib import Path

from bodacc.paths import DATA_DIR
from prospects import search

ROAD_FACTOR = 1.3
# (distance routière en km, prix bas €, prix haut €), interpolé linéairement entre deux points.
ANCHORS = [(0, 90, 130), (100, 100, 150), (200, 170, 250), (300, 260, 400), (500, 380, 560), (800, 600, 850), (1000, 720, 1000)]
BEYOND_1000 = (0.70, 0.95)          # €/km au-delà du dernier point
MAX_KM = 1500                       # au-delà (outre-mer, adresse mal géocodée) : pas d'estimation
CACHE_PATH = Path(DATA_DIR) / "geocache.json"


class TransportError(Exception):
    """Erreur attendue (destination introuvable...) : message destiné à l'utilisateur."""


def road_km(lat1, lon1, lat2, lon2):
    return search.distance_km(lat1, lon1, lat2, lon2) * ROAD_FACTOR


def estimate(km):
    """(prix bas, prix haut) en euros, arrondis à 10 €, pour `km` kilomètres de route."""
    if km <= ANCHORS[-1][0]:
        for (d0, lo0, hi0), (d1, lo1, hi1) in zip(ANCHORS, ANCHORS[1:]):
            if km <= d1:
                share = (km - d0) / (d1 - d0)
                low, high = lo0 + share * (lo1 - lo0), hi0 + share * (hi1 - hi0)
                break
    else:
        extra = km - ANCHORS[-1][0]
        low, high = ANCHORS[-1][1] + extra * BEYOND_1000[0], ANCHORS[-1][2] + extra * BEYOND_1000[1]
    return int(round(low / 10) * 10), int(round(high / 10) * 10)


class Geocoder:
    """Coordonnées d'un lieu, avec un cache sur disque : une adresse n'est demandée qu'une fois au géocodeur officiel."""

    def __init__(self, cache_path=CACHE_PATH, fetch=search.get_json, sleep=time.sleep, pause=0.25):
        self.path, self.fetch, self.sleep, self.pause = Path(cache_path) if cache_path else None, fetch, sleep, pause
        try:
            self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path and self.path.exists() else {}
        except (OSError, ValueError):
            self.cache = {}
        self.requests = 0

    def locate(self, text):
        """(lat, lon), ou None si le lieu est introuvable ou si le service ne répond pas (pas mis en cache : nouvel essai plus tard)."""
        key = " ".join(text.split()).lower()
        if key in self.cache:
            return tuple(self.cache[key]) if self.cache[key] else None
        if self.requests:
            self.sleep(self.pause)
        self.requests += 1
        try:
            found = search.geocode(text, self.fetch)
        except search.ProspectError as error:
            if "introuvable" in str(error):
                self.cache[key] = None                      # le lieu n'existe pas : inutile de le redemander
                self._save()
            return None
        self.cache[key] = [found["lat"], found["lon"]]
        self._save()
        return found["lat"], found["lon"]

    def _save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")


def annotate(rows, destination, geocoder):
    """Ajoute à chaque véhicule `km_route`, `transport_min`, `transport_max` et `transport` (« 310-440 € », vide si inconnu)."""
    target = geocoder.locate(destination)
    if target is None:
        raise TransportError(f"Destination introuvable : {destination!r}. Donnez un lieu, par exemple « 87000 Limoges ».")
    for row in rows:
        row.update(km_route=None, transport_min=None, transport_max=None, transport="")
        place = (row.get("lieu") or "").strip()
        if not place or place.startswith(("97", "98")):     # sans lieu, ou outre-mer
            continue
        origin = geocoder.locate(place)
        if origin is None:
            continue
        km = road_km(*origin, *target)
        if km > MAX_KM:
            continue
        low, high = estimate(km)
        row.update(km_route=int(round(km)), transport_min=low, transport_max=high, transport=f"{low}-{high} €")
    return rows
