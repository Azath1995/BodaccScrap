# BodaccScrap

**English summary.** A Python data pipeline that tracks French court-ordered liquidations published in the
BODACC (official bulletin of commercial notices) and the vehicles put up for sale by the liquidators in
charge, with a Spanish counterpart (BORME insolvency acts, eactivos.com auction lots, BOE auction portal,
Catastro lookups). Data comes from open APIs, RSS feeds and sitemaps; it is stored in SQLite with its
history (`first_seen` / `last_seen`, idempotent updates) and explored through command-line reports with
filters, sorting and CSV/Excel exports. 800 pytest tests, no network access needed. The documentation
below is in French.

---

Suivi des **liquidations judiciaires** publiées au BODACC et des **véhicules mis en vente**
par les mandataires judiciaires chargés de ces liquidations.

Projet scolaire. Il collecte des données publiques, les stocke dans une base SQLite avec
leur historique, et permet de voir ce qui est nouveau d'un jour à l'autre.

## Ce que fait le projet

```
BODACC (API ouverte)            Sites des cabinets (flux RSS Gemweb)
  liquidations du jour                  annonces d'actifs à vendre
        │                                        │
        ▼                                        ▼
  extraction du liquidateur  ──►  registre des cabinets  ◄──  description libre :
  (texte libre du greffe)         (config/cabinets.json)       marque, plaque, km, année
        │                                        │
        └──────────────► base SQLite (data/bodacc.db) ◄───────┘
                            first_seen / last_seen
                                     │
                     python -m bodacc.update   → nouveautés du jour
                     python -m bodacc.report   → tableaux et exports CSV
```

1. **Les liquidations** sont lues sur l'API ouverte du BODACC, jour par jour.
2. **Le liquidateur** est extrait du texte libre, puis rapproché d'un **registre** de cabinets
   dont on connaît le site.
3. **Les annonces** de ces cabinets sont lues dans leur flux RSS (`/rss/actif`, CMS Gemweb).
4. **Les véhicules** sont repérés par leur type, puis on en extrait marque, immatriculation,
   kilométrage, année et carburant depuis la description.
5. Tout est stocké avec `first_seen` (première apparition, jamais modifiée) et `last_seen`.
   Relancer le programme n'ajoute jamais de doublon et signale seulement les nouveautés.

## Installation

