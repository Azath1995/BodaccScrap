import csv
import json

import pytest

from bodacc import find_cabinets as fc
from bodacc.gemweb_rss import CabinetRegistry
from bodacc.storage import Storage

ROBOTS = "User-agent: *\nDisallow: /pj/\nDisallow: /anonym/mandat/creance/\n"
RSS = "<rss><channel><item><title>a</title></item><item><title>b</title></item></channel></rss>"


def sitemap(*slugs):
    return "<urlset>" + "".join(f"<url><loc>https://www.cnajmj.fr/etude/{s}/</loc></url>" for s in slugs) + "</urlset>"


def fiche(site=None):
    """Fiche CNAJMJ : le site du cabinet n'est que dans le bloc `right … h4` ; le reste est du bruit réel
    (carte, pied de page e-justice, réseaux sociaux) qui ne doit jamais être pris pour le site."""
    noise = ('<div class="left"><ul><li><a href="https://maps.app.goo.gl/x">BORDEAUX</a></li></ul></div>'
             '<a href="https://www.banquedesterritoires.fr/">bdt</a><a href="https://www.linkedin.com/company/x">in</a>'
             '<div class="liens_utiles_logos"><a href="https://e-justice.europa.eu/home?plang=fr">e-justice</a></div>')
    block = (f'<div class="right wow fadeInUp"><h4> <a href="{site}" target="_blank"> {site} </a></h4></div>'
             if site else '<div class="right wow fadeInUp"><h4> </h4><div class="info"></div></div>')
    return "<html>" + block + noise + "</html>"


def network(pages, robots=None):
    """Faux réseau : {url: (code, texte) | texte}. Tout ce qui manque répond 404. robots : {domaine: texte}."""
    calls = []
    robots = robots or {}

    def get(url):
        calls.append(url)
        if url.endswith("/robots.txt"):
            base = url[: -len("/robots.txt")]
            return (200, robots.get(base, ROBOTS))
        page = pages.get(url)
        if page is None:
            return (404, "")
        return page if isinstance(page, tuple) else (200, page)

    get.calls = calls
    return get


def index(*slugs):
    return {f"https://www.cnajmj.fr/etude/{s}/": fc.tokens(s.replace("-", " ")) for s in slugs}


class TestTokens:
    def test_drops_legal_forms_accents_and_generic_words(self):
        assert fc.tokens("SELARL Pellier") == ["pellier"]
        assert fc.tokens("Selas GUERIN et associées") == ["guerin"]
        assert fc.tokens("Etude Hidoux Jean-Charles") == ["hidoux", "jean", "charles"]

    def test_short_name_removes_the_legal_prefix(self):
        assert fc.short_name("Selarl Bleu Sud") == "Bleu Sud" and fc.short_name("Me Hélène GASCON") == "Hélène GASCON"


class TestFindFiches:
    IDX = index("selarl-bleu-sud", "selarl-bleu-nord", "selarl-alliance-mj", "etude-alliance", "etude-marchal-flavien")

    def slugs(self, name):
        return sorted(u.rstrip("/").rsplit("/", 1)[1] for u in fc.find_fiches(name, self.IDX))

    def test_all_words_must_be_found(self):
        assert self.slugs("Bleu Sud") == ["selarl-bleu-sud"]
        assert self.slugs("Bleu Ouest") == []

    def test_word_order_does_not_matter(self):
        assert self.slugs("Flavien Marchal") == ["etude-marchal-flavien"]

    def test_several_fiches_are_all_returned_so_the_caller_can_call_it_ambiguous(self):
        assert self.slugs("Bleu") == ["selarl-bleu-nord", "selarl-bleu-sud"]

    def test_an_identical_name_wins_over_a_longer_one(self):
        assert self.slugs("Alliance") == ["etude-alliance"]

    def test_a_name_with_no_distinctive_word_finds_nothing(self):
        assert self.slugs("Selarl Associés") == []


