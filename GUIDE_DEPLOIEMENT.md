# Déployer CIE Analytics sur GitHub + Streamlit Cloud

## Point important à comprendre avant de commencer

Streamlit Cloud **redémarre l'application** à chaque fois que tu pousses du
code sur GitHub, et la met aussi en veille après une période d'inactivité.
Or, les données importées via "🧹 Préparation" vivent en mémoire
(`st.session_state`), pas dans une base persistante — donc **elles
disparaissent à chaque redémarrage**. C'est très probablement la cause du
"rien ne marche" que tu as observé après un déploiement : ce n'est pas un
bug, c'est le fonctionnement normal de ce type d'hébergement avec ce mode de
stockage. Il faut réimporter les données après chaque redéploiement/réveil
(voir étape 5).

---

## Étape 1 — Mettre le code sur GitHub

### Si tu n'as pas encore de dépôt GitHub

1. Va sur [github.com](https://github.com) → bouton **"New repository"**
2. Nom du dépôt (ex: `cie-analytics`) → **Private** (recommandé, vu que ça touche
   des données clients) → **Create repository**
3. Sur ton ordinateur, dans le dossier du projet (celui qui contient `run/`,
   `viz/`, `requirements.txt`, etc.) :

```bash
cd chemin/vers/cie_analytics
git init
git add .
git commit -m "Version initiale"
git branch -M main
git remote add origin https://github.com/TON_UTILISATEUR/cie-analytics.git
git push -u origin main
```

### Si tu as déjà un dépôt existant

```bash
cd chemin/vers/cie_analytics
git add .
git commit -m "Mise à jour"
git push
```

⚠️ **Avant ce premier push**, vérifie que le fichier `.gitignore` fourni est
bien à la racine du projet (à côté de `run/main.py`) — il empêche ta clé
Gemini, ton `.env` et ta base d'utilisateurs locale de partir sur GitHub.

Vérification rapide avant de pousser :
```bash
git status
```
Tu ne dois **jamais** voir `.env` dans la liste des fichiers à ajouter. Si tu
le vois, le `.gitignore` n'est pas au bon endroit (il doit être à la racine,
au même niveau que `run/`).

---

## Étape 2 — Déployer sur Streamlit Cloud

1. Va sur [share.streamlit.io](https://share.streamlit.io) et connecte-toi
   avec ton compte GitHub
2. **"New app"**
3. Choisis :
   - **Repository** : `TON_UTILISATEUR/cie-analytics`
   - **Branch** : `main`
   - **Main file path** : `run/main.py`
4. Ne clique **pas encore** sur "Deploy" — d'abord les secrets (étape 3)

---

## Étape 3 — Configurer les secrets (remplace ton fichier `.env`)

Streamlit Cloud ne lit pas de fichier `.env` — il faut renseigner les mêmes
valeurs dans son propre panneau "Secrets".

Dans l'écran de création de l'app (ou après coup via **⋮ → Settings →
Secrets**), colle ceci (adapte les valeurs) :

```toml
GEMINI_API_KEY = "ta_vraie_cle_gemini"
BOOTSTRAP_ADMIN_EMAIL = "admin@cie.ci"
BOOTSTRAP_ADMIN_PASSWORD = "UnMotDePasseFort123!"
APP_SECRET_KEY = "une-chaine-aleatoire-longue-et-unique"
```

Le code lit automatiquement ces valeurs (déjà câblé dans
`config/settings.py` — rien à modifier).

**N'ajoute PAS** `DISABLE_LOGIN` (ou mets-le à `false`) : sur un déploiement
en ligne, la connexion doit rester active.

---

## Étape 4 — Déployer

Clique sur **"Deploy!"**. Premier déploiement : 2 à 5 minutes (installation
de `requirements.txt`, y compris `matplotlib`, `reportlab`, `python-pptx`,
etc.). Tu peux suivre les logs en direct dans l'interface Streamlit Cloud —
utile si quelque chose échoue à l'installation.

---

## Étape 5 — Après chaque déploiement : réimporter les données

Une fois l'app en ligne :
1. Connecte-toi avec l'email/mot de passe admin défini dans les secrets
2. Va sur **🧹 Préparation** → réimporte tes fichiers questionnaire
3. Seulement après ça, va sur **📊 Tableau de bord** / **🗞️ Générateur de
   rapport** — sinon les boutons resteront grisés (le nouveau message
   d'erreur explicite te le confirmera directement à l'écran).

---

## Pour les mises à jour futures

À chaque fois que tu modifies le code :
```bash
git add .
git commit -m "Description du changement"
git push
```
Streamlit Cloud redéploie automatiquement en quelques dizaines de secondes.
Pense à réimporter tes données après, comme à l'étape 5 — c'est le seul vrai
inconvénient de ce mode d'hébergement par rapport à un serveur local qui
reste allumé en continu.

---

## Checklist de vérification rapide

- [ ] `.gitignore` présent à la racine, `.env` n'apparaît jamais dans `git status`
- [ ] Secrets renseignés dans Streamlit Cloud (`GEMINI_API_KEY` en premier)
- [ ] Connexion possible avec l'email/mot de passe admin des secrets
- [ ] Données réimportées via Préparation après le déploiement
- [ ] Test : Tableau de bord affiche des graphiques, Générateur de rapport
      n'a plus de bouton grisé
