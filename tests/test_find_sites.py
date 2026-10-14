import csv

import pytest

from prospects import find_sites as fs
from prospects.search import ProspectError

LAT, LON = 44.85, 0.48          # Bergerac


def shop(name, dlat=0.0, dlon=0.0, site="https://example.fr", **tags):
    return {"type": "node", "lat": LAT + dlat, "lon": LON + dlon, "tags": {"shop": "car", "name": name, "website": site, **tags}}


def company(nom, adresse="1 RUE X 24100 BERGERAC", commune="BERGERAC", siren="1"):
    return {"nom": nom, "siren": siren, "adresse": adresse, "commune": commune}


def geo(score=0.95):
    return lambda text: {"lat": LAT, "lon": LON, "label": text, "score": score}


def run(companies, elements, score=0.95):
    rows, _ = fs.find_sites(companies, fetch_shops=lambda q: {"elements": elements}, geo=geo(score), pause=0)
    return {r["nom"]: r for r in rows}


class TestTokens:
    def test_drops_legal_forms_accents_and_generic_words(self):
        assert fs.tokens("SARL Garage Étoile Automobiles") == ["etoile"]

    def test_keeps_trade_names_in_parentheses(self):
        assert fs.tokens("MAGOT CAVARD SAS (EDENAUTO)") == ["magot", "cavard", "edenauto"]


class TestNameScore:
    def test_matches_osm_name_brand_or_website_host(self):
        s = {"tags": {"name": "Concession", "brand": "Faurie"}, "site": "https://x.fr"}
        assert fs.name_score("FAURIE AUTO", s) == 1
        s = {"tags": {"name": "Concession"}, "site": "https://www.jsdautomobiles.com/"}
        assert fs.name_score("JSD AUTOMOBILES", s) == 1

    def test_the_town_name_is_not_distinctive(self):
        s = {"tags": {"name": "Pare-brise Montpon"}, "site": "https://rapidparebrise-montpon.fr"}
        assert fs.name_score("MONTPON AUTOMOBILES", s, commune="MONTPON-MENESTEROL") == 0

    def test_partial_match(self):
        s = {"tags": {"name": "Magot"}, "site": "https://x.fr"}
        assert fs.name_score("MAGOT CAVARD", s) == 0.5


class TestMatch:
    def test_similar_name_nearby_is_found(self):
        rows = run([company("GARAGE DUPONT")], [shop("Dupont Automobiles", dlat=0.01, site="https://dupont.fr")])
        assert rows["GARAGE DUPONT"]["statut"] == "trouve (osm)" and rows["GARAGE DUPONT"]["site"] == "https://dupont.fr"

    def test_similar_name_too_far_is_ignored(self):
        assert run([company("GARAGE DUPONT")], [shop("Dupont", dlat=0.05)])["GARAGE DUPONT"]["statut"] == "non trouve"

    def test_same_address_other_name_is_flagged_not_trusted(self):
        r = run([company("SOCIETE ALPHA")], [shop("Enseigne Beta", dlat=0.0005)])["SOCIETE ALPHA"]
        assert r["statut"] == "a verifier (osm)" and "nom différent" in r["commentaire"]

    def test_same_address_is_ignored_when_the_geocoding_is_poor(self):
        assert run([company("ALPHA")], [shop("Beta")], score=0.4)["ALPHA"]["statut"] == "non trouve"

    def test_other_name_at_a_distance_is_ignored(self):
        assert run([company("ALPHA")], [shop("Beta", dlat=0.005)])["ALPHA"]["statut"] == "non trouve"

    def test_best_name_wins_over_a_closer_shop(self):
        rows = run([company("DUPONT MARTIN")],
                   [shop("Dupont", dlat=0.001, site="https://a.fr"), shop("Dupont Martin", dlat=0.01, site="https://b.fr")])
        assert rows["DUPONT MARTIN"]["site"] == "https://b.fr"

    def test_website_without_scheme_gets_https(self):
        rows = run([company("DUPONT")], [shop("Dupont", site="dupont.fr")])
        assert rows["DUPONT"]["site"] == "https://dupont.fr"

    def test_contact_website_tag_is_used(self):
        el = shop("Dupont")
        el["tags"].pop("website")
        el["tags"]["contact:website"] = "https://dupont.fr"
        assert run([company("DUPONT")], [el])["DUPONT"]["site"] == "https://dupont.fr"

    def test_shops_without_position_or_site_are_skipped(self):
        assert fs.shops_from({"elements": [{"tags": {"name": "X", "website": "https://x.fr"}},
                                           {"lat": 1, "lon": 1, "tags": {"name": "Y"}},
                                           {"center": {"lat": 1, "lon": 2}, "tags": {"website": "https://z.fr"}}]}) == [
            {"lat": 1, "lon": 2, "site": "https://z.fr", "tags": {"website": "https://z.fr"}}]


