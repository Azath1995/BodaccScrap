import json
from datetime import date

import pytest

from es import borme

# --- Textes réels du BORME (septembre 2026) --------------------------------------------------------------------------
BADAJOZ = ("Cierre provisional hoja registral Art.485 TRLC. Insuficiencia de masa activa. Situación concursal. Procedimiento "
           "concursal 221/2026. FIRME: SI, Fecha de resolución 01/09/2026. Auto de conclusión del concurso. Insuficiencia de la "
           "masa activa. Juzgado: num. 0 SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE BADAJOZ. PLAZA Nº. 1. Juez: ANA "
           "PEREZ SOTO. Resoluciones: Se declara la conclusión del Concurso y el cierre provisional de la Hoja de la Sociedad. "
           "Datos registrales. S 8 , H BA 1, I/A 5 (10.09.26).")
VALENCIA = ("Situación concursal. Procedimiento concursal 215/2026. FIRME: Si, Fecha de resolución 24/03/2026. Auto de declaración "
            "de concurso. Voluntario. Juzgado: num. 0 SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE VALENCIA. PLAZA Nº. 3. "
            "Juez: JUAN MARTIN GIL. Administrador Concursal. Fecha 27/03/2026, NIF/CIF 12345678Z. GARCIA LOPEZ ANTONIO. "
            "Situación concursal. Procedimiento concursal 215/2026. FIRME: Si, Fecha de resolución 24/03/2026. Resoluciones acordando "
            "la intervención o suspensión de las factultades de administración y disposición del concursado. Juzgado: num. 0 "
            "SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE VALENCIA. PLAZA Nº. 3. Juez: JUAN MARTIN GIL. Datos "
            "registrales. S 8 , H V 1, I/A 2 (7.09.26).")
LIQUIDACION = ("Situación concursal. Procedimiento concursal 1800/2024. FIRME: SI, Fecha de resolución 14/01/2025. Auto de apertura "
               "de la fase de liquidación. Juzgado: num. 0 JUZGADO DE PRIMERA INSTANCIA NUMERO 4 DE GUADALAJARA. Juez: MARIA DIAZ "
               "CANO. Datos registrales. S 8 , H GU 2, I/A 3 (8.09.26).")
CONCLUSION_TRAS_LIQUIDACION = ("Situación concursal. Procedimiento concursal 1162/2021. FIRME: Si, Fecha de resolución 9/04/2025. Auto de "
                               "conclusión del concurso. Finalizacion de la fase de liquidacion. Juzgado: num. 0 JUZGADO DE LO MERCANTIL "
                               "NUMERO 1 DE PALMA. Juez: LUCIA ROMERO VIDAL. Datos registrales. S 8 , H PM 3, I/A 4 (8.09.26).")
SOLO_ADMINISTRADOR = ("Administrador Concursal. Fecha 14/03/2025, NIF/CIF 87654321X. SANCHEZ RUIZ PEDRO. "
                      "Datos registrales. S 8 , H BI 14992, I/A 13 ( 7.09.26).")
ADMIN_CON_SIGLAS = ("Situación concursal. Procedimiento concursal 281/2023. FIRME: SI, Fecha de resolución 16/07/2026. Auto de conclusión "
                    "del concurso. Juzgado: num. 0 JUZGADO DE LO MERCANTIL NUMERO 17 DE MADRID. Juez: ELENA MORENO PRIETO. Administrador "
                    "Concursal. Fecha 16/07/2026, NIF/CIF B87068326. FTI &amp; PARTNERS CORPORATE RECOVERY SPAIN S.L.P. Extinción. "
                    "Datos registrales. S 8 , H M 2, I/A 18 ( 9.09.26).")
LIBRE = ("Otros conceptos: SECCION MERCANTIL TI BARCELONA.PLAZA 9,CONCURSO VOLUNTARIO 429/2026,AUTO FIRME DE FECHA 24/04/2026, "
         "DECLARACION DE CONCURSO VOLUNTARIO;AUTO FIRME 30/06/2026:CONCLUSION DE CONCURSO Y CIERRE PROVISIONAL DE LA HOJA REGISTRAL. "
         "Datos registrales. S 8 , H B 548089, I/A 12 (10.09.26).")
