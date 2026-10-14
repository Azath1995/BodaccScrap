import pytest

from es import eactivos, report
from es.storage import Storage

# --- Le vrai robots.txt d'eactivos.com (21 septembre 2026) --------------------------------------------------------------
ROBOTS = """User-agent: *

Sitemap: https://www.eactivos.com/sitemap.xml

Disallow: /favoritos/crear/*
Disallow: /favoritos/eliminar/*
Disallow: */solicitar-participacion-con-deposito$
Disallow: */con-certificado$
Disallow: */login/secure$
Disallow: */mejor-puja$
Disallow: */liquidaciones-similares$
"""

# --- Textes réels de trois fiches (deux ouvertes ou à venir, une close) ---------------------------------------------------
MASTER = ("Portada Liquidaciones Vehículos Vehículo Renault Master en Mejorada del Campo (Madrid) Vehículo Renault Master en Mejorada "
          "del Campo (Madrid) Mejorada del Campo, Madrid Guardar Guardado Compartir Imprimir Próximamente Próximamente Descripción "
          "Características Gastos y cargas Documentación Descripción Proced. concursal 470/2025 Sección de lo Mercantil del Tribunal "
          "de Instancia de Madrid Plaza Nº 16 Subasta de un vehículo Renault Master , con matrícula 2222CCC, procedente de la "
          "mercantil Ingeniería Técnica de Elevación, S.L., dedicada a la fabricación de maquinaria de elevación y manipulación. Se "
          "encuentra ubicado en las instalaciones de la concursada. Características UBICACIÓN Mejorada del Campo (Madrid) VISITAS En "
          "espera de información Gastos y cargas Todos los gastos. VALORACIÓN 4.600€ GASTOS DE GESTIÓN NO INCLUIDOS 5% sobre la oferta")
PIAGGIO = ("Portada Liquidaciones Vehículos Motocicleta Piaggio en Mislata (Valencia) Motocicleta Piaggio en Mislata (Valencia) Mislata, "
           "Valencia Guardar Guardado Compartir Imprimir Empieza el 21/09/2026 (Europa/Madrid) d h m s Próximamente Próximamente "
           "Descripción Características Descripción Concurso: 454/2025 Juzgado Mercantil 4 de Valencia Subasta de una motocicleta "
           "Piaggio en la localidad de Mislata. Características UBICACIÓN Mislata (Valencia) VISITAS Si desea concertar una visita "
           "Gastos y cargas Todos los gastos. VALORACIÓN 700€ GASTOS DE GESTIÓN NO INCLUIDOS 5% Documentación Auto Próximamente "
           "Empieza el 21/09/2026 d h m s VALORACIÓN 700€ PRECIO DE SALIDA 0€ Incremento de puja mínimo 1€")
CLOSED = ("Portada Liquidaciones Vehículos Furgoneta Volkswagen Caddy Vaya, la subasta se ha cerrado. Furgoneta Volkswagen Caddy "
          "VALORACIÓN 3.000€ Ver otras ventas y subastas Participar en nombre de: Nombre propio € Incremento de puja mínimo 1€ Pujar")

MASTER_URL = "https://www.eactivos.com/BRZG3MJX/vehiculo-renault-master-en-mejorada-del-campo-madrid"
PIAGGIO_URL = "https://www.eactivos.com/JK7JWY1X/motocicleta-piaggio-en-mislata-valencia"
CLOSED_URL = "https://www.eactivos.com/DVXWG6K9/furgoneta-volkswagen-caddy"


def page(title, body, liquidation_id=25353):
    return (f'<html><head><meta property="og:title" content="\n\t{title}\n"></head><body><p>{body}</p>'
            f"<script>const isActive = ''; const liquidationId = {liquidation_id}; const x = 'Próximamente VALORACIÓN 9€';</script>"
            f"<style>.a{{}} Próximamente</style></body></html>")


MASTER_PAGE = page("Vehículo Renault Master en Mejorada del Campo (Madrid)", MASTER, 25353)
PIAGGIO_PAGE = page("Motocicleta Piaggio en Mislata (Valencia)", PIAGGIO, 25356)
CLOSED_PAGE = page("Subasta de furgoneta Volkswagen Caddy", CLOSED, 394)


