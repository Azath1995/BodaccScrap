"""`bodacc.market` : prix de marché = médiane d'annonces Leboncoin comparables (via Carapis), sans réseau dans les tests."""
import json
from datetime import date

import pytest

from bodacc import market, report
from bodacc.storage import Storage

TODAY = date(2026, 10, 8)


def listing(id_, price_usd):
    # Forme réelle d'une annonce de liste Carapis (8 octobre 2026), réduite aux champs utiles.
    return {"id": id_, "source_code": "leboncoin", "brand_name": "Renault", "model_name": "Clio", "year": 2019,
            "mileage": 80000, "price_usd": price_usd}


DETAIL = {"id": "a1", "price_usd": 13500, "price_original": "11980.00", "price_original_currency": "EUR"}


def fake_api(prices_usd=(10000, 12000, 13500, 15000), status=200):
    calls = []

    def fetch(url, params, key):
        calls.append((url, dict(params)))
        if status != 200:
            return status, {"detail": "erreur"}
        if url.endswith("/vehicles/"):
            return 200, {"count": len(prices_usd), "results": [listing(f"a{i + 1}", p) for i, p in enumerate(prices_usd)]}
        return 200, DETAIL

    fetch.calls = calls
    return fetch


def make(tmp_path, fetch, **kw):
    return market.Market(key="car_test", cache_path=tmp_path / "cache.json", fetch=fetch, sleep=lambda s: None, today=TODAY, **kw)


class TestFindModel:
    @pytest.mark.parametrize("text, expected", [
        ("A vendre : RENAULT CLIO dCi 33220", ("Renault", "Clio")), ("PEUGEOT PARTNER | 300210 km", ("Peugeot", "Partner")),
        ("Ctte Volkswagen Transporter", ("Volkswagen", "Transporter")), ("VW GOLF VII", ("Volkswagen", "Golf")),
        ("A vendre : VEHICULE 07340 ANDANCE", (None, None)), ("TOYOTA COROLLA hybride", ("Toyota", "Corolla")),
        ("CITROEN C4 CACTUS", ("Citroën", "C4 Cactus"))])
    def test_examples(self, text, expected):
        assert market.find_model(text) == expected

    def test_a_model_of_another_brand_is_ignored_when_the_brand_is_known(self):
        assert market.find_model("RENAULT TRAFIC et FORD TRANSIT", "Renault") == ("Renault", "Trafic")
        assert market.find_model("RENAULT MASTER, outillage pour Transit", "Opel") == ("Opel", None)

    def test_numeric_models_need_the_brand(self):
        assert market.find_model("PEUGEOT 208 | 208 000 km", "Peugeot") == ("Peugeot", "208")
        assert market.find_model("lot 208") == (None, None)
        assert market.find_model("TOYOTA C-HR", "Toyota") == ("Toyota", "CHR")


class TestPlausibleYear:
    @pytest.mark.parametrize("year, km, expected", [(2019, 100000, 2019), (2027, None, None), (2025, 238000, None),
                                                    (2010, 238000, 2010), (None, 50000, None)])
    def test_examples(self, year, km, expected):
        assert market.plausible_year(year, km, TODAY) == expected


class TestQueriesFor:
    def test_from_most_precise_to_model_only(self):
        steps = market.queries_for({"titre": "A vendre : RENAULT CLIO", "marque": "Renault", "annee": 2019, "kilometrage": 100000}, TODAY)
        base = {"source": "leboncoin", "brand": "Renault", "model": "Clio", "page_size": 50}
        assert steps == [("année+km", {**base, "min_year": 2017, "max_year": 2021, "min_mileage": 60000, "max_mileage": 140000}),
                         ("année", {**base, "min_year": 2017, "max_year": 2021}), ("modèle seul", base)]

    def test_an_implausible_year_is_dropped(self):
        steps = market.queries_for({"titre": "RENAULT CLIO", "marque": "Renault", "annee": 2025, "kilometrage": 238000}, TODAY)
        assert [c for c, _ in steps] == ["km", "modèle seul"]

    def test_without_a_model_or_for_a_lot_there_is_no_search(self):
        assert market.queries_for({"titre": "A vendre : VEHICULE", "marque": "Renault"}) == []
        assert market.queries_for({"titre": "2 RENAULT CLIO", "marque": "Renault", "nb_vehicules": 2}) == []

    def test_carapis_brand_names_are_used(self):
        assert market.queries_for({"titre": "CITROEN BERLINGO", "marque": "Citroën"})[0][1]["brand"] == "Citroen"
        assert market.queries_for({"titre": "MERCEDES SPRINTER", "marque": "Mercedes"})[0][1]["brand"] == "Mercedes-Benz"


