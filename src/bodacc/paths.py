from pathlib import Path

# src/bodacc/paths.py -> parents[2] est la racine du projet, quel que soit le
# dossier depuis lequel on lance les scripts.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "bodacc.db"
