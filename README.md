# CIE Analytics

Application web d'analyse statistique (Python / Streamlit) pour la Direction Marketing de la CIE, destinée à remplacer progressivement les flux de traitement KNIME actuels (extraction, nettoyage, transformation, analyse, visualisation).

## ⚠️ Lancement — lis ceci avant de démarrer

```bash
streamlit run run/main.py
```

**Le point d'entrée est `run/main.py`.** Un dossier littéralement nommé `pages` juste à côté du script lancé déclenche un comportement automatique de Streamlit qui affiche toutes les pages du dossier dans le menu — y compris avant connexion, et même les fichiers non utilisés. C'est ce qui provoquait le menu visible avant authentification. `run/main.py` a pour voisin `run/screens/` (pas `pages/`), ce qui désactive ce comportement pour de bon. L'ancien `app.py` et l'ancien dossier `pages/` à la racine ont été supprimés : ils ne sont plus nécessaires et représentaient un risque si quelqu'un lançait l'app avec `streamlit run app.py` par erreur.

De plus, tant que personne n'est connecté, la barre latérale est entièrement masquée (CSS) et le menu de navigation est rendu avec `position="hidden"` : l'écran de connexion n'apparaît donc plus lui-même comme une entrée de menu ("onglet de connexion" visible avant identification) — c'est un écran isolé, sans aucun menu autour.

## État d'avancement

| Segment | État |
|---|---|
| 1. Accueil | ✅ Fonctionnel |
| 2. Import de données | ✅ Fonctionnel — Excel/CSV (structure libre, testé jusqu'à 100 000 lignes), jeu de démo, **et connexion réelle à une base externe** (PostgreSQL / MySQL / SQL Server / SQLite : test de connexion, liste des tables, extraction par table ou requête SQL libre) |
| 3. Préparation | ✅ Fonctionnel — import multi-fichiers + fusion (total de lignes fusionnées affiché), pipeline d'opérations (nettoyage, filtres, découpage multi-valeurs, colonnes calculées/constantes, agrégation), équivalent des nœuds KNIME |
| 4. Statistiques descriptives | ✅ Fonctionnel (statistiques personnalisées à la carte, respectant le type réel de chaque colonne, + graphique et commentaire automatique) |
| 5. Tableaux croisés dynamiques | ✅ Fonctionnel — lignes/colonnes/valeurs au choix, agrégation (somme, moyenne, comptage, min, max, médiane), tableau + graphique + commentaire |
| 6. Comparaisons & tendances | ✅ Fonctionnel — taux clés (ex : satisfaction), comparaison entre groupes (agences/services) avec verdict en langage clair, lien entre deux facteurs, évolution entre deux périodes |
| 7. Visualisation | ✅ Fonctionnel (7 types de graphiques adaptés à un public non technique + commentaire automatique) |
| 8. Filtres & export | ✅ Filtres + export CSV fonctionnels ; export PDF/Excel avancé à venir |
| 9. Administration | ✅ Fonctionnel (création de comptes, rôles, activation/désactivation, reset mot de passe) |

L'authentification, la gestion des rôles, et le mécanisme de commentaire automatique (règles + API Claude, avec interrupteur) sont opérationnels sur l'ensemble de l'application.

> **Choix assumé :** la régression linéaire/logistique (coefficients, p-values, matrices de confusion...) a été retirée du périmètre. Jugée trop technique pour l'usage réel de la majorité des utilisateurs (non-statisticiens), elle a été remplacée par le segment **Comparaisons & tendances**, qui répond directement à des questions de pilotage (où sommes-nous bons/en retard, est-ce que ça s'améliore) avec un verdict en langage clair plutôt qu'une sortie statistique brute. Même logique pour la boîte à moustaches, remplacée par une comparaison en barres, plus lisible.

## Installation

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

Copie `.env.example` en `.env`. Tout fonctionne avec les valeurs par défaut (y compris le compte administrateur) — tu peux les personnaliser mais ce n'est pas obligatoire pour démarrer.

```bash
cp .env.example .env
```

## Lancement et première connexion

```bash
streamlit run run/main.py
```