class TestSharedGuesses:
    def test_one_shop_proposed_to_two_companies_is_dropped(self):
        rows = run([company("ALPHA", siren="1"), company("GAMMA", siren="2")], [shop("Beta", dlat=0.0005)])
        assert {r["statut"] for r in rows.values()} == {"non trouve"} and not any(r["site"] for r in rows.values())

    def test_a_guess_on_a_shop_already_attributed_is_dropped(self):
        rows = run([company("DUPONT"), company("AUTRE")], [shop("Dupont", dlat=0.0005)])
        assert rows["DUPONT"]["statut"] == "trouve (osm)" and rows["AUTRE"]["statut"] == "non trouve"


class TestFindSites:
    def test_unlocated_address_is_reported(self):
        def nowhere(text):
            raise ProspectError("introuvable")
        rows, _ = fs.find_sites([company("X")], fetch_shops=lambda q: pytest.fail("aucune zone à interroger"),
                                geo=nowhere, pause=0)
        assert rows[0]["statut"] == "non trouve" and rows[0]["commentaire"] == "adresse non localisée"

    def test_one_overpass_request_covers_all_companies(self):
        queries = []

        def fetch(q):
            queries.append(q)
            return {"elements": []}
        places = iter([{"lat": 44.0, "lon": 0.0, "score": 1}, {"lat": 45.0, "lon": 1.0, "score": 1}])
        fs.find_sites([company("A"), company("B")], fetch_shops=fetch, geo=lambda t: next(places), pause=0)
        assert len(queries) == 1 and "car_rental" in queries[0] and "contact:website" in queries[0]

    def test_overpass_failure_is_reported(self, monkeypatch, tmp_path):
        src = tmp_path / "in.csv"
        src.write_text("nom,siren,adresse,commune\nA,1,1 RUE X 24100 BERGERAC,BERGERAC\n", encoding="utf-8")

        def down(q):
            raise ProspectError("Overpass a répondu HTTP 500.")
        with pytest.raises(SystemExit, match="HTTP 500"):
            fs.main(["--input", str(src), "--csv", str(tmp_path / "o.csv")], fetch_shops=down, geo=geo())


class TestCommandLine:
    @pytest.fixture
    def source(self, tmp_path):
        path = tmp_path / "prospects.csv"
        path.write_text("nom,siren,adresse,commune\nDUPONT,1,1 RUE X 24100 BERGERAC,BERGERAC\n"
                        "INCONNU,2,2 RUE Y 24100 BERGERAC,BERGERAC\n", encoding="utf-8")
        return path

    def test_writes_a_file_readable_by_vehicle_types(self, source, tmp_path, capsys):
        from prospects import vehicle_types
        out = tmp_path / "sites.csv"
        fs.main(["--input", str(source), "--csv", str(out), "--pause", "0"],
                fetch_shops=lambda q: {"elements": [shop("Dupont", site="https://dupont.fr")]}, geo=geo())
        with open(out, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert reader.fieldnames == fs.COLUMNS
        assert [(r["nom"], r["site"]) for r in rows] == [("DUPONT", "https://dupont.fr"), ("INCONNU", "")]
        assert vehicle_types.read_sites_csv(out)[0]["site"] == "https://dupont.fr"
        text = capsys.readouterr().out
        assert "1 site(s) sur 2" in text and "ne prouve pas" in text

    def test_semicolon_files_are_accepted(self, tmp_path):
        path = tmp_path / "p.csv"
        path.write_text("nom;siren;adresse;commune\nA;1;1 RUE X;BERGERAC\n", encoding="utf-8")
        assert fs.read_companies(path)[0]["adresse"] == "1 RUE X"

    def test_a_file_not_from_prospects_is_rejected(self, tmp_path):
        path = tmp_path / "p.csv"
        path.write_text("nom,site\nA,https://a.fr\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="adresse"):
            fs.read_companies(path)
