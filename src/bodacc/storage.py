import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from bodacc.paths import DB_PATH

# Une seule source de vérité : {table: (clé primaire, autres colonnes)}.
# Le schéma SQL et les requêtes d'upsert sont générés à partir de ce dict,
# donc ajouter une colonne = ajouter un nom ici.
TABLES = {
    "liquidations": (
        "id",
        [
            "date_publication", "numero_annonce", "date_jugement", "nature",
            "entreprise", "siren", "ville", "cp", "tribunal", "liquidateur",
            "url_bodacc", "cabinet",
        ],
    ),
    "actifs": (
        "guid",
        [
            "cabinet", "titre", "type", "estimation", "lieu",
            "date_limite_offre", "date_publication", "url_detail", "description",
            # Extraits de la description pour les véhicules (voir vehicles.py)
            "marque", "immatriculation", "kilometrage", "annee", "carburant",
            "nb_vehicules",                 # 1 sauf lot de plusieurs véhicules (voir count_vehicles)
        ],
    ),
}

# Par défaut chaque colonne est du TEXT. Les nombres sont déclarés INTEGER pour
# que ORDER BY kilometrage trie 9 000 avant 100 000 (en texte, "100000" < "9000").
COLUMN_TYPES = {"kilometrage": "INTEGER", "annee": "INTEGER", "nb_vehicules": "INTEGER"}


def utc_now():
    """Horodatage ISO 8601 en UTC. Ce format se trie correctement comme du texte."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    """Stocke liquidations et actifs dans SQLite, sans doublons, avec historique.

    - first_seen : date de la première apparition (jamais modifiée)
    - last_seen  : date du dernier run où la ligne était encore présente
    """

    def __init__(self, path=DB_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.conn.close()

    def _create_schema(self):
        with self.conn:
            for table, (key, columns) in TABLES.items():
                cols_sql = ", ".join(f"{c} {COLUMN_TYPES.get(c, 'TEXT')}" for c in columns)
                self.conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("
                    f"{key} TEXT PRIMARY KEY, {cols_sql}, "
                    f"first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)"
                )
                # CREATE TABLE IF NOT EXISTS ne touche pas une table qui existe
                # déjà : si on ajoute une colonne dans TABLES, on l'ajoute ici
                # aux bases créées avant (migration minimale).
                existing = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                for column in columns:
                    if column not in existing:
                        self.conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN {column} {COLUMN_TYPES.get(column, 'TEXT')}"
                        )
                self.conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_first_seen "
                    f"ON {table}(first_seen)"
                )
            # Cotes saisies à la main (bodacc.cote) : table à part, que la mise à jour ne touche jamais.
            self.conn.execute("CREATE TABLE IF NOT EXISTS cotes (guid TEXT PRIMARY KEY, valeur INTEGER NOT NULL, "
                              "source TEXT, date TEXT NOT NULL)")
            # Ce que bodacc.verify lit sur la fiche de l'annonce (date limite absente du flux RSS) : à part aussi,
            # sinon la mise à jour suivante l'effacerait avec la valeur vide du flux.
            self.conn.execute("CREATE TABLE IF NOT EXISTS fiches (guid TEXT PRIMARY KEY, date_limite TEXT, "
                              "verifie_le TEXT NOT NULL)")

    # Les noms de table/colonne viennent de TABLES (notre code), jamais de
    # l'utilisateur : les f-strings sont sûres ici. Les VALEURS passent
    # toujours par des "?" pour éviter toute injection SQL.
    def _upsert(self, table, rows, now=None):
        key, columns = TABLES[table]
        now = now or utc_now()
        rows = list(rows)

        for row in rows:
            if not row.get(key):
                raise ValueError(f"Ligne sans clé '{key}' pour la table {table} : {row}")

        existing = {r[0] for r in self.conn.execute(f"SELECT {key} FROM {table}")}
        new_keys = {row[key] for row in rows} - existing

        all_columns = [key, *columns]
        placeholders = ", ".join("?" * (len(all_columns) + 2))
        updates = ", ".join(f"{c}=excluded.{c}" for c in columns)
        sql = (
            f"INSERT INTO {table} ({', '.join(all_columns)}, first_seen, last_seen) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT({key}) DO UPDATE SET {updates}, last_seen=excluded.last_seen"
            # first_seen n'est volontairement PAS dans la liste : il reste intact.
        )
        values = [
            [row.get(c) or None for c in all_columns] + [now, now]
            for row in rows
        ]
        with self.conn:  # une transaction : tout est écrit, ou rien
            self.conn.executemany(sql, values)

        return len(new_keys)

    def upsert_liquidations(self, rows, now=None):
        """Insère ou met à jour des liquidations. Retourne le nombre de NOUVELLES lignes."""
        return self._upsert("liquidations", rows, now)

    def upsert_actifs(self, rows, now=None):
        """Insère ou met à jour des actifs. Retourne le nombre de NOUVELLES lignes."""
        return self._upsert("actifs", rows, now)

    def new_since(self, table, since):
        """Lignes vues pour la première fois à partir de `since` (texte ISO 8601)."""
        if table not in TABLES:
            raise ValueError(f"Table inconnue : {table}")
        cursor = self.conn.execute(
            f"SELECT * FROM {table} WHERE first_seen >= ? ORDER BY first_seen DESC",
            (since,),
        )
        return [dict(r) for r in cursor]

    def keys(self, table):
        """Ensemble des clés déjà en base (pour savoir ce qui est nouveau avant d'écrire)."""
        if table not in TABLES:
            raise ValueError(f"Table inconnue : {table}")
        key = TABLES[table][0]
        return {r[0] for r in self.conn.execute(f"SELECT {key} FROM {table}")}

    def set_cote(self, guid, valeur, source=None, date=None):
        """Enregistre (ou remplace) la cote d'un actif ; valeur None la supprime."""
        with self.conn:
            if valeur is None:
                self.conn.execute("DELETE FROM cotes WHERE guid = ?", (guid,))
            else:
                self.conn.execute("INSERT OR REPLACE INTO cotes (guid, valeur, source, date) VALUES (?, ?, ?, ?)",
                                  (guid, int(valeur), source, date or utc_now()[:10]))

    def cotes(self):
        """{guid: {'valeur', 'source', 'date'}} des cotes saisies."""
        return {r["guid"]: dict(r) for r in self.conn.execute("SELECT * FROM cotes")}

    def set_fiche(self, guid, date_limite, verifie_le=None):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO fiches (guid, date_limite, verifie_le) VALUES (?, ?, ?)",
                              (guid, date_limite, verifie_le or utc_now()))

    def fiches(self):
        """{guid: {'date_limite', 'verifie_le'}} des fiches lues par bodacc.verify."""
        return {r["guid"]: dict(r) for r in self.conn.execute("SELECT * FROM fiches")}

    def delete_actifs(self, guids):
        """Supprime des actifs (et leur cote, leur fiche). Retourne le nombre de lignes supprimées."""
        guids = list(guids)
        with self.conn:
            for table in ("cotes", "fiches"):
                self.conn.executemany(f"DELETE FROM {table} WHERE guid = ?", [(g,) for g in guids])
            return self.conn.executemany("DELETE FROM actifs WHERE guid = ?", [(g,) for g in guids]).rowcount

    def count(self, table):
        if table not in TABLES:
            raise ValueError(f"Table inconnue : {table}")
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