MICRO = ("Otros conceptos: Apertura del procedimiento especial de microempresas 1026/2026 de la entidad \"CON TOQUE GOURMET, S.L. EN "
         "LIQUIDACION\", que tiene el carácter voluntario en su modalidad liquidativa, en la Sección Mercantil del Tribunal de "
         "Instancia de Madrid, Plaza 16. Datos registrales. S 8 , H M 716719, I/A 2 (11.09.26).")
MICRO_CON_FALTA = ("Otros conceptos: Auto firme de fecha 23 de julio de 2026 de la SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE "
                   "MADRID. PLAZA Nº 8 por el que se declara el procedimiento especial de microsempresas. Datos registrales. S 8 , H M 2, I/A 6.")
AUDITOR = "Nombramientos. Auditor: AUDIT IBERICA INSOLVENCIAS SLP. Datos registrales. S 8 , H J 14840, I/A 9 (14.09.26)."
OBJETO_CONCURSOS = ("Constitución. Comienzo de operaciones: 2.09.26. Objeto social: a) La participación, individualmente o "
                    "conjuntamente con terceros, en concursos, licitaciones y contratas. Datos registrales. S 8 , H PM 1, I/A 1.")


def entry(text, num="419092", empresa="IMPERPAVIMENTOS EXTREMEÑOS S.L."):
    return {"num": num, "empresa": empresa, "texto": text}


class TestIso:
    def test_converts_spanish_dates(self):
        assert borme.iso("01/09/2026") == "2026-09-01" and borme.iso("9/04/2025") == "2025-04-09"

    def test_keeps_or_empties_what_it_cannot_read(self):
        assert borme.iso("pas une date") == "pas une date" and borme.iso("  ") is None


class TestParseEntries:
    XML = ('<?xml version="1.0" encoding="UTF-8"?><documento><metadatos><identificador>X</identificador></metadatos><texto>'
           '<p class="articulo">418800 - GRANJA AVICOLA S.L.</p><p class="parrafo">Constitución. Capital: 3.000,00 Euros.</p>'
           '<p class="articulo">418801 - FTI &amp; PARTNERS SL.</p><p class="parrafo">Cambio de domicilio.</p>'
           '<p class="parrafo">Datos registrales. S 8.</p></texto></documento>')

    def test_one_entry_per_company_with_number_name_and_text(self):
        entries = borme.parse_entries(self.XML)
        assert [(e["num"], e["empresa"]) for e in entries] == [("418800", "GRANJA AVICOLA S.L"), ("418801", "FTI & PARTNERS SL")]

    def test_several_paragraphs_of_one_company_are_joined(self):
        assert borme.parse_entries(self.XML)[1]["texto"] == "Cambio de domicilio. Datos registrales. S 8."

    def test_broken_xml_gives_no_entry(self):
        assert borme.parse_entries("<documento><texto>") == [] and borme.parse_entries("") == []


class TestAdministrators:
    def test_name_nif_and_date(self):
        assert borme.administrators(VALENCIA) == [{"fecha": "2026-03-27", "nif": "12345678Z", "nombre": "GARCIA LOPEZ ANTONIO"}]

    def test_names_with_ampersand_and_dots_are_kept_whole(self):
        found = borme.administrators(ADMIN_CON_SIGLAS)
        assert found[0]["nombre"] == "FTI & PARTNERS CORPORATE RECOVERY SPAIN S.L.P" and found[0]["nif"] == "B87068326"

    def test_none_when_there_is_no_administrator(self):
        assert borme.administrators(BADAJOZ) == []