class TestRobots:
    def test_the_real_file_forbids_actions_and_two_subpages_only(self):
        robots = eactivos.Robots(ROBOTS)
        for path in ("/listado-de-vehiculos", "/listado-de-liquidaciones/obtener", "/sitemap.liquidations.xml", "/DVXWG6K9/furgoneta-volkswagen-caddy"):
            assert robots.allowed(path), path
        for path in ("/DVXWG6K9/furgoneta/mejor-puja", "/DVXWG6K9/furgoneta/liquidaciones-similares", "/favoritos/crear/12",
                     "/394/solicitar-participacion-con-deposito", "/x/login/secure"):
            assert not robots.allowed(path), path

    def test_end_of_string_anchor_only_matches_the_end(self):
        robots = eactivos.Robots("User-agent: *\nDisallow: */mejor-puja$\n")
        assert not robots.allowed("/a/mejor-puja") and robots.allowed("/a/mejor-puja/historial") and robots.allowed("/a/mejor-pujas")

    def test_longest_rule_wins_and_allow_wins_a_tie(self):
        robots = eactivos.Robots("User-agent: *\nDisallow: /privado/\nAllow: /privado/public/\n")
        assert robots.allowed("/privado/public/x") and not robots.allowed("/privado/y")
        assert eactivos.Robots("User-agent: *\nDisallow: /a\nAllow: /a\n").allowed("/a")

    def test_disallow_everything(self):
        assert not eactivos.Robots("User-agent: *\nDisallow: /\n").allowed("/anything")

    def test_empty_disallow_and_missing_file_allow_everything(self):
        assert eactivos.Robots("User-agent: *\nDisallow:\n").allowed("/x") and eactivos.Robots("").allowed("/x")

    def test_the_group_naming_our_robot_replaces_the_general_one(self):
        text = "User-agent: *\nDisallow: /\n\nUser-agent: BodaccScrap\nAllow: /\n"
        assert eactivos.Robots(text).allowed("/x")

    def test_rules_of_other_robots_do_not_apply(self):
        assert eactivos.Robots("User-agent: Baiduspider\nDisallow: /\n").allowed("/x")

    def test_several_user_agent_lines_form_one_group(self):
        text = "User-agent: Baiduspider\nUser-agent: *\nDisallow: /secret\n"
        assert not eactivos.Robots(text).allowed("/secret")

    def test_comments_are_ignored(self):
        assert not eactivos.Robots("User-agent: *  # tous\nDisallow: /x # non\n").allowed("/x")


class TestSitemapAndUrls:
    def test_parse_sitemap(self):
        xml = ("<urlset><url><loc>https://www.eactivos.com/AAAAAAAA/furgoneta-x</loc><lastmod>2026-07-27</lastmod>"
               "<changefreq>daily</changefreq></url><url><loc>https://www.eactivos.com/BBBBBBBB/vivienda</loc>"
               "<lastmod>2013-09-18</lastmod></url></urlset>")
        assert eactivos.parse_sitemap(xml) == [("https://www.eactivos.com/AAAAAAAA/furgoneta-x", "2026-07-27"),
                                               ("https://www.eactivos.com/BBBBBBBB/vivienda", "2013-09-18")]

    @pytest.mark.parametrize("slug, expected", [
        ("furgoneta-volkswagen-caddy", True), ("lote-de-vehiculos-industriales-para-transporte", True), ("motocicleta-piaggio-en-mislata-valencia", True),
        ("turismo-seat-modelo-ibiza-1-9-sdi-5p-en-carlet", True), ("vivienda-en-naquera-finca-15865", False),
        ("local-comercial-en-valladolid", False), ("motor-electrico", False), ("cochera-en-madrid", False)])
    def test_vehicle_words_are_whole_words_of_the_address(self, slug, expected):
        assert eactivos.is_vehicle_url(f"https://www.eactivos.com/ABCD1234/{slug}") is expected

    def test_lot_code(self):
        assert eactivos.lot_code(MASTER_URL) == "BRZG3MJX" and eactivos.lot_code("https://www.eactivos.com/iso-27001") is None

    @pytest.mark.parametrize("text, value", [("4.600", 4600), ("700", 700), ("1.234,50", 1234), ("0", 0), ("abc", None)])
    def test_to_int(self, text, value):
        assert eactivos.to_int(text) == value


