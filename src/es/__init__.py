"""Espagne : procédures collectives publiées au BORME (Boletín Oficial del Registro Mercantil).

Ce paquet est indépendant de la France (`bodacc`) : il a son propre code, ses propres données
(`data/es/`), sa propre configuration (`config/es/`) et ses propres tests (`tests/es/`).

Mêmes commandes qu'en France (`bodacc.update`, `bodacc.report ...`) :

    python -m es.update --period last_7_days     # collecte (BORME + lots eactivos)
    python -m es.report vehicles                 # véhicules à vendre
    python -m es.report liquidations             # actes de liquidation du BORME
    python -m es.report unmatched                # les administrateurs concursaux les plus actifs
    python -m es.report links                    # lots rattachés à un acte du BORME
"""