class TestExtractActs:
    def test_conclusion_with_court_judge_and_reason(self):
        (act,) = [a for a in borme.extract_acts(entry(BADAJOZ)) if a["tipo"] == "Auto de conclusión del concurso"][:1]
        assert act["procedimiento"] == "221/2026" and act["fecha_resolucion"] == "2026-09-01" and act["firme"] == "SI"
        assert act["juez"] == "ANA PEREZ SOTO" and act["detalle"] == "Insuficiencia de la masa activa"
        assert act["juzgado"] == "num. 0 SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE BADAJOZ. PLAZA Nº. 1"

    def test_declaration_has_its_modality_and_the_administrator(self):
        acts = borme.extract_acts(entry(VALENCIA))
        declaration = acts[0]
        assert declaration["tipo"] == "Auto de declaración de concurso" and declaration["modalidad"] == "Voluntario"
        assert declaration["administradores"] == "GARCIA LOPEZ ANTONIO (12345678Z)"
        assert len(acts) == 2 and acts[1]["tipo"].startswith("Resoluciones acordando la intervención")

    def test_each_structured_block_becomes_one_act(self):
        assert len(borme.extract_acts(entry(BADAJOZ))) == 1

    def test_an_administrator_alone_gives_an_appointment_act(self):
        (act,) = borme.extract_acts(entry(SOLO_ADMINISTRADOR))
        assert act["tipo"] == "Nombramiento de administrador concursal" and act["fecha_resolucion"] == "2025-03-14"
        assert act["administradores"] == "SANCHEZ RUIZ PEDRO (87654321X)"

    def test_free_text_concurso_is_kept_with_its_procedure_number(self):
        (act,) = borme.extract_acts(entry(LIBRE))
        assert act["tipo"] == "Otros conceptos (concurso)" and act["procedimiento"] == "429/2026"
        assert "DECLARACION DE CONCURSO VOLUNTARIO" in act["detalle"]

    def test_microenterprise_procedure_including_the_source_typo(self):
        assert borme.extract_acts(entry(MICRO))[0]["procedimiento"] == "1026/2026"
        (typo,) = borme.extract_acts(entry(MICRO_CON_FALTA))
        assert typo["tipo"] == "Otros conceptos (concurso)"

    @pytest.mark.parametrize("text", [AUDITOR, OBJETO_CONCURSOS, "Constitución. Objeto social: venta de vehículos.", ""])
    def test_entries_that_only_look_similar_give_nothing(self, text):
        assert borme.extract_acts(entry(text)) == []


class TestLiquidationFlag:
    def flag(self, text):
        return borme.extract_acts(entry(text))[0]["liquidacion"]

    def test_opening_of_the_liquidation_phase(self):
        assert self.flag(LIQUIDACION) == 1

    def test_a_conclusion_after_the_liquidation_phase_is_not_an_opening(self):
        assert self.flag(CONCLUSION_TRAS_LIQUIDACION) == 0

    def test_declaration_of_concurso_is_not_a_liquidation(self):
        assert self.flag(VALENCIA) == 0

    def test_microenterprise_liquidation_procedure(self):
        assert self.flag(MICRO) == 1


class TestActId:
    def test_stable_and_distinct(self):
        e = entry(BADAJOZ)
        act = borme.extract_acts(e)[0]
        first = borme.act_id("BORME-A-2026-181-06", e, act, 0)
        assert first == borme.act_id("BORME-A-2026-181-06", e, act, 0) and len(first) == 20
        assert first != borme.act_id("BORME-A-2026-181-06", e, act, 1)
        assert first != borme.act_id("BORME-A-2026-182-06", e, act, 0)


def summary(*documents, single=False):
    items = [{"identificador": d, "titulo": d.split("-")[-1], "url_pdf": {"texto": "pdf"}, "url_html": f"https://h/{d}",
              "url_xml": f"https://x/{d}"} for d in documents]
    section = {"codigo": "A", "nombre": "SECCIÓN PRIMERA", "item": items[0] if single else items}
    return json.dumps({"status": {"code": "200"}, "data": {"sumario": {"metadatos": {}, "diario": [{"numero": "1", "seccion": [section]}]}}})