class TestParseLot:
    def test_open_lot_with_procedure_court_debtor_and_plate(self):
        lot = eactivos.parse_lot(MASTER_PAGE, MASTER_URL, "2026-09-17")
        assert lot["codigo"] == "BRZG3MJX" and lot["liquidation_id"] == "25353"
        assert lot["titulo"] == "Vehículo Renault Master en Mejorada del Campo (Madrid)" and lot["categoria"] == "Vehículos"
        assert lot["estado"] == "proxima" and lot["ubicacion"] == "Mejorada del Campo (Madrid)" and lot["valoracion"] == 4600
        assert lot["procedimiento"] == "470/2025"
        assert lot["juzgado"] == "Sección de lo Mercantil del Tribunal de Instancia de Madrid Plaza Nº 16"
        assert lot["concursada"] == "Ingeniería Técnica de Elevación, S.L." and lot["matricula"] == "2222CCC"
        assert lot["url"] == MASTER_URL and lot["fecha_sitemap"] == "2026-09-17"

    def test_concurso_form_with_start_date_and_opening_price(self):
        lot = eactivos.parse_lot(PIAGGIO_PAGE, PIAGGIO_URL)
        assert (lot["procedimiento"], lot["juzgado"]) == ("454/2025", "Juzgado Mercantil 4 de Valencia")
        assert lot["inicio"] == "2026-09-21" and lot["valoracion"] == 700 and lot["precio_salida"] == 0
        assert lot["estado"] == "proxima" and lot["concursada"] is None and lot["matricula"] is None

    def test_closed_lot_has_little_information(self):
        lot = eactivos.parse_lot(CLOSED_PAGE, CLOSED_URL)
        assert lot["estado"] == "cerrada" and lot["valoracion"] == 3000 and lot["procedimiento"] is None
        assert lot["titulo"] == "Subasta de furgoneta Volkswagen Caddy" and lot["ubicacion"] is None

    def test_a_lot_that_is_neither_closed_nor_upcoming_is_open(self):
        body = MASTER.replace("Próximamente Próximamente ", "")
        assert eactivos.parse_lot(page("Vehículo Renault Master en Mejorada del Campo (Madrid)", body), MASTER_URL)["estado"] == "abierta"

    def test_scripts_and_styles_do_not_count_as_text(self):
        # « Próximamente » et « VALORACIÓN 9€ » n'existent que dans un <script> et un <style> de la page de test
        lot = eactivos.parse_lot(page("Furgoneta X", CLOSED.replace("Vaya, la subasta se ha cerrado. ", "")), CLOSED_URL)
        assert lot["estado"] == "abierta" and lot["valoracion"] == 3000

    def test_unreadable_pages_give_none(self):
        assert eactivos.parse_lot("<html>rien</html>", MASTER_URL) is None
        assert eactivos.parse_lot(MASTER_PAGE, "https://www.eactivos.com/iso-27001") is None

    def test_no_description_text_or_photo_is_kept(self):
        lot = eactivos.parse_lot(MASTER_PAGE, MASTER_URL)
        assert not any("Advertencia" in str(v) or "img" in str(v) for v in lot.values())
        assert set(lot) <= {"codigo", *__import__("es.storage", fromlist=["LOTE_COLUMNS"]).LOTE_COLUMNS}


