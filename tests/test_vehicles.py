import pytest

from bodacc.vehicles import (
    count_vehicles, find_fuel, find_make, find_mileage, find_plate, find_year, parse_vehicle,
)

# Textes réels des flux RSS (titre, description nettoyée, résultat attendu).
REAL = [
    pytest.param(
        "A vendre : VEHICULE 07340 ANDANCE",
        "VP RENAULT ZOE | Immatriculé : FX-202-CD | 1ère mise en circulation : 31/10/2017 | Environ 105 759 kms",
        {"marque": "Renault", "immatriculation": "FX-202-CD", "kilometrage": 105759,
         "annee": 2017, "carburant": None},
        id="synergie-zoe"),
    pytest.param(
        "A vendre : VEHICULE 42000 SAINT-ÉTIENNE",
        "PEUGEOT PARTNER | Immatriculation : FX-303-EF | Kilométrage : 300210 | Mise en circulation : 02.03.2017",
        {"marque": "Peugeot", "immatriculation": "FX-303-EF", "kilometrage": 300210,
         "annee": 2017, "carburant": None},
        id="synergie-partner-kilometrage-avec-libelle"),
    pytest.param(
        "A vendre : FORD FIESTA FOURGON 91000 EVRY",
        "gasoil | Immatriculé FX-101-AB | 174 676 kms",
        {"marque": "Ford", "immatriculation": "FX-101-AB", "kilometrage": 174676,
         "annee": None, "carburant": "diesel"},
        id="basse-fiesta"),
    pytest.param(
        "A vendre : MERCEDES VITO 29870 LANNILIS",
        "MERCEDES VITO de 2016 - 209.309 km",
        {"marque": "Mercedes", "immatriculation": None, "kilometrage": 209309,
         "annee": 2016, "carburant": None},
        id="fides-vito-point-milliers"),
    pytest.param(
        "A vendre : Ctte Volkswagen Transporter 29490 GUIPAVAS",
        "Ctte Volkswagen Transporter | caisse plastifiée | 201.000 kms",
        {"marque": "Volkswagen", "immatriculation": None, "kilometrage": 201000,
         "annee": None, "carburant": None},
        id="fides-transporter"),
    pytest.param(
        "A vendre : Pelle mécanique 24610 SAINT-MÉARD-DE-GURÇON",
        "Pelle mécanique KOMATSU | modèle PC80 MR | Année 2011 | 3520,5h",
        {"marque": "Komatsu", "immatriculation": None, "kilometrage": None,
         "annee": 2011, "carburant": None},
        id="lga-pelle-heures-ne-sont-pas-des-km"),
    pytest.param(
        "A vendre : CLIO VASP - DERIV VP 91100 CORBEIL-ESSONNES",
        None,
        {"marque": "Renault", "immatriculation": None, "kilometrage": None,
         "annee": None, "carburant": None},
        id="marque-deduite-du-modele"),
    pytest.param(
        "A vendre : VOLVO XC60 HYBRIDE 33220 PINEUILH",
        "essence hybride rechargeable",
        {"marque": "Volvo", "immatriculation": None, "kilometrage": None,
         "annee": None, "carburant": "hybride"},
        id="hybride-prioritaire-sur-essence"),
]


@pytest.mark.parametrize("titre, description, attendu", REAL)
def test_real_listings(titre, description, attendu):
    assert parse_vehicle(titre, description) == attendu


def test_nothing_found_gives_none_everywhere():
    assert parse_vehicle("A vendre : TABLE 75001 PARIS", "Table en bois") == {
        "marque": None, "immatriculation": None, "kilometrage": None,
        "annee": None, "carburant": None,
    }


def test_missing_inputs_do_not_crash():
    assert parse_vehicle(None, None)["marque"] is None


