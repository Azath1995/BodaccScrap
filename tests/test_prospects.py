import csv

import pytest

from prospects import search
from prospects.search import (
    NEAR_URL, GEOCODER_URL, ProspectError, distance_km, find_companies, geocode, tranche_codes, vehicle_place,
)
from bodacc.storage import Storage

LAT, LON = 44.83, 0.23        # près de Pineuilh


def etab(lat=44.85, lon=0.24, etat="A", **extra):
    return {"adresse": "1 RUE DU TEST 33220 PINEUILH", "code_postal": "33220", "libelle_commune": "PINEUILH",
            "latitude": lat, "longitude": lon, "etat_administratif": etat, **extra}


def unit(siren="111111111", nom="MACONNERIE TEST", tranche="03", nature="5710", etats=None, **extra):
    return {"siren": siren, "nom_complet": nom, "activite_principale": "43.99C", "nature_juridique": nature,
            "tranche_effectif_salarie": tranche, "annee_tranche_effectif_salarie": "2023",
            "date_creation": "2015-01-01", "etat_administratif": "A", "statut_diffusion": "O",
            "nombre_etablissements_ouverts": 1, "matching_etablissements": etats if etats is not None else [etab()],
            # Ce que l'API renverrait par défaut, et que nous ne devons jamais reprendre :
            "dirigeants": [{"nom": "DUPONT", "prenoms": "JEAN", "annee_de_naissance": "1970"}],
            **extra}


def api(*pages, total=None):
    """Fausse API : renvoie la page demandée ; mémorise les paramètres reçus."""
    calls = []

    def fetch(url, params):
        calls.append((url, dict(params)))
        if url == GEOCODER_URL:
            return {"features": [{"geometry": {"coordinates": [LON, LAT]},
                                  "properties": {"label": "Pineuilh", "score": 0.94}}]}
        page = params["page"]
        return {"results": pages[page - 1], "total_results": total or sum(len(p) for p in pages),
                "page": page, "per_page": 25, "total_pages": len(pages)}

    fetch.calls = calls
    return fetch


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(search.time, "sleep", lambda s: None)


class TestTrancheCodes:
    def test_range_keeps_every_band_that_overlaps(self):
        assert tranche_codes(3, 19) == {"02", "03", "11"}        # 3-5, 6-9, 10-19

    def test_single_band(self):
        assert tranche_codes(1, 2) == {"01"}

    def test_open_ended(self):
        assert tranche_codes(50, None) == {"21", "22", "31", "32", "41", "42", "51", "52", "53"}

    def test_zero_includes_the_employer_less_bands(self):
        assert {"NN", "00"} <= tranche_codes(0, 2)
        assert not {"NN", "00"} & tranche_codes(1, 2)

    def test_no_bounds_means_every_band(self):
        assert tranche_codes() == set(search.TRANCHES)


class TestGeo:
    def test_distance(self):
        assert distance_km(48.8566, 2.3522, 45.7640, 4.8357) == pytest.approx(392, abs=5)   # Paris - Lyon
        assert distance_km(LAT, LON, LAT, LON) == 0

    def test_geocode_reads_longitude_first(self):
        place = geocode("33220 Pineuilh", api())
        assert (place["lat"], place["lon"]) == (LAT, LON)

    def test_unknown_place(self):
        with pytest.raises(ProspectError):
            geocode("zzzz", lambda url, params: {"features": []})


