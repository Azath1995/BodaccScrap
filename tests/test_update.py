import sqlite3

import pytest

from bodacc import update
from bodacc.gemweb_rss import CabinetRegistry
from bodacc.storage import Storage

NOW = "2026-09-19T10:00:00+00:00"
LATER = "2026-09-20T10:00:00+00:00"

REGISTRY = CabinetRegistry({
    "Les Mandataires": "https://sud.lesmandataires.com",
    "D Hazane": "https://www.scpanha.com",
    "Denis Hazane": "https://www.scpanha.com",   # même site : le 1er nom déclaré est le canonique
})


def liquidation(id_, liquidateur):
    return {"id": id_, "entreprise": f"Société {id_}", "liquidateur": liquidateur}


def actif(guid, type_="Mobilier", titre="Objet"):
    return {"guid": guid, "cabinet": "X", "titre": titre, "type": type_, "lieu": "Lyon",
            "url_detail": f"https://x/{guid}"}


@pytest.fixture
def db():
    storage = Storage(":memory:")
    yield storage
    storage.close()


class TestTagCabinets:
    def test_known_liquidator_gets_its_canonical_name(self):
        rows = [liquidation("1", "Sas les Mandataires Prise en la Personne de Maître X 1 rue A 13300 Salon")]
        assert update.tag_cabinets(rows, REGISTRY)[0]["cabinet"] == "Les Mandataires"

    def test_alias_resolves_to_the_canonical_name(self):
        rows = [liquidation("1", "SCP D Hazane représentée par Me Nina Rousseau 24 Rue des Forges 60200 Compiègne")]
        assert update.tag_cabinets(rows, REGISTRY)[0]["cabinet"] == "D Hazane"  # 1er nom déclaré du domaine

    def test_unknown_or_missing_liquidator_gets_none(self):
        rows = [liquidation("1", "la Selarl INCONNUE Représentée par Me X 1 rue A"), liquidation("2", None)]
        assert [r["cabinet"] for r in update.tag_cabinets(rows, REGISTRY)] == [None, None]


class TestStoreLiquidations:
    def test_summary_and_rerun(self, db):
        def rows():
            return [
                liquidation("1", "Sas les Mandataires Prise en la Personne de Maître X 1 rue A"),
                liquidation("2", "la Selarl INCONNUE Représentée par Me X 1 rue A"),
            ]

        first = update.store_liquidations(db, rows(), REGISTRY, NOW)
        second = update.store_liquidations(db, rows(), REGISTRY, LATER)

        assert first == {"seen": 2, "new": 2, "no_cabinet": 1}
        assert second == {"seen": 2, "new": 0, "no_cabinet": 1}
        assert db.count("liquidations") == 2

    def test_cabinet_is_persisted(self, db):
        update.store_liquidations(
            db, [liquidation("1", "Sas les Mandataires Prise en la Personne de Maître X 1 rue A")], REGISTRY, NOW)
        assert db.new_since("liquidations", "2000")[0]["cabinet"] == "Les Mandataires"


class TestStoreActifs:
    def test_new_vehicles_are_reported_once(self, db):
        rows = [actif("1", "Véhicules > Autres", "Golf"), actif("2", "Mobilier", "Table")]

        first = update.store_actifs(db, rows, NOW)
        second = update.store_actifs(db, rows, LATER)

        assert first["new"] == 2
        assert [v["titre"] for v in first["new_vehicles"]] == ["Golf"]
        assert second["new"] == 0
        assert second["new_vehicles"] == []

    def test_a_vehicle_appearing_later_is_new(self, db):
        update.store_actifs(db, [actif("1", "Véhicules", "Golf")], NOW)

        result = update.store_actifs(
            db, [actif("1", "Véhicules", "Golf"), actif("2", "Camions", "Iveco")], LATER)

        assert result["new"] == 1
        assert [v["titre"] for v in result["new_vehicles"]] == ["Iveco"]

    def test_lookalike_types_are_not_vehicles(self, db):
        result = update.store_actifs(db, [actif("1", "Automate de paiement")], NOW)
        assert result["new_vehicles"] == []


