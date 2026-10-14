"""`bodacc.verify` : date limite lue sur la fiche, suppression des seules annonces que le cabinet dit retirées."""
import pytest

from bodacc import report, verify
from bodacc.storage import Storage

# Extraits réels de fiches Gemweb (8 octobre 2026), réduits.
ON_SALE_WITH_DATE = ("<html><body>Informations Actif Type Véhicules Ville VILLENEUVE-SUR-ALLIER Plan "
                     "<h3>Date Limite de l'offre</h3> 15 oct. 2026 - 00:00 Date de vente prévue 20 octobre 2026</body></html>")
ON_SALE_NO_DATE = "<html><body>Type Véhicules > Autres Estimation Non renseigné Contact de l'étude</body></html>"
FREE_TEXT_DATE = "<html><body>Description : offres à adresser au plus tard le 12/11/2026 par courrier</body></html>"
WITHDRAWN = "<html><body>A vendre : NISSAN PULSAR 2017 Cet actif n'apparait plus sur le site. Il n'est plus en vente.</body></html>"


@pytest.mark.parametrize("status, page, expected", [
    (200, ON_SALE_WITH_DATE, ("en vente", "15 oct. 2026")), (200, ON_SALE_NO_DATE, ("en vente", None)),
    (200, FREE_TEXT_DATE, ("en vente", "12/11/2026")), (200, WITHDRAWN, ("retiré", None)),
    (404, "", ("retiré", None)), (None, "", ("inaccessible", None)), (500, "", ("inaccessible", None))])
def test_parse_page(status, page, expected):
    assert verify.parse_page(status, page) == expected


def vehicle(guid, date=None):
    return {"guid": guid, "cabinet": "LGA", "titre": f"A vendre : RENAULT CLIO {guid}", "type": "Véhicules",
            "date_limite_offre": date, "url_detail": f"https://lga.fr/anonym/actif/detail/{guid}"}


def test_only_listings_without_date_or_absent_from_the_last_feed_are_checked():
    rows = [{**vehicle("1", "15 oct. 2026"), "last_seen": "2026-10-08T18:00"},
            {**vehicle("2"), "last_seen": "2026-10-08T18:00"},
            {**vehicle("3", "1 oct. 2026"), "last_seen": "2026-09-28T20:00"}]
    assert [r["guid"] for r in verify.to_check(rows)] == ["2", "3"]
    assert len(verify.to_check(rows, everything=True)) == 3


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "base.db"
    with Storage(path) as storage:
        storage.upsert_actifs([vehicle("1"), vehicle("2"), vehicle("3")], now="2026-10-08T10:00:00+00:00")
        storage.set_cote("2", 9000)
    return path


def fake_get(pages, robots="User-agent: *\nAllow: /\n"):
    def get(url):
        if url.endswith("/robots.txt"):
            return 200, robots
        return pages.get(url, (None, ""))
    return get


PAGES = {"https://lga.fr/anonym/actif/detail/1": (200, ON_SALE_WITH_DATE),
         "https://lga.fr/anonym/actif/detail/2": (200, WITHDRAWN)}


def test_preview_keeps_everything_but_records_the_date(db):
    verify.main(["--db", str(db)], get=fake_get(PAGES), sleep=lambda s: None)
    with Storage(db) as storage:
        assert storage.count("actifs") == 3
        rows = {r["guid"]: r for r in report.vehicle_rows(storage)}
    assert rows["1"]["date_limite_offre"] == "15 oct. 2026"


def test_supprimer_removes_only_withdrawn_listings_and_their_cote(db, capsys):
    verify.main(["--db", str(db), "--supprimer"], get=fake_get(PAGES), sleep=lambda s: None)
    with Storage(db) as storage:
        assert storage.keys("actifs") == {"1", "3"} and storage.cotes() == {}
    assert "1 fiche(s) non vérifiée(s)" in capsys.readouterr().out          # la 3 était injoignable : gardée


def test_the_date_survives_the_next_feed_update(db):
    verify.main(["--db", str(db)], get=fake_get(PAGES), sleep=lambda s: None)
    with Storage(db) as storage:
        storage.upsert_actifs([vehicle("1")], now="2026-10-09T10:00:00+00:00")       # le flux n'a toujours pas de date
        assert {r["guid"]: r for r in report.vehicle_rows(storage)}["1"]["date_limite_offre"] == "15 oct. 2026"


def test_robots_txt_is_respected(db):
    calls = []
    get = fake_get(PAGES, robots="User-agent: *\nDisallow: /anonym/\n")
    verify.main(["--db", str(db), "--supprimer"], get=lambda url: calls.append(url) or get(url), sleep=lambda s: None)
    assert all(url.endswith("robots.txt") for url in calls)
    with Storage(db) as storage:
        assert storage.count("actifs") == 3
