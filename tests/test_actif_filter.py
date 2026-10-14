import pytest

from bodacc.actif_filter import ActifFilter, normalize


def matches(text, keywords=None):
    pattern = ActifFilter.build_pattern(keywords or ActifFilter.VEHICULE_KEYWORDS)
    return bool(pattern.search(normalize(text)))


class TestNormalize:
    def test_strips_accents_and_case(self):
        assert normalize("Véhicules > Autres") == "vehicules > autres"

    def test_handles_none(self):
        assert normalize(None) == ""


class TestPattern:
    @pytest.mark.parametrize("text", [
        "Véhicules > Autres",
        "vehicule",
        "Voitures",
        "Camion benne",
        "Deux-roues",
        "Auto",
        "Remorques",
    ])
    def test_matches_real_vehicle_types(self, text):
        assert matches(text)

    @pytest.mark.parametrize("text", [
        "Automate de paiement",     # contient 'auto' mais n'est pas un véhicule
        "Autoclave",
        "Motorisation industrielle",
        "Matériel de bureau",
        "",
    ])
    def test_rejects_lookalikes(self, text):
        assert not matches(text)

    def test_custom_keywords(self):
        assert matches("Bateau de pêche", keywords=["bateau"])
        assert not matches("Véhicules", keywords=["bateau"])