class TestSummarize:
    def test_median_and_quartiles_rounded_to_100(self):
        assert market.summarize([10000, 11000, 12000, 13000, 14000]) == {"median": 12000, "low": 10500, "high": 13500, "n": 5}

    def test_too_few_comparables_gives_nothing(self):
        assert market.summarize([10000, 12000]) is None

    def test_zero_or_missing_prices_are_ignored(self):
        assert market.summarize([0, None, 10000, 11000, 12000])["n"] == 3


class TestMarket:
    def test_a_missing_key_is_explained(self, tmp_path, monkeypatch):
        monkeypatch.setattr(market.env, "get", lambda name: None)
        with pytest.raises(market.MarketError, match=".env"):
            market.Market(cache_path=tmp_path / "c.json")

    def test_prices_are_converted_back_to_euros_with_the_rate_of_one_detail(self, tmp_path):
        rows = [{"titre": "RENAULT CLIO", "marque": "Renault", "annee": 2019}]
        market.annotate(rows, make(tmp_path, fake_api()))
        rate = 11980 / 13500
        expected = market.summarize([p * rate for p in (10000, 12000, 13500, 15000)])
        assert rows[0]["marche_median"] == expected["median"] and rows[0]["marche_n"] == 4
        assert rows[0]["marche"] == f"{expected['median']:,} € (4)".replace(",", " ")

    def test_the_cache_avoids_asking_twice_within_a_week(self, tmp_path):
        fetch = fake_api()
        row = {"titre": "RENAULT CLIO", "marque": "Renault", "annee": 2019}
        market.annotate([dict(row)], make(tmp_path, fetch))
        before = len(fetch.calls)
        market.annotate([dict(row)], make(tmp_path, fetch))
        assert len(fetch.calls) == before == 2                      # une liste + un détail pour le taux, puis rien
        assert json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))["rate"]["date"] == "2026-10-08"

    def test_the_request_limit_is_respected_and_reported(self, tmp_path):
        rows = [{"titre": f"RENAULT CLIO", "marque": "Renault", "annee": y} for y in (2010, 2014, 2018)]
        skipped = market.annotate(rows, make(tmp_path, fake_api(), max_requests=2))
        assert skipped == 2 and rows[0]["marche_n"] == 4 and rows[1]["marche"] == ""

    def test_a_refused_key_stops_with_a_clear_message(self, tmp_path):
        with pytest.raises(market.MarketError, match="401"):
            market.annotate([{"titre": "RENAULT CLIO", "marque": "Renault"}], make(tmp_path, fake_api(status=401)))

    def test_a_vehicle_without_model_or_with_too_few_comparables_stays_blank(self, tmp_path):
        rows = [{"titre": "VEHICULE", "marque": "Renault"}, {"titre": "RENAULT CLIO", "marque": "Renault"}]
        market.annotate(rows, make(tmp_path, fake_api(prices_usd=(10000, 12000))))
        assert rows[0]["marche"] == "" and rows[1]["marche"] == "" and rows[1]["marche_n"] is None

    def test_the_search_is_widened_and_the_criterion_shown(self, tmp_path):
        def fetch(url, params, key):
            if url.endswith("/vehicles/"):
                prices = (10000, 12000) if "min_mileage" in params else (10000, 12000, 13500)
                return 200, {"results": [listing(f"a{i}", p) for i, p in enumerate(prices)]}
            return 200, DETAIL
        rows = [{"titre": "RENAULT CLIO", "marque": "Renault", "annee": 2019, "kilometrage": 80000}]
        market.annotate(rows, make(tmp_path, fetch))
        assert rows[0]["marche_critere"] == "année" and rows[0]["marche"].endswith("(3), année")


class TestReportMarket:
    def test_the_table_gets_a_market_column_and_an_honest_note(self, tmp_path, capsys):
        path = tmp_path / "base.db"
        with Storage(path) as storage:
            storage.upsert_actifs([{"guid": "1", "cabinet": "LGA", "titre": "A vendre : RENAULT CLIO 33220", "type": "Véhicules",
                                    "marque": "Renault", "annee": 2019, "estimation": "8 000,00 €", "lieu": "33220 PINEUILH",
                                    "url_detail": "https://x/1"}], now="2026-10-08T10:00:00+00:00")
        report.main(["--db", str(path), "vehicles", "--market"], market=make(tmp_path, fake_api()))
        out = capsys.readouterr().out
        assert "marché € (n)" in out and "(4)" in out and "Pas la cote La Centrale" in out
