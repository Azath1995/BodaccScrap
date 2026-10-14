"""`es.immobilier.catastro` : consultation à la demande du Catastro (données non protégées : ni valeur, ni propriétaire)."""
import csv

import pytest

from es.immobilier import catastro

# --- Réponses réelles du service (23 septembre 2026), adresse d'un lot vu dans une enchère du BOE (SUB-JA-2026-265315) ---
LOCATION_XML = """<?xml version="1.0" encoding="utf-8"?>
<consulta_dnp xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.catastro.meh.es/">
  <control><cudnp>2</cudnp></control>
  <lrcdnp>
    <rcdnp>
      <rc><pc1>1234567</pc1><pc2>AB1234C</pc2><car>0002</car><cc1>X</cc1><cc2>Y</cc2></rc>
      <dt>
        <loine><cp>03</cp><cm>76</cm></loine><cmc>76</cmc><np>ALICANTE</np><nm>GUARDAMAR DEL SEGURA</nm>
        <locs><lous><lourb>
          <dir><cv>345</cv><tv>CL</tv><nv>MAYOR</nv><pnp>12</pnp><snp>0</snp><td>EDIFICIO EJEMPLO</td></dir>
          <loint><es>1</es><pt>00</pt><pu>01</pu></loint><dp>03140</dp><dm>1</dm>
        </lourb></lous></locs>
      </dt>
    </rcdnp>
    <rcdnp>
      <rc><pc1>1234567</pc1><pc2>AB1234C</pc2><car>0003</car><cc1>Z</cc1><cc2>W</cc2></rc>
      <dt>
        <loine><cp>03</cp><cm>76</cm></loine><cmc>76</cmc><np>ALICANTE</np><nm>GUARDAMAR DEL SEGURA</nm>
        <locs><lous><lourb>
          <dir><cv>345</cv><tv>CL</tv><nv>MAYOR</nv><pnp>12</pnp><snp>0</snp><td>EDIFICIO EJEMPLO</td></dir>
          <loint><es>1</es><pt>00</pt><pu>02</pu></loint><dp>03140</dp><dm>1</dm>
        </lourb></lous></locs>
      </dt>
    </rcdnp>
  </lrcdnp>
</consulta_dnp>"""

REFERENCE_XML = """<?xml version="1.0" encoding="utf-8"?>
<consulta_dnp xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.catastro.meh.es/">
  <control><cudnp>1</cudnp><cucons>3</cucons><cucul>0</cucul></control>
  <bico>
    <bi>
      <idbi><cn>UR</cn><rc><pc1>1234567</pc1><pc2>AB1234C</pc2><car>0002</car><cc1>X</cc1><cc2>Y</cc2></rc></idbi>
      <dt>
        <loine><cp>03</cp><cm>76</cm></loine><cmc>76</cmc><np>ALICANTE</np><nm>GUARDAMAR DEL SEGURA</nm>
        <locs><lous><lourb>
          <dir><cv>345</cv><tv>CL</tv><nv>MAYOR</nv><pnp>12</pnp><snp>0</snp><td>EDIFICIO EJEMPLO</td></dir>
          <loint><es>1</es><pt>00</pt><pu>01</pu></loint><dp>03140</dp><dm>1</dm>
        </lourb></lous></locs>
      </dt>
      <ldt>CL MAYOR 12 Es:1 Pl:00 Pt:01 EDIFICIO EJEMPLO 03140 GUARDAMAR DEL SEGURA (ALICANTE)</ldt>
      <debi><luso>Residencial</luso><sfc>81</sfc><cpt>2,540000</cpt><ant>2006</ant></debi>
    </bi>
    <lcons>
      <cons><lcd>VIVIENDA</lcd><dt><lourb><loint><pt>00</pt><pu>01</pu></loint></lourb></dt><dfcons><stl>36</stl></dfcons></cons>
      <cons><lcd>APARCAMIENTO</lcd><dt><lourb><loint><pt>00</pt><pu>01</pu></loint></lourb></dt><dfcons><stl>10</stl></dfcons></cons>
    </lcons>
  </bico>
</consulta_dnp>"""

VIA_NOT_FOUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<consulta_dnp xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.catastro.meh.es/">
  <control><cuerr>1</cuerr></control>
  <lerr><err><cod>33</cod><des>LA VÍA NO EXISTE</des></err></lerr>
