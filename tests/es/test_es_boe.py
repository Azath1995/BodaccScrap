"""`es.immobilier.boe` : enchères immobilières de la zone de Torrevieja sur subastas.boe.es.

Écart assumé et voulu par l'utilisateur : ce portail interdit tout aux robots (robots.txt : Disallow: /), mais la lecture
en a été explicitement demandée, limitée à l'immobilier de la zone de Torrevieja, à condition de ne jamais garder de nom
de personne (débiteur, créancier...). Ces tests vérifient justement cette limite (`TestRedact`, `test_a_name_word_cuts_the_text`).
"""
import csv

import pytest

from es.immobilier import boe
from es.storage import Storage

# --- Fragments réels de subastas.boe.es (23 septembre 2026), recherche « bien immobilier, Alicante, Torrevieja » ------
RESULT_JUDICIAL = """<li class="resultado-busqueda"> <h3>SUBASTA SUB-JA-2026-263520</h3>
<h4>Secci&#xF3;n Civil TI Torrevieja. Plz.n 5 - TORREVIEJA </h4>
<p>Expediente: 1362/24</p>
<p>Estado: Celebr&#xE1;ndose - [Conclusi&#xF3;n prevista: 28/09/2026 a las 18:00:00]</p>
<p>Finca 12.345. URBANA.&#x2013; Vivienda puerta A, tipo 42, en planta segunda, en Torrevieja (Alicante).</p>
<a href="./detalleSubasta.php?idSub=SUB-JA-2026-263520&amp;idBus=TOKEN1--50" class="resultado-busqueda-link-defecto" title="Subasta SUB-JA-2026-263520"> </a>
<ul> <li class="puntoHTML"> <a href="./detalleSubasta.php?idSub=SUB-JA-2026-263520&amp;idBus=TOKEN1--50" class="resultado-busqueda-link-otro" title="...">M&#xE1;s... (Referencia SUB-JA-2026-263520)</a> </li> </ul> </li>"""

RESULT_AEAT = """<li class="resultado-busqueda"> <h3>SUBASTA SUB-AT-2026-26R4186001366</h3>
<h4>U.R. SUBASTAS ANDALUCIA 41 - SEVILLA (AEAT)</h4>
<p>Estado: Celebr&#xE1;ndose - [Conclusi&#xF3;n prevista: 28/09/2026 a las 18:00:00]</p>
<p>50% NUDA PROPIEDAD F. 3264 AV. DR. GREGORIO MARA&#xD1;&#xD3;N, TORREVIEJA (ALICANTE) </p>
<a href="./detalleSubasta.php?idSub=SUB-AT-2026-26R4186001366&amp;idBus=TOKEN2--50" class="resultado-busqueda-link-defecto" title="..."> </a>
<ul> <li class="puntoHTML"> <a href="./detalleSubasta.php?idSub=SUB-AT-2026-26R4186001366&amp;idBus=TOKEN2--50" class="resultado-busqueda-link-otro" title="...">M&#xE1;s...</a> </li> </ul> </li>"""

RESULT_WITH_A_NAME = """<li class="resultado-busqueda"> <h3>SUBASTA SUB-JA-2026-999999</h3>
<h4>Juzgado de Torrevieja - TORREVIEJA</h4>
<p>Estado: Celebr&#xE1;ndose - [Conclusi&#xF3;n prevista: 01/10/2026 a las 12:00:00]</p>
<p>Vivienda en Torrevieja perteneciente al deudor Juan P&#xE9;rez L&#xF3;pez, con superficie de 80 m2.</p>
<a href="./detalleSubasta.php?idSub=SUB-JA-2026-999999&amp;idBus=TOKEN3--50" class="resultado-busqueda-link-defecto" title="..."> </a>
<ul> <li class="puntoHTML"> <a href="./detalleSubasta.php?idSub=SUB-JA-2026-999999&amp;idBus=TOKEN3--50" class="resultado-busqueda-link-otro" title="...">M&#xE1;s...</a> </li> </ul> </li>"""


def results_page(*blocks, next_href=None):
    pagination = (f'<div class="paginar2"><ul><li><a href="./subastas_ava.php?accion=Mas&amp;id_busqueda={next_href}">'
                 '<abbr title="Página">Pág. siguiente</abbr></a></li></ul></div>' if next_href else "")
    return f'<html><body>{pagination}<div class="listadoResult"><ul>{"".join(blocks)}</ul></div></body></html>'


