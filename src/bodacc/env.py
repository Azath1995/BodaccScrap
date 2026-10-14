"""Clés et mots de passe locaux : une variable d'environnement, sinon le fichier `.env` à la racine du projet.

Le fichier `.env` est exclu de git (`.gitignore`) : la clé reste sur cette machine. Format, une clé par ligne :

    CARAPIS_API_KEY=car_xxxxxxxx
    # une ligne commençant par # est un commentaire

Une variable d'environnement (`$env:CARAPIS_API_KEY = "..."` dans PowerShell) passe avant le fichier, pour pouvoir
tester une autre clé sans le modifier. Voir `.env.example` pour la liste des clés utilisées.
"""
import os
from pathlib import Path

from bodacc.paths import PROJECT_ROOT

ENV_FILE = PROJECT_ROOT / ".env"


def read_env_file(path=ENV_FILE):
    """{nom: valeur} lu dans le fichier ; vide s'il n'existe pas. Les guillemets autour d'une valeur sont retirés."""
    path = Path(path)
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def get(name, path=ENV_FILE, environ=None):
    """La valeur de `name` (variable d'environnement, sinon `.env`), ou None si elle est absente ou vide."""
    environ = os.environ if environ is None else environ
    value = environ.get(name) or read_env_file(path).get(name)
    return value or None