</consulta_dnp>"""

BAD_RC_XML = """<?xml version="1.0" encoding="utf-8"?>
<consulta_dnp xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.catastro.meh.es/">
  <control><cuerr>1</cuerr></control>
  <lerr><err><cod>3</cod><des>LA REFERENCIA CATASTRAL DEBE TENER 14,18 o 20 POSICIONES</des></err></lerr>
</consulta_dnp>"""

# --- Réel (23/09/2026) : ConsultaVia, filtré sur "HABANERAS" à Torrevieja (une seule rue trouvée) -----------------------
STREETS_XML = """<?xml version="1.0" encoding="utf-8"?>
<consulta_callejero xmlns="http://www.catastro.meh.es/">
  <control><cuca>2</cuca></control>
  <callejero>
    <calle><loine><cp>3</cp><cm>133</cm></loine><dir><cv>111</cv><tv>AV</tv><nv>HABANERAS DE LAS</nv></dir></calle>
    <calle><loine><cp>3</cp><cm>133</cm></loine><dir><cv>112</cv><tv>CL</tv><nv>HABANERAS PASAJE</nv></dir></calle>
  </callejero>
</consulta_callejero>"""

VIA_REQUIRED_XML = """<?xml version="1.0" encoding="utf-8"?>
<consulta_numerero xmlns="http://www.catastro.meh.es/">
  <control><cuerr>1</cuerr></control>
  <lerr><err><cod>41</cod><des>EL NÚMERO ES OBLIGATORIO.</des></err></lerr>
</consulta_numerero>"""


class TestViaCode:
    @pytest.mark.parametrize("text, code", [
        ("calle", "CL"), ("Avenida", "AV"), ("PLAZA", "PZ"), ("paseo", "PS"), ("carretera", "CR"),
        ("urbanizacion", "UR"), ("paraje", "PJ"), ("cl", "CL"), ("AV", "AV")])
    def test_common_words_and_existing_codes(self, text, code):
        assert catastro.via_code(text) == code

    def test_unknown_via_is_refused(self):
        with pytest.raises(catastro.CatastroError, match="type de voie inconnu"):
            catastro.via_code("boulevard")

    def test_default_is_calle(self):
        assert catastro.via_code(None) == "CL" and catastro.via_code("") == "CL"


class TestParseLocation:
    def test_reads_every_unit_with_its_reference_and_position(self):
        units = catastro.parse_location(LOCATION_XML)
        assert len(units) == 2
        assert units[0]["rc"] == "1234567AB1234C0002XY" and units[1]["rc"] == "1234567AB1234C0003ZW"
        assert units[0]["municipio"] == "GUARDAMAR DEL SEGURA" and units[0]["provincia"] == "ALICANTE"
        assert units[0]["calle"] == "CL MAYOR 12" and units[0]["edificio"] == "EDIFICIO EJEMPLO"
        assert units[0]["escalera"] == "1" and units[0]["planta"] == "00" and units[0]["puerta"] == "01"
        assert units[1]["puerta"] == "02"

    def test_a_not_found_address_raises_with_the_catastros_own_message(self):
        with pytest.raises(catastro.CatastroError, match="LA VÍA NO EXISTE"):
            catastro.parse_location(VIA_NOT_FOUND_XML)


class TestParseReference:
    def test_reads_address_use_surface_year_and_constructions(self):
        d = catastro.parse_reference(REFERENCE_XML)
        assert d["rc"] == "1234567AB1234C0002XY"
        assert d["direccion"] == "CL MAYOR 12 Es:1 Pl:00 Pt:01 EDIFICIO EJEMPLO 03140 GUARDAMAR DEL SEGURA (ALICANTE)"
        assert d["uso"] == "Residencial" and d["superficie_m2"] == 81 and d["ano_construccion"] == "2006"
        assert d["cuota_participacion"] == "2,540000"
        assert d["construcciones"] == [{"tipo": "VIVIENDA", "superficie_m2": 36}, {"tipo": "APARCAMIENTO", "superficie_m2": 10}]

    def test_an_invalid_reference_raises_with_the_catastros_own_message(self):
        with pytest.raises(catastro.CatastroError, match="20 POSICIONES"):
            catastro.parse_reference(BAD_RC_XML)

    def test_never_a_value_or_an_owner(self):
        """Aucun champ de valeur ni de propriétaire n'existe dans cette réponse : le service ne les fournit jamais ici."""
        d = catastro.parse_reference(REFERENCE_XML)
        blob = str(d).lower()
        for word in ("valor", "titular", "propietario"):
            assert word not in blob