DETAIL_PAGE = """<html><body>
<div>Identificador</div><div>SUB-JA-2026-263520</div>
<div>Tipo de subasta</div><div>JUDICIAL EN V&#xCD;A DE APREMIO</div>
<div>Cantidad reclamada</div><div>34.515,70 &#x20AC;</div>
<div>Lotes</div><div>Sin lotes</div>
<div>Anuncio BOE</div><div>BOE-B-2026-28668</div>
<div>Valor subasta</div><div>52.032,62 &#x20AC;</div>
<div>Tasaci&#xF3;n</div><div>0,00 &#x20AC;</div>
<div>Puja m&#xED;nima</div><div>Sin puja m&#xED;nima</div>
<div>Importe del dep&#xF3;sito</div><div>2.601,63 &#x20AC;</div>
</body></html>"""


class TestRedact:
    def test_text_without_a_banned_word_is_kept(self):
        assert boe.redact("Vivienda en Torrevieja, 80 m2.") == "Vivienda en Torrevieja, 80 m2."

    def test_a_name_word_cuts_the_text(self):
        assert boe.redact("Vivienda perteneciente al deudor Juan Pérez.") == "Vivienda perteneciente al"

    def test_a_name_word_at_the_start_leaves_nothing(self):
        assert boe.redact("Deudor: Juan Pérez López") is None

    @pytest.mark.parametrize("word", ["ejecutado", "EJECUTADA", "demandado", "titular", "acreedor", "propietaria"])
    def test_every_banned_word_is_caught(self, word):
        assert boe.redact(f"Bien libre. {word} X.") == "Bien libre."

    def test_empty_text(self):
        assert boe.redact(None) is None and boe.redact("") == ""

    def test_a_boundary_clause_naming_neighbours_is_kept(self):
        """« Linda : » nomme les voisins d'un bien : décision explicite de l'utilisateur de la garder (23/09/2026),
        car c'est une donnée de registre public sur des tiers, pas l'identité du débiteur."""
        text = ("URBANA. Casa de habitación en Rojales. LINDA: derecha entrando, casa de Pedro Ejemplo Ruiz; "
               "izquierda, la de Luis Modelo Gil; y fondo, patio de la casa de Mario Prueba Sanz.")
        assert boe.redact(text) == text


class TestToInt:
    @pytest.mark.parametrize("text, value", [
        ("52.032,62 €", 52032), ("0,00 €", 0), ("34.515,70 €", 34515), ("Sin puja mínima", None), (None, None), ("", None)])
    def test_formats(self, text, value):
        assert boe.to_int(text) == value


class TestParseResultsPage:
    def test_reads_id_court_case_state_description_and_link(self):
        (row,), next_url = boe.parse_results_page(results_page(RESULT_JUDICIAL))
        assert row["id"] == "SUB-JA-2026-263520" and row["expediente"] == "1362/24"
        assert row["organo"] == "Sección Civil TI Torrevieja. Plz.n 5 - TORREVIEJA"
        assert row["estado_texto"] == "Celebrándose - [Conclusión prevista: 28/09/2026 a las 18:00:00]"
        assert "Vivienda puerta A" in row["descripcion"] and "Torrevieja" in row["descripcion"]
        assert row["url"] == "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"

    def test_an_auction_without_an_expediente_line_is_still_read(self):
        (row,), _ = boe.parse_results_page(results_page(RESULT_AEAT))
        assert row["id"] == "SUB-AT-2026-26R4186001366" and row["expediente"] is None
        assert "TORREVIEJA" in row["descripcion"]

    def test_several_items_on_one_page(self):
        rows, _ = boe.parse_results_page(results_page(RESULT_JUDICIAL, RESULT_AEAT))
        assert [r["id"] for r in rows] == ["SUB-JA-2026-263520", "SUB-AT-2026-26R4186001366"]

    def test_a_name_in_the_description_is_redacted_before_storage(self):
        (row,), _ = boe.parse_results_page(results_page(RESULT_WITH_A_NAME))
        assert "Pérez" not in row["descripcion"] and "deudor" not in row["descripcion"].lower()
        assert row["descripcion"] == "Vivienda en Torrevieja perteneciente al"

    def test_no_next_page_when_on_the_last_one(self):
        _, next_url = boe.parse_results_page(results_page(RESULT_JUDICIAL))
        assert next_url is None

    def test_the_next_page_link_is_absolute_and_unescaped(self):
        _, next_url = boe.parse_results_page(results_page(RESULT_JUDICIAL, next_href="TOKEN,,-50-50"))
        assert next_url == "https://subastas.boe.es/subastas_ava.php?accion=Mas&id_busqueda=TOKEN,,-50-50"

    def test_an_empty_page_gives_no_rows(self):
        assert boe.parse_results_page(results_page()) == ([], None)