class TestVehicleDetails:
    def car(self):
        return actif("1", "Véhicules > Autres", "A vendre : FORD FIESTA FOURGON 91000 EVRY") | {
            "description": "gasoil | Immatriculé FX-101-AB | 174 676 kms", "estimation": "1 200,00 €"}

    def test_details_are_extracted_and_stored(self, db):
        result = update.store_actifs(db, [self.car()], NOW)

        stored = db.new_since("actifs", "2000")[0]
        assert (stored["marque"], stored["immatriculation"], stored["kilometrage"], stored["carburant"]) == \
               ("Ford", "FX-101-AB", 174676, "diesel")
        assert result["new_vehicles"][0]["marque"] == "Ford"

    def test_non_vehicles_get_no_vehicle_details(self, db):
        update.store_actifs(db, [actif("2", "Mobilier", "Table") | {"description": "Table 200 km de bois"}], NOW)
        assert db.new_since("actifs", "2000")[0]["kilometrage"] is None

    def test_rerun_fills_details_on_rows_stored_before_this_feature(self, db):
        db.upsert_actifs([{"guid": "1", "type": "Véhicules", "titre": "A vendre : FORD FIESTA"}], now=NOW)

        update.store_actifs(db, [self.car() | {"type": "Véhicules"}], LATER)

        assert db.new_since("actifs", "2000")[0]["marque"] == "Ford"

    def test_the_number_of_vehicles_of_a_lot_is_stored(self, db):
        lot = actif("7", "Véhicules", "A vendre : Cession de Véhicule 92200") | {"description": "deux véhicules CLIO"}
        result = update.store_actifs(db, [lot, actif("8", "Véhicules", "Golf")], NOW)

        stored = {r["guid"]: r["nb_vehicules"] for r in db.new_since("actifs", "2000")}
        assert stored == {"7": 2, "8": 1}
        assert [v["nb_vehicules"] for v in result["new_vehicles"]] == [2, 1]

    def test_describe_says_when_it_is_a_lot(self):
        assert update.describe({"titre": "A vendre : CLIO", "nb_vehicules": 2, "marque": "Renault", "url_detail": "https://x/1"}) == \
               "CLIO | lot de 2 véhicules, Renault | https://x/1"

    def test_describe_is_one_readable_line(self):
        car = self.car() | {"marque": "Ford", "kilometrage": 174676, "immatriculation": "FX-101-AB",
                            "carburant": "diesel", "annee": None}
        assert update.describe(car) == (
            "FORD FIESTA FOURGON 91000 EVRY | Ford, 174 676 km, FX-101-AB, diesel | 1 200,00 € | https://x/1")

    def test_describe_skips_missing_parts(self):
        assert update.describe({"titre": "A vendre : TABLE", "url_detail": "https://x/2"}) == "TABLE | https://x/2"


class TestMain:
    def fake_network(self, monkeypatch, actifs):
        monkeypatch.setattr(update, "fetch_liquidations", lambda *a, **k: [
            liquidation("L1", "Sas les Mandataires Prise en la Personne de Maître X 1 rue A")])
        monkeypatch.setattr(update, "fetch_actifs", lambda registry: (actifs, 0))

    def test_first_run_then_second_run(self, tmp_path, monkeypatch, capsys):
        db_path = tmp_path / "t.db"
        self.fake_network(monkeypatch, [actif("A1", "Véhicules", "Golf")])

        update.main(["--db", str(db_path)])
        first = capsys.readouterr().out
        update.main(["--db", str(db_path)])
        second = capsys.readouterr().out

        assert "1 nouvelles" in first and "1 nouveaux dont 1 véhicule" in first
        assert "Golf" in first and "Premier passage" in first
        assert "0 nouvelles" in second and "0 nouveaux dont 0 véhicule" in second
        assert "Premier passage" not in second

    def test_skip_flags(self, tmp_path, monkeypatch, capsys):
        self.fake_network(monkeypatch, [actif("A1")])
        update.main(["--db", str(tmp_path / "t.db"), "--skip-bodacc"])
        out = capsys.readouterr().out
        assert "Liquidations" not in out and "Actifs" in out

    def test_skip_liquidations_is_the_same_option_as_skip_bodacc(self, tmp_path, monkeypatch, capsys):
        """Même option que côté Espagne (`es.update --skip-liquidations`) ; l'ancien nom continue de marcher."""
        self.fake_network(monkeypatch, [actif("A1")])
        update.main(["--db", str(tmp_path / "t.db"), "--skip-liquidations"])
        out = capsys.readouterr().out
        assert "Liquidations" not in out and "Actifs" in out

    def test_start_without_end_is_rejected(self):
        with pytest.raises(SystemExit):
            update.main(["--start", "2026-09-01"])


def test_storage_adds_missing_columns_to_an_old_database(tmp_path):
    """Une base créée avant l'ajout de la colonne 'cabinet' doit continuer à fonctionner."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE liquidations (id TEXT PRIMARY KEY, entreprise TEXT, "
                 "first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)")
    conn.execute("INSERT INTO liquidations VALUES ('1', 'Ancienne', 'a', 'a')")
    conn.commit()
    conn.close()

    with Storage(path) as db:
        db.upsert_liquidations([{"id": "1", "cabinet": "Nouveau"}], now="b")
        row = db.new_since("liquidations", "a")[0]

    assert row["cabinet"] == "Nouveau"                        # la colonne existe désormais
    assert (row["first_seen"], row["last_seen"]) == ("a", "b")  # l'historique est conservé