class TestFetchSummary:
    def test_documents_of_the_day(self):
        docs = borme.fetch_summary(date(2026, 9, 18), lambda url, accept_json=False: (200, summary("BORME-A-2026-181-02", "BORME-A-2026-181-06")))
        assert [d["id"] for d in docs] == ["BORME-A-2026-181-02", "BORME-A-2026-181-06"]
        assert docs[0]["url_xml"] == "https://x/BORME-A-2026-181-02" and docs[0]["seccion"] == "A"

    def test_a_single_item_is_not_a_list_in_the_api(self):
        docs = borme.fetch_summary(date(2026, 9, 18), lambda url, accept_json=False: (200, summary("BORME-A-1", single=True)))
        assert [d["id"] for d in docs] == ["BORME-A-1"]

    def test_the_url_asks_for_json_and_carries_the_date(self):
        seen = []
        borme.fetch_summary(date(2026, 9, 5), lambda url, accept_json=False: seen.append((url, accept_json)) or (404, ""))
        assert seen == [("https://www.boe.es/datosabiertos/api/borme/sumario/20260905", True)]

    @pytest.mark.parametrize("status", [404, 204])
    def test_days_without_borme_give_nothing(self, status):
        assert borme.fetch_summary(date(2026, 9, 19), lambda url, accept_json=False: (status, "")) == []

    def test_a_server_error_is_raised_not_silenced(self):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            borme.fetch_summary(date(2026, 9, 18), lambda url, accept_json=False: (500, ""))

    def test_unreadable_answer_gives_nothing(self):
        assert borme.fetch_summary(date(2026, 9, 18), lambda url, accept_json=False: (200, "pas du json")) == []


def xml_doc(*entries):
    body = "".join(f'<p class="articulo">{n} - {name}</p><p class="parrafo">{text}</p>' for n, name, text in entries)
    return f'<?xml version="1.0" encoding="UTF-8"?><documento><texto>{body}</texto></documento>'


class TestCollectDay:
    def fake(self, docs):
        calls = []

        def fetch(url, accept_json=False):
            calls.append(url)
            if "sumario" in url:
                return 200, summary(*docs)
            return 200, xml_doc(("100", "EMPRESA UNO SL.", BADAJOZ), ("101", "OTRA SL.", "Constitución. Capital: 3.000 Euros."),
                                ("102", "TERCERA SL.", VALENCIA))

        fetch.calls = calls
        return fetch

    def test_only_insolvency_acts_are_returned_with_their_context(self):
        rows = borme.collect_day(date(2026, 9, 18), self.fake(["BORME-A-2026-181-06"]), pause=0, sleep=lambda s: None)
        assert {r["empresa"] for r in rows} == {"EMPRESA UNO SL", "TERCERA SL"}
        first = rows[0]
        assert first["fecha_publicacion"] == "2026-09-18" and first["borme_id"] == "BORME-A-2026-181-06"
        assert first["url_html"] == "https://h/BORME-A-2026-181-06" and first["empresa_num"] == "100"

    def test_ids_are_unique_within_a_day(self):
        rows = borme.collect_day(date(2026, 9, 18), self.fake(["BORME-A-2026-181-06"]), pause=0, sleep=lambda s: None)
        assert len({r["id"] for r in rows}) == len(rows)

    def test_pause_between_documents(self):
        sleeps = []
        borme.collect_day(date(2026, 9, 18), self.fake(["BORME-A-1", "BORME-A-2", "BORME-A-3"]), pause=2.5, sleep=sleeps.append)
        assert sleeps == [2.5, 2.5, 2.5]

    def test_a_document_that_fails_is_skipped_not_fatal(self):
        def fetch(url, accept_json=False):
            if "sumario" in url:
                return 200, summary("BORME-A-1", "BORME-A-2")
            return (500, "") if url.endswith("BORME-A-1") else (200, xml_doc(("100", "EMPRESA SL.", BADAJOZ)))
        rows = borme.collect_day(date(2026, 9, 18), fetch, pause=0, sleep=lambda s: None)
        assert {r["borme_id"] for r in rows} == {"BORME-A-2"}


