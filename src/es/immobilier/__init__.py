"""Espagne : actifs immobiliers des liquidations concursales d'une zone (par défaut : la région de Torrevieja, Vega Baja).

Même vocabulaire de commandes que le reste du projet (`update`, `report`), rangé dans ce dossier pour ne pas se mêler aux véhicules :

    python -m es.immobilier.update                      # lots immobiliers de la zone (eactivos, 365 derniers jours)
    python -m es.immobilier.update --since 2020-01-01   # plus loin dans le temps
    python -m es.immobilier.report lots                 # lots ouverts ou à venir
    python -m es.immobilier.report lots --municipio torrevieja --tipo vivienda --xlsx data\\es\\exports\\inmuebles.xlsx
    python -m es.immobilier.report links                # lots rattachés à une société et un administrateur du BORME

Source : eactivos.com, comme pour les véhicules (plan du site, robots.txt évalué en entier, une requête par seconde, faits
seulement). Le BORME ne donne ni adresse ni bien : la zone se reconnaît à l'adresse du lot eactivos, qui cite la commune.
"""