class TestFindCompanies:
    def rows(self, *units, **kwargs):
        return find_companies(LAT, LON, pause=0, fetch=api(list(units)), **kwargs)["rows"]

    def test_keeps_only_active_publicly_listed_companies(self):
        rows = self.rows(unit("1"), unit("2", etat_administratif="C"), unit("3", statut_diffusion="P"))
        assert [r["siren"] for r in rows] == ["1"]

    def test_sole_traders_are_excluded(self):
        rows = self.rows(unit("1", nature="1000"), unit("2", nature="5710"))
        assert [r["siren"] for r in rows] == ["2"]

    def test_headcount_filter_uses_the_band_and_drops_unknown_bands(self):
        units = [unit("small", tranche="02"), unit("big", tranche="21"), unit("unknown", tranche=None), unit("none", tranche="NN")]
        assert [r["siren"] for r in self.rows(*units, min_employees=3, max_employees=19)] == ["small"]

    def test_without_a_headcount_filter_unknown_bands_are_kept(self):
        rows = self.rows(unit("unknown", tranche=None))
        assert rows[0]["effectif"] == "inconnu"

    def test_uses_the_nearest_open_establishment_and_sorts_by_distance(self):
        far = unit("far", etats=[etab(lat=45.10, lon=0.50)])
        near = unit("near", etats=[etab(lat=45.10, lon=0.50), etab(lat=44.831, lon=0.231, adresse="PRES DU POINT")])
        rows = self.rows(far, near)
        assert [r["siren"] for r in rows] == ["near", "far"]
        assert rows[0]["adresse"] == "PRES DU POINT" and rows[0]["distance_km"] < rows[1]["distance_km"]

    def test_closed_or_unlocated_establishments_are_ignored(self):
        assert self.rows(unit("1", etats=[etab(etat="F")]), unit("2", etats=[etab(lat=None)]), unit("3", etats=[])) == []

    def test_partially_disclosed_establishment_is_ignored(self):
        assert self.rows(unit("1", etats=[etab(statut_diffusion_etablissement="P")])) == []

    def test_row_content_and_link(self):
        row = self.rows(unit("333333333", nom="CAP SUD"))[0]
        assert row["nom"] == "CAP SUD" and row["effectif"] == "6 à 9 salariés" and row["annee_effectif"] == "2023"
        assert row["lien"] == "https://annuaire-entreprises.data.gouv.fr/entreprise/333333333"

    def test_directors_are_never_requested_nor_kept(self):
        fetch = api([unit("1")])
        rows = find_companies(LAT, LON, pause=0, fetch=fetch)["rows"]
        params = fetch.calls[0][1]
        assert params["minimal"] == "true" and params["include"] == "matching_etablissements"
        assert "dirigeants" not in params["include"]
        assert "dirigeants" not in rows[0] and "DUPONT" not in str(rows)

    def test_reads_every_page_until_the_last(self):
        fetch = api([unit("1")], [unit("2")], [unit("3")])
        result = find_companies(LAT, LON, pause=0, fetch=fetch)
        assert sorted(r["siren"] for r in result["rows"]) == ["1", "2", "3"]
        assert result["pages_read"] == 3 and not result["truncated"]

    def test_max_pages_bounds_the_requests_and_says_so(self):
        fetch = api([unit("1")], [unit("2")], [unit("3")])
        result = find_companies(LAT, LON, pause=0, max_pages=2, fetch=fetch)
        assert len(fetch.calls) == 2 and result["truncated"] and result["pages_read"] == 2

    def test_naf_codes_replace_the_section(self):
        fetch = api([unit("1")])
        find_companies(LAT, LON, pause=0, naf=["43.22A", "43.21A"], fetch=fetch)
        params = fetch.calls[0][1]
        assert params["activite_principale"] == "43.22A,43.21A" and "section_activite_principale" not in params

    def test_default_section_is_construction(self):
        fetch = api([unit("1")])
        find_companies(LAT, LON, pause=0, fetch=fetch)
        assert fetch.calls[0][1]["section_activite_principale"] == "F"
        assert fetch.calls[0][0] == NEAR_URL


