"""Estimation du coût de transport : courbe dégressive calée sur des prix publiés, distances, géocodage en cache, option --destination."""
import json

import pytest

from bodacc import report, transport
from bodacc.storage import Storage
from prospects.search import ProspectError

LIMOGES = (45.8336, 1.2611)
PLACES = {
    "87000 limoges": (45.8336, 1.2611),
    "42130 marcilly-le-châtel": (45.6389, 4.0206),
    "33220 pineuilh": (44.8083, 0.1817),
    "87100 limoges": (45.8, 1.25),
    "97400 saint-denis (la reunion)": (-20.88, 55.45),
}


def fake_fetch(calls=None):
    def fetch(url, params):
        text = params["q"].lower()
        if calls is not None:
            calls.append(text)
        if text == "panne":
            raise ProspectError("api-adresse.data.gouv.fr a répondu HTTP 503.")
        if text not in PLACES:
            return {"features": []}
        lat, lon = PLACES[text]
        return {"features": [{"geometry": {"coordinates": [lon, lat]}, "properties": {"label": text, "score": 0.9}}]}
    return fetch


class TestEstimate:
    @pytest.mark.parametrize("km, low, high", [(0, 90, 130), (100, 100, 150), (200, 170, 250), (300, 260, 400), (500, 380, 560), (1000, 720, 1000)])
    def test_the_anchor_points(self, km, low, high):
        assert transport.estimate(km) == (low, high)

    def test_the_published_prices_fall_inside_the_range(self):
        for km, published in [(420, 355), (300, 380), (775, 735)]:          # Hiflow Lyon-Marseille ; Lyon-Clermont ; Paris-Marseille
            low, high = transport.estimate(km)
            assert low <= published <= high, (km, published, low, high)

    def test_the_price_grows_with_distance_and_the_per_km_price_falls(self):
        kms = [50, 100, 200, 400, 800, 1200]
        highs = [transport.estimate(k)[1] for k in kms]
        assert highs == sorted(highs)
        assert transport.estimate(1200)[1] / 1200 < transport.estimate(100)[1] / 100          # dégressif

    def test_low_never_exceeds_high_and_amounts_are_round(self):
        for km in range(0, 1400, 37):
            low, high = transport.estimate(km)
            assert low <= high and low % 10 == 0 and high % 10 == 0

    def test_beyond_the_last_anchor_the_price_keeps_growing_linearly(self):
        assert transport.estimate(1200) == (860, 1190)


class TestGeocoder:
    def test_a_place_is_asked_once_then_read_from_the_cache_file(self, tmp_path):
        calls, cache = [], tmp_path / "geo.json"
        geo = transport.Geocoder(cache, fake_fetch(calls), sleep=lambda s: None)
        assert geo.locate("87000 Limoges") == pytest.approx(LIMOGES)
        assert geo.locate("87000  LIMOGES") == pytest.approx(LIMOGES)            # espaces et casse : même clé
        assert calls == ["87000 limoges"]
        again = transport.Geocoder(cache, fake_fetch(calls), sleep=lambda s: None)
        assert again.locate("87000 Limoges") == pytest.approx(LIMOGES) and len(calls) == 1
        assert json.loads(cache.read_text(encoding="utf-8"))["87000 limoges"]

    def test_an_unknown_place_is_remembered_but_a_service_failure_is_not(self, tmp_path):
        calls = []
        geo = transport.Geocoder(tmp_path / "geo.json", fake_fetch(calls), sleep=lambda s: None)
        assert geo.locate("nulle part") is None and geo.locate("nulle part") is None and calls == ["nulle part"]
        assert geo.locate("panne") is None and geo.locate("panne") is None and calls.count("panne") == 2    # on réessaiera

    def test_requests_are_spaced(self, tmp_path):
        pauses = []
        geo = transport.Geocoder(tmp_path / "g.json", fake_fetch(), sleep=pauses.append, pause=0.25)
        geo.locate("87000 Limoges")
        geo.locate("33220 Pineuilh")
        assert pauses == [0.25]                                                   # rien avant la première requête

    def test_a_corrupt_cache_file_is_ignored(self, tmp_path):
        cache = tmp_path / "g.json"
        cache.write_text("{pas du json", encoding="utf-8")
        assert transport.Geocoder(cache, fake_fetch(), sleep=lambda s: None).locate("87000 Limoges")


