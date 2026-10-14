import csv
import json
from datetime import date

import pytest

from es import report, update
from es.storage import Storage

BADAJOZ = ("Situación concursal. Procedimiento concursal 221/2026. FIRME: SI, Fecha de resolución 01/09/2026. Auto de conclusión del "
           "concurso. Juzgado: num. 0 JUZGADO DE LO MERCANTIL DE BADAJOZ. Juez: ANA PEREZ. Administrador Concursal. Fecha "
           "01/09/2026, NIF/CIF 11111111A. ALFA ADMINISTRADOR. Datos registrales. S 8.")
LIQUIDACION = ("Situación concursal. Procedimiento concursal 1800/2024. FIRME: SI, Fecha de resolución 14/01/2025. Auto de apertura de "
               "la fase de liquidación. Juzgado: num. 0 JUZGADO DE PRIMERA INSTANCIA 4 DE GUADALAJARA. Juez: MARIA DIAZ. "
               "Administrador Concursal. Fecha 14/01/2025, NIF/CIF 11111111A. ALFA ADMINISTRADOR. Datos registrales. S 8.")
DECLARACION = ("Situación concursal. Procedimiento concursal 5/2026. FIRME: SI, Fecha de resolución 02/09/2026. Auto de declaración de "
               "concurso. Voluntario. Juzgado: num. 0 JUZGADO DE LO MERCANTIL 1 DE SEVILLA. Juez: PEDRO RUIZ. Administrador "
               "Concursal. Fecha 02/09/2026, NIF/CIF 22222222B. BETA CONCURSAL SLP. Datos registrales. S 8.")


def summary(*docs):
    items = [{"identificador": d, "titulo": t, "url_html": f"https://h/{d}", "url_xml": f"https://x/{d}"} for d, t in docs]
    return json.dumps({"data": {"sumario": {"diario": [{"seccion": [{"codigo": "A", "item": items}]}]}}})


def xml(*entries):
    return "<documento><texto>" + "".join(f'<p class="articulo">{n} - {e}</p><p class="parrafo">{t}</p>' for n, e, t in entries) + "</texto></documento>"


def fake_borme():
    """Vendredi 18 : deux provinces ; samedi 19 : pas de BORME (404)."""
    pages = {
        "https://www.boe.es/datosabiertos/api/borme/sumario/20260918": summary(("BORME-A-2026-181-06", "BADAJOZ"), ("BORME-A-2026-181-41", "SEVILLA")),
        "https://x/BORME-A-2026-181-06": xml(("100", "ALFA SL.", BADAJOZ), ("101", "SANS PROBLEME SL.", "Constitución. Capital: 3.000 Euros."),
                                             ("102", "GAMA SA.", LIQUIDACION)),
        "https://x/BORME-A-2026-181-41": xml(("200", "BETA SL.", DECLARACION)),
    }
    calls = []

    def fetch(url, accept_json=False):
        calls.append(url)
        return (200, pages[url]) if url in pages else (404, "")

    fetch.calls = calls
    return fetch


@pytest.fixture
def db(tmp_path):
    return tmp_path / "es" / "borme.db"


def collect(db, *args, fetch=None):
    """Collecte du BORME seulement : ces tests ne doivent jamais toucher au vrai réseau d'eactivos."""
    fetch = fetch or fake_borme()
    update.main(["--db", str(db), "--pause", "0", "--skip-actifs", *args], fetch=fetch, sleep=lambda s: None, today=date(2026, 9, 19))
    return fetch


class TestUpdate:
    def test_collects_the_range_and_skips_days_without_borme(self, db, capsys):
        collect(db, "--start", "2026-09-18", "--end", "2026-09-19")
        out = capsys.readouterr().out
        assert "2026-09-18 : 3 acte(s) de procédure collective, 3 nouveau(x)" in out and "2026-09-19 : 0 acte(s)" in out
        with Storage(db) as s:
            assert s.count() == 3

    def test_running_twice_creates_no_duplicates(self, db, capsys):
        collect(db, "--start", "2026-09-18", "--end", "2026-09-18")
        assert "3 nouveau(x)" in capsys.readouterr().out
        collect(db, "--start", "2026-09-18", "--end", "2026-09-18", "--refresh")
        second = capsys.readouterr().out
        assert "3 acte(s) de procédure collective, 0 nouveau(x)" in second and "Base : 3 acte(s)" in second
        with Storage(db) as s:
            assert s.count() == 3

    def test_named_period_is_relative_to_today(self, db):
        fetch = collect(db, "--period", "last_7_days")
        days = [u.rsplit("/", 1)[1] for u in fetch.calls if "sumario" in u]
        assert days[0] == "20260913" and days[-1] == "20260919" and len(days) == 7

    def test_start_and_end_go_together(self, db):
        with pytest.raises(SystemExit):
            update.main(["--db", str(db), "--start", "2026-09-01"], fetch=fake_borme())

    def test_start_must_not_follow_end(self, db):
        with pytest.raises(SystemExit):
            update.main(["--db", str(db), "--start", "2026-09-05", "--end", "2026-09-01"], fetch=fake_borme())

    def test_invalid_date_is_refused(self, db):
        with pytest.raises(SystemExit):
            update.main(["--db", str(db), "--start", "18/09/2026", "--end", "2026-09-19"], fetch=fake_borme())

    def test_a_failing_day_is_reported_and_the_others_are_kept(self, db, capsys):
        good = fake_borme()

        def fetch(url, accept_json=False):
            return (500, "") if url.endswith("20260917") else good(url, accept_json)

        update.main(["--db", str(db), "--pause", "0", "--skip-actifs", "--start", "2026-09-17", "--end", "2026-09-18"],
                    fetch=fetch, sleep=lambda s: None)
        out = capsys.readouterr().out
        assert "2026-09-17 : ERREUR" in out and "2026-09-18 : 3 acte(s)" in out


