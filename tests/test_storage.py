import pytest

from bodacc.storage import Storage


@pytest.fixture
def db():
    storage = Storage(":memory:")  # base jetable, en RAM
    yield storage
    storage.close()


def actif(guid, titre="Golf", **extra):
    return {"guid": guid, "cabinet": "A", "titre": titre, "type": "Véhicules", **extra}


class TestUpsert:
    def test_counts_new_rows(self, db):
        assert db.upsert_actifs([actif("1"), actif("2")]) == 2
        assert db.count("actifs") == 2

    def test_rerun_creates_no_duplicates(self, db):
        db.upsert_actifs([actif("1"), actif("2")])
        assert db.upsert_actifs([actif("1"), actif("2")]) == 0
        assert db.count("actifs") == 2

    def test_only_unseen_rows_count_as_new(self, db):
        db.upsert_actifs([actif("1")])
        assert db.upsert_actifs([actif("1"), actif("2")]) == 1

    def test_duplicate_inside_one_batch_counts_once(self, db):
        assert db.upsert_actifs([actif("1"), actif("1")]) == 1
        assert db.count("actifs") == 1

    def test_first_seen_is_kept_and_last_seen_moves(self, db):
        db.upsert_actifs([actif("1")], now="2026-09-01T10:00:00+00:00")
        db.upsert_actifs([actif("1")], now="2026-09-05T10:00:00+00:00")

        row = db.new_since("actifs", "2000-01-01")[0]
        assert row["first_seen"] == "2026-09-01T10:00:00+00:00"
        assert row["last_seen"] == "2026-09-05T10:00:00+00:00"

    def test_existing_row_gets_updated_fields(self, db):
        db.upsert_actifs([actif("1", titre="Ancien titre")])
        db.upsert_actifs([actif("1", titre="Nouveau titre")])

        assert db.new_since("actifs", "2000-01-01")[0]["titre"] == "Nouveau titre"

    def test_empty_string_is_stored_as_null(self, db):
        db.upsert_actifs([actif("1", lieu="")])
        assert db.new_since("actifs", "2000-01-01")[0]["lieu"] is None

    def test_row_without_key_is_rejected(self, db):
        with pytest.raises(ValueError):
            db.upsert_actifs([{"titre": "pas de guid"}])
        assert db.count("actifs") == 0

    def test_liquidations_use_their_own_table_and_key(self, db):
        rows = [{"id": "A1", "entreprise": "ACME", "siren": "123456789"}]
        assert db.upsert_liquidations(rows) == 1
        assert db.upsert_liquidations(rows) == 0
        assert db.count("liquidations") == 1
        assert db.count("actifs") == 0


class TestNewSince:
    def test_returns_only_rows_first_seen_after_cutoff(self, db):
        db.upsert_actifs([actif("old")], now="2026-09-01T10:00:00+00:00")
        db.upsert_actifs([actif("new")], now="2026-09-10T10:00:00+00:00")

        result = db.new_since("actifs", "2026-09-05T00:00:00+00:00")

        assert [r["guid"] for r in result] == ["new"]

    def test_row_seen_again_is_not_new(self, db):
        db.upsert_actifs([actif("1")], now="2026-09-01T10:00:00+00:00")
        db.upsert_actifs([actif("1")], now="2026-09-10T10:00:00+00:00")

        assert db.new_since("actifs", "2026-09-05T00:00:00+00:00") == []

    def test_unknown_table_is_rejected(self, db):
        with pytest.raises(ValueError):
            db.new_since("users; DROP TABLE actifs", "2000-01-01")


def test_data_survives_reopening_the_file(tmp_path):
    path = tmp_path / "sub" / "test.db"  # le dossier "sub" est créé automatiquement

    with Storage(path) as db:
        db.upsert_actifs([actif("1")])

    with Storage(path) as db:
        assert db.count("actifs") == 1