class TestFicheSite:
    def test_site_is_kept_as_https_host(self):
        assert fc.fiche_site(fiche("http://WWW.Exemple.fr/accueil/x?y=1")) == "https://www.exemple.fr"

    def test_a_fiche_without_a_site_gives_none_even_with_other_links_on_the_page(self):
        assert fc.fiche_site(fiche()) is None                       # carte, e-justice, LinkedIn... ne sont pas le site

    def test_the_footer_link_is_never_taken_for_the_site(self):
        page = '<div class="liens_utiles_logos"><a href="https://e-justice.europa.eu/home">x</a></div>'
        assert fc.fiche_site(page) is None

    def test_a_social_or_map_link_in_the_site_block_is_refused(self):
        assert fc.fiche_site(fiche("https://www.linkedin.com/company/x")) is None

    def test_real_philae_block(self):
        real = ('<div class="right wow fadeInUp"><h4> <a href="https://www.philaemj.fr/accueil" target="_blank"> '
                'https://www.philaemj.fr/accueil </a></h4><div class="info"></div></div>')
        assert fc.fiche_site(real) == "https://www.philaemj.fr"


class TestProbe:
    def test_valid_feed(self):
        get = network({"https://a.fr/rss/actif": RSS})
        assert fc.probe("https://a.fr", get) == (fc.GEMWEB, 2, "")

    def test_missing_feed(self):
        status, items, detail = fc.probe("https://a.fr", network({}))
        assert status == "pas de flux" and items == 0 and "404" in detail

    def test_html_page_is_not_a_feed(self):
        assert fc.probe("https://a.fr", network({"https://a.fr/rss/actif": "<html>Erreur</html>"}))[0] == "pas de flux"

    def test_robots_refusal_means_the_feed_is_never_requested(self):
        get = network({"https://a.fr/rss/actif": RSS}, robots={"https://a.fr": "User-agent: *\nDisallow: /rss/\n"})
        assert fc.probe("https://a.fr", get)[0] == "robots interdit"
        assert "https://a.fr/rss/actif" not in get.calls

    def test_unreachable_site(self):
        get = lambda url: (200, ROBOTS) if url.endswith("robots.txt") else (None, "")
        assert fc.probe("https://a.fr", get)[0] == "site inaccessible"


class TestInvestigate:
    REGISTRY = CabinetRegistry({"Berthelot & Associes": "https://www.berthelot-mj.eu"})

    def run(self, name, pages, slugs=("selarl-bleu-sud", "selarl-bleu-nord", "selarl-rare", "berthelot-et-associes")):
        return fc.investigate(name, index(*slugs), self.REGISTRY, network(pages))

    def test_no_fiche(self):
        assert self.run("Zzz Inconnu", {})["statut"] == "pas de fiche"

    def test_ambiguous_names_are_never_decided(self):
        result = self.run("Bleu", {})
        assert result["statut"] == "ambigu" and "selarl-bleu-nord" in result["detail"] and result["site"] == ""

    def test_fiche_without_a_site(self):
        pages = {"https://www.cnajmj.fr/etude/selarl-rare/": fiche()}
        assert self.run("Rare", pages)["statut"] == "fiche sans site"

    def test_valid_gemweb_site(self):
        pages = {"https://www.cnajmj.fr/etude/selarl-bleu-sud/": fiche("https://www.bleusud.eu/"), "https://www.bleusud.eu/rss/actif": RSS}
        result = self.run("Bleu Sud", pages)
        assert (result["statut"], result["site"], result["annonces"]) == (fc.GEMWEB, "https://www.bleusud.eu", 2)

    def test_site_without_a_feed(self):
        pages = {"https://www.cnajmj.fr/etude/selarl-bleu-sud/": fiche("https://www.bleusud.eu")}
        assert self.run("Bleu Sud", pages)["statut"] == "pas de flux"

    def test_a_site_already_in_the_registry_is_reported_as_an_alias_case(self):
        pages = {"https://www.cnajmj.fr/etude/berthelot-et-associes/": fiche("https://berthelot-mj.eu/")}
        result = self.run("Berthelot", pages)
        assert result["statut"] == "deja au registre" and "Berthelot & Associes" in result["detail"]
        assert "https://berthelot-mj.eu/rss/actif" not in network(pages).calls        # inutile de sonder un site connu


def make_config(tmp_path, cabinets=None, pending=None, a_verifier=None):
    path = tmp_path / "cabinets.json"
    path.write_text(json.dumps({
        "_comment": "test", "cabinets": cabinets if cabinets is not None else [{"name": "Existant", "domain": "https://existant.fr"}],
        "pending": pending or {}, "_comment_a_verifier": "x", "a_verifier": a_verifier or {}}, ensure_ascii=False), encoding="utf-8")
    return path


