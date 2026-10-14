"""Stockage SQLite des données espagnoles, sans doublons, avec historique.

Deux tables : `actos` (actes de procédure collective du BORME) et `lotes` (lots de véhicules vus sur eactivos.com).
Même principe que côté France (`bodacc.storage`) mais volontairement séparé : chaque pays a son code et sa base.
- first_seen : première apparition (jamais modifiée) ; last_seen : dernier passage où la ligne était présente.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from es.paths import DB_PATH

COLUMNS = [
    "fecha_publicacion", "provincia", "borme_id", "empresa_num", "empresa", "procedimiento", "fecha_resolucion",
    "firme", "tipo", "detalle", "modalidad", "juzgado", "juez", "administradores", "liquidacion", "url_html",
]
LOTE_COLUMNS = [
    "liquidation_id", "titulo", "categoria", "ubicacion", "estado", "inicio", "fin", "valoracion", "precio_salida",
    "procedimiento", "juzgado", "concursada", "matricula", "url", "fecha_sitemap",
]
# `inmuebles` : lots immobiliers d'eactivos d'une zone (voir es.immobilier), séparés des véhicules pour ne pas se mélanger.
INMUEBLE_COLUMNS = [*LOTE_COLUMNS, "municipio", "tipo"]
# `subastas_boe` : enchères (judiciaires, notariales, fiscales...) du Portal de Subastas du BOE, voir es.immobilier.boe.
# Portail distinct d'eactivos : pas de lien avec le BORME ni les administrateurs concursaux, d'où une table à part.
BOE_COLUMNS = [
    "origen", "tipo_subasta", "organo", "expediente", "municipio", "tipo", "descripcion", "estado_boe", "estado",
    "fecha_inicio", "fecha_fin", "valor", "tasacion", "puja_minima", "deposito", "cantidad_reclamada", "lotes",
    "anuncio_boe", "url",
]
# table -> (clé primaire, autres colonnes)
DIA_COLUMNS = ["documentos", "actos"]
# `dias` : un jour du BORME entièrement collecté (permet de reprendre une longue collecte là où elle s'est arrêtée).
TABLES = {"actos": ("id", COLUMNS), "lotes": ("codigo", LOTE_COLUMNS), "inmuebles": ("codigo", INMUEBLE_COLUMNS),
          "subastas_boe": ("id", BOE_COLUMNS), "dias": ("fecha", DIA_COLUMNS)}
COLUMN_TYPES = {"liquidacion": "INTEGER", "valoracion": "INTEGER", "precio_salida": "INTEGER", "documentos": "INTEGER", "actos": "INTEGER",
                "valor": "INTEGER", "tasacion": "INTEGER", "puja_minima": "INTEGER", "deposito": "INTEGER",
                "cantidad_reclamada": "INTEGER", "lotes": "INTEGER"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path=DB_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        with self.conn:
            for table, (key, columns) in TABLES.items():
                cols = ", ".join(f"{c} {COLUMN_TYPES.get(c, 'TEXT')}" for c in columns)
                self.conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({key} TEXT PRIMARY KEY, {cols}, "
                                  f"first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)")
                # CREATE TABLE IF NOT EXISTS ne touche pas une table qui existe déjà : une colonne ajoutée plus tard
                # dans TABLES est ajoutée ici aux bases créées avant (migration minimale).
                existing = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                for column in columns:
                    if column not in existing:
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {COLUMN_TYPES.get(column, 'TEXT')}")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_actos_fecha ON actos(fecha_publicacion)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_actos_empresa ON actos(empresa)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_lotes_estado ON lotes(estado)")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.conn.close()

    def close(self):
        self.conn.close()

    def _upsert(self, table, rows, now=None):
        key, columns = TABLES[table]
        now = now or utc_now()
        rows = list(rows)
        existing = {r[0] for r in self.conn.execute(f"SELECT {key} FROM {table}")}
        new = len({row[key] for row in rows} - existing)
        all_columns = [key, *columns]
        updates = ", ".join(f"{c}=excluded.{c}" for c in columns)
        sql = (f"INSERT INTO {table} ({', '.join(all_columns)}, first_seen, last_seen) "
               f"VALUES ({', '.join('?' * (len(all_columns) + 2))}) "
               f"ON CONFLICT({key}) DO UPDATE SET {updates}, last_seen=excluded.last_seen")
        with self.conn:
            self.conn.executemany(sql, [[row.get(c) if row.get(c) != "" else None for c in all_columns] + [now, now] for row in rows])
        return new

    def upsert(self, rows, now=None):
        """Actes du BORME. Retourne le nombre de NOUVELLES lignes."""
        return self._upsert("actos", rows, now)

    def upsert_lotes(self, rows, now=None):
        """Lots eactivos. Retourne le nombre de NOUVELLES lignes."""
        return self._upsert("lotes", rows, now)

    def upsert_inmuebles(self, rows, now=None):
        """Lots immobiliers eactivos. Retourne le nombre de NOUVELLES lignes."""
        return self._upsert("inmuebles", rows, now)

    def upsert_subastas_boe(self, rows, now=None):
        """Enchères du Portal de Subastas du BOE. Retourne le nombre de NOUVELLES lignes."""
        return self._upsert("subastas_boe", rows, now)

    def mark_day(self, day, documents, acts, now=None):
        """Note qu'un jour du BORME a été lu en entier (tous ses documents)."""
        self._upsert("dias", [{"fecha": day, "documentos": documents, "actos": acts}], now)

    def days_done(self):
        """Ensemble des jours (AAAA-MM-JJ) déjà lus en entier."""
        return {r[0] for r in self.conn.execute("SELECT fecha FROM dias")}

    def count(self, table="actos"):
        if table not in TABLES:
            raise ValueError(f"Table inconnue : {table}")
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def rows(self, where="1=1", params=(), order="fecha_publicacion DESC, empresa"):
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM actos WHERE {where} ORDER BY {order}", params)]

    def rows_lotes(self, where="1=1", params=(), order="fecha_sitemap DESC, codigo"):
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM lotes WHERE {where} ORDER BY {order}", params)]

    def rows_inmuebles(self, where="1=1", params=(), order="fecha_sitemap DESC, codigo"):
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM inmuebles WHERE {where} ORDER BY {order}", params)]

    def rows_subastas_boe(self, where="1=1", params=(), order="fecha_fin DESC, id"):
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM subastas_boe WHERE {where} ORDER BY {order}", params)]
