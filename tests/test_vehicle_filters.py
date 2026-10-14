import csv

import pytest

from bodacc import report
from bodacc.storage import Storage
from bodacc.vehicle_filters import filter_vehicles, parse_price, sort_vehicles


def car(guid, prix=None, km=None, annee=None, marque="Renault", cabinet="LGA",
        lieu="33220 PINEUILH", carburant=None):
    return {"guid": guid, "type": "Véhicules > Autres", "titre": f"A vendre : {guid}",
            "url_detail": f"https://site.example/{guid}",
            "marque": marque, "annee": annee, "kilometrage": km, "cabinet": cabinet, "lieu": lieu,
            "carburant": carburant, "first_seen": "2026-09-18T10:00:00+00:00",
            "estimation": f"{prix:,.2f} €".replace(",", " ").replace(".", ",") if prix is not None else "Non renseigné"}


def guids(rows):
    return [r["guid"] for r in rows]


class TestParsePrice:
    @pytest.mark.parametrize("text, expected", [
        ("18 000,00 €", 18000.0), ("3 500,00 €", 3500.0), ("2 000 €", 2000.0), ("999 €", 999.0),
        ("1 200,5 €", 1200.5), ("1.200,00 €", 1200.0), ("20 000,00 €", 20000.0),
    ])
    def test_formats(self, text, expected):
        assert parse_price(text) == expected

    @pytest.mark.parametrize("text", ["Non renseigné", "", None, "à débattre"])
    def test_no_price_gives_none(self, text):
        assert parse_price(text) is None


class TestFilterVehicles:
    # La requête demandée : prix <= 20 000 et km <= 50 000.
    CARS = [
        car("A", prix=10500, km=35814), car("B", prix=14000, km=11177), car("C", prix=16000, km=30126),
        car("too-dear", prix=25000, km=10000), car("too-many-km", prix=5000, km=80000),
        car("price-unknown", km=20000), car("km-unknown", prix=8000),
    ]

    def test_price_and_mileage_together(self):
        assert guids(filter_vehicles(self.CARS, max_price=20000, max_km=50000)) == ["A", "B", "C"]

    def test_unknown_values_are_excluded_by_default(self):
        kept = guids(filter_vehicles(self.CARS, max_price=20000, max_km=50000))
        assert "price-unknown" not in kept and "km-unknown" not in kept

    def test_keep_unknown_brings_them_back(self):
        kept = guids(filter_vehicles(self.CARS, max_price=20000, max_km=50000, keep_unknown=True))
        assert kept == ["A", "B", "C", "price-unknown", "km-unknown"]

    def test_bounds_are_inclusive(self):
        rows = [car("on-the-limit", km=50000), car("just-over", km=50001)]
        assert guids(filter_vehicles(rows, max_km=50000)) == ["on-the-limit"]
        assert guids(filter_vehicles(rows, min_km=50001)) == ["just-over"]

    def test_year_range(self):
        rows = [car("old", annee=2005), car("mid", annee=2015), car("new", annee=2022)]
        assert guids(filter_vehicles(rows, min_year=2010)) == ["mid", "new"]
        assert guids(filter_vehicles(rows, max_year=2015)) == ["old", "mid"]
        assert guids(filter_vehicles(rows, min_year=2010, max_year=2020)) == ["mid"]

    def test_price_range(self):
        rows = [car("cheap", prix=900), car("mid", prix=5000), car("dear", prix=30000)]
        assert guids(filter_vehicles(rows, min_price=1000, max_price=10000)) == ["mid"]

    def test_no_criteria_keeps_everything_including_unknowns(self):
        assert guids(filter_vehicles(self.CARS)) == guids(self.CARS)

    def test_text_filters_ignore_case_and_accents(self):
        rows = [car("lga", cabinet="LGA", lieu="33220 PINEUILH"),
                car("haz", cabinet="Denis Hazane", lieu="60150 MÉLICOCQ", carburant="électrique")]
        assert guids(filter_vehicles(rows, cabinet="lga")) == ["lga"]
        assert guids(filter_vehicles(rows, lieu="pineuilh")) == ["lga"]
        assert guids(filter_vehicles(rows, lieu="33220")) == ["lga"]
        assert guids(filter_vehicles(rows, lieu="melicocq")) == ["haz"]
        assert guids(filter_vehicles(rows, carburant="electrique")) == ["haz"]

    def test_unknown_fuel_is_excluded_unless_keep_unknown(self):
        rows = [car("diesel", carburant="diesel"), car("unknown"), car("petrol", carburant="essence")]
        assert guids(filter_vehicles(rows, carburant="diesel")) == ["diesel"]
        assert guids(filter_vehicles(rows, carburant="diesel", keep_unknown=True)) == ["diesel", "unknown"]

    def test_rows_get_a_numeric_price_and_the_originals_are_untouched(self):
        original = car("A", prix=10500)
        kept = filter_vehicles([original], max_price=20000)
        assert kept[0]["prix"] == 10500.0 and "prix" not in original