class TestWorkersOption:
    def test_parallel_collection_stores_exactly_what_the_sequential_one_does(self, tmp_path, capsys):
        sequential, parallel = tmp_path / "seq.db", tmp_path / "par.db"
        collect(sequential, "--start", "2026-09-18", "--end", "2026-09-18")
        capsys.readouterr()
        collect(parallel, "--start", "2026-09-18", "--end", "2026-09-18", "--workers", "3")
        assert "3 requêtes en parallèle" in capsys.readouterr().out
        with Storage(sequential) as a, Storage(parallel) as b:
            assert {r["id"] for r in a.rows()} == {r["id"] for r in b.rows()} and b.count() == 3 and b.days_done() == {"2026-09-18"}

    def test_the_sequential_header_does_not_mention_parallelism(self, db, capsys):
        collect(db, "--start", "2026-09-18", "--end", "2026-09-18")
        assert "en parallèle" not in capsys.readouterr().out

    @pytest.mark.parametrize("value", ["0", "-2", "9", "abc"])
    def test_invalid_worker_counts_are_refused(self, db, value):
        with pytest.raises(SystemExit):
            update.main(["--db", str(db), "--workers", value], fetch=fake_borme())


def summary_calls(fetch):
    return [u.rsplit("/", 1)[1] for u in fetch.calls if "sumario" in u]


class TestResume:
    """Une longue collecte doit pouvoir s'interrompre et reprendre sans tout relire."""

    def test_a_complete_day_is_not_read_again(self, db, capsys):
        collect(db, "--start", "2026-09-18", "--end", "2026-09-18")
        capsys.readouterr()
        second = collect(db, "--start", "2026-09-18", "--end", "2026-09-19")
        out = capsys.readouterr().out
        assert summary_calls(second) == ["20260919"] and "1 jour(s) ignoré(s)" in out

    def test_refresh_reads_complete_days_again(self, db):
        collect(db, "--start", "2026-09-18", "--end", "2026-09-18")
        again = collect(db, "--start", "2026-09-18", "--end", "2026-09-18", "--refresh")
        assert summary_calls(again) == ["20260918"]

    def test_days_without_borme_are_marked_done_too(self, db):
        collect(db, "--start", "2026-09-12", "--end", "2026-09-12")           # un samedi : 404
        with Storage(db) as s:
            assert s.days_done() == {"2026-09-12"}
        assert summary_calls(collect(db, "--start", "2026-09-12", "--end", "2026-09-12")) == []

    def test_the_current_day_is_never_marked_done_because_it_may_still_grow(self, db):
        collect(db, "--start", "2026-09-19", "--end", "2026-09-19")            # today = 2026-09-19 dans ces tests
        with Storage(db) as s:
            assert s.days_done() == set()
        assert summary_calls(collect(db, "--start", "2026-09-19", "--end", "2026-09-19")) == ["20260919"]

    def test_future_days_are_neither_read_nor_marked(self, db, capsys):
        fetch = collect(db, "--start", "2026-09-20", "--end", "2026-09-22")
        assert fetch.calls == [] and "3 jour(s) ignoré(s)" in capsys.readouterr().out
        with Storage(db) as s:
            assert s.days_done() == set()

    def test_a_day_with_an_unreadable_document_is_kept_incomplete_and_read_again(self, db, capsys):
        good = fake_borme()

        def flaky(url, accept_json=False):
            return (500, "") if url.endswith("BORME-A-2026-181-41") else good(url, accept_json)

        collect(db, "--start", "2026-09-18", "--end", "2026-09-18", fetch=flaky)
        out = capsys.readouterr().out
        assert "1 document(s) illisible(s), jour à relire" in out and "1 jour(s) incomplet(s)" in out
        with Storage(db) as s:
            assert s.days_done() == set() and s.count() == 2                     # les actes lus sont gardés
        repaired = collect(db, "--start", "2026-09-18", "--end", "2026-09-18")
        assert summary_calls(repaired) == ["20260918"]
        with Storage(db) as s:
            assert s.days_done() == {"2026-09-18"} and s.count() == 3


