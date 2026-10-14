import csv

import pytest

from prospects import vehicle_types as vt

PAD = "<p>" + "texte neutre sans rapport " * 40 + "</p>"      # rend la page assez longue (> 500 caractères)


def page(body):
    return f"<html><body>{body}{PAD}</body></html>"


def network(pages, robots=None):
    """Faux réseau : {url: html}. Retourne une fonction get(url) -> (code, url, html) qui mémorise les appels."""
    calls = []

    def get(url):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return (200, url, robots) if robots is not None else (404, url, "")
        return (200, url, pages[url]) if url in pages else (404, url, "")

    get.calls = calls
    return get


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(vt.time, "sleep", lambda s: None)


class TestClassify:
    def hits(self, text):
        return vt.classify(text)["hits"]

    def test_ignores_case_and_accents(self):
        assert self.hits("Nos UTILITAIRES et FOURGONS d'occasion")["utilitaires"] == 2
        assert self.hits("Voitures ÉLECTRIQUES et hybrides")["electriques"] == 2

    def test_models_only_count_with_their_brand(self):
        assert self.hits("Renault Trafic, Ford Transit et Peugeot Partner")["utilitaires"] == 3
        assert self.hits("trafic routier, master en droit, expert-comptable, partner")["utilitaires"] == 0

    def test_city_car_models_and_the_word_itself(self):
        assert self.hits("Une citadine : Renault Clio, Toyota Aygo, Fiat 500")["citadines"] == 4

    def test_one_repeated_term_is_capped(self):
        assert self.hits("utilitaire " * 30)["utilitaires"] == vt.TERM_CAP

    def test_everyday_words_are_not_vehicle_types(self):
        h = self.hits("Une entreprise familiale, porteur de projet, esprit d'équipe")
        assert h["berlines"] == 0 and h["poids_lourds"] == 0

    def test_a_van_is_not_a_truck_but_a_truck_is(self):
        assert self.hits("camionnette")["poids_lourds"] == 0 and self.hits("camionnette")["utilitaires"] == 1
        assert self.hits("camions et poids lourds")["poids_lourds"] == 2

    def test_camper_spellings(self):
        assert self.hits("camping-car, camping car, caravane, van aménagé")["camping_cars"] == 4

    def test_family_car_and_estate(self):
        assert self.hits("berline, break, monospace, voiture familiale")["berlines"] == 4

    def test_evidence_lists_the_most_frequent_terms(self):
        evidence = vt.classify("fourgon fourgon fourgon utilitaire")["evidence"]["utilitaires"]
        assert evidence[0] == "fourgon" and "utilitaire" in evidence

    def test_empty_text(self):
        assert sum(self.hits("").values()) == 0


class TestMainTypes:
    def test_keeps_types_with_enough_mentions_and_share(self):
        hits = {c: 0 for c in vt.CATEGORIES} | {"utilitaires": 20, "berlines": 8, "citadines": 2, "suv_4x4": 1}
        assert vt.main_types(hits) == ["utilitaires", "berlines"]           # citadines < 3, suv < 3

    def test_a_marginal_type_is_dropped_even_with_three_mentions(self):
        hits = {c: 0 for c in vt.CATEGORIES} | {"utilitaires": 40, "citadines": 3}
        assert vt.main_types(hits) == ["utilitaires"]                       # 3/43 < 20 %

    def test_no_mention_no_type(self):
        assert vt.main_types({c: 0 for c in vt.CATEGORIES}) == []


class TestStockLinks:
    HTML = (
        '<a href="/occasions">Accueil</a><a href="/contact">Contact</a><a href="/nos-vehicules">Voir</a>'
        '<a href="https://autre-site.fr/occasion">Externe</a><a href="/img/stock.jpg">Photo</a>'
        '<a href="/histoire">Nos véhicules</a><a href="/occasions">Doublon</a>'
    )

    def test_keeps_same_site_stock_like_links_once(self):
        assert vt.stock_links(self.HTML, "https://ex.fr/", limit=5) == [
            "https://ex.fr/occasions", "https://ex.fr/nos-vehicules", "https://ex.fr/histoire"]

    def test_matches_on_the_link_label_too(self):
        assert "https://ex.fr/histoire" in vt.stock_links(self.HTML, "https://ex.fr/", limit=5)

    def test_limit(self):
        assert len(vt.stock_links(self.HTML, "https://ex.fr/", limit=1)) == 1
        assert vt.stock_links(self.HTML, "https://ex.fr/", limit=0) == []


class TestReadSite:
    HOME = page('<a href="/occasions">Nos occasions</a> accueil')

    def test_reads_home_and_the_stock_page(self):
        get = network({"https://ex.fr/": self.HOME, "https://ex.fr/occasions": page("fourgon utilitaire")})
        result = vt.read_site("https://ex.fr/", get=get)
        assert result["status"] == "ok" and result["pages"] == ["https://ex.fr/", "https://ex.fr/occasions"]
        assert "fourgon utilitaire" in result["text"]

    def test_robots_txt_forbidding_the_site_stops_everything(self):
        get = network({"https://ex.fr/": self.HOME}, robots="User-agent: *\nDisallow: /")
        result = vt.read_site("https://ex.fr/", get=get)
        assert result["status"] == "interdit par robots.txt" and result["pages"] == []
        assert "https://ex.fr/" not in get.calls                               # la page n'a même pas été demandée

    def test_a_stock_page_forbidden_by_robots_is_not_read(self):
        get = network({"https://ex.fr/": self.HOME, "https://ex.fr/occasions": page("x")},
                      robots="User-agent: *\nDisallow: /occasions")
        result = vt.read_site("https://ex.fr/", get=get)
        assert result["pages"] == ["https://ex.fr/"] and "https://ex.fr/occasions" not in get.calls

    def test_unreachable_site(self):
        assert vt.read_site("https://ex.fr/", get=network({}))["status"] == "inaccessible"

    def test_max_pages_one_reads_only_the_home_page(self):
        get = network({"https://ex.fr/": self.HOME, "https://ex.fr/occasions": page("x")})
        assert vt.read_site("https://ex.fr/", max_pages=1, get=get)["pages"] == ["https://ex.fr/"]

    def test_almost_empty_page_is_flagged(self):
        get = network({"https://ex.fr/": "<html><body>Chargement...</body></html>"})
        assert vt.read_site("https://ex.fr/", get=get)["status"] == "peu de contenu"