class TestProcedureFormats:
    """Les cinq formats réellement vus sur les fiches ouvertes (21 septembre 2026)."""

    @pytest.mark.parametrize("text, procedure, court", [
        ("Descripción Proced. concursal 470/2025 Sección de lo Mercantil del Tribunal de Instancia de Madrid Plaza Nº 16 Subasta de un vehículo",
         "470/2025", "Sección de lo Mercantil del Tribunal de Instancia de Madrid Plaza Nº 16"),
        ("Descripción Concurso: 454/2025 Juzgado Mercantil 4 de Valencia Subasta de una motocicleta Piaggio", "454/2025", "Juzgado Mercantil 4 de Valencia"),
        ("Descripción Autos 1192.5/2025 Juzgado de lo Mercantil Nº4 de Sevilla Subasta de un vehículo Renault Clio", "1192.5/2025",
         "Juzgado de lo Mercantil Nº4 de Sevilla"),
        ("Descripción Autos 286/2025 Juzgado de lo Mercantil Nº 2 de Badajoz (Sede en Mérida) Venta de un vehículo Mercedes", "286/2025",
         "Juzgado de lo Mercantil Nº 2 de Badajoz (Sede en Mérida)"),
        ("Descripción Concurso 159/2026 Sección de lo Mercantil del tribunal de Instancia de Donostia. Plaza Nº1 Se ofrece en subasta una carretilla",
         "159/2026", "Sección de lo Mercantil del tribunal de Instancia de Donostia. Plaza Nº1"),
        ("Descripción Autos 74/2026 Sección de lo Mercantil del Tribunal de Instancia de Madrid. Plaza Nº 16 Land Rover, con matrícula 1111BBB",
         "74/2026", "Sección de lo Mercantil del Tribunal de Instancia de Madrid. Plaza Nº 16"),
    ])
    def test_procedure_and_court(self, text, procedure, court):
        assert eactivos.parse_procedure(text) == (procedure, court)

    def test_no_procedure_in_the_text(self):
        assert eactivos.parse_procedure("Descripción Se subasta camión IVECO 35E12, con matrícula AL-8383-AB, ubicado en La Mojonera") == (None, None)

    def test_the_word_concurso_alone_is_not_a_procedure(self):
        assert eactivos.parse_procedure("contrario al interés del concurso, se reservará el derecho de repetirla") == (None, None)

    def test_plates_in_every_seen_shape_and_debtor_named_as_owner(self):
        body = ("Portada Liquidaciones Vehículos Carretilla X Carretilla X Descripción Concurso 159/2026 Sección de lo Mercantil de Donostia. Plaza Nº1 "
                "Se ofrece en subasta una carretilla, con matrícula 3333ddd, propiedad de Olgaiz Construcciones Mecánicas, S.L.L. (LICAR), empresa industrial")
        lot = eactivos.parse_lot(page("Carretilla X", body), "https://www.eactivos.com/ABCD1234/carretilla-x")
        assert lot["matricula"] == "3333DDD" and lot["concursada"] == "Olgaiz Construcciones Mecánicas, S.L.L."
        old = eactivos.parse_lot(page("Camión Iveco", "Portada Liquidaciones Vehículos Camión Iveco Descripción Se subasta camión, con matrícula AL-8383-AB, ubicado en X"),
                                 "https://www.eactivos.com/ABCD1235/camion-iveco")
        assert old["matricula"] == "AL-8383-AB" and old["procedimiento"] is None

    def test_end_date_of_a_running_auction(self):
        body = "Portada Liquidaciones Vehículos Ford B-MAX Ford B-MAX Finaliza el 24/09/2026 (Europa/Madrid) d h m s Descripción Se vende Ford"
        lot = eactivos.parse_lot(page("Ford B-MAX", body), "https://www.eactivos.com/ABCD1236/vehiculo-ford-b-max-en-avila")
        assert lot["fin"] == "2026-09-24" and lot["estado"] == "abierta" and lot["inicio"] is None


class TestMigration:
    def test_a_database_created_before_a_column_existed_gets_it(self, tmp_path):
        import sqlite3
        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE lotes (codigo TEXT PRIMARY KEY, titulo TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)")
        conn.execute("INSERT INTO lotes VALUES ('A1', 'ancien lot', '2026-09-01', '2026-09-01')")
        conn.commit()
        conn.close()
        with Storage(path) as s:
            assert s.rows_lotes()[0]["titulo"] == "ancien lot"                  # rien n'est perdu
            s.upsert_lotes([{"codigo": "A2", "titulo": "nouveau", "fin": "2026-10-01", "procedimiento": "1/2026"}])
            assert {r["codigo"]: r["fin"] for r in s.rows_lotes()} == {"A1": None, "A2": "2026-10-01"}


ENTRIES = [(MASTER_URL, "2026-09-17"), (PIAGGIO_URL, "2026-09-10"), (CLOSED_URL, "2026-07-27"),
           ("https://www.eactivos.com/OLDVEH01/furgoneta-antigua", "2019-01-01"), ("https://www.eactivos.com/VIVIENDA/vivienda-en-madrid", "2026-09-17")]


