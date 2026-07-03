# Cahier des charges - GUI interne pour lancer les backtests

## 1. Contexte

Aujourd'hui, le lancement des backtests repose principalement sur des notebooks Jupyter. Ce mode de fonctionnement pose plusieurs problemes operationnels :

- il faut retrouver a la main les bonnes colonnes et les bonnes metriques ;
- il y a beaucoup de copier-coller de cellules et de parametres ;
- certaines parties du code sont commentees/decommentees selon le besoin du moment ;
- chaque backtest produit ou laisse un notebook, ce qui disperse la configuration et les resultats ;
- il devient difficile de reproduire un run passe, de mutualiser les usages dans l'equipe, ou de lancer des campagnes de tests sur plusieurs metriques.

L'objectif est donc de remplacer ce mode notebook par une application desktop interne, plus simple a utiliser, plus robuste et plus reproductible.

## 2. Objectif du projet

Construire une interface graphique desktop permettant de lancer les backtests sans passer par Jupyter, en s'appuyant sur le moteur existant dans `C:\GoogleDrive\TP\backtest\BacktestEngine.py`.

Cette GUI doit :

- centraliser les configurations de backtest ;
- permettre de lancer un backtest unitaire ou une campagne batch ;
- distinguer clairement les usages recherche et production ;
- sauvegarder automatiquement la configuration et les artefacts de chaque run ;
- rendre les resultats consultables sans reouvrir un notebook.

## 3. Principe d'implementation

Le moteur de calcul existant reste la reference. La GUI ne doit pas reimplementer la logique de selection, de ponderation ou de calcul de performance. Elle doit orchestrer les appels au moteur `PtfBuilder` et habiller ces appels avec :

- une interface utilisateur ;
- une couche de validation des donnees et des parametres ;
- une gestion centralisee des configurations ;
- une gestion des sorties et de l'historique des runs ;
- une presentation lisible des resultats et des erreurs.

En pratique, la GUI s'appuie sur les points d'entree suivants du moteur :

- `PtfBuilder.__init__()` pour charger la configuration principale ;
- `sec_list_spot()` pour la generation mensuelle d'une sec list ;
- `generic_histo_seclist()` pour construire la sec list historique ;
- `backtest_create_ptf_weight()` pour reconstruire les poids benchmark dans le backtest indice ;
- `backtest()` pour calculer la performance du portefeuille ;
- `backtest_get_bench_perf()` pour calculer la performance du benchmark ;
- `backtest_plot_ptf_bench()` pour generer le graphique HTML ;
- `save_portfolio_data_incremental()` pour le mode production.

## 4. Perimetre V1

La V1 couvre les deux usages suivants :

- usage recherche ;
- usage production.

La V1 doit permettre :

- de charger des fichiers de donnees ;
- de detecter les colonnes utiles ;
- de choisir les parametres du backtest dans l'interface ;
- de sauvegarder une configuration reutilisable ;
- de lancer un run simple ;
- de lancer un batch de runs sur plusieurs combinaisons de parametres ;
- de visualiser les sorties principales ;
- d'exporter ou d'ouvrir les fichiers produits ;
- de conserver un historique des runs.

La V1 ne doit pas :

- regenerer des notebooks ;
- dupliquer la logique du moteur ;
- introduire une orchestration distribuee ou complexe ;
- dependre d'edition manuelle de code Python pour lancer un run standard.

## 5. Utilisateurs cibles

### 5.1 Profil principal

- ingenieurs quant / recherche ;
- membres de l'equipe ayant besoin de lancer ou rejouer un backtest ;
- utilisateurs production devant generer les fichiers attendus sans manipuler du code.

### 5.2 Niveau d'expertise attendu

L'utilisateur peut comprendre les concepts benchmark, metric, neutralisation, ESG, top picks, etc., mais ne doit plus avoir a manipuler directement des notebooks ou des noms de colonnes memorises a la main.

## 6. Probleme principal a resoudre

Le point cle n'est pas seulement de "mettre un bouton sur le backtest". Il faut surtout supprimer les frictions suivantes :

