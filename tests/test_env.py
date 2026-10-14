"""`bodacc.env` : clés locales lues dans une variable d'environnement, sinon dans `.env` (exclu de git)."""
import subprocess

from bodacc import env


def write(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


class TestReadEnvFile:
    def test_reads_names_and_values_and_skips_comments_and_blank_lines(self, tmp_path):
        path = write(tmp_path, "# commentaire\n\nCARAPIS_API_KEY=car_abc\nAUTRE = valeur avec espaces \n")
        assert env.read_env_file(path) == {"CARAPIS_API_KEY": "car_abc", "AUTRE": "valeur avec espaces"}

    def test_quotes_around_a_value_are_removed(self, tmp_path):
        path = write(tmp_path, 'A="car_1"\nB=\'car_2\'\n')
        assert env.read_env_file(path) == {"A": "car_1", "B": "car_2"}

    def test_a_value_containing_an_equal_sign_is_kept_whole(self, tmp_path):
        assert env.read_env_file(write(tmp_path, "K=abc=def\n")) == {"K": "abc=def"}

    def test_a_missing_file_gives_nothing(self, tmp_path):
        assert env.read_env_file(tmp_path / "absent.env") == {}


class TestGet:
    def test_the_environment_variable_wins_over_the_file(self, tmp_path):
        path = write(tmp_path, "CARAPIS_API_KEY=car_fichier\n")
        assert env.get("CARAPIS_API_KEY", path, environ={"CARAPIS_API_KEY": "car_env"}) == "car_env"

    def test_the_file_is_used_when_the_variable_is_absent(self, tmp_path):
        path = write(tmp_path, "CARAPIS_API_KEY=car_fichier\n")
        assert env.get("CARAPIS_API_KEY", path, environ={}) == "car_fichier"

    def test_an_empty_value_counts_as_absent(self, tmp_path):
        path = write(tmp_path, "CARAPIS_API_KEY=\n")
        assert env.get("CARAPIS_API_KEY", path, environ={"CARAPIS_API_KEY": ""}) is None


def test_the_real_env_file_is_ignored_by_git():
    """La clé ne doit jamais pouvoir partir dans un commit."""
    result = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=env.PROJECT_ROOT)
    assert result.returncode == 0