class TestCountVehicles:
    @pytest.mark.parametrize("titre, description, attendu", [
        ("A vendre : VEHICULE 07340 ANDANCE", "VP RENAULT ZOE | Immatriculé : FX-202-CD", 1),
        ("A vendre : LJ - Cession de Véhicule 92200 NEUILLY", "liquidation de la société UBIQUE, deux véhicules CLIO", 2),
        ("A vendre : Lot de 3 camions 33000 BORDEAUX", None, 3),
        ("A vendre : Cinq voitures 75001 PARIS", None, 5),
        ("A vendre : 12 véhicules 75001 PARIS", None, 12),
        ("A vendre : VEHICULES 69000 LYON", "FX-101-AB et AB-123-CD", 2),               # deux plaques distinctes
        ("A vendre : VEHICULE 69000 LYON", "1 véhicule Renault Kangoo, FX-101-AB | FX 101 AB", 1),   # même plaque écrite deux fois
        ("A vendre : Matériel professionnel + véhicule (électricien)", "matériel d'électricité et véhicules", 1),
        ("A vendre : Table 75001 PARIS", "Table en bois", 1),
    ])
    def test_count(self, titre, description, attendu):
        assert count_vehicles(titre, description) == attendu

    def test_the_largest_indication_wins_and_they_are_not_added(self):
        """Le titre et la description répètent souvent la même chose : 2 + 2 ne fait pas 4."""
        assert count_vehicles("A vendre : 2 véhicules 75001", "deux véhicules dont un CLIO") == 2

    def test_a_number_that_is_not_in_front_of_a_vehicle_word_is_ignored(self):
        assert count_vehicles("A vendre : Fourgon 33000", "174 676 kms, 4 portes, 2 clés, année 2016") == 1

    def test_missing_inputs_do_not_crash(self):
        assert count_vehicles(None, None) == 1


class TestPlate:
    @pytest.mark.parametrize("text, attendu", [
        ("Immatriculé FX-101-AB", "FX-101-AB"),
        ("immatriculation ab123cd", "AB-123-CD"),      # sans tirets, en minuscules
        ("FX 404 GH", "FX-404-GH"),
    ])
    def test_formats(self, text, attendu):
        assert find_plate(text) == attendu

    def test_letters_i_o_u_are_not_valid_in_a_plate(self):
        assert find_plate("IO-123-UI") is None

    def test_old_format_is_not_recognised(self):
        assert find_plate("RENAULT MASTER BENNE 6639 PE 33") is None   # limite connue


class TestMileage:
    @pytest.mark.parametrize("text, attendu", [
        ("174 676 kms", 174676), ("209.309 km", 209309), ("95000 km", 95000),
        ("Kilométrage : 300210", 300210), ("Environ 105 759 kms", 105759),
    ])
    def test_formats(self, text, attendu):
        assert find_mileage(text) == attendu

    def test_year_right_before_the_mileage_is_not_glued_to_it(self):
        assert find_mileage("de 2016 209.309 km") == 209309

    def test_implausible_values_are_rejected(self):
        assert find_mileage("9 999 999 km") is None

    def test_hours_are_not_kilometres(self):
        assert find_mileage("3520,5h") is None


class TestYear:
    @pytest.mark.parametrize("text, attendu", [
        ("1ère MEC: 22/08/2022", 2022), ("Année 2011", 2011), ("MILLESIME 2004", 2004),
        ("Mise en circulation : 02.03.2017", 2017), ("Golf de 2019", 2019),
        ("PEUGEOT EXPERT DU 29/10/19 FL463DY", 2019), ("RENAULT MASTER L2H2 , FX-505-JK, du 12/02/2024", 2024),
        ("CTTE RENAULT CLIO SOCIETE EY889PM | GO 4CV DU 27/06/18", 2018), ("TRACTEUR du 12/05/98", 1998),
    ])
    def test_formats(self, text, attendu):
        assert find_year(text) == attendu

    def test_a_year_in_the_future_is_rejected(self):
        assert find_year("Année 2099") is None


class TestMakeAndFuel:
    def test_word_boundaries(self):
        assert find_make("MANUSCOPIQUE") is None          # ne contient pas "MAN" comme mot
        assert find_make("Semi remorque MAN TGX") == "MAN"

    def test_earliest_brand_wins(self):
        assert find_make("FORD TRANSIT") == "Ford"

    @pytest.mark.parametrize("text, attendu", [
        ("gasoil", "diesel"), ("Diesel", "diesel"), ("SP95", "essence"),
        ("Électrique", "électrique"), ("rien", None),
    ])
    def test_fuel(self, text, attendu):
        assert find_fuel(text) == attendu