- saisie manuelle de noms de colonnes ;
- oubli de configs ou de chemins de fichiers ;
- confusion entre usages recherche et usages production ;
- impossibilite de reproduire un run ancien ;
- accumulation de notebooks parasites ;
- difficulte a comparer plusieurs metriques ou variantes de parametrage.

## 7. Parcours utilisateur cible

```mermaid
flowchart LR
loadData[LoadData] --> inspectData[InspectData]
inspectData --> chooseMode[ChooseMode]
chooseMode --> editConfig[EditConfig]
editConfig --> validateRun[ValidateRun]
validateRun --> launchRun[LaunchRun]
launchRun --> viewResults[ViewResults]
viewResults --> saveSnapshot[SaveSnapshot]
saveSnapshot --> reloadRun[ReloadConfigOrRun]
```

## 8. Modules fonctionnels attendus

### 8.1 Ecran d'accueil

L'ecran d'accueil doit proposer au minimum :

- `Nouveau run Recherche`
- `Nouveau run Production`
- `Nouveau batch`
- `Ouvrir une configuration existante`
- `Consulter l'historique des runs`

### 8.2 Centre de configuration

Le centre de configuration doit permettre :

- de creer une configuration ;
- de la modifier ;
- de la dupliquer ;
- de la sauvegarder ;
- de la charger ;
- de l'archiver ;
- de l'utiliser comme base pour un nouveau run.

Chaque configuration doit etre enregistree dans un format unique, lisible et versionnable.

Recommandation V1 :

- un seul format de configuration pour toute l'application ;
- `JSON` est recommande pour limiter les dependances et simplifier la maintenance.

### 8.3 Inspection des donnees chargees

Apres chargement du `screen` et des `returns`, l'application doit analyser automatiquement les donnees pour aider l'utilisateur.

La GUI doit afficher :

- la liste des colonnes detectees dans `screen` ;
- les colonnes obligatoires presentes / manquantes ;
- les benchmarks detectes automatiquement a partir des colonnes `Weight in <bench>` ;
- les colonnes candidates pour les metrics ;
- la disponibilite des colonnes ESG, secteur, market cap ;
- un apercu des dates disponibles ;
- un apercu du nombre de lignes et du nombre d'actifs.

Exigence importante :

- l'utilisateur ne doit pas avoir a taper a la main un nom de colonne si la GUI peut le detecter ou le proposer.

### 8.3.1 Regles d'auto-detection recommandees

Pour reduire le travail manuel dans la GUI, les regles suivantes sont recommandees :

- benchmarks detectes a partir des colonnes commencant par `Weight in ` ;
- metrics candidates detectees parmi les colonnes numeriques, hors colonnes techniques (`Date`, identifiants, poids benchmark, market cap) ;
- groupes de neutralisation proposes a partir des aliases supportes par le moteur (`ICB 19`, `ICB 11`) ;
- previsualisation des colonnes candidates avec taux de valeurs manquantes et exemples de valeurs.

### 8.4 Mode Recherche

Le mode Recherche est concu pour explorer des hypotheses.

Il doit permettre :

- de modifier librement la majorite des parametres ;
- de lancer un backtest ponctuel ;
- de lancer un batch sur plusieurs combinaisons ;
- de comparer les resultats entre runs ;
- d'ouvrir facilement les sorties generees.

### 8.5 Mode Production

Le mode Production est concu pour generer les sorties attendues dans un cadre plus controle.

Il doit :

- partir d'un preset ou d'une configuration pre-validee ;
- limiter les champs modifiables ;
- afficher clairement le repertoire de sortie ;
- s'appuyer sur `mode_monthly_prod=True` si le run releve de cette logique ;
- utiliser `save_portfolio_data_incremental()` si le cas d'usage production le requiert ;
- reduire les risques de mauvaise manipulation.

### 8.6 Historique des runs

La GUI doit proposer un historique centralise avec au minimum :

- date et heure du run ;
- nom du run ;
- mode utilise (`research`, `production`, `batch`) ;
- configuration source ;
- statut (`success`, `warning`, `failed`) ;
- fichiers produits ;
- message d'erreur si echec.

