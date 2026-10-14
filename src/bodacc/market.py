"""Prix de marché d'un véhicule : médiane des annonces comparables sur Leboncoin, via l'API Carapis.

    python -m bodacc.report vehicles --market

**Ce que c'est** : pour un véhicule de la base dont on connaît la marque et le modèle, on cherche les annonces
de même marque et modèle (année à ±2 ans, kilométrage à ±40 % quand on les connaît) et on donne la médiane de leur
prix, avec le nombre d'annonces et la fourchette du quart le moins cher au quart le plus cher. **Ce n'est pas la
cote La Centrale** (que Carapis ne fournit pas : « on request », non collectée) ni un prix de vente garanti : un
prix demandé en annonce, pas un prix payé.

**Source** : Carapis (`api.carapis.com`), qui collecte lui-même Leboncoin. Choix de l'utilisateur (8 octobre 2026),
comme pour eactivos : Leboncoin protège ses annonces contre les robots, ce module passe par un tiers qui le fait.
Vérifié le 8 octobre 2026 :
- Leboncoin y est `on_demand` : un **échantillon**, pas tout le site (68 Clio de 2016 à 2020, quand Leboncoin en
  compte des milliers) ; AutoScout24 n'y couvre que l'Allemagne, il n'est donc pas utilisé ;
- les listes donnent un prix **converti en dollars** (`price_usd`) ; le prix d'origine en euros n'est que dans le
  détail d'une annonce. Le taux est donc relevé une fois sur une annonce (prix d'origine / prix en dollars), gardé
  une semaine, et appliqué aux autres.

**Quota** : le compte gratuit donne 100 requêtes par jour. Une recherche par couple marque/modèle/année/km, mise en
cache une semaine dans `data/market_cache.json` ; au plus `max_requests` par exécution (50 par défaut).

**Clé** : `CARAPIS_API_KEY`, dans une variable d'environnement ou dans `.env` (voir `bodacc/env.py`).
"""
import json
import statistics
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from bodacc import env
from bodacc.actif_filter import normalize
from bodacc.paths import DATA_DIR
from bodacc.vehicles import MODELS

BASE = "https://api.carapis.com/apix/api"
USER_AGENT = "BodaccScrap (projet scolaire)"
SOURCE = "leboncoin"
CACHE_PATH = Path(DATA_DIR) / "market_cache.json"
CACHE_DAYS = 7
MIN_COMPARABLES = 3
YEAR_SPAN = 2
KM_SPAN = 0.40
# Modèles reconnus dans le titre ou la description, en plus de ceux de vehicles.MODELS (marque déduite du modèle).
EXTRA_MODELS = {
    "scenic": "Renault", "espace": "Renault", "kadjar": "Renault", "laguna": "Renault", "modus": "Renault",
    "golf": "Volkswagen", "polo": "Volkswagen", "tiguan": "Volkswagen", "passat": "Volkswagen", "touran": "Volkswagen",
    "corsa": "Opel", "astra": "Opel", "vivaro": "Opel", "movano": "Opel", "combo": "Opel", "zafira": "Opel",
    "yaris": "Toyota", "auris": "Toyota", "corolla": "Toyota", "rav4": "Toyota", "hilux": "Toyota",
    "qashqai": "Nissan", "juke": "Nissan", "micra": "Nissan", "navara": "Nissan", "focus": "Ford", "kuga": "Ford",
    "picasso": "Citroën", "nemo": "Citroën", "cactus": "Citroën", "doblo": "Fiat", "panda": "Fiat", "punto": "Fiat",
}
KNOWN_MODELS = {**MODELS, **EXTRA_MODELS}
# Noms de modèles à afficher autrement que le mot trouvé (« cactus » -> « C4 Cactus »).
MODEL_NAMES = {"cactus": "C4 Cactus", "rav4": "RAV4"}
# Modèles faits de chiffres ou de lettres et chiffres : trop ambigus seuls (« 208 » peut être un kilométrage), donc
# reconnus seulement quand la marque est déjà connue.
ALNUM_MODELS = {
    "Peugeot": {"106", "107", "108", "206", "207", "208", "306", "307", "308", "406", "407", "508", "2008", "3008", "5008"},
    "Citroën": {"c1", "c2", "c3", "c4", "c5", "c8", "ds3", "ds4", "ds5"},
    "Toyota": {"chr"},
}
# Nom de marque attendu par Carapis quand il diffère du nôtre.
CARAPIS_BRANDS = {"Citroën": "Citroen", "Mercedes": "Mercedes-Benz"}
MAX_KM_PER_YEAR = 60000          # au-delà, l'année extraite de l'annonce est sans doute une autre date (jugement...)


