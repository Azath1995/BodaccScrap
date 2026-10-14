"""Consulte les lots immobiliers de la zone (région de Torrevieja). Mêmes options que `es.report vehicles`.

    python -m es.immobilier.report lots                                  # lots ouverts ou à venir
    python -m es.immobilier.report lots --status all --municipio orihuela
    python -m es.immobilier.report lots --tipo vivienda --max-price 150000 --sort price
    python -m es.immobilier.report lots --status all --xlsx data\\es\\exports\\inmuebles.xlsx
    python -m es.immobilier.report links                                 # lots rattachés à une société et un administrateur du BORME
"""
import argparse

from es import report as core
from es.immobilier import zone
from es.paths import DB_PATH
from es.storage import Storage

LOT_TABLE = [("vu_le", "vu le"), ("etat", "état"), ("municipio", "commune"), ("tipo", "type"), ("titulo", "lot"),
             ("valoracion", "valorisation €"), ("procedimiento", "procédure")]
LINK_TABLE = [("municipio", "commune"), ("titulo", "lot"), ("estado", "état"), ("valoracion", "valor. €"),
              ("procedimiento", "procédure"), ("candidatos", "cand."), ("empresa", "société (BORME)"),
              ("administradores", "administrateur (BORME)")]
TYPES = ["vivienda", "local", "nave/edificio", "terreno/finca", "garaje/trastero", "lote"]


def lot_rows(storage, status="live", since=None, municipio=None, tipo=None):
    """Lots immobiliers, les plus récemment vus d'abord ; ajoute les clés d'affichage vu_le, etat, url_detail."""
    rows = []
    wanted = zone.keys_for([municipio]) if municipio else None
    towns = {zone.MUNICIPALITIES[k] for k in wanted} if wanted else None
    for lot in storage.rows_inmuebles(order="first_seen DESC, codigo"):
        if core.STATUSES[status] is not None and lot["estado"] not in core.STATUSES[status]:
            continue
        if since and lot["first_seen"][:10] < since:
            continue
        if towns is not None and lot["municipio"] not in towns:
            continue
        if tipo and lot["tipo"] != tipo:
            continue
        rows.append({**lot, "vu_le": lot["first_seen"][:10], "etat": core.STATE_LABELS.get(lot["estado"], lot["estado"]),
                     "url_detail": lot["url"]})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Consulte les lots immobiliers de la zone de Torrevieja.")
    parser.add_argument("--db", default=DB_PATH, help="fichier SQLite (défaut : data/es/borme.db)")
    commands = parser.add_subparsers(dest="command", required=True)

    lots = commands.add_parser("lots", help="lots immobiliers en vente")
    lots.add_argument("--status", choices=list(core.STATUSES), default="live",
                      help="live (défaut : ouverts ou à venir), open, upcoming, closed, all")
    lots.add_argument("--since", help="vus pour la première fois à partir de AAAA-MM-JJ")
    lots.add_argument("--municipio", help="une commune de la zone (ex : torrevieja, orihuela, guardamar)")
    lots.add_argument("--tipo", choices=TYPES, help="type de bien")
    lots.add_argument("--min-price", type=float, help="valorisation minimum en euros")
    lots.add_argument("--max-price", type=float, help="valorisation maximum en euros")
    lots.add_argument("--sort", choices=core.SORTS, default="recent", help="recent (défaut) ou price (croissant)")
    lots.add_argument("--limit", type=int, default=30, help="lignes affichées (défaut : 30)")
    lots.add_argument("--csv", help="exporter tous les résultats dans ce fichier CSV")
    lots.add_argument("--xlsx", help="exporter tous les résultats dans ce classeur Excel (.xlsx)")
    lots.add_argument("--no-links", action="store_true", help="ne pas afficher le lien de l'annonce sous chaque lot")
    lots.add_argument("--include-unknown", action="store_true", help="garder les lots dont la valorisation est inconnue")

    links = commands.add_parser("links", help="lots rattachés à une société et un administrateur du BORME")
    links.add_argument("--status", choices=list(core.STATUSES), default="all")
    links.add_argument("--limit", type=int, default=30)
    links.add_argument("--csv", help="exporter dans ce fichier CSV")
    links.add_argument("--xlsx", help="exporter dans ce classeur Excel (.xlsx)")

    args = parser.parse_args(argv)
    try:
        with Storage(args.db) as storage:
            if args.command == "lots":
                found = lot_rows(storage, args.status, args.since, args.municipio, args.tipo)
                rows = core.sort_vehicles(core.filter_price(found, args.min_price, args.max_price, args.include_unknown), args.sort)
                note = ""
                if not args.include_unknown:
                    hidden = len(core.filter_price(found, args.min_price, args.max_price, True)) - len(rows)
                    if hidden:
                        note = f"\n{hidden} autre(s) lot(s) écarté(s) car la valorisation est inconnue (--include-unknown pour les garder)"
                columns = ["codigo", *core.LOTE_COLUMNS, "municipio", "tipo", "first_seen"]
                if args.csv or args.xlsx:
                    if args.csv:
                        core.write_csv(rows, args.csv, columns)
                    if args.xlsx:
                        core.write_xlsx(rows, args.xlsx, columns)
                    print(f"{len(rows)} lot(s) exporté(s) dans {' et '.join(p for p in (args.csv, args.xlsx) if p)}{note}")
                else:
                    print(core.table(rows[:args.limit], LOT_TABLE, width=48, link_key=None if args.no_links else "url_detail")
                          if rows else "Aucun lot immobilier.")
                    print(f"\n{len(rows)} lot(s)" + (f", {args.limit} affiché(s)" if len(rows) > args.limit else "") + note)
            else:
                statuses = core.STATUSES[args.status]
                lots_ = [l for l in storage.rows_inmuebles() if statuses is None or l["estado"] in statuses]
                rows = core.vinculos(storage, lots_)
                columns = ["codigo", "municipio", "tipo", "titulo", "estado", "valoracion", "procedimiento", "juzgado", "candidatos",
                           "empresa", "administradores", "tipo_acto", "url_borme", "url"]
                if args.csv or args.xlsx:
                    if args.csv:
                        core.write_csv(rows, args.csv, columns)
                    if args.xlsx:
                        core.write_xlsx(rows, args.xlsx, columns)
                    print(f"{len(rows)} ligne(s) exportée(s) dans {' et '.join(p for p in (args.csv, args.xlsx) if p)}")
                else:
                    print(core.table(rows[:args.limit], LINK_TABLE, width=40) if rows else "Aucun lot rattaché à un acte du BORME.")
                    ambiguous = len({r["codigo"] for r in rows if r["candidatos"] > 1})
                    print(f"\n{len({r['codigo'] for r in rows})} lot(s) rattaché(s)"
                          + (f", dont {ambiguous} avec plusieurs sociétés possibles (une ligne par société, colonne « cand. »)" if ambiguous else "")
                          + f", sur {len(lots_)} lot(s) immobilier(s).")
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