## 9. Mapping fonctionnel entre GUI et moteur

### 9.1 Actions GUI vers methode moteur

| Action GUI | Methode moteur | Role |
| --- | --- | --- |
| Charger la configuration | `PtfBuilder.__init__()` | Instancie le moteur avec les parametres principaux |
| Generer une sec list mensuelle | `sec_list_spot()` | Produit la liste titres + exclusions pour un mois |
| Generer l'historique de sec lists | `generic_histo_seclist()` | Produit l'historique mensuel a partir d'une date de debut |
| Calculer la perf portefeuille | `backtest()` | Calcule la performance du portefeuille sur les returns |
| Calculer la perf benchmark | `backtest_get_bench_perf()` | Construit et calcule le benchmark de comparaison |
| Generer le graphique | `backtest_plot_ptf_bench()` | Produit un HTML avec courbe portefeuille / benchmark / ratio |
| Export production | `save_portfolio_data_incremental()` | Alimente le fichier de sortie production |

### 9.2 Etats a exposer dans l'interface

Le moteur stocke deja plusieurs resultats en memoire. La GUI doit les recuperer et les rendre visibles :

| Etat / sortie | Source moteur | Usage GUI |
| --- | --- | --- |
| sec list mensuelle | `self.sec_list_monthly` | affichage et export |
| sec list historique | `self.sec_list_historical` | affichage historique |
| exclusions mensuelles | `self.list_exclusion_monthly` | affichage des raisons d'exclusion |
| exclusions historiques | `self.list_exclusion_histo` | consultation multi-mois |
| perf portefeuille | `self.perf_ptf` | graphe et tableau de performance |
| perf benchmark | `self.perf_bench` | comparaison avec le portefeuille |
| holdings backtestes | `self.buy_list` | consultation detaillee des poids |

## 10. Parametres a exposer dans la GUI

La GUI doit structurer les parametres en sections claires. Les champs suivants sont obligatoirement couverts.

### 10.1 Sources de donnees

| Champ | Description |
| --- | --- |
| `screen` | fichier source du screen ou dataset equivalent |
| `returns` | fichier de returns journalieres |
| `liste_noire` | fichier Excel de blacklist ou chemin equivalent |
| `output_dir` | repertoire de sortie |

### 10.2 Identite du portefeuille

| Champ | Description |
| --- | --- |
| `ptf_name` | nom du portefeuille ou nom force |
| `bench` | benchmark cible |

### 10.3 Selection des titres

| Champ | Description |
| --- | --- |
| `metrics` | une ou plusieurs metriques de selection |
| `percentile` | proportion ou nombre de titres a retenir |
| `Top` | selection des meilleurs ou des pires titres |
| `top_mandatory` | nombre de titres imposes |

### 10.4 Ponderation et contraintes

| Champ | Description |
| --- | --- |
| `ponderation` | mode de ponderation (`Racine cube`, `Racine carrée`, `Market cap`, `Log`, `Equalweight`) |
| `cap_weight_threshold` | cap individuel de poids |
| `cut_mkt_cap` | seuil minimal de market cap |
| `max_weight` | cap applique en phase de backtest |

### 10.5 Filtres et neutralisation

| Champ | Description |
| --- | --- |
| `esg_exclusion` | seuil d'exclusion ESG |
| `score_pivot_esg` | seuil ESG pivot ou identifiant d'index a resoudre dans le fichier pivot |
| `score_pivot_esg_path` | repertoire dans lequel chercher le dernier fichier de score pivot ESG |
| `score_neutral` | neutralisation des scores |
| `weight_neutral` | neutralisation des poids |
| `sector_neutral` | neutralisation benchmark lors du backtest |
### 10.6 Recommendations

| Champ | Description |
| --- | --- |
| `reco_secto` | ajustements sectoriels |
| `reco_facto` | ajustements factoriels pour `Multi Avg Percentile` |

### 10.7 Parametres historiques

