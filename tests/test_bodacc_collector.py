import json

import pytest

from bodacc.bodacc_collector import BodaccLiquidationScraper

extract = BodaccLiquidationScraper.extract_liquidateur

BOILERPLATE = (
    " Les déclarations des créances sont à adresser au liquidateur judiciaire "
    "ou sur le portail électronique prévu par les articles L. 814-2 et L. 814-13 "
    "du code de commerce dans les deux mois à compter de la présente publication."
)

# Textes réels du BODACC (18/09/2026), un par variante de formulation.
REAL_CASES = [
    pytest.param(
        "Jugement prononçant la liquidation judiciaire, date de cessation des "
        "paiements le 1 janvier 2026, désignant liquidateur Sas les Mandataires "
        "Prise en la Personne de Maître Durand Paul 305 boulevard "
        "des Platanes 13300 Salon-de-Provence." + BOILERPLATE,
        "Sas les Mandataires Prise en la Personne de Maître Durand Paul "
        "305 boulevard des Platanes 13300 Salon-de-Provence",
        id="designant-liquidateur",
    ),
    pytest.param(
        "Jugement prononçant la liquidation judiciaire simplifiée, date de "
        "cessation des paiements le 9 mars 2025, désignant en qualité de "
        "liquidateur la Selarl BLEU SUD Représentée par Maître MARTIN Claire "
        "8 avenue des Tilleuls 30000 Nîmes." + BOILERPLATE,
        "la Selarl BLEU SUD Représentée par Maître MARTIN Claire "
        "8 avenue des Tilleuls 30000 Nîmes",
        id="en-qualite-de-liquidateur",
    ),
    pytest.param(
        "Jugement prononçant la liquidation judiciaire simplifiée, date de "
        "cessation des paiements le 1 juillet 2026, désignant en qualtié de "
        "liquidateur la Selarlu LEROY Marc Pris en la Personne de Maître "
        "LEROY Marc 285 rue des Oliviers 30900 Nîmes." + BOILERPLATE,
        "la Selarlu LEROY Marc Pris en la Personne de Maître "
        "LEROY Marc 285 rue des Oliviers 30900 Nîmes",
        id="faute-de-frappe-qualtie",
    ),
    pytest.param(
        "Jugement du Tribunal de Commerce de Nîmes en date du 08/09/2026 "
        "prononçant la conversion en liquidation judiciaire désignant en "
        "qualité de Liquidateur judiciaire la SELARL BLEU SUD représentée par "
        "Maître MARTIN Claire 8 avenue des Tilleuls 30000 Nîmes",
        "la SELARL BLEU SUD représentée par Maître MARTIN Claire "
        "8 avenue des Tilleuls 30000 Nîmes",
        id="liquidateur-judiciaire-sans-point-final",
    ),
    pytest.param(
        "Jugement du Tribunal de Commerce de Gap en date du 16/09/2026 "
        "prononçant la conversion en liquidation judiciaire. Liquidateur "
        "judiciaire : SAS LES MANDATAIRES, mission conduite par Maître Paul "
        "DURAND, 3 rue des Écoles, Cs 90000, 05000 Gap CEDEX.",
        "SAS LES MANDATAIRES, mission conduite par Maître Paul "
        "DURAND, 3 rue des Écoles, Cs 90000, 05000 Gap CEDEX",
        id="liquidateur-judiciaire-deux-points",
    ),
    pytest.param(
        "Jugement prononçant la liquidation judiciaire, désignant liquidateur "
        "Maître Jean-Pierre CELERI 22, cours des Palmiers - 20000 Ajaccio . Les "
        "créances sont à adresser, dans les deux mois de la présente publication.",
        "Maître Jean-Pierre CELERI 22, cours des Palmiers - 20000 Ajaccio",
        id="phrase-finale-les-creances",
    ),
    pytest.param(
        "Jugement de conversion en liquidation judiciaire, désignant liquidateur "
        "la Selarl Cardon Prise en la Personne de Me Cardon 1 rue A 75001 Paris, "
        "et mettant fin à la mission de l'administrateur Me Hugo Lambert.",
        "la Selarl Cardon Prise en la Personne de Me Cardon 1 rue A 75001 Paris",
        id="clause-et-mettant-fin-a-la-mission",
    ),
]


@pytest.mark.parametrize("texte, attendu", REAL_CASES)
def test_extract_liquidateur_real_wordings(texte, attendu):
    assert extract({"complementJugement": texte}) == attendu


@pytest.mark.parametrize("texte, attendu", REAL_CASES)
def test_never_captures_the_boilerplate(texte, attendu):
    assert "Les déclarations" not in extract({"complementJugement": texte})


class TestNoLiquidateur:
    def test_boilerplate_mention_alone_is_not_a_designation(self):
        # "au liquidateur judiciaire" dans la phrase finale ne doit pas matcher.
        texte = "Jugement prononçant la liquidation judiciaire." + BOILERPLATE
        assert extract({"complementJugement": texte}) is None

    @pytest.mark.parametrize("jugement", [None, "", {}, {"complementJugement": ""}])
    def test_empty_inputs(self, jugement):
        assert extract(jugement) is None


def test_accepts_jugement_as_json_string():
    texte = "désignant liquidateur la Selarl X 1 rue A 75001 Paris." + BOILERPLATE
    as_json = json.dumps({"complementJugement": texte})
    assert extract(as_json) == "la Selarl X 1 rue A 75001 Paris"


class TestExtractSiren:
    def test_finds_nine_digit_number_ignoring_spaces(self):
        assert BodaccLiquidationScraper.extract_siren(["RCS Lyon", "123 456 789"]) == "123456789"

    def test_returns_none_when_absent(self):
        assert BodaccLiquidationScraper.extract_siren(["RCS Lyon", None]) is None
        assert BodaccLiquidationScraper.extract_siren(None) is None