class TestUpdateActifs:
    """`es.update` fait comme `bodacc.update` : les liquidations (BORME) ET les annonces (lots eactivos)."""

    def run(self, db, *args, borme_fetch=None, actifs=None):
        import test_es_eactivos as ea
        borme_fetch = borme_fetch or fake_borme()
        actifs = actifs or ea.network()
        update.main(["--db", str(db), "--pause", "0", *args], fetch=borme_fetch, sleep=lambda s: None,
                    today=date(2026, 9, 19), actifs_fetch=actifs)
        return borme_fetch, actifs

    def test_both_sources_by_default(self, db, capsys):
        borme_fetch, actifs = self.run(db, "--start", "2026-09-18", "--end", "2026-09-18", "--actifs-since", "2026-01-01")
        out = capsys.readouterr().out
        assert "Liquidations (BORME)" in out and "Actifs (eactivos)" in out
        assert "→ 3 lus, 3 nouveaux dont 3 véhicule(s)" in out and "Vehículo Renault Master en Mejorada del Campo (Madrid)" in out
        with Storage(db) as s:
            assert s.count() == 3 and s.count("lotes") == 3
        assert summary_calls(borme_fetch) == ["20260918"] and actifs.calls

    def test_skip_liquidations_reads_only_the_lots(self, db, capsys):
        borme_fetch, _ = self.run(db, "--skip-liquidations", "--actifs-since", "2026-01-01")
        out = capsys.readouterr().out
        assert "Liquidations" not in out and "Actifs (eactivos)" in out and borme_fetch.calls == []

    def test_skip_borme_is_an_alias_of_skip_liquidations(self, db, capsys):
        borme_fetch, _ = self.run(db, "--skip-borme", "--actifs-since", "2026-01-01")
        assert borme_fetch.calls == [] and "Liquidations" not in capsys.readouterr().out

    def test_skip_actifs_reads_only_the_borme(self, db, capsys):
        _, actifs = self.run(db, "--skip-actifs", "--start", "2026-09-18", "--end", "2026-09-18")
        out = capsys.readouterr().out
        assert "Actifs" not in out and "Liquidations (BORME)" in out and actifs.calls == []

    def test_skipping_everything_touches_no_network(self, db, capsys):
        borme_fetch, actifs = self.run(db, "--skip-liquidations", "--skip-actifs")
        assert borme_fetch.calls == [] and actifs.calls == [] and capsys.readouterr().out == ""

    def test_second_run_finds_no_new_lot(self, db, capsys):
        self.run(db, "--skip-liquidations", "--actifs-since", "2026-01-01")
        capsys.readouterr()
        self.run(db, "--skip-liquidations", "--actifs-since", "2026-01-01")
        assert "→ 2 lus, 0 nouveaux dont 0 véhicule(s)" in capsys.readouterr().out        # les 2 lots vivants sont relus, le clos non

    def test_actifs_since_narrows_the_window(self, db, capsys):
        self.run(db, "--skip-liquidations", "--actifs-since", "2026-09-01")
        assert "→ 2 lus, 2 nouveaux" in capsys.readouterr().out

    def test_default_window_is_180_days_before_today(self, db, capsys):
        self.run(db, "--skip-liquidations")
        assert "depuis 2026-03-23" in capsys.readouterr().out

    def test_a_forbidden_lot_is_reported(self, db, capsys):
        import test_es_eactivos as ea
        self.run(db, "--skip-liquidations", "--actifs-since", "2026-01-01", actifs=ea.network(robots=ea.ROBOTS + "Disallow: /DVXWG6K9/\n"))
        assert "1 interdit(s) par robots.txt" in capsys.readouterr().out

    def test_same_option_names_as_the_french_update(self):
        """Une même commande dans les deux pays : ces options existent des deux côtés."""
        from bodacc import update as fr_update
        for module in (update, fr_update):
            with pytest.raises(SystemExit) as exit_info:
                module.main(["--help"])
            assert exit_info.value.code == 0


@pytest.fixture
def filled(db):
    collect(db, "--start", "2026-09-18", "--end", "2026-09-18")
    return db


def run_report(db, *args):
    report.main(["--db", str(db), *args])