| Champ | Description |
| --- | --- |
| `start_date` | date de debut du backtest |
| `freq_rebal` | frequence de rebalancement |
| `screen_start_date` | logique de selection des mois (`mois_pair`, `mois_impair`, ou date directe) |
| `fill_method` | methode de remplissage des mois manquants dans `generic_histo_seclist()` (`drift` ou `copy`) |

### 10.8 Parametres de mode

| Champ | Description |
| --- | --- |
| `mode_monthly_prod` | active le mode de sortie production |
| `multiprocessing` | present dans le moteur mais non prioritaire en V1 |

### 10.9 Parametres a ne pas exposer en V1

La GUI ne doit pas exposer par defaut les parametres historiques/legacy de `backtest()` qui ne sont pas necessaires pour le flux cible, sauf besoin explicitement revalide :

- `method`
- `critere`
- `max_weights`
- `list_secto`
- `repechage_filter`
- `nb_titres`
- `te_max`
- `rebalancing_start_backward`

Le flux V1 recommande est :

- instancier `PtfBuilder` ;
- lancer `generic_histo_seclist(start_date, freq_rebal, screen_start_date, fill_method)` ;
- lancer `backtest()` sur la sec list produite ;
- lancer le calcul benchmark puis la generation du graphique.

## 11. Exigences de design de l'interface

### 11.1 Principes UX

- pas de champ libre inutile si une liste de choix peut etre proposee ;
- les options avancees doivent etre repliees par defaut ;
- les dependances entre champs doivent etre explicites ;
- les messages d'erreur doivent etre comprehensibles pour un utilisateur metier/quant ;
- l'utilisateur doit savoir avant le run ce qui va etre ecrit sur disque.

### 11.2 Comportement attendu de certains champs

- `bench` doit etre propose a partir des colonnes detectees `Weight in ...` ;
- `metrics` doit etre propose sous forme de liste multi-selection ;
- `score_neutral` et `weight_neutral` doivent proposer au minimum les aliases utilises dans le moteur (`ICB 19`, `ICB 11`, etc.) ;
- si `metrics == "Multi Avg Percentile"`, la GUI doit afficher la zone `reco_facto` ;
- si `score_pivot_esg` est renseigne, la GUI doit permettre soit une valeur numerique, soit un identifiant d'index pour recuperer automatiquement le score pivot ;
- si `freq_rebal` cree des trous mensuels, la GUI doit proposer le choix `fill_method = drift` ou `fill_method = copy` ;
- si `mode_monthly_prod` est active, les options de sortie production doivent devenir visibles ;
- la GUI doit afficher les valeurs par defaut heritees du moteur, mais sans imposer a l'utilisateur de lire le code Python.

## 12. Differenciation Recherche vs Production

| Sujet | Mode Recherche | Mode Production |
| --- | --- | --- |
| Objectif | explorer des hypotheses | produire une sortie fiable |
| Niveau de liberte | eleve | restreint |
| Modification des parametres | large | limitee ou encadree |
| Batch | oui | non prioritaire |
| Sauvegarde de preset | oui | obligatoire |
| Export incremental | optionnel | obligatoire si flux prod concerne |
| Tolérance a l'essai-erreur | elevee | faible |
| Affichage detail technique | plus riche | plus guide |

Exigence :

- les deux modes reutilisent le meme moteur ;
- ils ne doivent pas partager exactement la meme interface si cela degrade la lisibilite ;
- la production doit etre plus guidee et moins permissive que la recherche.

## 13. Batch run

Le batch est un besoin explicite de la V1.

Le batch doit permettre de lancer une grille de runs sur des combinaisons de :

- `metrics`
- `percentile`
- `bench`
- `start_date`
- eventuellement `Top`, `ponderation`, `esg_exclusion`, `weight_neutral`

Contraintes V1 :

- execution sequentielle recommandee pour limiter la complexite ;
- chaque run du batch doit produire son propre snapshot de configuration ;
- un run en erreur ne doit pas annuler automatiquement tout le batch si l'utilisateur ne le demande pas ;
- l'ecran de batch doit montrer la progression et le statut run par run ;
- l'utilisateur doit pouvoir reouvrir le detail d'un run issu d'un batch.