class TestCommandLine:
    @pytest.fixture
    def files(self, tmp_path):
        sites = tmp_path / "sites.csv"
        with open(sites, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["nom", "siren", "site"])
            w.writerows([["VANS SA", "111", "https://vans.fr/"], ["CITY SA", "222", "https://city.fr/"],
                         ["SANS SITE", "333", ""], ["HORS LIGNE", "444", "https://off.fr/"]])
        get = network({
            "https://vans.fr/": page("utilitaires fourgons camionnettes bennes frigorifiques renault master"),
            "https://city.fr/": page("citadines renault clio toyota aygo fiat 500 petites voitures"),
        })
        return sites, get

    def test_filtering_on_a_type_keeps_and_ranks_the_matching_sites(self, files, capsys):
        sites, get = files
        vt.main(["--input", str(sites), "--type", "utilitaires", "--pause", "0"], get=get)
        out = capsys.readouterr().out
        assert "VANS SA" in out and "CITY SA" not in out and "HORS LIGNE" not in out
        assert "https://vans.fr/" in out                                        # lien sous la ligne
        assert "1 société(s) sans site ignorée(s)" in out and "1 site(s) pour « utilitaires »" in out

    def test_several_types_add_up(self, files, capsys):
        sites, get = files
        vt.main(["--input", str(sites), "--type", "utilitaires,citadines", "--pause", "0"], get=get)
        out = capsys.readouterr().out
        assert "VANS SA" in out and "CITY SA" in out

    def test_min_hits_raises_the_bar(self, files, capsys):
        sites, get = files
        vt.main(["--input", str(sites), "--type", "utilitaires", "--min-hits", "999", "--pause", "0"], get=get)
        assert "0 site(s)" in capsys.readouterr().out

    def test_without_a_type_every_site_is_listed_with_its_main_types(self, files, capsys):
        sites, get = files
        vt.main(["--input", str(sites), "--pause", "0"], get=get)
        out = capsys.readouterr().out
        vans = next(line for line in out.splitlines() if line.startswith("VANS SA"))
        city = next(line for line in out.splitlines() if line.startswith("CITY SA"))
        assert "utilitaires" in vans and "citadines" in city and "citadines" not in vans
        assert "HORS LIGNE" in out and "inaccessible" in out

    def test_main_only_drops_sites_that_merely_mention_the_type(self, tmp_path, capsys):
        sites = tmp_path / "sites.csv"
        sites.write_text("nom;siren;site\nMIXTE SA;1;https://mixte.fr/\nVANS SA;2;https://vans.fr/\n", encoding="utf-8")
        get = network({
            # 3 mentions d'utilitaires noyées dans une longue liste de citadines : présent, mais pas principal
            "https://mixte.fr/": page("utilitaire fourgon camionnette citadine clio aygo fiat 500 petites voitures "
                                      "dacia sandero kia picanto opel corsa ford fiesta hyundai i10 smart fortwo "
                                      "peugeot 208 peugeot 108 citroen c3 citroen c1 volkswagen polo"),
            "https://vans.fr/": page("utilitaires fourgons camionnettes bennes frigorifiques renault master"),
        })
        args = ["--input", str(sites), "--type", "utilitaires", "--pause", "0"]

        vt.main(args, get=get)
        assert "MIXTE SA" in capsys.readouterr().out                        # 3 mentions >= 3

        vt.main(args + ["--main-only"], get=get)
        out = capsys.readouterr().out
        assert "VANS SA" in out and "MIXTE SA" not in out

    def test_csv_export_has_the_counts_and_the_status(self, files, tmp_path):
        sites, get = files
        target = tmp_path / "out.csv"
        vt.main(["--input", str(sites), "--csv", str(target), "--pause", "0"], get=get)
        with open(target, encoding="utf-8-sig", newline="") as f:
            rows = {r["nom"]: r for r in csv.DictReader(f)}
        assert int(rows["VANS SA"]["mentions_utilitaires"]) >= 5 and rows["VANS SA"]["statut"] == "ok"
        assert rows["HORS LIGNE"]["statut"] == "inaccessible" and rows["HORS LIGNE"]["mentions_utilitaires"] == "0"
        assert rows["VANS SA"]["siren"] == "111"

    def test_unknown_type_is_rejected(self, files):
        sites, get = files
        with pytest.raises(SystemExit):
            vt.main(["--input", str(sites), "--type", "voitures-volantes"], get=get)

    def test_input_needs_a_site_column(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("nom;siren\nX;1\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="colonne « site »"):
            vt.main(["--input", str(bad)])