Windows, PowerShell, Python 3.11 ou plus (testé avec 3.14).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . pytest
```

Toutes les commandes ci-dessous utilisent le Python du dossier `.venv` directement, ce qui évite
d'avoir à « activer » l'environnement (l'activation peut être bloquée par la politique d'exécution
de PowerShell).

## Utilisation

**1. Collecter les données** (1 à 2 minutes ; la première fois, tout est « nouveau ») :

```powershell
.\.venv\Scripts\python.exe -m bodacc.update
.\.venv\Scripts\python.exe -m bodacc.update --period last_7_days
.\.venv\Scripts\python.exe -m bodacc.update --start 2026-09-01 --end 2026-09-07
.\.venv\Scripts\python.exe -m bodacc.update --skip-bodacc      # seulement les annonces des cabinets
```

Attention : la période par défaut est `today`. Un jour sans publication BODACC donne 0 liquidation.
Dans ce cas, utilisez `--period last_7_days`.

**2. Consulter** :

```powershell
.\.venv\Scripts\python.exe -m bodacc.report vehicles                          # 30 derniers véhicules
.\.venv\Scripts\python.exe -m bodacc.report vehicles --max-price 20000 --max-km 50000
.\.venv\Scripts\python.exe -m bodacc.report vehicles --marque renault --min-year 2018 --sort km
.\.venv\Scripts\python.exe -m bodacc.report vehicles --marque renault --since 2026-09-19
.\.venv\Scripts\python.exe -m bodacc.report vehicles --csv data\exports\vehicules.csv # tout, pour Excel
.\.venv\Scripts\python.exe -m bodacc.report unmatched                         # cabinets absents du registre
.\.venv\Scripts\python.exe -m bodacc.report unmatched --csv data\exports\pistes.csv   # les liquidations concernées
```

Si l'export CSV échoue, le fichier est probablement ouvert dans Excel : fermez-le et relancez.

### Filtrer et trier les véhicules

Aucun SQL nécessaire. Les options se combinent (toutes doivent être respectées) :

| Option | Effet |
|---|---|
| `--marque`, `--cabinet`, `--carburant`, `--lieu` | contient ce texte, sans tenir compte des majuscules ni des accents (`--lieu 33220` ou `--lieu pineuilh`) |
| `--min-year`, `--max-year` | année du véhicule |
| `--min-price`, `--max-price` | prix en euros |
| `--min-km`, `--max-km` | kilométrage |
| `--since AAAA-MM-JJ` | vus pour la première fois à partir de cette date |
| `--sort` | `recent` (défaut), `estimation` (ou `price`), `km`, `cote`, `year` ; plusieurs clés : `km,estimation,cote` ; les valeurs inconnues vont à la fin |
| `--limit N`, `--csv fichier` | nombre de lignes affichées ; export de tous les résultats |
| `--no-links` | ne pas afficher le lien de l'annonce sous chaque véhicule |

Deux règles à connaître :

- **Les bornes sont inclusives** : `--max-km 50000` accepte un véhicule à 50 000 km.
- **Un filtre écarte les valeurs inconnues** : avec `--max-km 50000`, un véhicule dont le kilométrage
  n'est pas indiqué n'est pas retenu, puisqu'on ne peut pas dire qu'il respecte le critère. Le programme
  indique combien de véhicules sont écartés pour cette raison ; `--include-unknown` les garde.

Chaque véhicule est suivi du **lien de son annonce** sur le site du cabinet (en entier, sous la ligne
du véhicule ; cliquable dans Windows Terminal avec Ctrl+clic). L'export CSV le contient dans la colonne
`url_detail`.

Le prix est stocké comme du texte dans la base (`14 000,00 €`) ; l'export CSV contient en plus une
colonne `prix` numérique, plus pratique dans Excel.

**Lots de plusieurs véhicules.** Une annonce peut vendre plusieurs véhicules d'un coup (« deux véhicules CLIO »,
« Lote de cinco vehículos »). La colonne `nb` donne leur nombre, et le résumé dit « 2 annonce(s), 3 véhicules » quand
ils diffèrent. Le nombre vient d'un chiffre ou d'un mot devant un nom de véhicule (« 3 camions », « deux voitures ») ou,
en France, de plaques d'immatriculation distinctes dans le texte ; on garde le plus grand indice, sans les additionner.
C'est donc un **minimum** : « des véhicules » sans nombre ni plaque reste compté 1. Le **prix est celui du lot entier**,
jamais divisé (on ne sait pas comment il se répartit) : `--max-price` compare donc le total du lot. Le comptage est propre à chaque pays
(`bodacc.vehicles.count_vehicles`, `es.report.count_vehicles`) : les mots ne sont pas les mêmes.

### Estimer le coût de transport

```powershell
.\.venv\Scripts\python.exe -m bodacc.report vehicles --destination "87000 Limoges" --max-price 5000
.\.venv\Scripts\python.exe -m bodacc.report vehicles --destination "87000 Limoges" --xlsx data\exports\vehicules_limoges.xlsx
```

Ajoute deux colonnes : **km route** (distance routière estimée) et **transport €** (une **fourchette**, par exemple `340-500 €`). Ce
n'est **pas l'algorithme d'un transporteur** (propriétaire, dynamique ; Hiflow interdit d'ailleurs à ses robots ses pages de simulation) :
c'est une courbe dégressive calée sur des prix publiés (Hiflow : Lyon-Marseille environ 420 km, 355 € TTC ; guides : Lyon-Clermont
300 km, 380 € ; Paris-Marseille 775 km, 735 €), pour une **voiture standard qui roule, en convoyage, tout compris**. La distance est la
distance à vol d'oiseau × 1,3 (erreur typique de ±15 %), avec les coordonnées du géocodeur officiel (`api-adresse.data.gouv.fr`, une
requête par lieu, mémorisée dans `data/geocache.json`). Non pris en compte : véhicule non roulant (plateau, 1,2 à 2 €/km), SUV ou
utilitaire (+10 à 25 %), urgence (+20 à 40 %), lots de plusieurs véhicules, et **engins** (tracteur, grue, chariot : la fourchette d'une voiture
ne vaut pas pour eux). Les points de la courbe sont dans `bodacc/transport.py` (`ANCHORS`) : remplacez-les par vos propres devis.

### Trouver des acheteurs potentiels près d'un véhicule

```powershell
.\.venv\Scripts\python.exe -m prospects --vehicule AB-456-EF --min-effectif 3 --max-effectif 19
.\.venv\Scripts\python.exe -m prospects --near "33220 Pineuilh" --radius 25 --naf 43.22A,43.21A
.\.venv\Scripts\python.exe -m prospects --vehicule AB-456-EF --csv data\exports\prospects.csv
```

Elle liste les entreprises actives autour d'un lieu (celui d'un véhicule de la base avec `--vehicule`,
ou n'importe quel lieu avec `--near`), de la plus proche à la plus éloignée, avec un lien vers leur
fiche dans l'annuaire officiel des entreprises. Options : `--radius` (50 km au plus), `--secteur`
(section NAF, `F` = construction par défaut), `--naf` (codes précis), `--min-effectif` et
`--max-effectif`, `--limit`, `--csv`.

Ce module est **indépendant du BODACC** : il vit dans son propre paquet, `src/prospects/`. Ses
sources sont l'API « Recherche d'entreprises » (base Sirene, Licence Ouverte) et le géocodeur de
l'État, deux services de data.gouv. Il ne s'appuie sur `bodacc` que pour retrouver le lieu d'un
véhicule dans la base (`--vehicule`) et pour afficher ses tableaux. À savoir :

- **L'effectif est une tranche** (« 6 à 9 salariés »), pour **l'entreprise entière** et non pour
  l'établissement voisin, à la date de référence de l'INSEE (souvent 2023). Les entreprises dont la
  tranche est inconnue sont écartées dès qu'un filtre d'effectif est demandé.
- **Aucune coordonnée de contact** : ni e-mail ni téléphone, seulement le nom, l'adresse et l'activité.
  Avant tout démarchage, voir les règles de la CNIL.
- **Données personnelles écartées** : les dirigeants ne sont jamais demandés à l'API ni lus, les
  entrepreneurs individuels (personnes physiques) et les entreprises à diffusion partielle sont exclus.
- L'API limite chaque page à 25 résultats ; la commande lit 60 pages au plus (`--max-pages`) et le dit
  quand la recherche est tronquée.

### Chercher les sites web des sociétés (OpenStreetMap)

```powershell
.\.venv\Scripts\python.exe -m prospects.find_sites --input data\exports\prospects_64.csv --csv data\exports\sites_64.csv
```

L'annuaire officiel n'a pas de champ « site web ». La commande télécharge en une requête les garages,
concessions et loueurs d'OpenStreetMap (licence ODbL) sur la zone, puis rapproche chaque société d'un
commerce par la distance et la ressemblance du nom. Chaque ligne a un statut :

| Statut | Sens |
|---|---|
| `trouve (osm)` | commerce à moins de 2 km dont le nom ou l'adresse du site ressemble à la société |
| `a verifier (osm)` | commerce à moins de 150 m, mais au nom différent (autre enseigne à la même adresse) |
| `non trouve` | rien de convaincant |

**Limite importante** : OpenStreetMap est incomplet. Sur les 40 sociétés autour de Bergerac, dont 27 ont
un site connu, la commande n'en retrouve qu'une petite partie (surtout les concessions de marque) et
elle en rate beaucoup, notamment les réseaux (Faurie, Hertz, Sixt...) et les petits garages. Un
« non trouve » ne prouve pas l'absence de site : complétez ces lignes à la main dans le CSV. Un commerce
proposé à plusieurs sociétés est écarté, car c'est une coïncidence d'adresse.

### Classer des sociétés selon les véhicules dont leur site parle

```powershell
.\.venv\Scripts\python.exe -m prospects.vehicle_types --type utilitaires --main-only
.\.venv\Scripts\python.exe -m prospects.vehicle_types --type citadines,electriques --min-hits 5 --csv data\exports\sites_types.csv
.\.venv\Scripts\python.exe -m prospects.vehicle_types --input data\exports\mes_sites.csv
```

Le fichier d'entrée est un CSV avec une colonne **`site`** (et si possible `nom` et `siren`) ; par défaut
`data\prospects_vehicules_sites.csv`. Pour chaque site, la commande lit la page d'accueil et jusqu'à deux
pages « stock, occasions, véhicules, location », compte des mots-clés par type, puis classe les sites.

| Option | Effet |
|---|---|
| `--type` | un ou plusieurs types séparés par des virgules : `utilitaires`, `citadines`, `berlines`, `suv_4x4`, `camping_cars`, `poids_lourds`, `electriques` |
| `--min-hits N` | mentions minimum du type demandé (3 par défaut) |
| `--main-only` | ne garder que les sites dont le type demandé est un type **principal** (au moins 3 mentions et 20 % de toutes leurs mentions), pas une simple mention |
| `--max-pages`, `--pause`, `--limit`, `--csv`, `--input` | pages lues par site ; secondes entre deux requêtes ; lignes affichées ; export ; fichier d'entrée |

Sans `--type`, tous les sites sont listés avec leurs types principaux. **Limites à connaître :**

- **Le compte mesure ce dont le site parle, pas son stock réel.** Un même terme compte 5 fois au plus, et un
  modèle (Trafic, Master, Clio…) ne compte qu'avec sa marque, car ce sont aussi des mots courants.
- **Sites mal vus :** ceux dont le stock est chargé par JavaScript (page presque vide, statut « peu de contenu »)
  et ceux écrits en anglais.
- **Les sites doivent être fournis** : ni le BODACC ni l'annuaire officiel des entreprises n'en contiennent. Ils ont été
  trouvés par recherche web ; « non trouvé » ne veut pas dire « pas de site ».
- **Respect des sites :** le `robots.txt` est lu, une requête par seconde, trois pages au plus par site.

La base `data/bodacc.db` s'ouvre aussi avec un outil comme DB Browser for SQLite.

## Structure

```
config/cabinets.json      registre des cabinets : nom, domaine, alias ; liste "pending" des échecs
src/bodacc/
  update.py               commande de mise à jour (BODACC + cabinets → base)
  report.py               commande de consultation (tableaux, CSV)
  find_cabinets.py        cherche le site Gemweb des cabinets absents du registre (annuaire CNAJMJ)
  storage.py              base SQLite, upsert, first_seen / last_seen, migration de colonnes
  bodacc_collector.py     API BODACC, filtrage des liquidations, extraction du liquidateur
  cabinets.py             du texte du greffe au nom du cabinet, puis au registre
  gemweb_rss.py           registre + lecture des flux RSS Gemweb
  vehicles.py             marque, plaque, km, année, carburant depuis la description
  vehicle_filters.py      filtres et tris des véhicules (prix converti du texte en nombre)
  actif_filter.py         repère les véhicules par mots entiers (« auto » ≠ « automate »)
  paths.py                chemins du projet (data/, base)
  market.py               prix de marché : médiane d'annonces Leboncoin comparables via l'API Carapis (--market)
  env.py                  lit les clés locales du fichier .env (jamais dans git)
  cote.py                 cote saisie à la main (plaque -> valeur), colonne « cote » du rapport ; `python -m bodacc.cote`
  verify.py               relit les fiches : date limite absente du flux, suppression des annonces retirées ; `python -m bodacc.verify --supprimer`