class TestSelectUrls:
    def test_recent_vehicles_only_newest_first(self):
        assert [u for u, _ in eactivos.select_urls(ENTRIES, "2026-01-01")] == [MASTER_URL, PIAGGIO_URL, CLOSED_URL]

    def test_known_closed_lots_are_skipped_and_limit_applies(self):
        assert [u for u, _ in eactivos.select_urls(ENTRIES, "2026-01-01", known_closed={"DVXWG6K9"})] == [MASTER_URL, PIAGGIO_URL]
        assert len(eactivos.select_urls(ENTRIES, "2026-01-01", limit=1)) == 1


SITEMAP = ("<urlset>" + "".join(f"<url><loc>{u}</loc><lastmod>{d}</lastmod></url>" for u, d in ENTRIES) + "</urlset>")


def network(robots=ROBOTS, extra=None):
    pages = {f"{eactivos.BASE}/robots.txt": robots, eactivos.SITEMAP_URL: SITEMAP,
             MASTER_URL: MASTER_PAGE, PIAGGIO_URL: PIAGGIO_PAGE, CLOSED_URL: CLOSED_PAGE, **(extra or {})}
    calls = []

    def fetch(url):
        calls.append(url)
        return (200, pages[url]) if url in pages else (404, "")

    fetch.calls = calls
    return fetch


@pytest.fixture
def storage():
    with Storage(":memory:") as s:
        yield s


def run_collect(storage, fetch, **kwargs):
    sleeps = []
    result = eactivos.collect("2026-01-01", storage, fetch, pause=2.0, sleep=sleeps.append, log=lambda *a: None, **kwargs)
    return result, sleeps


class TestCollect:
    def test_reads_the_vehicle_lots_and_stores_the_facts(self, storage):
        fetch = network()
        result, sleeps = run_collect(storage, fetch)
        assert {k: v for k, v in result.items() if k != "nouveaux_lots"} == {"lus": 3, "nouveaux": 3, "interdits": 0, "illisibles": 0}
        assert {lot["codigo"] for lot in result["nouveaux_lots"]} == {"BRZG3MJX", "JK7JWY1X", "DVXWG6K9"}
        assert {r["codigo"]: r["estado"] for r in storage.rows_lotes()} == {"BRZG3MJX": "proxima", "JK7JWY1X": "proxima", "DVXWG6K9": "cerrada"}
        assert storage.rows_lotes("codigo = 'BRZG3MJX'")[0]["concursada"] == "Ingeniería Técnica de Elevación, S.L."
        assert not any("VIVIENDA" in c or "OLDVEH01" in c for c in fetch.calls)          # ni non-véhicules ni anciens lots

    def test_a_pause_precedes_every_request_after_robots_and_sitemap(self, storage):
        _, sleeps = run_collect(storage, network())
        assert sleeps == [2.0] * 4            # robots -> plan (1), puis une pause avant chacune des 3 fiches

    def test_a_forbidden_page_is_never_requested(self, storage):
        blocked = ROBOTS + "Disallow: /DVXWG6K9/\n"
        fetch = network(robots=blocked)
        result, _ = run_collect(storage, fetch)
        assert result["interdits"] == 1 and result["lus"] == 2 and CLOSED_URL not in fetch.calls

    def test_a_forbidden_sitemap_stops_everything(self, storage):
        fetch = network(robots="User-agent: *\nDisallow: /sitemap\n")
        with pytest.raises(SystemExit, match="interdit son plan du site"):
            run_collect(storage, fetch)
        assert eactivos.SITEMAP_URL not in fetch.calls

    def test_missing_robots_file_means_nothing_is_forbidden(self, storage):
        fetch = network()
        fetch_no_robots = lambda url: (404, "") if url.endswith("/robots.txt") else fetch(url)
        assert run_collect(storage, fetch_no_robots)[0]["lus"] == 3

    def test_unreadable_pages_are_counted_not_fatal(self, storage):
        fetch = network(extra={PIAGGIO_URL: "<html>page cassée</html>"})
        result, _ = run_collect(storage, fetch)
        assert result["illisibles"] == 1 and result["lus"] == 2

    def test_a_server_error_on_a_page_is_counted(self, storage):
        base = network()
        fetch = lambda url: (500, "") if url == MASTER_URL else base(url)
        assert run_collect(storage, fetch)[0]["illisibles"] == 1

    def test_closed_lots_are_not_read_again_but_open_ones_are(self, storage):
        run_collect(storage, network())
        second = network()
        result, _ = run_collect(storage, second)
        assert CLOSED_URL not in second.calls and MASTER_URL in second.calls and result["lus"] == 2 and result["nouveaux"] == 0

    def test_refresh_reads_closed_lots_again(self, storage):
        run_collect(storage, network())
        again = network()
        run_collect(storage, again, refresh=True)
        assert CLOSED_URL in again.calls

    def test_limit(self, storage):
        assert run_collect(storage, network(), limit=1)[0]["lus"] == 1

    def test_unreadable_sitemap(self, storage):
        fetch = network(extra={eactivos.SITEMAP_URL: ""})
        broken = lambda url: (500, "") if url == eactivos.SITEMAP_URL else fetch(url)
        with pytest.raises(SystemExit, match="HTTP 500"):
            run_collect(storage, broken)


