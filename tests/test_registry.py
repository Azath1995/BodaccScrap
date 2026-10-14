import html
import json

import pytest
import requests

from bodacc.cabinets import match_cabinet
from bodacc.gemweb_rss import CabinetRegistry, GemwebActifScraper


def rss(*titles, free=""):
    """Un flux RSS minimal, avec la description doublement encodée comme Gemweb.

    free : texte libre du cabinet, placé avant les blocs <h3> (comme dans les vrais flux).
    """
    description = html.escape(html.escape(
        f"{free}<h3>Type</h3> Véhicules > Autres <h3>Estimation</h3> 1 000 € <h3>Lieu</h3> Lyon"
    ))
    items = "".join(
        f"<item><title>{t}</title><link>https://x/{t}</link><guid>https://x/{t}</guid>"
        f"<pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>"
        f"<description>{description}</description></item>"
        for t in titles
    )
    return f"<rss><channel>{items}</channel></rss>".encode("utf-8")


class TestShippedConfig:
    def test_loads_the_default_config(self):
        registry = CabinetRegistry()
        assert len(registry.by_domain()) >= 50
        assert registry.get("MJ Synergie") == "https://www.mj-synergie.fr"

    def test_no_two_cabinets_share_a_domain(self):
        with open(CabinetRegistry.DEFAULT_CONFIG, encoding="utf-8") as f:
            domains = [c["domain"].lower().rstrip("/") for c in json.load(f)["cabinets"]]
        assert len(domains) == len(set(domains))

    def test_a_verifier_is_a_work_list_that_the_registry_never_reads(self):
        with open(CabinetRegistry.DEFAULT_CONFIG, encoding="utf-8") as f:
            config = json.load(f)
        names = CabinetRegistry().names()
        assert config["a_verifier"] and all(isinstance(n, int) and n > 0 for n in config["a_verifier"].values())
        assert not set(config["a_verifier"]) & set(names)                    # jamais un nom déjà au registre
        assert not any(match_cabinet(name, names) for name in config["a_verifier"])   # ni une variante d'un nom connu

    def test_every_domain_is_https(self):
        assert all(d.startswith("https://") for d in CabinetRegistry().by_domain())

    @pytest.mark.parametrize("alias, canonical", [
        ("Serrano Philippe", "Philippe Serrano"),
        ("M.J.S. Partners", "MJS Partners"),
        ("Mjc2a", "MJ2A"),
        ("D Hazane", "Denis Hazane"),
        ("Deslorieux", "Delorieux"),
    ])
    def test_aliases_point_to_the_same_site(self, alias, canonical):
        registry = CabinetRegistry()
        assert registry.get(alias) == registry.get(canonical) != None  # noqa: E711

    def test_bodacc_spellings_now_resolve_to_a_site(self):
        registry = CabinetRegistry()
        designation = "SCP D Hazane représentée par Me Nina Rousseau 24 Rue des Forges 60200 Compiègne"
        matched = match_cabinet(designation, registry.names())
        assert matched == "D Hazane"
        assert registry.get(matched) == "https://www.scpanha.com"


class TestRegistry:
    def test_by_domain_groups_names_and_keeps_canonical_first(self):
        registry = CabinetRegistry({
            "Serrano": "https://a.fr",
            "Serrano Philippe": "https://a.fr/",   # slash final ignoré
            "Autre": "https://b.fr",
        })
        assert registry.by_domain() == {
            "https://a.fr": ["Serrano", "Serrano Philippe"],
            "https://b.fr": ["Autre"],
        }

    def test_domains_are_compared_case_insensitively(self):
        registry = CabinetRegistry({"A": "https://Exemple.FR", "B": "https://exemple.fr"})
        assert len(registry.by_domain()) == 1

    def test_from_json_expands_aliases_and_reads_accents(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"cabinets": [
            {"name": "Étude X", "domain": "https://x.fr", "aliases": ["Etude X"]},
        ]}, ensure_ascii=False), encoding="utf-8")

        registry = CabinetRegistry.from_json(path)

        assert registry.get("Étude X") == registry.get("Etude X") == "https://x.fr"

    def test_same_name_on_two_domains_is_rejected(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"cabinets": [
            {"name": "X", "domain": "https://a.fr"},
            {"name": "X", "domain": "https://b.fr"},
        ]}), encoding="utf-8")

        with pytest.raises(ValueError):
            CabinetRegistry.from_json(path)


class TestFetchAll:
    def make_scraper(self, monkeypatch, registry, responses):
        """responses: {domaine: octets RSS | exception}. Retourne (scraper, appels)."""
        calls = []

        def fake_fetch(domain):
            calls.append(domain)
            outcome = responses[domain]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        scraper = GemwebActifScraper(registry=registry)
        monkeypatch.setattr(scraper, "_fetch_rss", fake_fetch)
        return scraper, calls

    def test_a_site_with_several_names_is_fetched_once(self, monkeypatch):
        registry = CabinetRegistry({"Serrano": "https://a.fr", "Serrano Philippe": "https://a.fr"})
        scraper, calls = self.make_scraper(monkeypatch, registry, {"https://a.fr": rss("one", "two")})

        rows = scraper.fetch_all()

        assert calls == ["https://a.fr"]
        assert [r["titre"] for r in rows] == ["one", "two"]      # pas de doublons
        assert {r["cabinet"] for r in rows} == {"Serrano"}        # nom canonique

    def test_parsed_fields(self, monkeypatch):
        registry = CabinetRegistry({"A": "https://a.fr"})
        scraper, _ = self.make_scraper(monkeypatch, registry, {"https://a.fr": rss("golf")})

        row = scraper.fetch_all()[0]

        assert (row["type"], row["estimation"], row["lieu"]) == ("Véhicules > Autres", "1 000 €", "Lyon")

    def test_free_text_description_is_kept_on_one_line(self, monkeypatch):
        registry = CabinetRegistry({"A": "https://a.fr"})
        free = "gasoil</BR>Immatriculé FX-101-AB</BR>174 676 kms"
        scraper, _ = self.make_scraper(monkeypatch, registry, {"https://a.fr": rss("golf", free=free)})

        row = scraper.fetch_all()[0]

        assert row["description"] == "gasoil | Immatriculé FX-101-AB | 174 676 kms"

    def test_no_free_text_gives_none(self, monkeypatch):
        registry = CabinetRegistry({"A": "https://a.fr"})
        scraper, _ = self.make_scraper(monkeypatch, registry, {"https://a.fr": rss("golf")})

        assert scraper.fetch_all()[0]["description"] is None

    def test_one_broken_site_does_not_stop_the_others(self, monkeypatch):
        registry = CabinetRegistry({"Down": "https://down.fr", "Html": "https://html.fr", "Ok": "https://ok.fr"})
        scraper, calls = self.make_scraper(monkeypatch, registry, {
            "https://down.fr": requests.exceptions.ConnectionError("boom"),
            "https://html.fr": b"<html><body>page d'erreur</body>",   # pas du XML valide
            "https://ok.fr": rss("kept"),
        })

        rows = scraper.fetch_all()

        assert calls == ["https://down.fr", "https://html.fr", "https://ok.fr"]
        assert [r["titre"] for r in rows] == ["kept"]