class MarketError(Exception):
    """Erreur attendue (clé absente ou refusée, service indisponible) : message destiné à l'utilisateur."""


def find_model(text, brand=None):
    """(marque, modèle) cités dans le texte (« RENAULT CLIO dCi » -> ('Renault', 'Clio')), ou (brand, None).

    Si la marque est déjà connue, un modèle d'une autre marque est ignoré : une description cite parfois plusieurs
    véhicules, et « Renault » + « Transit » ne désigne aucun véhicule réel.
    """
    words = set(normalize(text or "").replace("-", "").split()) | set(normalize(text or "").replace("-", " ").split())
    for model in sorted(KNOWN_MODELS, key=len, reverse=True):
        if model in words and (brand is None or KNOWN_MODELS[model] == brand):
            return KNOWN_MODELS[model], MODEL_NAMES.get(model, model.title())
    for token in sorted(ALNUM_MODELS.get(brand, ()), key=len, reverse=True):
        if token in words:
            return brand, MODEL_NAMES.get(token, token.upper())
    return brand, None


def plausible_year(year, km, today=None):
    """L'année si elle est vraisemblable ; None si elle est dans le futur ou incompatible avec le kilométrage."""
    current = (today or date.today()).year
    if not year or year > current:
        return None
    if km and km / max(1, current - year + 1) > MAX_KM_PER_YEAR:
        return None
    return year


def queries_for(vehicle, today=None):
    """[(critère, paramètres)] du plus précis au plus large, ou [] si marque/modèle manquent ou si c'est un lot.

    Le Leboncoin de Carapis est un petit échantillon : si la recherche la plus précise donne moins de MIN_COMPARABLES
    annonces, on élargit (année seule, puis modèle seul) — chaque étape coûte une requête, et le critère retenu est
    affiché pour qu'on sache sur quoi porte la médiane.
    """
    if (vehicle.get("nb_vehicules") or 1) > 1:
        return []
    brand, model = find_model(f"{vehicle.get('titre') or ''} {vehicle.get('description') or ''}", vehicle.get("marque"))
    if not brand or not model:
        return []
    base = {"source": SOURCE, "brand": CARAPIS_BRANDS.get(brand, brand), "model": model, "page_size": 50}
    km = vehicle.get("kilometrage")
    year = plausible_year(vehicle.get("annee"), km, today)
    steps = []
    if year:
        by_year = {**base, "min_year": year - YEAR_SPAN, "max_year": year + YEAR_SPAN}
        if km:
            steps.append(("année+km", {**by_year, "min_mileage": int(km * (1 - KM_SPAN)), "max_mileage": int(km * (1 + KM_SPAN))}))
        steps.append(("année", by_year))
    elif km:
        steps.append(("km", {**base, "min_mileage": int(km * (1 - KM_SPAN)), "max_mileage": int(km * (1 + KM_SPAN))}))
    steps.append(("modèle seul", base))
    return steps


def summarize(prices_eur):
    """{'median', 'low', 'high', 'n'} : médiane et quartiles, arrondis à 100 € ; None sous MIN_COMPARABLES annonces."""
    prices = sorted(p for p in prices_eur if p and p > 0)
    if len(prices) < MIN_COMPARABLES:
        return None
    low, _, high = statistics.quantiles(prices, n=4) if len(prices) >= 4 else (prices[0], None, prices[-1])

    def r(x):
        return int(round(x / 100) * 100)

    return {"median": r(statistics.median(prices)), "low": r(low), "high": r(high), "n": len(prices)}


def get(url, params, key):
    try:
        response = requests.get(url, params=params, timeout=60,
                                headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT})
    except requests.exceptions.RequestException as error:
        return None, {"detail": str(error)}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"detail": response.text[:200]}