class TestParseStreets:
    def test_reads_type_and_name(self):
        streets = catastro.parse_streets(STREETS_XML)
        assert streets == [{"tipo": "AV", "nombre": "HABANERAS DE LAS"}, {"tipo": "CL", "nombre": "HABANERAS PASAJE"}]

    def test_a_service_error_raises(self):
        with pytest.raises(catastro.CatastroError, match="(?i)obligatorio"):
            catastro.parse_streets(VIA_REQUIRED_XML)


class TestListStreets:
    def test_sends_the_filters_and_parses_the_result(self):
        calls = []

        def fetch(url, params):
            calls.append((url, params))
            return 200, STREETS_XML

        streets = catastro.list_streets("alicante", "torrevieja", nombre="habaneras", fetch=fetch)
        assert len(streets) == 2
        (url, params), = calls
        assert url.endswith("/ConsultaVia")
        assert params == {"Provincia": "alicante", "Municipio": "torrevieja", "TipoVia": "", "NombreVia": "habaneras"}

    def test_a_via_type_filter_is_converted_to_its_code(self):
        calls = []
        catastro.list_streets("alicante", "torrevieja", tipo="avenida", fetch=lambda u, p: (calls.append(p), (200, STREETS_XML))[1])
        assert calls[0]["TipoVia"] == "AV"


class TestReadAddresses:
    def test_reads_required_and_optional_columns(self, tmp_path):
        path = tmp_path / "adresses.csv"
        path.write_text("provincia,municipio,calle,numero,via\nalicante,torrevieja,calle la sal,21,calle\n", encoding="utf-8")
        rows = catastro.read_addresses(path)
        assert rows == [{"provincia": "alicante", "municipio": "torrevieja", "calle": "calle la sal", "numero": "21", "via": "calle"}]

    def test_missing_required_column_is_explained(self, tmp_path):
        path = tmp_path / "adresses.csv"
        path.write_text("provincia,municipio,calle\nalicante,torrevieja,calle la sal\n", encoding="utf-8")
        with pytest.raises(catastro.CatastroError, match="numero"):
            catastro.read_addresses(path)

    def test_a_missing_file_is_explained(self, tmp_path):
        with pytest.raises(catastro.CatastroError, match="introuvable"):
            catastro.read_addresses(tmp_path / "nope.csv")