class TestMain:
    def run(self, tmp_path, *args, fetch=None):
        eactivos.main(["--db", str(tmp_path / "es.db"), "--pause", "0", *args], fetch=fetch or network(), sleep=lambda s: None,
                      today=__import__("datetime").date(2026, 9, 21))

    def test_default_window_is_180_days(self, tmp_path, capsys):
        self.run(tmp_path)
        out = capsys.readouterr().out
        assert "depuis 2026-03-25" in out and "3 lot(s) lu(s)" in out and "Base : 3 lot(s)" in out and "2 proxima" in out

    def test_since_and_counts(self, tmp_path, capsys):
        self.run(tmp_path, "--since", "2026-09-01")
        assert "2 véhicule(s) à lire depuis 2026-09-01" in capsys.readouterr().out

    @pytest.mark.parametrize("args", [["--since", "21/09/2026"], ["--limit", "0"], ["--pause", "-1"]])
    def test_bad_options_are_refused(self, tmp_path, args):
        with pytest.raises(SystemExit):
            self.run(tmp_path, *args)


class TestStorageLotes:
    def test_new_rows_history_and_the_two_tables_are_independent(self, storage):
        lot = eactivos.parse_lot(MASTER_PAGE, MASTER_URL, "2026-09-17")
        assert storage.upsert_lotes([lot], now="2026-09-20T10:00:00+00:00") == 1
        assert storage.upsert_lotes([{**lot, "estado": "cerrada"}], now="2026-09-25T10:00:00+00:00") == 0
        (saved,) = storage.rows_lotes()
        assert saved["estado"] == "cerrada" and saved["first_seen"].startswith("2026-09-20") and saved["last_seen"].startswith("2026-09-25")
        assert storage.count("lotes") == 1 and storage.count("actos") == 0
        with pytest.raises(ValueError):
            storage.count("inconnue")


def acto(**extra):
    base = {"id": "a1", "fecha_publicacion": "2026-09-18", "provincia": "MADRID", "borme_id": "BORME-A-2026-181-28", "empresa_num": "1",
            "empresa": "INGENIERIA TECNICA DE ELEVACION SL", "procedimiento": "470/2025", "tipo": "Auto de declaración de concurso",
            "administradores": "LENER ADMINISTRACIONES CONCURSALES SLP (B86598968)", "url_html": "https://h/1"}
    return {**base, **extra}


