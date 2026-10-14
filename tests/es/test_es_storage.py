import pytest

from es.storage import Storage


def row(id="a1", **extra):
    base = {"id": id, "fecha_publicacion": "2026-09-18", "provincia": "MADRID", "borme_id": "BORME-A-2026-181-28",
            "empresa_num": "420120", "empresa": "GEO DATA BLOCK SL", "procedimiento": "149/2026", "tipo": "Auto de declaración de concurso",
            "administradores": "GARCIA LOPEZ ANTONIO (12345678Z)", "liquidacion": 0}
    return {**base, **extra}


@pytest.fixture
def storage():
    with Storage(":memory:") as s:
        yield s


class TestUpsert:
    def test_counts_new_rows_only(self, storage):
        assert storage.upsert([row("a1"), row("a2")], now="2026-09-18T10:00:00+00:00") == 2
        assert storage.upsert([row("a2"), row("a3")], now="2026-09-19T10:00:00+00:00") == 1
        assert storage.count() == 3

    def test_first_seen_never_changes_but_last_seen_and_content_do(self, storage):
        storage.upsert([row("a1", firme="NO")], now="2026-09-18T10:00:00+00:00")
        storage.upsert([row("a1", firme="SI")], now="2026-09-25T10:00:00+00:00")
        (saved,) = storage.rows()
        assert saved["first_seen"] == "2026-09-18T10:00:00+00:00" and saved["last_seen"] == "2026-09-25T10:00:00+00:00"
        assert saved["firme"] == "SI"

    def test_empty_text_is_stored_as_null_and_liquidation_stays_an_integer(self, storage):
        storage.upsert([row("a1", juez="", liquidacion=1)])
        (saved,) = storage.rows()
        assert saved["juez"] is None and saved["liquidacion"] == 1

    def test_a_row_without_an_id_is_refused(self, storage):
        with pytest.raises(Exception):
            storage.upsert([{"empresa": "X"}])

    def test_nothing_to_write(self, storage):
        assert storage.upsert([]) == 0 and storage.count() == 0


class TestDays:
    def test_days_done_are_remembered_and_marking_twice_is_harmless(self, storage):
        assert storage.days_done() == set()
        storage.mark_day("2026-09-18", 33, 20)
        storage.mark_day("2026-09-18", 34, 21)
        storage.mark_day("2026-09-17", 0, 0)
        assert storage.days_done() == {"2026-09-17", "2026-09-18"} and storage.count("dias") == 2

    def test_the_day_row_keeps_its_counts(self, storage):
        storage.mark_day("2026-09-18", 33, 20)
        row = dict(storage.conn.execute("SELECT * FROM dias").fetchone())
        assert (row["fecha"], row["documentos"], row["actos"]) == ("2026-09-18", 33, 20)


class TestRows:
    def test_filter_and_order(self, storage):
        storage.upsert([row("a1", fecha_publicacion="2026-09-10"), row("a2", fecha_publicacion="2026-09-18"),
                        row("a3", fecha_publicacion="2026-09-15", liquidacion=1)])
        assert [r["id"] for r in storage.rows()] == ["a2", "a3", "a1"]                  # les plus récents d'abord
        assert [r["id"] for r in storage.rows("liquidacion = 1")] == ["a3"]
        assert [r["id"] for r in storage.rows("fecha_publicacion >= ?", ["2026-09-15"])] == ["a2", "a3"]

    def test_the_database_file_and_its_folder_are_created(self, tmp_path):
        path = tmp_path / "es" / "borme.db"
        with Storage(path) as s:
            s.upsert([row()])
        assert path.exists()
