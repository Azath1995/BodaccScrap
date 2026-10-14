"""Recherche d'acheteurs potentiels : entreprises autour d'un lieu.

Ce paquet est indépendant du BODACC. Ses sources sont des services de data.gouv :
- l'annuaire officiel des entreprises (API « Recherche d'entreprises », base Sirene) ;
- le géocodeur de l'État (API Adresse).

Il ne dépend du paquet `bodacc` que pour retrouver le lieu d'un véhicule dans la base
et pour afficher/exporter ses tableaux.
"""