src/prospects/            paquet indépendant du BODACC : sources data.gouv (annuaire des entreprises, géocodeur)
  search.py               entreprises autour d'un lieu ou d'un véhicule ; commande `python -m prospects`
  find_sites.py           cherche le site web des sociétés via OpenStreetMap ; `python -m prospects.find_sites`
  vehicle_types.py        classe des sites web selon les types de véhicules ; `python -m prospects.vehicle_types`
src/es/                   ESPAGNE, indépendant de la France : procédures collectives du BORME
  borme.py                API ouverte du BOE, lecture des documents, extraction des « concursos » et des administrateurs
  eactivos.py             lots de véhicules d'eactivos.com : plan du site, robots.txt complet, extraction de faits
  storage.py              base SQLite propre à l'Espagne (data/es/borme.db) : actes du BORME et lots eactivos
  update.py               commande de collecte (BORME + eactivos) ; `python -m es.update`
  report.py               consultation : `vehicles`, `unmatched`, `liquidations`, `links` ; `python -m es.report`
  immobilier/             actifs immobiliers d'une zone (région de Torrevieja) : zone.py, update.py, report.py, boe.py, catastro.py
  paths.py                chemins : data/es, config/es
tests/                    800 tests (pytest) ; tests/es/ pour l'Espagne
data/                     exclus de git : bases (bodacc.db), caches (geocache, market_cache) ;
  exports/                tous les CSV/Excel produits par les commandes (régénérables, supprimables sans risque)
  es/                     même chose pour l'Espagne : borme.db, exports/