class TestVehiclePlace:
    def db(self, tmp_path, *rows):
        path = tmp_path / "t.db"
        with Storage(path) as s:
            s.upsert_actifs(list(rows))
        return path

    def test_finds_the_place_whatever_the_plate_formatting(self, tmp_path):
        path = self.db(tmp_path, {"guid": "1", "immatriculation": "AB-456-EF", "lieu": "33220 PINEUILH"})
        assert vehicle_place("ab 456 ef", path) == "33220 PINEUILH"

    def test_unknown_plate(self, tmp_path):
        with pytest.raises(ProspectError):
            vehicle_place("AA-111-AA", self.db(tmp_path, {"guid": "1", "immatriculation": "AB-456-EF", "lieu": "X"}))

    def test_ambiguous_place(self, tmp_path):
        path = self.db(tmp_path, {"guid": "1", "immatriculation": "AB-456-EF", "lieu": "A"},
                       {"guid": "2", "immatriculation": "AB-456-EF", "lieu": "B"})
        with pytest.raises(ProspectError):
            vehicle_place("AB-456-EF", path)


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload


class TestGetJson:
    def test_retries_after_a_rate_limit_then_succeeds(self, monkeypatch):
        answers = iter([FakeResponse(429), FakeResponse(200, {"ok": True})])
        monkeypatch.setattr(search.requests, "get", lambda *a, **k: next(answers))
        assert search.get_json("https://x.example/a", {}) == {"ok": True}

    def test_gives_up_with_a_clear_message(self, monkeypatch):
        monkeypatch.setattr(search.requests, "get", lambda *a, **k: FakeResponse(500))
        with pytest.raises(ProspectError, match="HTTP 500"):
            search.get_json("https://x.example/a", {})

    def test_network_failure_becomes_a_prospect_error(self, monkeypatch):
        def boom(*a, **k):
            raise search.requests.exceptions.ConnectionError("no network")
        monkeypatch.setattr(search.requests, "get", boom)
        with pytest.raises(ProspectError, match="Connexion impossible"):
            search.get_json("https://x.example/a", {})


class TestCommandLine:
    def run(self, *args, fetch=None):
        return search.main(list(args), fetch=fetch or api(
            [unit("111111111", nom="ARTISAN A"), unit("222222222", nom="ARTISAN B", tranche="21")]))

    def test_table_with_links_and_reminders(self, capsys):
        self.run("--near", "33220 Pineuilh", "--min-effectif", "3", "--max-effectif", "19")
        out = capsys.readouterr().out
        assert "Lieu : Pineuilh" in out and "ARTISAN A" in out and "ARTISAN B" not in out
        assert "https://annuaire-entreprises.data.gouv.fr/entreprise/111111111" in out
        assert "1 entreprise(s) dans un rayon de 15 km" in out
        assert "aucune coordonnée de contact" in out and "CNIL" in out

    def test_csv_export_has_no_personal_columns(self, tmp_path, capsys):
        out = tmp_path / "p.csv"
        self.run("--near", "33220 Pineuilh", "--csv", str(out))
        with open(out, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert [r["nom"] for r in rows] == ["ARTISAN A", "ARTISAN B"]
        assert reader.fieldnames == search.CSV_COLUMNS
        assert not any(name in "".join(reader.fieldnames) for name in ("dirigeant", "mail", "tel"))
        assert "DUPONT" not in out.read_text(encoding="utf-8-sig")

    def test_vehicle_option_reads_its_place_from_the_database(self, tmp_path, capsys):
        db = tmp_path / "t.db"
        with Storage(db) as s:
            s.upsert_actifs([{"guid": "1", "immatriculation": "AB-456-EF", "lieu": "33220 PINEUILH"}])
        self.run("--vehicule", "AB-456-EF", "--db", str(db))
        assert "demandé : 33220 PINEUILH" in capsys.readouterr().out

    def test_unknown_place_exits_with_a_message(self):
        with pytest.raises(SystemExit, match="introuvable"):
            self.run("--near", "zzz", fetch=lambda url, params: {"features": []})

    def test_radius_above_the_api_limit_is_rejected(self):
        with pytest.raises(SystemExit):
            self.run("--near", "x", "--radius", "80")

    def test_a_place_is_required(self):
        with pytest.raises(SystemExit):
            search.main([])

    def test_truncation_is_reported(self, capsys):
        fetch = api([unit("1")], [unit("2")], [unit("3")])
        search.main(["--near", "x", "--max-pages", "1"], fetch=fetch)
        assert "recherche limitée" in capsys.readouterr().out
