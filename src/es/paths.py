from pathlib import Path

# src/es/paths.py -> parents[2] est la racine du projet. Un dossier par pays : data/es, config/es, tests/es.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "es"
CONFIG_DIR = PROJECT_ROOT / "config" / "es"
DB_PATH = DATA_DIR / "borme.db"