class TestAnnotate:
    def geo(self, tmp_path):
        return transport.Geocoder(tmp_path / "g.json", fake_fetch(), sleep=lambda s: None)

    def test_adds_distance_and_range(self, tmp_path):
        (row,) = transport.annotate([{"lieu": "33220 PINEUILH"}], "87000 Limoges", self.geo(tmp_path))
        assert 150 < row["km_route"] < 250 and row["transport_min"] < row["transport_max"]        # environ 140 km à vol d'oiseau x 1,3
        assert row["transport"] == f"{row['transport_min']}-{row['transport_max']} €"

    def test_unknown_missing_and_overseas_places_get_no_estimate(self, tmp_path):
        rows = transport.annotate([{"lieu": "99999 NULLE PART"}, {"lieu": None}, {"lieu": "97400 SAINT-DENIS (LA REUNION)"}],
                                  "87000 Limoges", self.geo(tmp_path))
        assert all(r["transport"] == "" and r["km_route"] is None for r in rows)

    def test_an_unknown_destination_is_explained(self, tmp_path):
        with pytest.raises(transport.TransportError, match="Destination introuvable"):
            transport.annotate([{"lieu": "33220 PINEUILH"}], "Atlantide", self.geo(tmp_path))

    def test_the_destination_is_geocoded_once_for_all_vehicles(self, tmp_path):
        calls = []
        geo = transport.Geocoder(tmp_path / "g.json", fake_fetch(calls), sleep=lambda s: None)
        transport.annotate([{"lieu": "33220 PINEUILH"}, {"lieu": "33220 PINEUILH"}], "87000 Limoges", geo)
        assert calls.count("87000 limoges") == 1 and calls.count("33220 pineuilh") == 1


class TestReportDestination:
    @pytest.fixture
    def path(self, tmp_path):
        target = tmp_path / "base.db"
        with Storage(target) as storage:
            storage.upsert_actifs([
                {"guid": "1", "cabinet": "LGA", "titre": "A vendre : RENAULT KANGOO", "type": "Véhicules", "marque": "Renault", "lieu": "33220 PINEUILH",
                 "estimation": "1 000,00 €", "url_detail": "https://x/1"},
                {"guid": "2", "cabinet": "LGA", "titre": "A vendre : FORD FIESTA", "type": "Véhicules", "marque": "Ford", "lieu": "99999 NULLE PART",
                 "estimation": "2 000,00 €", "url_detail": "https://x/2"},
            ], now="2026-09-01T10:00:00+00:00")
        return target

    def geo(self, tmp_path):
        return transport.Geocoder(tmp_path / "g.json", fake_fetch(), sleep=lambda s: None)

    def test_the_table_gets_distance_and_transport_columns_and_a_disclaimer(self, path, tmp_path, capsys):
        report.main(["--db", str(path), "vehicles", "--destination", "87000 Limoges"], geocoder=self.geo(tmp_path))
        out = capsys.readouterr().out
        assert "km route" in out and "transport €" in out and " €" in out
        assert "pas un devis" in out and "Transport vers 87000 Limoges" in out

    def test_without_the_option_nothing_changes_and_nothing_is_geocoded(self, path, capsys):
        report.main(["--db", str(path), "vehicles"], geocoder=None)
        assert "km route" not in capsys.readouterr().out

    def test_csv_and_xlsx_have_numeric_transport_columns(self, path, tmp_path):
        import csv
        from openpyxl import load_workbook
        csv_path, xlsx_path = tmp_path / "v.csv", tmp_path / "v.xlsx"
        report.main(["--db", str(path), "vehicles", "--destination", "87000 Limoges", "--csv", str(csv_path), "--xlsx", str(xlsx_path)],
                    geocoder=self.geo(tmp_path))
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            rows = {r["marque"]: r for r in csv.DictReader(f)}
        assert int(rows["Renault"]["km_route"]) > 0 and int(rows["Renault"]["transport_min"]) < int(rows["Renault"]["transport_max"])
        assert rows["Ford"]["transport_min"] == ""                                # lieu introuvable : vide, pas 0
        sheet = load_workbook(xlsx_path).active
        headers = [c.value for c in sheet[1]]
        assert {"km route", "transport min €", "transport max €"} <= set(headers)

    def test_an_unknown_destination_stops_with_a_clear_message(self, path, tmp_path):
        with pytest.raises(SystemExit, match="Destination introuvable"):
            report.main(["--db", str(path), "vehicles", "--destination", "Atlantide"], geocoder=self.geo(tmp_path))