## 14. Contrat de donnees et validations pre-run

La validation doit se faire avant l'execution. Le moteur actuel declenche encore plusieurs erreurs au runtime ou via `print()`. La GUI doit absorber cette complexite et presenter un diagnostic avant le lancement.

### 14.1 Contrat minimal pour `screen`

Colonnes minimales attendues :

- `Date`
- `ISIN`
- `Company SEDOL`
- `Benchmark Market Value Millions in EUR`
- au moins une colonne `Weight in <bench>`
- une colonne secteur si neutralisation active :
  - ` Benchmark ICB Supersector `
  - ou ` Benchmark ICB Industry `
- une colonne ESG si filtrage ESG actif :
  - `ESG_ANALYST_SCORE`
- les colonnes de metrics selectionnees

Note importante pour cette version du moteur :

- certaines colonnes sont manipulees avec leur nom brut exact, y compris les espaces en debut ou fin de libelle ;
- en particulier, ` Benchmark ICB Supersector `, ` Benchmark ICB Industry ` et `Benchmark Market Value Millions in EUR ` doivent etre traites avec prudence dans la couche de mapping GUI.

### 14.2 Contrat minimal pour `returns`

- l'index doit representer des dates ;
- les colonnes doivent correspondre aux `Company SEDOL` ;
- les dates doivent couvrir la periode du backtest ;
- les rendements doivent etre suffisamment complets pour les titres retenus.

### 14.3 Contrat pour la blacklist

- le fichier doit etre lisible ;
- il doit contenir la cle attendue (`ISIN` par defaut) ;
- les colonnes d'exclusion attendues doivent etre presentes si ce filtre est active.

### 14.4 Validations fonctionnelles

La GUI doit verifier au minimum :

- presence des fichiers ;
- presence des colonnes obligatoires ;
- existence des metrics selectionnees ;
- presence d'au moins un benchmark valide ;
- coherence entre `bench` choisi et colonne `Weight in <bench>` ;
- couverture des dates pour `reco_secto` / `reco_facto` si fournis sous forme tabulaire ;
- validite de `score_pivot_esg` si renseigne :
  - valeur numerique utilisable directement ;
  - ou identifiant texte exploitable dans le fichier pivot ESG ;
- accessibilite de `score_pivot_esg_path` si la recuperation automatique du pivot ESG est utilisee ;
- compatibilite entre options activees et colonnes disponibles ;
- coherence entre `mode_monthly_prod`, `ptf_name` et benchmark si le nommage auto production est utilise ;
- compatibilite entre `fill_method` et le comportement attendu par l'utilisateur pour les mois manquants ;
- existence du repertoire de sortie ou capacite a le creer.

### 14.5 Validations UX

Avant le run, l'utilisateur doit voir :

- un resume du parametrage ;
- les fichiers qui seront lus ;
- le repertoire cible des sorties ;
- les warnings non bloquants ;
- les erreurs bloquantes a corriger.

## 15. Gestion des erreurs et des warnings

La GUI doit transformer les erreurs internes du moteur en messages actionnables.

Exemples de cas a gerer explicitement :

- metric introuvable ;
- colonne benchmark absente ;
- colonne secteur absente alors que `score_neutral`, `weight_neutral` ou `sector_neutral` sont actifs ;
- date absente dans `reco_facto` ou `reco_secto` ;
- repertoire ou fichier pivot ESG introuvable ;
- identifiant `score_pivot_esg` introuvable dans le fichier pivot ;
- benchmark non supporte pour le nommage auto production ;
- repertoire de sortie inaccessible ;
- run lance sans `output_dir` alors qu'un export est attendu.

## 16. Artefacts a produire pour chaque run

Chaque run doit etre centralise dans un dossier ou un enregistrement unique. Le contenu minimal attendu est :

- snapshot de configuration ;
- date/heure du run ;
- statut final ;
- chemin des fichiers source ;
- sec list ;
- exclusion list ;
- performance portefeuille ;
- performance benchmark ;
- graphique HTML ;
- journal de warnings / erreurs ;
- chemin vers les exports de sortie.