class TestBatch:
    def address(self, **extra):
        return {"provincia": "alicante", "municipio": "guardamar del segura", "calle": "mayor", "numero": "12", **extra}

    def test_one_address_gives_one_row_per_unit_without_detail_by_default(self):
        fetch = lambda u, p: (200, LOCATION_XML)  # noqa: E731
        rows = catastro.batch([self.address()], sleep=lambda s: None, fetch=fetch)
        assert len(rows) == 2 and rows[0]["rc"] == "1234567AB1234C0002XY" and "uso" not in rows[0]

    def test_detalle_adds_a_second_request_per_unit_and_the_full_fields(self):
        calls = []

        def fetch(url, params):
            calls.append(url)
            return (200, LOCATION_XML) if url.endswith("DNPLOC") else (200, REFERENCE_XML)

        rows = catastro.batch([self.address()], detalle=True, sleep=lambda s: None, fetch=fetch)
        assert rows[0]["uso"] == "Residencial" and rows[0]["superficie_m2"] == 81
        assert calls.count("http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx/Consulta_DNPRC") == 2  # une par unité

    def test_an_address_that_fails_is_logged_and_does_not_stop_the_rest(self):
        logs = []
        addresses = [self.address(calle="rue qui n'existe pas"), self.address()]

        def fetch(url, params):
            return (200, VIA_NOT_FOUND_XML) if params["Calle"] == "rue qui n'existe pas" else (200, LOCATION_XML)

        rows = catastro.batch(addresses, sleep=lambda s: None, fetch=fetch, log=logs.append)
        assert len(rows) == 2 and any("LA VÍA NO EXISTE" in line for line in logs)

    def test_requests_are_paced(self):
        pauses = []
        catastro.batch([self.address(), self.address()], sleep=pauses.append, pause=1.0, fetch=lambda u, p: (200, LOCATION_XML))
        assert pauses == [1.0]                                             # rien avant la première adresse

    def test_a_detail_request_that_fails_once_is_retried_and_can_still_succeed(self):
        """Vu en réel sur un immeuble de 39 unités : le service échoue parfois sur une longue série (12 échecs sur 39)."""
        attempts = {}

        def fetch(url, params):
            if url.endswith("DNPLOC"):
                return 200, LOCATION_XML
            rc = params["RC"]
            attempts[rc] = attempts.get(rc, 0) + 1
            return (None, "") if attempts[rc] == 1 else (200, REFERENCE_XML)          # échoue une fois, réussit ensuite

        rows = catastro.batch([self.address()], detalle=True, sleep=lambda s: None, fetch=fetch)
        assert all(r["uso"] == "Residencial" for r in rows) and set(attempts.values()) == {2}

    def test_a_detail_request_that_always_fails_gives_an_empty_detail_not_a_crash(self):
        logs = []

        def fetch(url, params):
            return (200, LOCATION_XML) if url.endswith("DNPLOC") else (None, "")

        rows = catastro.batch([self.address()], detalle=True, sleep=lambda s: None, fetch=fetch, log=logs.append)
        assert all(r.get("uso") is None for r in rows) and len(rows) == 2
        assert sum("HTTP None" in line for line in logs) == 2                          # une fois par unité, après la relance

    def test_the_retry_waits_longer_than_the_first_attempt(self):
        pauses = []

        def fetch(url, params):
            return (200, LOCATION_XML) if url.endswith("DNPLOC") else (None, "")

        catastro.batch([self.address()], detalle=True, sleep=pauses.append, pause=1.0, fetch=fetch)
        assert pauses[-2:] == [1.0, 3.0]                                               # dernière unité : essai puis relance


class TestByLocationAndByReference:
    def test_by_location_sends_every_required_field_and_parses_the_result(self):
        calls = []

        def fetch(url, params):
            calls.append((url, params))
            return 200, LOCATION_XML

        units = catastro.by_location("alicante", "guardamar del segura", "mayor", "12", fetch=fetch)
        assert len(units) == 2
        (url, params), = calls
        assert url.endswith("/Consulta_DNPLOC")
        assert params == {"Provincia": "alicante", "Municipio": "guardamar del segura", "Sigla": "CL",
                          "Calle": "mayor", "Numero": "12", "Bloque": "", "Escalera": "", "Planta": "", "Puerta": ""}

    def test_by_reference_sends_the_rc_and_parses_the_result(self):
        calls = []

        def fetch(url, params):
            calls.append((url, params))
            return 200, REFERENCE_XML

        d = catastro.by_reference("1234567AB1234C0002XY", fetch=fetch)
        assert d["superficie_m2"] == 81
        (url, params), = calls
        assert url.endswith("/Consulta_DNPRC") and params["RC"] == "1234567AB1234C0002XY"

    def test_a_connection_failure_is_explained(self):
        with pytest.raises(catastro.CatastroError, match="HTTP 503"):
            catastro.by_reference("x", fetch=lambda u, p: (503, ""))