class TestCollectDayRetry:
    def fetch_failing_first_time(self, times):
        state = {"n": 0}

        def fetch(url, accept_json=False):
            if "sumario" in url:
                return 200, summary("BORME-A-1")
            state["n"] += 1
            return (500, "") if state["n"] <= times else (200, xml_doc(("100", "EMPRESA SL.", BADAJOZ)))
        return fetch

    def test_one_failure_is_retried_and_the_day_stays_complete(self):
        stats, sleeps = {}, []
        rows = borme.collect_day(date(2026, 9, 18), self.fetch_failing_first_time(1), pause=2.0, sleep=sleeps.append, stats=stats)
        assert len(rows) == 1 and stats == {"documentos": 1, "fallidos": []}
        assert sleeps == [2.0, 6.0]                                    # pause normale, puis pause triple avant la seconde chance

    def test_two_failures_leave_the_document_unread_and_reported(self):
        stats = {}
        rows = borme.collect_day(date(2026, 9, 18), self.fetch_failing_first_time(2), pause=0, sleep=lambda s: None, stats=stats)
        assert rows == [] and stats == {"documentos": 1, "fallidos": ["BORME-A-1"]}

    def test_stats_are_optional(self):
        assert borme.collect_day(date(2026, 9, 18), self.fetch_failing_first_time(0), pause=0, sleep=lambda s: None)


class TestWorkers:
    DOCS = ["BORME-A-1", "BORME-A-2", "BORME-A-3"]

    def fetch(self, barrier=None, fail=()):
        def fetch(url, accept_json=False):
            if "sumario" in url:
                return 200, summary(*self.DOCS)
            document = url.rsplit("/", 1)[1]
            if barrier is not None:
                barrier.wait()                              # ne se débloque que si les trois requêtes sont en cours en même temps
            if document in fail:
                return 500, ""
            return 200, xml_doc((document[-1], f"EMPRESA {document[-1]} SL.", BADAJOZ))
        return fetch

    def test_the_documents_of_a_day_are_really_downloaded_at_the_same_time(self):
        import threading
        barrier = threading.Barrier(3, timeout=10)
        rows = borme.collect_day(date(2026, 9, 18), self.fetch(barrier), pause=0, sleep=lambda s: None, workers=3)
        assert len(rows) == 3                                # en séquentiel, la barrière n'aurait jamais lâché

    def test_the_result_is_identical_to_the_sequential_one_and_in_the_same_order(self):
        sequential = borme.collect_day(date(2026, 9, 18), self.fetch(), pause=0, sleep=lambda s: None, workers=1)
        parallel = borme.collect_day(date(2026, 9, 18), self.fetch(), pause=0, sleep=lambda s: None, workers=3)
        assert parallel == sequential and [r["borme_id"] for r in parallel] == self.DOCS

    def test_every_document_still_has_its_own_pause(self):
        sleeps = []
        borme.collect_day(date(2026, 9, 18), self.fetch(), pause=0.5, sleep=sleeps.append, workers=3)
        assert sleeps == [0.5, 0.5, 0.5]

    def test_a_failing_document_is_reported_and_the_others_are_kept(self):
        stats = {}
        rows = borme.collect_day(date(2026, 9, 18), self.fetch(fail={"BORME-A-2"}), pause=0, sleep=lambda s: None, stats=stats, workers=3)
        assert {r["borme_id"] for r in rows} == {"BORME-A-1", "BORME-A-3"} and stats == {"documentos": 3, "fallidos": ["BORME-A-2"]}

    def test_a_single_document_or_worker_needs_no_threads(self):
        assert len(borme.collect_day(date(2026, 9, 18), lambda url, accept_json=False: (200, summary("BORME-A-1")) if "sumario" in url
                                     else (200, xml_doc(("1", "X SL.", BADAJOZ))), pause=0, sleep=lambda s: None, workers=8)) == 1

    @pytest.mark.parametrize("workers", [0, -1, borme.MAX_WORKERS + 1])
    def test_workers_out_of_range_are_refused(self, workers):
        with pytest.raises(ValueError, match="workers"):
            borme.collect_day(date(2026, 9, 18), self.fetch(), pause=0, sleep=lambda s: None, workers=workers)


class TestPeriods:
    def test_days_between_is_inclusive(self):
        days = borme.days_between(date(2026, 9, 1), date(2026, 9, 3))
        assert days == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]

    def test_named_periods(self):
        today = date(2026, 9, 20)
        assert borme.period_days("today", today) == (today, today)
        assert borme.period_days("last_7_days", today) == (date(2026, 9, 14), today)
        assert borme.period_days("last_month", today) == (date(2026, 8, 22), today)