Recommandation de structure minimale :

```text
runs/
  2026-04-15_103000_backtest-name/
    config.json
    sec_list.xlsx
    exclusions.xlsx
    perf_ptf.csv
    perf_bench.csv
    plot.html
    run.log
```

En mode production, ce stockage n'empeche pas l'ecriture du fichier cible metier ; il ajoute uniquement la tracabilite du run.

## 17. Resultats a afficher dans l'interface

L'utilisateur doit pouvoir consulter dans la GUI :

- la sec list generee ;
- les exclusions avec `Raison Exclusion` ;
- les raisons de repechage (`Raison Repechage`) si presentes ;
- la performance du portefeuille ;
- la performance du benchmark ;
- le ratio portefeuille / benchmark ;
- le detail des fichiers ecrits ;
- les logs du run.

La GUI doit proposer des actions simples :

- ouvrir le dossier du run ;
- ouvrir le graphique HTML ;
- exporter les tables ;
- dupliquer la configuration de ce run pour un nouveau run.

## 18. Exigences non fonctionnelles

### 18.1 Reproductibilite

- tout run doit etre rejouable a partir de son snapshot de configuration ;
- deux utilisateurs doivent pouvoir reutiliser la meme config sans notebook intermediaire.

### 18.2 Maintenabilite

- le code UI doit rester separe du moteur de calcul ;
- les adaptations du moteur doivent etre minimes et justifiees ;
- il faut eviter de multiplier les formats de configuration et les conventions locales.

### 18.3 Robustesse

- l'application doit gerer proprement les erreurs de validation et les erreurs runtime ;
- un run ne doit pas necessiter de commenter/decommenter du code ;
- un echec de run doit laisser une trace exploitable.

### 18.4 Performance

- la V1 doit prioriser la stabilite et la lisibilite sur l'optimisation ;
- le batch parallelise est un sujet V2, pas une exigence V1.

## 19. Hors perimetre V1

Les points suivants peuvent etre traites plus tard :

- parallelisation des batches ;
- orchestration multi-machine ;
- systeme de permissions avance ;
- comparaison graphique avancee entre nombreux runs ;
- edition manuelle experte des snapshots directement depuis la GUI ;
- remplacement profond du moteur `BacktestEngine`.

## 20. Criteres d'acceptation

La V1 est consideree comme acceptable si les conditions suivantes sont remplies :

1. Un utilisateur peut lancer un backtest complet sans ouvrir Jupyter.
2. Les benchmarks et metrics peuvent etre choisis via l'interface sans recopier des noms de colonnes a la main.
3. Une configuration peut etre sauvegardee, rechargee et rejouee.
4. Un batch de plusieurs runs peut etre lance et suivi depuis l'interface.
5. Les resultats principaux sont consultables sans notebook : sec list, exclusions, performance, benchmark, ratio.
6. Le mode production permet de generer les sorties attendues de maniere guidee.
7. Chaque run conserve un snapshot de configuration et des artefacts consultables.
8. Deux membres de l'equipe peuvent reproduire le meme run a partir des fichiers et de la configuration sauvegardee.

## 21. Recommandations techniques a discuter avec Titouen

Points recommandes pour la discussion de conception :

- garder `C:\GoogleDrive\TP\backtest\BacktestEngine.py` comme noyau de calcul ;
- construire la GUI comme couche externe d'orchestration ;
- choisir un seul format de configuration en V1 ;
- separer visuellement et fonctionnellement les parcours Recherche et Production ;
- centraliser les runs dans un historique local plutot que dans des notebooks ;
- garder la batch execution simple et sequentielle en V1.

## 22. Questions ouvertes a arbitrer en atelier

Ces points peuvent etre tranches lors de la discussion avec Titouen :

- stack UI desktop exacte ;
- emplacement exact du stockage local des runs ;
- format final de configuration si l'equipe prefere autre chose que JSON ;
- niveau de verrouillage du mode production ;
- niveau de detail de l'historique et des comparaisons entre runs.