def make_db(tmp_path, counts):
    path = tmp_path / "t.db"
    rows = []
    for label, n in counts.items():
        rows += [{"id": f"{label}-{i}", "liquidateur": f"la {label} Représentée par Me X 8 avenue A 30000 Nîmes"} for i in range(n)]
    with Storage(path) as s:
        s.upsert_liquidations(rows)
    return path


class TestIsNoted:
    def test_a_longer_bodacc_spelling_is_noted_but_no_other_name_is(self):
        noted = {"legras de grandcourt", "mj alpes"}
        assert fc.is_noted("legras de grandcourt patrick", noted) and fc.is_noted("mj alpes", noted)
        assert not fc.is_noted("mj", noted)                           # un nom court n'est pas écarté par un nom plus long
        assert not fc.is_noted("mjuris", {"mj"}) and not fc.is_noted("grandcourt", {"legras de grandcourt"})


class TestCandidates:
    def test_most_frequent_first_and_known_or_noted_names_are_skipped(self, tmp_path):
        db = make_db(tmp_path, {"Selarl AAA": 5, "Selarl BBB": 3, "Selarl CCC": 1, "Selarl Existant": 9})
        registry = CabinetRegistry({"Existant": "https://existant.fr"})
        with Storage(db) as s:
            got = fc.candidates(s, registry, {"bbb"}, top=10, minimum=1)
            limited = fc.candidates(s, registry, set(), top=1, minimum=1)
            frequent = fc.candidates(s, registry, set(), top=10, minimum=3)
        assert [(k, n) for _, k, n in got] == [("aaa", 5), ("ccc", 1)]
        assert [k for _, k, _ in limited] == ["aaa"] and [k for _, k, _ in frequent] == ["aaa", "bbb"]


class TestApply:
    def finding(self, cabinet, statut, site="", detail=""):
        return {"cabinet": cabinet, "liquidations": 3, "statut": statut, "site": site, "annonces": 2, "fiche": "f", "detail": detail}

    def test_valid_sites_are_added_noted_ones_go_to_pending_and_a_verifier_shrinks(self, tmp_path):
        path = make_config(tmp_path, a_verifier={"Selarl Bleu Sud": 3, "Selarl Sans Flux": 2, "Selarl Rare": 1})
        added, noted = fc.apply_findings(path, [
            self.finding("Selarl Bleu Sud", fc.GEMWEB, "https://www.bleusud.eu"),
            self.finding("Selarl Sans Flux", "pas de flux", "https://sansflux.fr", "/rss/actif : HTTP 404, pas un flux RSS"),
            self.finding("Selarl Rare", "fiche sans site"),
        ], "2026-09-20")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert added == [("Selarl Bleu Sud", "Bleu Sud")] and noted == ["Sans Flux"]
        assert {"name": "Bleu Sud", "domain": "https://www.bleusud.eu"} in data["cabinets"]
        assert "sansflux.fr" in data["pending"]["Sans Flux"] and "2026-09-20" in data["pending"]["Sans Flux"]
        assert data["a_verifier"] == {"Selarl Rare": 1}                     # le non résolu reste à traiter
        assert CabinetRegistry.from_json(path).get("Bleu Sud") == "https://www.bleusud.eu"

    def test_an_existing_site_gets_the_new_spelling_as_an_alias(self, tmp_path):
        path = make_config(tmp_path, cabinets=[{"name": "Berthelot & Associes", "domain": "https://www.berthelot-mj.eu"}],
                           a_verifier={"Selarl Berthelot": 6})
        added, _ = fc.apply_findings(path, [self.finding("Selarl Berthelot", "deja au registre", "https://berthelot-mj.eu")], "d")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["cabinets"][0]["aliases"] == ["Berthelot"] and data["a_verifier"] == {}
        assert added == [("Selarl Berthelot", "Berthelot (alias de Berthelot & Associes)")]

    def test_a_domain_already_known_is_not_added_twice(self, tmp_path):
        path = make_config(tmp_path)
        fc.apply_findings(path, [self.finding("Selarl Autre", fc.GEMWEB, "https://www.existant.fr")], "d")
        assert len(json.loads(path.read_text(encoding="utf-8"))["cabinets"]) == 1

    def test_an_invalid_result_is_never_written(self, tmp_path):
        path = make_config(tmp_path, cabinets=[{"name": "Bleu Sud", "domain": "https://a.fr"}])
        before = path.read_text(encoding="utf-8")
        with pytest.raises(ValueError):                                      # même nom, deux domaines
            fc.apply_findings(path, [self.finding("Selarl Bleu Sud", fc.GEMWEB, "https://b.fr")], "d")
        assert path.read_text(encoding="utf-8") == before

    def test_other_keys_of_the_file_are_preserved_in_order(self, tmp_path):
        path = make_config(tmp_path)
        fc.apply_findings(path, [self.finding("Selarl X", fc.GEMWEB, "https://x.fr")], "d")
        assert list(json.loads(path.read_text(encoding="utf-8"))) == ["_comment", "cabinets", "pending", "_comment_a_verifier", "a_verifier"]