class TestCommandLine:
    def test_by_reference_prints_the_detail_and_the_protected_data_notice(self, capsys):
        catastro.main(["--rc", "1234567AB1234C0002XY"], fetch=lambda u, p: (200, REFERENCE_XML))
        out = capsys.readouterr().out
        assert "81 m2" in out and "Residencial" in out and "2006" in out and "VIVIENDA" in out
        assert "ne donne ici ni valeur ni nom de propriétaire" in out

    def test_by_address_prints_the_list_of_units(self, capsys):
        catastro.main(["--provincia", "alicante", "--municipio", "guardamar del segura", "--calle", "mayor",
                       "--numero", "12"], fetch=lambda u, p: (200, LOCATION_XML))
        out = capsys.readouterr().out
        assert "2 unité(s)" in out and "1234567AB1234C0002XY" in out and "1234567AB1234C0003ZW" in out

    def test_neither_rc_nor_a_full_address_is_refused(self):
        with pytest.raises(SystemExit):
            catastro.main(["--provincia", "alicante"])

    def test_a_catastro_error_stops_cleanly(self, capsys):
        with pytest.raises(SystemExit, match="LA VÍA NO EXISTE"):
            catastro.main(["--provincia", "alicante", "--municipio", "torrevieja", "--calle", "x", "--numero", "1"],
                          fetch=lambda u, p: (200, VIA_NOT_FOUND_XML))

    def test_via_defaults_to_calle_and_accepts_a_common_word(self, capsys):
        calls = []

        def fetch(url, params):
            calls.append(params)
            return 200, LOCATION_XML

        catastro.main(["--provincia", "alicante", "--municipio", "torrevieja", "--via", "avenida", "--calle", "x", "--numero", "1"],
                      fetch=fetch)
        assert calls[0]["Sigla"] == "AV"

    def test_by_address_with_detalle_gives_the_full_detail_of_every_unit(self, capsys):
        def fetch(url, params):
            return (200, LOCATION_XML) if url.endswith("DNPLOC") else (200, REFERENCE_XML)

        catastro.main(["--provincia", "alicante", "--municipio", "guardamar del segura", "--calle", "mayor",
                       "--numero", "12", "--detalle", "--pause", "0"], fetch=fetch, sleep=lambda s: None)
        out = capsys.readouterr().out
        assert "2 unité(s)" in out and "Residencial" in out and "81" in out            # pas seulement la liste des RC

    def test_by_address_with_detalle_and_csv_exports_every_unit(self, tmp_path):
        target = tmp_path / "batiment.csv"

        def fetch(url, params):
            return (200, LOCATION_XML) if url.endswith("DNPLOC") else (200, REFERENCE_XML)

        catastro.main(["--provincia", "alicante", "--municipio", "guardamar del segura", "--calle", "mayor",
                       "--numero", "12", "--detalle", "--csv", str(target), "--pause", "0"], fetch=fetch, sleep=lambda s: None)
        with open(target, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2 and all(r["uso"] == "Residencial" for r in rows)

    def test_calles_lists_the_streets_of_a_municipality(self, capsys):
        catastro.main(["--calles", "--provincia", "alicante", "--municipio", "torrevieja", "--calle", "habaneras"],
                      fetch=lambda u, p: (200, STREETS_XML))
        out = capsys.readouterr().out
        assert "2 rue(s)" in out and "HABANERAS DE LAS" in out and "HABANERAS PASAJE" in out

    def test_calles_needs_provincia_and_municipio(self):
        with pytest.raises(SystemExit):
            catastro.main(["--calles", "--provincia", "alicante"])

    def test_adresses_prints_a_table_of_every_unit(self, tmp_path, capsys):
        path = tmp_path / "adresses.csv"
        path.write_text("provincia,municipio,calle,numero\nalicante,guardamar del segura,mayor,12\n", encoding="utf-8")
        catastro.main(["--adresses", str(path), "--pause", "0"], fetch=lambda u, p: (200, LOCATION_XML), sleep=lambda s: None)
        out = capsys.readouterr().out
        assert "2 unité(s)" in out and "1234567AB1234C0002XY" in out

    def test_adresses_with_csv_exports_and_flattens_constructions(self, tmp_path):
        input_path, output_path = tmp_path / "in.csv", tmp_path / "out.csv"
        input_path.write_text("provincia,municipio,calle,numero\nalicante,guardamar del segura,mayor,12\n", encoding="utf-8")

        def fetch(url, params):
            return (200, LOCATION_XML) if url.endswith("DNPLOC") else (200, REFERENCE_XML)

        catastro.main(["--adresses", str(input_path), "--detalle", "--csv", str(output_path), "--pause", "0"], fetch=fetch, sleep=lambda s: None)
        with open(output_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2 and rows[0]["uso"] == "Residencial" and "VIVIENDA" in rows[0]["construcciones"]

    def test_adresses_file_not_found_is_explained(self):
        with pytest.raises(SystemExit, match="introuvable"):
            catastro.main(["--adresses", "nope.csv"], fetch=lambda u, p: (200, ""))