class TestParseDetail:
    def test_reads_amounts_and_identifiers_never_a_name(self):
        details = boe.parse_detail(DETAIL_PAGE)
        assert details == {
            "tipo_subasta": "JUDICIAL EN VÍA DE APREMIO", "cantidad_reclamada": 34515, "lotes": None,
            "anuncio_boe": "BOE-B-2026-28668", "valor": 52032, "tasacion": 0, "puja_minima": None, "deposito": 2601,
        }

    def test_a_page_missing_fields_gives_none_not_a_crash(self):
        assert boe.parse_detail("<html><body>rien ici</body></html>")["valor"] is None


def fake_network(pages, detail_pages):
    """pages : {(municipio, estado): html} ; detail_pages : {url: html}. Mémorise les appels."""
    calls = {"post": [], "get": []}

    def fetch_post(url, data):
        calls["post"].append((data["dato[7]"], data["dato[2]"]))
        html = pages.get((data["dato[7]"], data["dato[2]"]), results_page())
        return 200, html

    def fetch_get(url):
        calls["get"].append(url)
        return (200, detail_pages[url]) if url in detail_pages else (404, "")

    fetch_post.calls, fetch_get.calls = calls["post"], calls["get"]
    return fetch_post, fetch_get


class TestCollect:
    def test_reads_live_states_for_every_town_of_the_zone_by_default(self):
        fetch_post, fetch_get = fake_network({}, {})
        with Storage(":memory:") as storage:
            boe.collect(storage, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
        assert ("Torrevieja", "PU") in fetch_post.calls and ("Torrevieja", "EJ") in fetch_post.calls
        assert ("Torrevieja", "CA") not in fetch_post.calls                      # « live » : pas les closes

    def test_restricting_to_one_town_asks_only_that_town(self):
        fetch_post, fetch_get = fake_network({}, {})
        with Storage(":memory:") as storage:
            boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
        assert {m for m, _ in fetch_post.calls} == {"Torrevieja"}

    def test_a_found_auction_is_stored_with_town_type_and_amounts(self):
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"
        fetch_post, fetch_get = fake_network({("Torrevieja", "EJ"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
        with Storage(":memory:") as storage:
            result = boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
            (saved,) = storage.rows_subastas_boe()
        assert result["nouveaux"] == 1 and saved["municipio"] == "Torrevieja" and saved["tipo"] == "vivienda"
        assert saved["estado"] == "abierta" and saved["estado_boe"] == "EJ" and saved["fecha_fin"] == "2026-09-28"
        assert saved["valor"] == 52032 and saved["deposito"] == 2601 and saved["origen"] == "JA"

    def test_the_same_auction_found_under_two_towns_is_stored_once(self):
        """La ville de l'autorité (h4) peut différer de celle du bien : le doublon inter-communes ne compte pas deux fois."""
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-AT-2026-26R4186001366&idBus=TOKEN2--50"
        fetch_post, fetch_get = fake_network(
            {("Torrevieja", "EJ"): results_page(RESULT_AEAT), ("Orihuela", "EJ"): results_page(RESULT_AEAT)}, {url: DETAIL_PAGE})
        with Storage(":memory:") as storage:
            result = boe.collect(storage, municipios={"torrevieja", "orihuela"}, sleep=lambda s: None,
                                 fetch_post=fetch_post, fetch_get=fetch_get)
            assert result["lus"] == 1 and storage.count("subastas_boe") == 1

    def test_a_failed_search_request_is_skipped_without_crashing(self):
        def broken_post(url, data):
            return 503, ""

        with Storage(":memory:") as storage:
            result = boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=broken_post, fetch_get=boe.get)
        assert result == {"lus": 0, "nouveaux": 0, "nouvelles_encheres": []}

    def test_a_second_run_finds_nothing_new(self):
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"
        fetch_post, fetch_get = fake_network({("Torrevieja", "EJ"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
        with Storage(":memory:") as storage:
            boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
            second = boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
        assert second["nouveaux"] == 0 and second["lus"] == 1

    def test_a_second_run_does_not_refetch_a_known_auctions_detail_page(self):
        """La recherche est refaite (elle seule dit si une enchère a changé d'état), mais pas la fiche déjà lue."""
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"
        fetch_post, fetch_get = fake_network({("Torrevieja", "EJ"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
        with Storage(":memory:") as storage:
            boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
            after_first = len(fetch_get.calls)
            boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
        assert fetch_get.calls.count(url) == 1 and len(fetch_get.calls) == after_first          # aucun appel de plus

    def test_refresh_forces_the_detail_page_to_be_reread(self):
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"
        fetch_post, fetch_get = fake_network({("Torrevieja", "EJ"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
        with Storage(":memory:") as storage:
            boe.collect(storage, municipios={"torrevieja"}, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
            boe.collect(storage, municipios={"torrevieja"}, refresh=True, sleep=lambda s: None, fetch_post=fetch_post, fetch_get=fetch_get)
        assert fetch_get.calls.count(url) == 2

    def test_a_town_newly_appearing_in_the_estado_still_updates_it(self):
        """Une enchère déjà connue mais dont l'état a changé (à venir -> en cours) est mise à jour sans relire sa fiche."""
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"
        fetch_post, fetch_get = fake_network({("Torrevieja", "PU"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
        with Storage(":memory:") as storage:
            boe.collect(storage, municipios={"torrevieja"}, estados=("proxima",), sleep=lambda s: None,
                       fetch_post=fetch_post, fetch_get=fetch_get)
            fetch_post2, _ = fake_network({("Torrevieja", "EJ"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
            boe.collect(storage, municipios={"torrevieja"}, estados=("abierta",), sleep=lambda s: None,
                       fetch_post=fetch_post2, fetch_get=fetch_get)
            (saved,) = storage.rows_subastas_boe()
        assert saved["estado"] == "abierta" and fetch_get.calls.count(url) == 1                 # détail lu une seule fois


class TestPropertyTypeFromDescription:
    """Le préfixe notarial (« Finca NNN. URBANA.– », « URBANA. VEINTIOCHO.- »...) ne doit pas faire gagner « finca »
    sur le vrai type du bien cité juste après (23/09/2026 : 42 des 56 enchères classées « terreno/finca » à tort)."""

    @pytest.mark.parametrize("description, tipo", [
        ("Finca 12.345. URBANA.– Vivienda puerta A, tipo 42, en planta segunda, en Torrevieja (Alicante).", "vivienda"),
        ("URBANA. VEINTIOCHO.- Vivienda en planta quinta del edificio sito en Orihuela", "vivienda"),
        ('URBANA.- TRES.- En término de ORIHUELA (Alicante)... CHALET "dúplex" en construcción', "vivienda"),
        ("Urbana.- NUEVE.-Bungalow número veitiuno, bloque seis", "vivienda"),
        ("URBANA.UNO.-Vivienda tipo A.- del edificio en construcción sito en Orihuela", "vivienda"),
        ("FINCA RUSTICA. PJ PARAJE PUENTE DE LA LOSA S/N DAYA VIEJA ALICANTE", "terreno/finca"),
        ("FINCA REGISTRAL Nº 7549, inscrita al REGISTRO DE LA PROPIEDAD DE ALMORADÍ, al tomo 2518.", "terreno/finca"),
    ])
    def test_examples(self, description, tipo):
        from es.immobilier import zone
        assert zone.property_type(zone.slug_of_text(boe.REGISTRY_PREFIX.sub("", description))) == tipo


class TestCommandLine:
    def run(self, tmp_path, *args, fetch_post=None, fetch_get=None):
        boe.main(["--db", str(tmp_path / "boe.db"), "--municipios", "torrevieja", "--pause", "0", *args],
                 fetch_post=fetch_post or (lambda u, d: (200, results_page())), fetch_get=fetch_get or (lambda u: (404, "")))

    def test_prints_a_summary_and_a_table(self, tmp_path, capsys):
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"
        fetch_post, fetch_get = fake_network({("Torrevieja", "EJ"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
        self.run(tmp_path, fetch_post=fetch_post, fetch_get=fetch_get)
        out = capsys.readouterr().out
        assert "1 nouvelle(s) enchère(s)" in out and "Torrevieja" in out and "en cours" in out and "1 enchère(s)" in out

    def test_no_result_is_said_plainly(self, tmp_path, capsys):
        self.run(tmp_path)
        assert "Aucune enchère." in capsys.readouterr().out

    def test_csv_export(self, tmp_path):
        url = "https://subastas.boe.es/detalleSubasta.php?idSub=SUB-JA-2026-263520&idBus=TOKEN1--50"
        fetch_post, fetch_get = fake_network({("Torrevieja", "EJ"): results_page(RESULT_JUDICIAL)}, {url: DETAIL_PAGE})
        target = tmp_path / "subastas.csv"
        self.run(tmp_path, "--csv", str(target), fetch_post=fetch_post, fetch_get=fetch_get)
        with open(target, encoding="utf-8-sig", newline="") as f:
            (row,) = list(csv.DictReader(f))
        assert row["municipio"] == "Torrevieja" and row["valor"] == "52032"

    def test_an_unknown_town_is_refused(self, tmp_path):
        with pytest.raises(SystemExit):
            boe.main(["--db", str(tmp_path / "b.db"), "--municipios", "madrid"])