class Market:
    """Recherche et cache. `fetch(url, params, key)` -> (code HTTP, json) : remplaçable dans les tests."""

    def __init__(self, key=None, cache_path=CACHE_PATH, fetch=get, sleep=time.sleep, pause=1.0, max_requests=50, today=None):
        self.key = key or env.get("CARAPIS_API_KEY")
        if not self.key:
            raise MarketError("clé Carapis absente : mettez CARAPIS_API_KEY=car_... dans le fichier .env (voir .env.example).")
        self.path, self.fetch, self.sleep, self.pause = Path(cache_path) if cache_path else None, fetch, sleep, pause
        self.max_requests, self.requests = max_requests, 0
        self.today = today or date.today()
        try:
            self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path and self.path.exists() else {}
        except (OSError, ValueError):
            self.cache = {}
        self.cache.setdefault("queries", {})

    def _fresh(self, entry):
        return entry and date.fromisoformat(entry["date"]) >= self.today - timedelta(days=CACHE_DAYS)

    def _call(self, url, params):
        if self.requests >= self.max_requests:
            return None
        if self.requests:
            self.sleep(self.pause)
        self.requests += 1
        status, data = self.fetch(url, params, self.key)
        if status == 401:
            raise MarketError("clé Carapis refusée (HTTP 401) : vérifiez CARAPIS_API_KEY dans .env (elle commence par car_).")
        if status == 429:
            raise MarketError("quota Carapis atteint (HTTP 429) : réessayez demain, le compte gratuit donne 100 requêtes par jour.")
        return data if status == 200 else None

    def usd_to_eur(self, sample_id):
        """Taux dollars -> euros relevé sur le détail d'une annonce (prix d'origine en euros / prix en dollars)."""
        entry = self.cache.get("rate")
        if self._fresh(entry):
            return entry["value"]
        detail = self._call(f"{BASE}/vehicles/{sample_id}/", {})
        if not detail or detail.get("price_original_currency") not in (None, "EUR") or not detail.get("price_usd"):
            return entry["value"] if entry else None
        value = float(detail["price_original"]) / float(detail["price_usd"])
        self.cache["rate"] = {"value": value, "date": self.today.isoformat()}
        return value

    def comparables(self, params):
        """Prix en dollars des annonces comparables (depuis le cache si récent), ou None si la recherche n'a pu se faire."""
        key = json.dumps(params, sort_keys=True)
        entry = self.cache["queries"].get(key)
        if self._fresh(entry):
            return entry["prices_usd"], entry.get("sample_id")
        data = self._call(f"{BASE}/vehicles/", params)
        if data is None:
            return None
        results = data.get("results", [])
        prices = [v["price_usd"] for v in results if v.get("price_usd")]
        sample = results[0]["id"] if results else None
        self.cache["queries"][key] = {"date": self.today.isoformat(), "prices_usd": prices, "sample_id": sample}
        return prices, sample

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")


def annotate(rows, market):
    """Ajoute à chaque véhicule `marche` (« 11 900 € (12) ») et les colonnes chiffrées ; vide si impossible.

    Retourne le nombre de véhicules non estimés faute de quota (pour le dire à l'utilisateur).
    """
    skipped = 0
    for row in rows:
        row.update(marche="", marche_median=None, marche_bas=None, marche_haut=None, marche_n=None, marche_critere=None)
        for widened, (criterion, params) in enumerate(queries_for(row, market.today)):
            found = market.comparables(params)
            if found is None:
                skipped += 1
                break
            prices_usd, sample = found
            rate = market.usd_to_eur(sample) if sample else market.cache.get("rate", {}).get("value")
            stats = summarize([p * rate for p in prices_usd]) if rate else None
            if stats:
                shown = f"{stats['median']:,} € ({stats['n']})".replace(",", " ")
                row.update(marche=f"{shown}, {criterion}" if widened else shown, marche_median=stats["median"],
                           marche_bas=stats["low"], marche_haut=stats["high"], marche_n=stats["n"], marche_critere=criterion)
                break
    market.save()
    return skipped