class TestReportLiquidations:
    def test_lists_the_latest_acts(self, filled, capsys):
        run_report(filled, "liquidations")
        out = capsys.readouterr().out
        assert "ALFA SL" in out and "BETA SL" in out and "3 acte(s)" in out and "ALFA ADMINISTRADOR (11111111A)" in out

    def test_filter_by_type(self, filled, capsys):
        run_report(filled, "liquidations", "--type", "liquidation")
        out = capsys.readouterr().out
        assert "GAMA SA" in out and "ALFA SL" not in out and "1 acte(s)" in out
        run_report(filled, "liquidations", "--type", "declaration")
        assert "BETA SL" in capsys.readouterr().out

    def test_filter_by_place_ignores_case_and_accents(self, filled, capsys):
        run_report(filled, "liquidations", "--lieu", "sevilla")
        out = capsys.readouterr().out
        assert "BETA SL" in out and "ALFA SL" not in out

    def test_filter_by_company_and_date(self, filled, capsys):
        run_report(filled, "liquidations", "--entreprise", "gama")
        assert "1 acte(s)" in capsys.readouterr().out
        run_report(filled, "liquidations", "--since", "2030-01-01")
        assert "Aucun acte." in capsys.readouterr().out

    def test_csv_export_has_every_row_and_the_link_to_the_official_text(self, filled, tmp_path, capsys):
        target = tmp_path / "liquidations.csv"
        run_report(filled, "liquidations", "--csv", str(target), "--limit", "1")
        with open(target, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3 and all(r["url_html"].startswith("https://h/BORME-A-2026-181-") for r in rows)

    def test_empty_database(self, db, capsys):
        run_report(db, "liquidations")
        assert "Aucun acte." in capsys.readouterr().out


class TestReportUnmatched:
    """`unmatched` : comme en France, les liquidateurs dont on ne lit pas encore les ventes (ici : tous les administrateurs)."""

    def test_administrators_are_ranked_by_distinct_procedures(self, filled, capsys):
        run_report(filled, "unmatched")
        out = capsys.readouterr().out
        ranking = [l for l in out.splitlines() if l.startswith(("ALFA ADMINISTRADOR", "BETA CONCURSAL"))]
        assert len(ranking) == 2
        assert ranking[0].startswith("ALFA ADMINISTRADOR (11111111A)") and ranking[0].rstrip().endswith("2")   # deux procédures
        assert ranking[1].startswith("BETA CONCURSAL SLP (22222222B)") and ranking[1].rstrip().endswith("1")
        assert "2 administrateur(s) distinct(s)" in out

    def test_the_same_administrator_under_two_spellings_is_counted_once(self, db):
        """Même NIF, deux écritures (« SLP » et « SOCIEDAD LIMITADA PROFESIONAL ») : une seule ligne, procédures additionnées."""
        with Storage(db) as storage:
            storage.upsert([
                {"id": "p1", "fecha_publicacion": "2026-09-01", "provincia": "MADRID", "empresa_num": "1", "procedimiento": "1/2025",
                 "administradores": "PKF ATTEST CONCURSAL SLP (B95669628)"},
                {"id": "p2", "fecha_publicacion": "2026-09-02", "provincia": "MADRID", "empresa_num": "2", "procedimiento": "2/2025",
                 "administradores": "PKF ATTEST CONCURSAL SOCIEDAD LIMITADA PROFESIONAL (B95669628)"},
                {"id": "p3", "fecha_publicacion": "2026-09-03", "provincia": "MADRID", "empresa_num": "3", "procedimiento": "3/2025",
                 "administradores": "PKF ATTEST CONCURSAL SLP (B95669628)"}])
            assert report.top_administrators(storage) == [("PKF ATTEST CONCURSAL SLP (B95669628)", 3)]   # l'écriture la plus fréquente

    def test_administrators_without_a_nif_are_grouped_by_name(self, db):
        with Storage(db) as storage:
            storage.upsert([{"id": "q1", "provincia": "MADRID", "empresa_num": "1", "procedimiento": "1/2025", "administradores": "Juan Pérez"},
                            {"id": "q2", "provincia": "MADRID", "empresa_num": "2", "procedimiento": "2/2025", "administradores": "JUAN PEREZ"}])
            assert [n for _, n in report.top_administrators(storage)] == [2]

    def test_csv_exports_the_liquidations_that_have_an_administrator(self, filled, tmp_path, capsys):
        target = tmp_path / "pistes.csv"
        run_report(filled, "unmatched", "--csv", str(target))
        with open(target, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3 and all(r["administradores"] for r in rows)
        assert "3 liquidation(s) avec administrateur" in capsys.readouterr().out

    def test_empty_database(self, db, capsys):
        run_report(db, "unmatched")
        assert "Aucun administrateur." in capsys.readouterr().out

    def test_old_spanish_command_names_are_gone(self, filled):
        for old in ("actos", "administradores", "lotes", "vinculos"):
            with pytest.raises(SystemExit):
                run_report(filled, old)