class TestSortVehicles:
    def priced(self, *rows):
        return filter_vehicles(rows)          # ajoute la clé « prix »

    def test_price_cheapest_first_unknown_last(self):
        rows = self.priced(car("none"), car("dear", prix=18000), car("cheap", prix=900))
        assert guids(sort_vehicles(rows, "price")) == ["cheap", "dear", "none"]

    def test_km_ascending_unknown_last(self):
        rows = self.priced(car("none"), car("high", km=200000), car("low", km=20000))
        assert guids(sort_vehicles(rows, "km")) == ["low", "high", "none"]

    def test_year_newest_first_unknown_last(self):
        rows = self.priced(car("none"), car("old", annee=2005), car("new", annee=2022))
        assert guids(sort_vehicles(rows, "year")) == ["new", "old", "none"]

    def test_recent_keeps_the_incoming_order(self):
        rows = self.priced(car("b"), car("a"), car("c"))
        assert guids(sort_vehicles(rows, "recent")) == ["b", "a", "c"]

    def test_several_keys_km_then_estimation_then_cote(self):
        rows = self.priced(car("c", km=50000, prix=9000), car("a", km=50000, prix=8000), car("x", km=10000, prix=20000),
                           car("b", km=50000, prix=8000), car("none"))
        rows[1]["cote"], rows[3]["cote"] = 15000, 12000
        assert guids(sort_vehicles(rows, "km,estimation,cote")) == ["x", "b", "a", "c", "none"]


class TestCommandLine:
    @pytest.fixture
    def db_path(self, tmp_path):
        path = tmp_path / "t.db"
        with Storage(path) as s:
            s.upsert_actifs(TestFilterVehicles.CARS)
        return path

    def run(self, db_path, *args):
        report.main(["--db", str(db_path), "vehicles", *args])

    def test_the_requested_query(self, db_path, capsys):
        self.run(db_path, "--max-price", "20000", "--max-km", "50000")
        out = capsys.readouterr().out
        assert "3 véhicule(s)" in out
        assert "2 autre(s) véhicule(s) écarté(s) car une valeur est inconnue" in out
        assert "--include-unknown" in out

    def test_include_unknown_flag_keeps_them_and_drops_the_hint(self, db_path, capsys):
        self.run(db_path, "--max-price", "20000", "--max-km", "50000", "--include-unknown")
        out = capsys.readouterr().out
        assert "5 véhicule(s)" in out and "écarté" not in out

    def test_no_hint_when_nothing_was_hidden_by_an_unknown(self, db_path, capsys):
        self.run(db_path)
        assert "écarté" not in capsys.readouterr().out

    def test_sort_km_orders_the_table(self, db_path, capsys):
        self.run(db_path, "--sort", "km", "--max-km", "50000")
        out = capsys.readouterr().out
        assert out.index("11 177") < out.index("30 126") < out.index("35 814")

    def test_text_options(self, db_path, capsys):
        self.run(db_path, "--cabinet", "lga", "--lieu", "33220", "--marque", "renault")
        assert "7 véhicule(s)" in capsys.readouterr().out

    def test_csv_export_respects_filters_and_has_a_numeric_price(self, db_path, tmp_path):
        out = tmp_path / "o.csv"
        self.run(db_path, "--max-price", "12000", "--max-km", "50000", "--csv", str(out))

        with open(out, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        assert [r["kilometrage"] for r in rows] == ["35814"] and rows[0]["estimation"] == "10500" and "prix" not in rows[0]

    def test_each_vehicle_is_followed_by_its_full_link(self, db_path, capsys):
        self.run(db_path, "--max-km", "50000")
        lines = capsys.readouterr().out.splitlines()

        for km, guid in [("35 814", "A"), ("11 177", "B"), ("30 126", "C")]:
            row = next(i for i, line in enumerate(lines) if km in line)
            assert lines[row + 1].strip() == f"https://site.example/{guid}"

    def test_no_links_flag_gives_the_compact_table(self, db_path, capsys):
        self.run(db_path, "--max-km", "50000", "--no-links")
        assert "https://" not in capsys.readouterr().out

    def test_csv_has_the_link_column(self, db_path, tmp_path):
        out = tmp_path / "o.csv"
        self.run(db_path, "--max-price", "20000", "--max-km", "50000", "--csv", str(out))
        with open(out, encoding="utf-8-sig", newline="") as f:
            assert {r["url_detail"] for r in csv.DictReader(f)} == {
                "https://site.example/A", "https://site.example/B", "https://site.example/C"}

    def test_unknown_sort_is_rejected(self, db_path):
        with pytest.raises(SystemExit):
            self.run(db_path, "--sort", "banana")