class TestReportLotes:
    @pytest.fixture
    def filled(self, storage):
        storage.upsert_lotes([eactivos.parse_lot(MASTER_PAGE, MASTER_URL, "2026-09-17"), eactivos.parse_lot(PIAGGIO_PAGE, PIAGGIO_URL, "2026-09-10"),
                              eactivos.parse_lot(CLOSED_PAGE, CLOSED_URL, "2026-07-27")])
        return storage

    def test_normalize_procedure(self):
        assert report.normalize_procedure("000360/2022") == "360/2022" and report.normalize_procedure("470/2025") == "470/2025"
        assert report.normalize_procedure("") == "" and report.normalize_procedure("0/2022") == "0/2022"
        assert report.normalize_procedure("1192.5/2025") == "1192/2025"                     # sous-numéro ignoré

    def test_states(self, filled):
        assert {r["codigo"] for r in report.vehicle_rows(filled, "live")} == {"BRZG3MJX", "JK7JWY1X"}
        assert [r["codigo"] for r in report.vehicle_rows(filled, "closed")] == ["DVXWG6K9"]
        assert len(report.vehicle_rows(filled, "all")) == 3

    def test_a_lot_is_linked_by_procedure_number_and_province(self, filled):
        filled.upsert([acto()])
        (link,) = report.vinculos(filled)
        assert link["codigo"] == "BRZG3MJX" and link["empresa"] == "INGENIERIA TECNICA DE ELEVACION SL"
        assert link["administradores"].startswith("LENER") and link["url_borme"] == "https://h/1"

    def test_same_number_in_another_province_is_not_a_link(self, filled):
        filled.upsert([acto(provincia="VALENCIA/VALÈNCIA")])
        assert report.vinculos(filled) == []

    def test_leading_zeros_and_bilingual_provinces(self, filled):
        filled.upsert([acto(id="a2", procedimiento="000454/2025", provincia="VALENCIA/VALÈNCIA", empresa="OTRA SL", administradores=None)])
        (link,) = report.vinculos(filled)
        assert link["codigo"] == "JK7JWY1X" and link["empresa"] == "OTRA SL"

    @pytest.mark.parametrize("lot_court, act_court, expected", [
        # cas réels : tribunal du lot eactivos / tribunal de l'acte du BORME
        ("Sección de lo Mercantil del Tribunal de Instancia de Madrid Plaza Nº 16",
         "num. 0 SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE MADRID. PLAZA Nº 1. 6", True),     # « 1. 6 » = 16
        ("Juzgado Mercantil 4 de Valencia", "num. 0 JUZGADO DE LO MERCANTIL NUMERO 4 VALENCIA", True),
        ("Juzgado Mercantil 4 de Valencia", "num. 0 JUZGADO DE LO MERCANTIL NUMERO 3 DE VALENCIA", False),  # même ville, autre chambre
        ("Juzgado de lo Mercantil Nº4 de Sevilla", "num. 0 JUZGADO DE LO MERCANTIL NUMERO 4 DE SEVILLA", True),
        ("Sección de lo Mercantil del tribunal de Instancia de Donostia. Plaza Nº1",
         "num. 0 SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE DONOSTIA/SAN SEBAS. TIAN. PLAZA Nº 1", True),
        ("Sección de lo Mercantil del Tribunal de Instancia de Madrid. Plaza Nº 16",
         "num. 0 SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE VALENCIA. PLAZA Nº. 2", False),      # 74/2026 : autre ville
        ("Juzgado de lo Mercantil Nº 2 de Badajoz (Sede en Mérida)", "num. 0 JUZGADO DE LO MERCANTIL NUMERO 1 DE OVIEDO", False),
        (None, "num. 0 JUZGADO DE LO MERCANTIL NUMERO 4 DE SEVILLA", None),                              # rien à comparer
        ("Juzgado de lo Mercantil de Sevilla", "num. 0 JUZGADO DE LO MERCANTIL NUMERO 4 DE SEVILLA", True),  # un seul numéro connu : la ville suffit
    ])
    def test_same_court(self, lot_court, act_court, expected):
        assert report.same_court(lot_court, act_court) is expected

    def test_the_court_decides_when_both_sides_have_one(self, storage):
        """Le lot de Mislata (454/2025, Valencia 4) ne se rattache plus qu'à la société du même juzgado, pas à celle du n° 3."""
        storage.upsert_lotes([eactivos.parse_lot(PIAGGIO_PAGE, PIAGGIO_URL, "2026-09-10")])
        storage.upsert([acto(id="c1", procedimiento="454/2025", provincia="VALENCIA/VALÈNCIA", empresa="BELDA SL",
                             juzgado="num. 0 JUZGADO DE LO MERCANTIL NUMERO 4 VALENCIA"),
                        acto(id="c2", procedimiento="454/2025", provincia="VALENCIA/VALÈNCIA", empresa="LEXECON SL",
                             juzgado="num. 0 JUZGADO DE LO MERCANTIL NUMERO 3 DE VALENCIA")])
        (link,) = report.vinculos(storage)
        assert link["empresa"] == "BELDA SL" and link["candidatos"] == 1

    def test_the_court_finds_a_link_the_registry_province_would_miss(self, storage):
        """Une société inscrite au registre d'une autre province que son tribunal : le tribunal fait foi."""
        storage.upsert_lotes([eactivos.parse_lot(MASTER_PAGE, MASTER_URL, "2026-09-17")])
        storage.upsert([acto(id="c3", provincia="ILLES BALEARS", empresa="INSCRITE AILLEURS SL",
                             juzgado="num. 0 SECCION DE LO MERCANTIL DEL TRIBUNAL DE INSTANCIA DE MADRID. PLAZA Nº 1. 6")])
        (link,) = report.vinculos(storage)
        assert link["empresa"] == "INSCRITE AILLEURS SL"

    def test_the_same_number_at_another_court_is_not_a_link_even_in_the_same_province(self, storage):
        storage.upsert_lotes([eactivos.parse_lot(MASTER_PAGE, MASTER_URL, "2026-09-17")])
        storage.upsert([acto(id="c4", provincia="MADRID", juzgado="num. 0 JUZGADO DE LO MERCANTIL NUMERO 5 DE MADRID")])
        assert report.vinculos(storage) == []

    def test_several_acts_of_the_same_company_give_one_link(self, filled):
        filled.upsert([acto(),
                       acto(id="a4", fecha_publicacion="2026-09-25", tipo="Auto de conclusión del concurso", url_html="https://h/4",
                            administradores="OTRO ADMINISTRADOR SLP (B11111111)")])
        (link,) = report.vinculos(filled)
        assert link["candidatos"] == 1 and link["tipo_acto"] == "Auto de conclusión del concurso" and link["url_borme"] == "https://h/4"
        assert link["administradores"] == "LENER ADMINISTRACIONES CONCURSALES SLP (B86598968); OTRO ADMINISTRADOR SLP (B11111111)"

    def test_the_same_administrator_written_twice_is_listed_once(self, filled):
        filled.upsert([acto(), acto(id="a5", administradores="LENER ADMINISTRACIONES CONCURSALES SOCIEDAD LIMITADA (B86598968)")])
        (link,) = report.vinculos(filled)
        assert link["administradores"].count("B86598968") == 1

    def test_two_different_companies_with_the_same_number_are_both_reported_as_ambiguous(self, filled):
        filled.upsert([acto(id="a6", procedimiento="000454/2025", provincia="VALENCIA/VALÈNCIA", empresa="BELDA SL"),
                       acto(id="a7", procedimiento="454/2025", provincia="VALENCIA/VALÈNCIA", empresa="LEXECON SL"),
                       acto(id="a8", procedimiento="454/2025", provincia="VALENCIA/VALÈNCIA", empresa="LEXECON SL", tipo="Otro acto")])
        links = report.vinculos(filled)
        assert sorted(l["empresa"] for l in links) == ["BELDA SL", "LEXECON SL"] and {l["candidatos"] for l in links} == {2}

    def test_links_command_counts_lots_not_rows_and_flags_ambiguity(self, filled, tmp_path, capsys):
        filled.upsert([acto(id="a6", procedimiento="454/2025", provincia="VALENCIA/VALÈNCIA", empresa="BELDA SL"),
                       acto(id="a7", procedimiento="454/2025", provincia="VALENCIA/VALÈNCIA", empresa="LEXECON SL")])
        path = tmp_path / "links.db"
        filled.conn.execute("VACUUM INTO ?", (str(path),))
        report.main(["--db", str(path), "links"])
        out = capsys.readouterr().out
        assert "1 lot(s) rattaché(s), dont 1 avec plusieurs sociétés possibles" in out and "cand." in out

    def test_lots_without_a_procedure_and_acts_without_one_are_ignored(self, filled):
        filled.upsert([acto(id="a3", procedimiento=None)])
        assert report.vinculos(filled) == []