Au tout premier lancement, un compte administrateur est créé automatiquement. **Avec les valeurs par défaut de `.env.example` (si tu n'as rien changé) :**

- Email : `admin@cie.ci`
- Mot de passe : `ChangeMoi123!`

Si tu as personnalisé `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` dans ton `.env`, utilise tes propres valeurs. **Change ce mot de passe dès la première connexion** via le segment Administration.

L'écran de connexion est le seul élément visible tant que personne n'est authentifié : le menu de navigation (et toutes les pages) n'apparaît qu'après une connexion réussie — vérifié par exécution réelle (voir plus bas).

## Rôles

- **Administrateur** : gestion complète des comptes (création, rôle, activation, réinitialisation de mot de passe)
- **Direction** : vue de synthèse, accès aux rapports et exports
- **Responsable de service** : données et analyses de son périmètre
- **Utilisateur standard** : consultation et analyses sur les données mises à disposition

Chaque session (par utilisateur) a ses propres données chargées, filtres et graphiques — aucune interférence entre utilisateurs connectés simultanément.

## Connexion à une base de données externe

Dans **Import de données → Base de données externe** : choix du type (PostgreSQL, MySQL/MariaDB, SQL Server, ou SQLite), saisie des coordonnées (pré-remplies depuis `.env` si `EXTERNAL_DB_*` est configuré, sinon libres), test de connexion réel, puis choix de la table à extraire ou d'une requête SQL libre (SELECT uniquement, pour la sécurité). Le mot de passe saisi à l'écran n'est jamais enregistré. PostgreSQL/MySQL/SQL Server nécessitent leur pilote Python (`psycopg2-binary`, `pymysql`, `pyodbc` respectivement) — message clair à l'écran si absent.

## Commentaire automatique

Deux moteurs, activables via un interrupteur dans l'interface, sur chaque graphique de l'application (Statistiques, TCD, Comparaisons, Visualisation) :

- **Règles statistiques** : templates de phrases remplis avec les statistiques déjà calculées (valeur dominante, tendance, corrélation, verdict de comparaison...). Gratuit, aucune dépendance externe.
- **API Claude (Anthropic)** : envoie uniquement un résumé structuré (jamais les données brutes) pour un commentaire plus nuancé. Nécessite `ANTHROPIC_API_KEY` dans `.env`. En cas d'erreur (clé absente, réseau, quota), l'application retombe automatiquement sur le moteur par règles — jamais de plantage.

## Identité visuelle

Thème sobre inspiré du drapeau ivoirien (orange `#F7941D`, blanc, vert `#009A44`), police Inter, cartes avec ombre légère, boutons arrondis, liseré tricolore en haut de chaque page. Écran de connexion en deux volets : présentation de l'application à gauche, formulaire à droite — pensé pour ne pas laisser d'espace vide. Défini dans `.streamlit/config.toml` (thème natif Streamlit) et `config/theme.py` (habillage CSS partagé).

## Architecture

```
cie_analytics/
├── run/
│   ├── main.py              # ✅ VRAI point d'entrée : streamlit run run/main.py
│   └── screens/             # Une page Streamlit par segment de navigation

├── config/settings.py       # Configuration centralisée (variables d'environnement)
├── config/theme.py          # Habillage visuel (CSS partagé, couleurs CIE)
├── auth/                    # Base utilisateurs (SQLAlchemy) + hachage bcrypt + sessions
├── data/                    # Import, connexion base externe, détection de type, démo, état de session
├── pipeline/                # Opérations de préparation réutilisables (équivalent nœuds KNIME)
├── stats/                   # Statistiques descriptives + comparisons.py (comparaisons/tendances)
└── viz/                     # Graphiques Plotly adaptatifs + moteur de commentaire
```

Migration vers une autre base de données utilisateurs (PostgreSQL, base CIE) : changer uniquement `USERS_DB_URL` dans `.env`, aucun changement de code nécessaire (SQLAlchemy).

## Vérifications effectuées

L'application a été exécutée réellement (pas seulement relue) avec le framework de test officiel de Streamlit (`streamlit.testing.v1.AppTest`), à partir du vrai point d'entrée `run/main.py` :

- Aucun élément de menu visible avant connexion (0 élément détecté dans la barre latérale), menu complet après connexion réussie
- Connexion avec les identifiants par défaut (`admin@cie.ci` / `ChangeMoi123!`), création/édition d'utilisateur
- Import d'un fichier de 100 000 lignes (CSV : ~0,6 s ; Excel : ~14 s — message d'avertissement à l'écran pour les gros fichiers Excel)
- Connexion réelle à une base SQLite de test, liste des tables, extraction d'une table et d'une requête SQL personnalisée
- Génération du jeu de démonstration, pipeline de préparation, fusion multi-fichiers
- Les 7 graphiques de Visualisation, les 4 analyses de Comparaisons & tendances, et le TCD (mode comptage et mode croisé 2 dimensions) génèrent tous un graphique + un commentaire, sans erreur, sur les 9 segments

## Prochaines étapes

1. Export PDF/Excel avancé et historique des analyses par utilisateur
2. Pilotes optionnels PostgreSQL/MySQL/SQL Server à installer selon la base réelle de la CIE (`pip install psycopg2-binary` ou `pymysql` ou `pyodbc`)
3. Retours utilisateur sur le segment Comparaisons & tendances pour affiner les questions métier couvertes