```

### Une séparation par pays

Chaque pays a **son paquet de code, ses données, sa configuration et ses tests**, sans rien partager avec un
autre pays : ce qui est propre à un pays (source, format, cabinets, mots-clés) ne doit pas déborder chez les autres.

| | France | Espagne |
|---|---|---|
| Code | `src/bodacc/` (+ `src/prospects/`) | `src/es/` |
| Données | `data/` (`bodacc.db`, caches, exports) | `data/es/` |
| Configuration | `config/` (`cabinets.json`) | `config/es/` (à créer quand il y aura un registre) |
| Tests | `tests/` | `tests/es/` |

Un nouveau pays reprend le même modèle (`src/<code pays>/`, `data/<code>/`, `config/<code>/`, `tests/<code>/`).
La France n'a pas encore été déplacée sous `fr/` : ses commandes (`python -m bodacc.update`) et sa base
(`data/bodacc.db`) restent inchangées pour ne rien casser.

## Espagne : procédures collectives du BORME

Le BORME (Boletín Oficial del Registro Mercantil) est l'équivalent espagnol du BODACC pour les sociétés. Le BOE
en publie une **API ouverte** (REST, sans clé ni compte) : un sommaire par jour et un document XML par province.

```powershell
.\.venv\Scripts\python.exe -m es.update --period last_7_days               # collecte (data\es\borme.db)
.\.venv\Scripts\python.exe -m es.update --start 2026-01-01 --end 2026-09-18 --pause 0.3
.\.venv\Scripts\python.exe -m es.report liquidations                       # les 30 derniers actes
.\.venv\Scripts\python.exe -m es.report liquidations --type liquidation --lieu madrid
.\.venv\Scripts\python.exe -m es.report unmatched                          # les administrateurs concursaux les plus actifs
.\.venv\Scripts\python.exe -m es.report liquidations --csv data\es\exports\actos.csv
```

**Mêmes commandes qu'en France.** On n'apprend qu'un vocabulaire ; seul le nom du paquet change :

| | France | Espagne |
|---|---|---|
| Collecter | `bodacc.update` | `es.update` |
| Véhicules à vendre | `bodacc.report vehicles` | `es.report vehicles` |
| Liquidateurs sans cabinet | `bodacc.report unmatched` | `es.report unmatched` (tous les administrateurs : il n'y a pas de registre espagnol) |
| Annonces de liquidation | `bodacc.report liquidations` | `es.report liquidations` |
| Lots ↔ annonces | (lien dans la fiche) | `es.report links` |

Les options communes ont le même nom : `--period --start --end --skip-liquidations --skip-actifs --marque --lieu
--min-price --max-price --since --sort --limit --csv --include-unknown --no-links`. Côté France,
`--skip-liquidations` est un synonyme de l'ancien `--skip-bodacc` ; côté Espagne c'est aussi `--skip-borme`.
Différence : les lots espagnols n'ont ni kilométrage, ni année, ni carburant, donc pas de `--max-km` ni de
`--carburant` (refusés).

Chaque ligne d'`es.report liquidations` est un **acte** : déclaration de concours, ouverture de la liquidation,
clôture, procédure spéciale de microentreprise… avec le numéro de procédure, le tribunal, le juge et, quand le BORME
le donne, l'**administrateur concursal avec son NIF** (plus précis que le texte libre du BODACC). `--type` vaut
`declaration`, `liquidation` ou `conclusion`. Les actes se rattachent au texte officiel par leur lien (`url_html`).

- **Volume** : environ 15 à 30 actes par jour de publication. Sur la semaine du 14 au 20 septembre 2026, 105 actes ;
  seuls 12 avaient un administrateur nommé dans la même entrée, donc le classement des administrateurs ne devient
  utile que sur plusieurs mois.
- **Durée** : par défaut une requête à la fois, une seconde de pause, environ 33 documents par jour de publication :
  environ 35 secondes par jour, donc une année prend quelques heures. L'API du BOE n'annonce pas de limite, la prudence
  est un choix : `--pause 0.5` accélère un peu, et **`--workers 3`** télécharge trois documents d'un même jour en même
  temps (environ 3 fois plus vite, sans changer le résultat : même contenu, même ordre). Le plafond est de 8. Les
  écritures en base restent séquentielles. Les week-ends et jours fériés (sans BORME) sont simplement ignorés.
- **Reprise** : chaque jour lu en entier (tous ses documents) est noté dans la base ; relancer la même commande ne
  relit que les jours manquants ou incomplets (`--refresh` pour tout relire). Un document illisible est retenté
  une fois ; s'il échoue encore, le jour reste « incomplet » et sera relu. Le jour en cours n'est jamais noté comme
  terminé, car de nouvelles publications peuvent encore y arriver.
- **Limites** : seul le BORME est lu, pas le Registro Público Concursal ; une entrée dont le texte est libre
  (« Otros conceptos ») donne un type approximatif et parfois pas de numéro de procédure ; les sociétés dont
  la procédure n'est pas inscrite au registre du commerce n'apparaissent pas.
- **Étape suivante** (non faite) : retrouver, pour ces administrateurs, où sont annoncés les biens à vendre.
  Une source voisine n'est **pas utilisée** (vérifié le 20 septembre 2026) : le Registro Público Concursal
  (`publicidadconcursal.es`) a un `robots.txt` ouvert, mais son **avis légal interdit** les « indexations ou
  robotisations » visant à récupérer automatiquement ses données, ainsi que leur réutilisation sans autorisation
  écrite du CORPME. Son « portail de liquidations » concerne d'ailleurs des unités productives (entreprises), pas
  des véhicules à l'unité. Un `robots.txt` permissif ne vaut donc pas autorisation : il faut aussi lire les
  conditions d'utilisation. Le portail d'enchères du BOE (`subastas.boe.es`), lui, interdit tout par son
  `robots.txt` mais est lu quand même pour l'immobilier de la zone de Torrevieja — écart voulu par l'utilisateur,
  voir `es.immobilier.boe` plus bas.
- **Existe-t-il un équivalent de Gemweb ?** Analyse faite le 20 septembre 2026 sur les 12 administrateurs de la
  semaine collectée (5 sociétés, 7 personnes physiques) : les 8 sites accessibles sont des **sites vitrines WordPress
  sans aucun catalogue d'actifs**, 3 sont inaccessibles et 1 administrateur n'a pas de site trouvé. Il n'y a donc
  **pas de plateforme commune aux administrateurs** comme Gemweb. Le seul canal commun repéré est une plateforme
  privée, `eactivos.com` (Activos Concursales S.L.), qui n'est pas propre à un administrateur : voir la section
  suivante.

### Lots de véhicules d'eactivos.com

```powershell
.\.venv\Scripts\python.exe -m es.update --skip-liquidations               # lots de véhicules des 180 derniers jours
.\.venv\Scripts\python.exe -m es.update --skip-liquidations --actifs-since 2026-01-01
.\.venv\Scripts\python.exe -m es.report vehicles                          # lots ouverts ou à venir (--status all pour tout)
.\.venv\Scripts\python.exe -m es.report vehicles --marque mitsubishi --max-price 15000
.\.venv\Scripts\python.exe -m es.report links                             # lots rattachés à un acte du BORME (donc à un administrateur)
```

`es.update` collecte les deux sources d'un coup (BORME puis eactivos), comme `bodacc.update` le fait pour le BODACC et
Gemweb ; `--skip-actifs` ou `--skip-liquidations` en saute une. `python -m es.eactivos` existe toujours comme lecteur
autonome, mais n'est plus la commande à utiliser.

- **Source** : le plan du site (`sitemap.liquidations.xml`, 23 649 lots dont environ 1 150 dont l'adresse cite un
  véhicule) puis la fiche de chaque lot, une requête par seconde. Rien d'autre n'est appelé : jamais d'enchère,
  jamais les appels internes de la plateforme.
- **`robots.txt`** (vérifié le 21 septembre 2026) : il n'interdit que des actions (favoris, dépôt de participation,
  enchère, connexion) et deux sous-pages de lot. Il est **évalué avec ses règles complètes** (jokers `*`, fin de
  chaîne `$`, que `urllib.robotparser` ne gère pas) avant chaque requête. Les domaines cités dans ses JavaScript
  ne sont que des bibliothèques et des outils d'audience : la liste n'est pas servie par une API tierce.
- **Ce qui est conservé** : uniquement des faits extraits (titre, lieu, état, valorisation, numéro de procédure,
  tribunal, société concursée, plaque) et le lien vers l'annonce d'origine. Ni photos ni textes de description.
- **Les lots ouverts ou à venir sont bien plus riches que les lots clos.** Une fiche ouverte indique le numéro de
  procédure et le tribunal (« Proced. concursal 470/2025, Sección de lo Mercantil du Tribunal de Instancia de
  Madrid »), parfois la plaque et la société concursée ; une fiche close ne garde que le titre et la valorisation.
  Le 21 septembre 2026, 16 des 21 lots vivants avaient un numéro de procédure (5 formats de rédaction différents).
- **Le rattachement au BORME** (`es.report links`) exige le même numéro de procédure **et** le même tribunal (chaque
  tribunal recommence sa numérotation). Le BORME donne le tribunal de chaque acte : on compare sa ville et son numéro
  de chambre (« Plaza Nº 16 », « NUMERO 4 DE VALENCIA ») avec ceux du lot. Sans tribunal d'un côté ou de l'autre, on se
  rabat sur la province du registre de l'acte, moins précise (une société peut être inscrite ailleurs que son
  tribunal). Un lot compatible avec plusieurs sociétés donne une ligne par société, colonne `cand.` > 1. Il n'y a de
  lien que si le BORME collecté couvre la date de l'acte.
- **Tous les lots** : `es.update --skip-liquidations --actifs-since 2000-01-01` lit toutes les fiches de véhicules du
  plan du site (environ 1 150, une requête par seconde). Les lots clos n'ont plus de numéro de procédure ni de plaque :
  ils ne sont ni rattachables ni utiles pour une demande, mais restent en base (prix de référence).
- **Autres plateformes examinées, non utilisées** (21 septembre 2026) : `concursal.es` (avis légal : « el usuario no
  puede transmitir, reproducir, tratar ni difundir esta información », usage « para fines propios ») ; Escrapalia
  (conditions du site illisibles sans JavaScript ; l'avis de sa maison mère interdit la reproduction sans autorisation) ;
  Diario de Subastas (`robots.txt` interdit `/vehiculo/` et les clients Python). Le portail de données ouvertes des
  Registradores (`opendata.registradores.org`) rejette les requêtes automatiques : non utilisé.
- **Réserve de droits** : l'avis légal d'eactivos réserve tous les droits sur son contenu et interdit toute
  reproduction ou exploitation de tout ou partie, sans mentionner les robots. Ce lecteur est un usage scolaire,
  minimal, avec renvoi vers la source ; il n'a **pas d'accord écrit** de l'exploitant. L'usage en est de la
  responsabilité de son utilisateur.

### Actifs immobiliers d'une zone (`es/immobilier/`)

Recherche des liquidations d'une **région** avec des biens immobiliers, ici Torrevieja et la Vega Baja. Le BORME ne donne ni
adresse ni bien : la zone se reconnaît sur eactivos, dont l'adresse de chaque lot cite la commune (`vivienda-duplex-b11-en-torrevieja-alicante`).
Mêmes règles que pour les véhicules (plan du site, `robots.txt` complet, une requête par seconde, faits seulement).

```powershell
.\.venv\Scripts\python.exe -m es.immobilier.update --since 2015-01-01           # 71 fiches lues pour toute la zone
.\.venv\Scripts\python.exe -m es.immobilier.update --municipios torrevieja,guardamar
.\.venv\Scripts\python.exe -m es.immobilier.report lots                         # ouverts ou à venir
.\.venv\Scripts\python.exe -m es.immobilier.report lots --status all --tipo vivienda --xlsx data\es\exports\inmuebles.xlsx
.\.venv\Scripts\python.exe -m es.immobilier.report links                        # lots rattachés à une société du BORME
```

- **Dossiers séparés des véhicules** : table `inmuebles` (jamais `lotes`), code dans `src/es/immobilier/`, tests dans
  `tests/es/test_es_immobilier.py`. Les communes se règlent dans `zone.py` (31 mots d'adresse, 20 communes).
- **Ce qui est lu** : seulement les fiches dont l'adresse cite une commune de la zone **et** un bien (vivienda, local, nave, parcela,
  garaje, trastero…) ; un « lote » mixte est gardé et marqué `lote`. Les homonymes hors d'Alicante (Guardamar de la Safor, Villamartín de
  Cadix) sont écartés grâce à la province citée dans le titre.
- **Limites** : un lot dont l'adresse ne cite pas la commune n'est pas vu. Une fiche **close ne garde ni le numéro de procédure ni la
  société** : ces lots ne se rattachent pas au BORME, seuls les lots ouverts le peuvent. Un même bien republié apparaît plusieurs fois
  (64 lots pour 45 annonces distinctes).
- **Mesure du 21 septembre 2026** : 64 lots dans la zone depuis 2016, dont 1 seul ouvert (et ce n'est pas de l'immobilier : un lot de
  carpas et toldos à Orihuela), 63 clos. Orihuela 37, Pilar de la Horadada 6, Torrevieja 4. Aucun rattachement au BORME possible.

### Enchères du Portal de Subastas du BOE (`es/immobilier/boe.py`)

Le portail public de **toutes** les enchères espagnoles (judiciaires, notariales, fiscales, administratives), pas
seulement concursales : il n'a pas de lien avec le BORME ni `es.report links`. Vue le 21 puis le 23 septembre 2026
depuis eactivos et Escrapalia, l'immobilier de la zone reste peu couvert : ce lecteur cherche directement sur le
portail des enchères d'État.

```powershell
.\.venv\Scripts\python.exe -m es.immobilier.boe                              # enchères en cours ou à venir de la zone
.\.venv\Scripts\python.exe -m es.immobilier.boe --municipios torrevieja,orihuela
.\.venv\Scripts\python.exe -m es.immobilier.boe --estados all --csv data\es\exports\subastas_boe_torrevieja.csv
```

- **Écart volontaire et explicite** au reste du projet : `subastas.boe.es` interdit tout à son `robots.txt`
  (`Disallow: /`), et ce module ne le vérifie pas — décision de l'utilisateur (23 septembre 2026), limitée à
  l'immobilier de la zone de Torrevieja. Une requête par seconde est gardée par égard pour le serveur.
- **Recherche** : commune par commune et état par état (le texte libre du portail ne repère pas toujours la bonne
  ville — l'autorité qui gère l'enchère peut être ailleurs que le bien), sur la province d'Alicante. Une deuxième
  exécution ne relit **pas** la fiche de détail (valeur, dépôt…) d'une enchère déjà connue, seulement si elle
  change d'état (`--refresh` pour tout relire quand même).
- **Le débiteur, le créancier et le titulaire ne sont jamais gardés** : aucune fiche publique, avec ou sans compte,
  ne les montre (vérifié avant d'écrire ce lecteur), et un filtre coupe le texte par précaution s'ils y apparaissaient.
  **Les voisins cités dans une clause « Linda : »** (la formule notariale qui décrit les limites d'un bien en
  nommant les propriétaires voisins) sont en revanche gardés, sur décision explicite de l'utilisateur : ce sont des
  données de registre public sur des tiers, pas l'identité du débiteur.
- **Le type de bien est un best-effort** sur le texte de la fiche (« vivienda », « local », « terreno/finca »…) : le
  classificateur de registre (« URBANA », qui désigne un usage du sol, pas un type de bien) est retiré avant de
  deviner, sinon il l'emporterait sur le vrai type cité juste après.
- **Mesure du 23 septembre 2026** : 56 enchères en cours ou à venir dans la zone, dont 31 à Torrevieja, 46 avec une
  valorisation connue (de 2 903 € à 4 725 434 €). 11 logements, 32 terrains, 2 locaux identifiés ; le reste sans
  type reconnu ou en lot mixte.

### Vérifier un bien au Catastro (`es/immobilier/catastro.py`)

Consultation **à la demande**, pas une collecte : pas de base de données, juste une adresse ou une référence
cadastrale, et une réponse imprimée à l'écran.

```powershell
.\.venv\Scripts\python.exe -m es.immobilier.catastro --provincia alicante --municipio "guardamar del segura" --calle "mayor" --numero 12
.\.venv\Scripts\python.exe -m es.immobilier.catastro --rc 1234567AB1234C0003ZW
.\.venv\Scripts\python.exe -m es.immobilier.catastro --calles --provincia alicante --municipio torrevieja --calle mar   # rues qui contiennent « mar »
.\.venv\Scripts\python.exe -m es.immobilier.catastro --adresses adresses.csv --detalle --csv sortie.csv                # plusieurs immeubles d'un coup
```

**Réutilisable pour n'importe quelle commune** : `--provincia`/`--municipio` sont des paramètres libres, jamais
écrits en dur — Torrevieja n'est qu'un premier exemple.

- **Deux valeurs existent au Catastro, une seule est accessible.** Le **valor catastral** (base de l'impôt foncier)
  est une **donnée protégée par la loi espagnole** : réservée au propriétaire, avec certificat électronique — ce
  n'est pas une question de `robots.txt` qu'on pourrait lever, la loi le réserve au titulaire quel que soit le
  moyen technique. Le **valor de referencia** (le plancher fiscal d'une vente, pensé pour qu'un acheteur le
  consulte avant d'acheter) est public et gratuit, mais son outil de consultation est une page interactive sans
  API documentée : non automatisé ici.
- **Ce que la commande donne** : adresse complète, usage, surface, année de construction, quote-part, et le détail
  des constructions (logement, garage…) — jamais de valeur ni de nom de propriétaire, qui n'existent dans aucune
  des deux données non protégées lues ici.
- **Source** : le service web libre du Catastro (`ovc.catastro.meh.es`), gratuit, sans compte, documenté par la
  Direction générale du Cadastre. Aucun `robots.txt` sur ce domaine (23 septembre 2026 : HTTP 404).
- **Vérifié en conditions réelles** : l'adresse d'un lot d'une enchère du BOE a retrouvé les 39 unités du bâtiment, puis le détail de l'unité correspondante a donné une quote-part
  de 2,49 % — exactement celle citée dans l'annonce.
- **`--calles`** liste les rues d'une commune, gratuitement (Torrevieja en a 1 027) — utile pour repérer une rue avant
  de chercher son numéro. **Il n'existe en revanche aucun moyen gratuit d'énumérer les numéros d'une rue** :
  `ConsultaNumero` exige un numéro déjà connu, il ne les liste pas. On ne peut donc pas demander « tout le cadastre
  de Torrevieja » : chaque immeuble se cherche par une adresse déjà connue (trouvée dans une enchère, une annonce...).
- **`--adresses fichier.csv`** traite plusieurs adresses d'un coup (colonnes : `provincia,municipio,calle,numero`,
  et en option `via,bloque,escalera,planta,puerta`), une requête par adresse, une de plus par unité avec `--detalle`
  (coûteux sur un immeuble de plusieurs dizaines d'unités) ; export dans un CSV avec `--csv`,
  une adresse introuvable est signalée et n'arrête pas les autres.
- **Limite persistante** : peu d'annonces du BOE donnent une adresse exploitable (5 sur 56 dans la zone de
  Torrevieja, dont des faux positifs) ; la plupart citent un numéro de Finca du Registre de la Propriété, sans lien
  direct avec la référence cadastrale. Pas d'enrichissement automatique de `es.immobilier.boe` pour cette raison :
  un outil à la demande, alimenté par les adresses que vous lui donnez.

## Le registre des cabinets

`config/cabinets.json` associe un nom de cabinet (tel qu'il s'écrit au BODACC) au site où il publie.

```json
{ "name": "MJS Partners", "domain": "https://www.etude-soinne.fr", "aliases": ["M.J.S. Partners"] }
```

- `aliases` : autres orthographes du même cabinet (le greffe n'écrit pas toujours pareil).
- Un site n'est interrogé qu'une fois, même s'il a plusieurs noms.
- `pending` : cabinets dont le site est connu mais inutilisable (pas de flux, site en construction,
  certificat invalide…), avec la raison. Cela évite de refaire les mêmes vérifications.
- `a_verifier` : liquidateurs vus au BODACC, absents du registre et pas encore vérifiés, avec leur nombre
  de liquidations. **Aucun domaine** : `update` ne lit jamais cette section. C'est la liste de travail :
  quand le site Gemweb d'un nom est trouvé, on le déplace dans `cabinets`.

Huit gros cabinets sans flux Gemweb (Legras de Grandcourt, JSA, MJA, SBCMJ, Martin, Lex MJ, MJ Corp, et Asteren
qui est à part) ont une page `/biens` WordPress. Vérifié le 21 septembre 2026 : pour sept d'entre eux, la liste
est chargée par JavaScript depuis **une API tierce, `api.mh25c.eu`, dont le `robots.txt` interdit tout** (`Disallow: /`) ;
les pages des cabinets sont lisibles mais ne contiennent pas la liste. **Aucun scraper n'est donc écrit pour ces
sites.** Leurs catalogues sont d'ailleurs presque sans véhicules (7 catalogues, environ 110 annonces : fonds de
commerce et immobilier, un seul véhicule).

Pour ajouter un cabinet : trouver son site, vérifier que `/rss/actif` renvoie un flux, **vérifier
que l'adresse du site correspond à celle du BODACC** (un nom court peut désigner un autre cabinet),
puis ajouter l'entrée et lancer `pytest`.

### Automatiser la recherche des sites (`find_cabinets`)

```powershell
.\.venv\Scripts\python.exe -m bodacc.find_cabinets                    # rapport sur les 40 cabinets hors registre les plus fréquents
.\.venv\Scripts\python.exe -m bodacc.find_cabinets --top 100 --csv data\exports\cabinets_trouves.csv
.\.venv\Scripts\python.exe -m bodacc.find_cabinets --apply            # ajoute au registre ce qui est sûr
```

Pour chaque cabinet absent du registre (le classement de `report unmatched`), la commande cherche sa fiche
dans le répertoire officiel des administrateurs et mandataires judiciaires (CNAJMJ, dont le `robots.txt`
autorise la lecture), lit l'adresse du site que la fiche indique, puis vérifie sur ce site que `/rss/actif`
renvoie un flux valide (donc un site Gemweb). Une requête par seconde, `robots.txt` respecté à chaque étape.

| Statut | Sens |
|---|---|
| `gemweb valide` | site trouvé, flux valide : prêt à entrer au registre |
| `deja au registre` | ce site est déjà celui d'un cabinet connu : le nom est une autre orthographe (alias) |
| `pas de flux` / `robots interdit` / `site inaccessible` | site trouvé mais inutilisable : noté dans `pending` avec `--apply` |
| `fiche sans site` / `pas de fiche` | rien à lire : le cabinet reste dans `a_verifier` |
| `ambigu` | plusieurs fiches portent ce nom : jamais tranché automatiquement |

Sans `--apply`, **rien n'est écrit**. Avec `--apply`, le fichier obtenu est d'abord rechargé par le lecteur
du registre (qui refuse un même nom sur deux domaines) avant de remplacer `cabinets.json`. Relisez ensuite
`git diff config/cabinets.json` : le rapprochement repose sur le nom, donc un rapprochement plausible mais
faux reste possible. Les cabinets déjà notés dans `pending` ne sont pas réexaminés.

## Résultats mesurés

Données du **13 au 18 septembre 2026** (5 jours de publication, 1 419 liquidations avec liquidateur) :

| Mesure | Valeur |
|---|---|
| Liquidations rattachées à un cabinet du registre | 892 sur 1 419 (**62,9 %**) |
| Sites interrogés | 82 |
| Cabinets distincts encore hors registre | 74 (527 liquidations) |

Sur les **83 véhicules** relevés le 18-19 septembre 2026 (50 sites à l'époque), part des champs
retrouvés dans la description : marque environ 84 %, immatriculation 71 %, kilométrage 58 %,
année 41 %, carburant 11 %.

Deux enseignements :

- **La couverture n'est pas le bon indicateur.** Quatre cabinets (LGA, Hazane, MJ Synergie, Basse)
  fournissent 59 des 83 véhicules. Ajouter des petits cabinets a fait monter la couverture de 44 %
  à 48 % sans ajouter de véhicule.
- Un cabinet peut avoir beaucoup de liquidations et ne vendre aucun véhicule : Asteren (54
  liquidations) ne publie que des fonds de commerce et de l'immobilier.

## Limites connues

- **Environ la moitié des liquidations n'a pas de cabinet connu.** Ces cabinets n'ont pas de site,
  n'utilisent pas Gemweb, ou bloquent les scripts. Leurs annonces ne sont pas collectées.
- **L'extraction des véhicules est heuristique.** Chaque cabinet rédige sa description à sa façon.
  Un champ introuvable reste vide, il n'est jamais deviné. Les anciennes plaques (`6639 PE 33`)
  ne sont pas reconnues.
- **Des « véhicules » ne sont pas des voitures.** Les cabinets classent parfois remorques, cabines
  de chantier ou stocks dans « Véhicules » ; nous reprenons leur classement.
- **Le prix est souvent « Non renseigné »** dans les annonces : 46 véhicules sur 83 n'ont pas de prix
  dans le champ Estimation. Il n'existe pas dans la source, et certains cabinets n'en publient jamais
  (MJ Synergie, Fides, Berthelot : aucun prix pour leurs véhicules). Ces biens se vendent souvent par
  offres. Pour ces cas, la seule voie fiable est de demander au cabinet.
- **Un prix peut être écrit dans la description au lieu du champ Estimation** (Berthelot : « … | 4500 € »).
  Ces montants ne sont pas extraits : on ne sait pas s'ils sont des prix de vente, et un même lot peut
  regrouper plusieurs véhicules. Une faute de frappe est aussi possible (« Environ 152.000 € » est
  vraisemblablement un kilométrage écrit avec le mauvais symbole).
- **Une annonce n'est pas toujours un véhicule.** Trois annonces sur 83 regroupent plusieurs véhicules
  (2, 3 et 6 plaques) : le tableau compte donc des annonces, et marque, plaque et kilométrage ne
  décrivent que le premier véhicule d'un lot.
- Les rapprochements par nom peuvent se tromper pour les noms très courts ; ils sont vérifiés à la
  main avant d'entrer dans le registre.
- Une réécriture d'une ligne remplace tous ses champs : un champ absent d'un scrape ultérieur
  devient vide.
- Un seul instantané par jour : le programme ne suit pas la disparition d'une annonce
  (seul `last_seen` en garde une trace indirecte).

## Choix éthiques et légaux

- **Sources ouvertes uniquement.** L'API du BODACC est publique. Les flux RSS des cabinets sont
  faits pour être lus par des programmes.
- **`robots.txt` respecté.** Vérifié pour les 82 sites : tous autorisent `/rss/actif`, sans délai
  imposé. Le programme envoie une requête par site, sans pause ; à conserver si vous le planifiez
  souvent.
- **Actify n'est pas utilisé.** Cette plateforme du CNAJMJ regroupe les actifs de tous les
  mandataires, mais son `robots.txt` interdit tout accès automatisé (`Disallow: /`) et ses mentions
  légales réservent la base de données. Une demande d'accord au CNAJMJ serait la voie légitime.
- **Demandes d'accès plutôt que contournement.** Pour chaque source qui interdit les robots ou réserve ses données, un
  brouillon de demande d'autorisation est rédigé dans `data/demandes_acces.md` (France) et `data/es/demandas_acceso.md`
  (Espagne), hors de git : chaque lettre ne dit que ce qui est vrai (ce qui a été lu, ce qui ne l'a pas été).
- **Aucun contournement.** Un site qui refuse les scripts (erreur 403) ou dont le certificat est
  invalide est noté dans `pending`, pas contourné.
- **Les descriptions peuvent contenir des noms de personnes** (ex. « carte grise au nom de … », gage,
  opposition). Les exports CSV reprennent la description : ne les diffusez pas.
- **Recherche d'entreprises : minimisation des données.** `prospects` demande à l'API une réponse
  minimale, sans les dirigeants, et exclut les personnes physiques. Elle n'envoie que des requêtes
  espacées de 0,25 s et s'identifie par un `User-Agent`.
- **Données personnelles.** Le BODACC publie aussi des noms de commerçants individuels
  (mentions « (EI) »). Ce sont des données publiques, mais les exports (`data/exports/`) ne doivent pas
  être diffusés tels quels. Le dossier `data/` est exclu de git.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

800 tests, sans accès réseau : les appels externes sont remplacés par de fausses réponses. Les
extracteurs (liquidateur, cabinet, véhicule) sont testés sur des **textes réels** copiés du BODACC
et des flux, un par variante de rédaction rencontrée. Dans cette version publique, les noms de personnes,
adresses, plaques et identifiants de ces textes sont remplacés par des valeurs fictives.

## Pistes d'amélioration

- Planifier `update` chaque jour, et faire remonter la période par défaut aux derniers jours ouvrés.
- Ajouter des cabinets au registre en priorité selon leur **rendement en véhicules**.
- Lire la page de détail de chaque annonce pour plus d'informations (modèle, photos), après avoir
  vérifié `robots.txt` pour ces pages.
- Remplacer les `print` des premiers scripts par du `logging`.