class TestCommandLine:
    @pytest.fixture
    def env(self, tmp_path):
        config = make_config(tmp_path, a_verifier={"Selarl Bleu Sud": 3, "Selarl Rare": 1})
        db = make_db(tmp_path, {"Selarl Bleu Sud": 3, "Selarl Rare": 1, "Selarl Zzz Inconnu": 1})
        get = network({
            "https://www.cnajmj.fr/etude-sitemap.xml": sitemap("selarl-bleu-sud", "selarl-rare"),
            "https://www.cnajmj.fr/etude/selarl-bleu-sud/": fiche("https://www.bleusud.eu"),
            "https://www.cnajmj.fr/etude/selarl-rare/": fiche(),
            "https://www.bleusud.eu/rss/actif": RSS,
        })
        return config, db, get

    def args(self, env, *extra):
        config, db, _ = env
        return ["--config", str(config), "--db", str(db), "--pause", "0", *extra]

    def test_default_run_only_reports(self, env, tmp_path, capsys):
        config, _, get = env
        before = config.read_text(encoding="utf-8")
        fc.main(self.args(env, "--csv", str(tmp_path / "r.csv")), get=get)
        out = capsys.readouterr().out
        assert config.read_text(encoding="utf-8") == before and "rien n'a été modifié" in out
        assert "1 gemweb valide" in out and "1 fiche sans site" in out and "1 pas de fiche" in out
        with open(tmp_path / "r.csv", encoding="utf-8-sig", newline="") as f:
            rows = {r["cabinet"]: r for r in csv.DictReader(f)}
        assert rows["Selarl Bleu Sud"]["site"] == "https://www.bleusud.eu" and rows["Selarl Bleu Sud"]["annonces"] == "2"

    def test_apply_updates_the_registry_and_the_cabinet_then_leaves_the_list(self, env, capsys):
        config, _, get = env
        fc.main(self.args(env, "--apply"), get=get)
        out = capsys.readouterr().out
        assert "1 ajout(s)" in out and "+ Bleu Sud" in out and "git diff" in out
        assert CabinetRegistry.from_json(config).get("Bleu Sud") == "https://www.bleusud.eu"
        assert json.loads(config.read_text(encoding="utf-8"))["a_verifier"] == {"Selarl Rare": 1}
        assert "toujours" not in out                                          # « Bleu Sud » se rapproche bien du BODACC
        fc.main(self.args(env), get=get)                                      # deuxième passage : Bleu Sud n'est plus candidat
        assert "Bleu Sud" not in capsys.readouterr().out.split("Bilan")[0]

    def test_top_limits_the_number_examined(self, env, capsys):
        _, _, get = env
        fc.main(self.args(env, "--top", "1"), get=get)
        assert "1 cabinet(s) à examiner" in capsys.readouterr().out

    def test_nothing_to_examine(self, tmp_path):
        config = make_config(tmp_path)
        db = make_db(tmp_path, {"Selarl Existant": 2})
        with pytest.raises(SystemExit, match="Aucun cabinet à examiner"):
            fc.main(["--config", str(config), "--db", str(db)], get=network({}))

    def test_a_directory_that_forbids_crawling_stops_everything(self, env):
        get = network({}, robots={"https://www.cnajmj.fr": "User-agent: *\nDisallow: /etude/\n"})
        with pytest.raises(SystemExit, match="interdit"):
            fc.main(self.args(env), get=get)
        assert not [u for u in get.calls if "/etude" in u and not u.endswith("robots.txt")]

    def test_requests_are_spaced(self, env, monkeypatch):
        config, db, get = env
        sleeps = []
        monkeypatch.setattr(fc.time, "sleep", sleeps.append)
        fc.main(["--config", str(config), "--db", str(db), "--pause", "5"], get=get)
        assert sleeps and all(0 < s <= 5 for s in sleeps)
