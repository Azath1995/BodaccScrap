import pytest

from bodacc.cabinets import cabinet_name, match_cabinet, normalize_cabinet

# (désignation brute réelle, nom de cabinet attendu)
NAME_CASES = [
    pytest.param(
        "la Selarl BLEU SUD Représentée par Maître MARTIN Claire 8 avenue des Tilleuls 30000 Nîmes",
        "Selarl BLEU SUD", id="representee-par"),
    pytest.param(
        "Sas les Mandataires Prise en la Personne de Maître Durand Paul 305 boulevard des Platanes",
        "Sas les Mandataires", id="prise-en-la-personne"),
    pytest.param(
        "SAS LES MANDATAIRES, mission conduite par Maître Paul DURAND, 3 rue des Écoles",
        "SAS LES MANDATAIRES", id="virgule"),
    pytest.param(
        "Selarl Mj Alpes, Prise en la Personne de Me Morel cs 90000 91-93 rue de la Gare",
        "Selarl Mj Alpes", id="virgule-puis-prise-en"),
    pytest.param(
        "SELARL Mj Synergie - Mandataires Judiciaires en la personne de Me Luc Bernard 9 Place",
        "SELARL Mj Synergie", id="tiret-espace"),
    pytest.param(
        "la SELARL MJ SYNERGIE (en la personne de Me Jean-Luc PETIT) 9 rue des Lilas",
        "SELARL MJ SYNERGIE", id="parenthese"),
    pytest.param(
        "Selarl Sophie Garnier (me Sophie Garnier) 13 bis Boulevard des Roses Cs 40000",
        "Selarl Sophie Garnier", id="parenthese-meme-personne"),
    pytest.param(
        "SELARL B.G.H./ Me J.-P.Roux Et Me A.Blanc 44 Rue des Acacias",
        "SELARL B.G.H.", id="slash-sans-espace"),
    pytest.param(
        "Selarl C.Basse Mission Conduite Par Me Christophe Basse 171 AVENUE DES PINS",
        "Selarl C.Basse", id="mission-conduite-majuscules"),
    pytest.param(
        "la SCP Louis-Lageat & Associes, Prise en la Personne de Maître Julie Moreau, le président, 90 boulevard",
        "SCP Louis-Lageat & Associes", id="esperluette-conservee"),
    pytest.param(
        "SELARL S21Y - Maître Anne LEFEBVRE", "SELARL S21Y", id="chiffre-dans-le-nom"),
    pytest.param(
        "Selarl Miquel-aras 35-37 Rue du Moulin 62000 Arras",
        "Selarl Miquel-aras", id="adresse-directe"),
    pytest.param(
        "Maître Jean-Pierre CELERI 22, cours des Palmiers - 20000 Ajaccio",
        "Maître Jean-Pierre CELERI", id="mandataire-individuel"),
    pytest.param(
        "Danguy Marie 2 Bis Rue des Fleurs 93000 Bobigny", "Danguy Marie", id="sans-civilite"),
    pytest.param(
        "Me Yann Lefort Pour La Selarl MJ Lefort 207, rue du Port Et 127 rue des Vignes - 83600 Fréjus",
        "Selarl MJ Lefort", id="pour-la-selarl"),
    pytest.param(
        "Maître Philippe Delaere de la Selarl Philippe Delaere et associes 20 rue des Mouettes 44000 Nantes",
        "Selarl Philippe Delaere et associes", id="de-la-selarl"),
    pytest.param(
        "(selarl) Etude BALINCOURT représentée par Me Thomas GIRARD et Me Emma FAURE 3, boulevard du Lac - 07",
        "Etude BALINCOURT", id="forme-juridique-entre-parentheses-en-tete"),
    pytest.param(
        "(selarl) MJ Synergie représentée par Maître Luc BERNARD 7, rue du Pont - 07100 Annonay",
        "MJ Synergie", id="parentheses-en-tete-2"),
    pytest.param(
        "/ Selarl Guigon associés 3 avenue des Chênes 25000 Besançon",
        "Selarl Guigon associés", id="slash-en-tete"),
    pytest.param(
        "Lambert Pierre 1 rue A 75001 Paris", "Lambert Pierre", id="nom-commencant-par-la-sans-etre-un-article"),
    pytest.param(
        "Legras De Grandcourt Patrick 10/14 passage des Arts 92000 Nanterre",
        "Legras De Grandcourt Patrick", id="nom-commencant-par-le"),
    pytest.param(
        "l'Etude Martin 3 rue B 69003 Lyon", "Etude Martin", id="article-elide"),
    pytest.param(
        "le Cabinet Durand 2 rue B 75002 Paris", "Cabinet Durand", id="article-le"),
]


@pytest.mark.parametrize("designation, attendu", NAME_CASES)
def test_cabinet_name(designation, attendu):
    assert cabinet_name(designation) == attendu


@pytest.mark.parametrize("vide", [None, "", "   "])
def test_cabinet_name_empty(vide):
    assert cabinet_name(vide) is None


class TestNormalize:
    def test_case_accents_and_legal_forms_are_ignored(self):
        assert normalize_cabinet("SAS LES MANDATAIRES") == normalize_cabinet("Sas les Mandataires")
        assert normalize_cabinet("Selarl Étude Balincourt") == "etude balincourt"

    def test_punctuation_and_ampersand(self):
        assert normalize_cabinet("C.BASSE") == "c basse"
        assert normalize_cabinet("SELARL BENOIT & ASSOCIES") == normalize_cabinet("Benoit & Associés")

    def test_none(self):
        assert normalize_cabinet(None) == ""

    @pytest.mark.parametrize("text", ["l'Etude Martin", "l’Etude Martin", "L'ETUDE MARTIN"])
    def test_elided_article_is_dropped(self, text):
        assert normalize_cabinet(text) == "etude martin"

    def test_the_letter_l_in_initials_is_kept(self):
        assert normalize_cabinet("SELAS C.L.R. & ASSOCIES") == "c l r associes"
        assert normalize_cabinet("SELAS C.L.R. & ASSOCIES") != normalize_cabinet("SELAS C.R. & ASSOCIES")


REGISTRY = ["Les Mandataires", "C.BASSE", "Etude Balincourt", "Benoit & Associés", "BTSG"]


class TestMatchCabinet:
    @pytest.mark.parametrize("designation, attendu", [
        ("Sas les Mandataires Prise en la Personne de Maître Durand Paul 305 boulevard", "Les Mandataires"),
        ("Selarl C.Basse Mission Conduite Par Me Christophe Basse 171 AVENUE", "C.BASSE"),
        ("la Selarl ETUDE BALINCOURT Représentée par Me GIRARD Thomas 29 rue des Peupliers", "Etude Balincourt"),
        ("SELARL BENOIT & ASSOCIES prise en la personne de Maître Laura MERCIER 16, rue", "Benoit & Associés"),
    ])
    def test_finds_registry_entry(self, designation, attendu):
        assert match_cabinet(designation, REGISTRY) == attendu

    def test_leading_parenthesis_no_longer_hides_a_known_cabinet(self):
        designation = "(selarl) Etude BALINCOURT représentée par Me Thomas GIRARD 3, boulevard du Lac - 07"
        assert match_cabinet(designation, REGISTRY) == "Etude Balincourt"

    def test_initials_with_an_l_do_not_collide_with_other_initials(self):
        clr = "SELAS C.L.R. & ASSOCIES prise en la personne de Maître X 3, rue des Saules - 49000 Angers"
        cr = "SELAS C.R. & ASSOCIES prise en la personne de Maître X 3, rue des Saules - 49000 Angers"
        assert match_cabinet(clr, ["C.L.R. & Associes"]) == "C.L.R. & Associes"
        assert match_cabinet(cr, ["C.L.R. & Associes"]) is None

    def test_unknown_cabinet_gives_none(self):
        assert match_cabinet("la Selarl BLEU SUD Représentée par Maître MARTIN Claire 8 avenue", REGISTRY) is None

    def test_empty_designation_gives_none(self):
        assert match_cabinet(None, REGISTRY) is None

    def test_longest_known_name_wins(self):
        known = ["Mandataires", "Les Mandataires Sud"]
        assert match_cabinet("Sas Les Mandataires Sud représentée par Me X", known) == "Les Mandataires Sud"

    def test_matches_whole_words_only(self):
        assert match_cabinet("Selarl MJ2A représentée par Me X", ["MJ"]) is None
