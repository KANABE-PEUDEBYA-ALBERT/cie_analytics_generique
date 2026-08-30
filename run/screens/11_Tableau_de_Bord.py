"""Page — Tableau de bord.

Page centrale de l'application (première position du menu). Deux moteurs
possibles, choisis automatiquement et invisiblement selon la provenance des
données (voir data/state.py — is_questionnaire_data()) :

- Questionnaires satisfaction (flux principal, inchangé) : dashboard HTML/
  Chart.js CIE (indicateurs, 10 graphiques indépendants personnalisables,
  filtres agence/période/granularité, verbatims triés avec résumé IA...).
- Fichier brut quelconque (import générique via 🏠 Accueil) : dashboard
  générique (assets/dashboard_generic_auto.html) — 10 emplacements avec
  variable/opération/type au choix libre dans chaque fenêtre, verbatims
  détectés automatiquement si une colonne de texte libre existe. Même
  verrou, même ordre personnalisable, mêmes commentaires IA que la version
  CIE — juste un autre moteur d'analyse en dessous.

Dans les deux cas, connecté directement aux données préparées via
🏠 Accueil — aucun import distinct n'est nécessaire ici.

En bas de cette page : le Générateur de rapport (PDF/Word/PowerPoint), en
second point d'accès au même moteur que la page dédiée 🗞️ Générateur de
rapport (voir viz/report_ui.py) — pratique pour générer le rapport juste
après avoir personnalisé le tableau de bord, sans changer de page. En mode
générique, ce générateur PDF/Word/PPTX n'est pas encore disponible (il est
bâti spécifiquement pour la structure du questionnaire CIE) — le bouton
« 📄 Générer le rapport » intégré au dashboard générique lui-même prend le
relais (rapport HTML imprimable, avec les mêmes graphiques/commentaires/
verbatims que ceux personnalisés à l'écran).
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from config.settings import get_settings
from config.theme import set_page_title
from data.state import get_current_dataframe, has_current_dataframe, is_questionnaire_data
from viz.dashboard_bridge import COMPONENT_DIR as _COMPONENT_DIR
from viz.dashboard_bridge import dashboard_bridge
from viz.report_ui import render_report_generator

set_page_title("📊 Tableau de bord", "Indicateurs clés de satisfaction")

# Le dashboard doit occuper toute la largeur de la zone de contenu, sans
# marge parasite, et l'iframe ne doit laisser aucun liseré autour de lui.
# padding-bottom volontairement généreux (pas 0) : tout ce qui s'affiche
# APRÈS l'iframe sur cette page (le Générateur de rapport, en bas) se
# retrouvait collé au tout dernier pixel de la fenêtre, sans la moindre
# marge — le bouton "Télécharger" en particulier devenait à peine visible,
# voire caché derrière la barre flottante "Gérer l'application" de
# Streamlit Cloud, en bas à droite.
st.markdown(
    "<style>"
    ".block-container{padding-top:1rem;padding-bottom:5rem;padding-left:0.5rem;padding-right:0.5rem;max-width:100%;}"
    "iframe{display:block;width:100%;border:none;}"
    # Neutralise l'espacement par défaut de Streamlit (gap:22px) entre
    # éléments — sans ça, le bloc <style> injecté ci-dessus (invisible,
    # hauteur 0) garde quand même sa marge par défaut, ce qui poussait le
    # vrai contenu de la page ~150px plus bas que la barre de menu du
    # haut. Même bug déjà rencontré et corrigé sur la page Préparation.
    ".block-container > [data-testid=\"stVerticalBlock\"]{gap:0 !important;}"
    "</style>",
    unsafe_allow_html=True,
)

if not has_current_dataframe():
    st.info(
        "Aucune donnée n'est chargée dans cette session. Va dans **🏠 Accueil** "
        "pour déposer un ou plusieurs exports du questionnaire de satisfaction, ou un "
        "fichier brut quelconque — le tableau de bord s'alimentera automatiquement "
        "à partir de ces données, sans étape supplémentaire."
    )
    st.stop()

df_all = get_current_dataframe()
questionnaire_mode = is_questionnaire_data()

# --- Filtre agence global, natif Streamlit (persiste réellement) -----------
# Uniquement pertinent pour le flux questionnaire (colonne Agence garantie).
# Contrairement aux sélections faites À L'INTÉRIEUR du dashboard HTML
# ci-dessous (pur JavaScript, dans une iframe recréée à chaque rendu — donc
# perdues en quittant la page), ce filtre est un widget Streamlit classique,
# soutenu par st.session_state via sa `key`. Streamlit conserve
# automatiquement la valeur d'un widget tant que sa clé ne change pas —
# donc en quittant cette page puis en y revenant, la sélection reste en
# place. C'est aussi CETTE même clé de session que lit le Générateur de
# rapport pour proposer par défaut la même agence : les deux pages sont
# ainsi connectées.
GLOBAL_AGENCE_KEY = "global_agence_filter"
if questionnaire_mode and "Agence" in df_all.columns:
    agences_dispo = sorted(df_all["Agence"].dropna().unique().tolist())

    # Widget de sélection retiré de l'affichage (demande explicite) — la clé
    # de session GLOBAL_AGENCE_KEY reste néanmoins alimentée avec TOUTES les
    # agences, car le Générateur de rapport lit cette même clé pour proposer
    # par défaut la même agence : les deux pages restent connectées, juste
    # sans widget visible ici pour changer la sélection.
    agences_choisies = agences_dispo
    st.session_state[GLOBAL_AGENCE_KEY] = agences_dispo
    df = df_all[df_all["Agence"].isin(agences_choisies)] if agences_choisies else df_all.iloc[0:0]
else:
    df = df_all

if df.empty:
    st.warning("Aucune réponse pour la sélection d'agence(s) actuelle.")
    st.stop()

# --- Demandes/réclamations enregistrées par agence, natif Streamlit --------
# Uniquement pertinent pour le flux questionnaire — un fichier brut
# quelconque n'a pas de notion de "demandes enregistrées par agence".
DEMANDES_KEY = "demandes_par_agence"
if DEMANDES_KEY not in st.session_state:
    st.session_state[DEMANDES_KEY] = {}

# --- Données injectées telles quelles dans le dashboard HTML --------------
# Le dashboard CIE reconnaît les colonnes standardisées produites par
# data/questionnaire.py (Agence, Horodatage, Satisfaction, Motif_insatisfaction,
# Apprecie_liste, Resolu, Commentaire...). Le dashboard générique ne présume
# rien : il détecte lui-même les types de colonnes à partir des données
# réellement présentes (voir analyzeColumns() dans dashboard_generic_auto.html).
raw_data_json = df.to_json(orient="records", date_format="iso", force_ascii=False)
columns_json = json.dumps(list(df.columns), ensure_ascii=False)
# Évite qu'une séquence "</script>" dans les données ne ferme
# prématurément la balise <script> de la page hôte.
raw_data_json = raw_data_json.replace("</", "<\\/")
columns_json = columns_json.replace("</", "<\\/")

_ASSET_NAME = "dashboard_auto.html" if questionnaire_mode else "dashboard_generic_auto.html"
_HTML_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / _ASSET_NAME


@st.cache_data
def _load_dashboard_template(asset_name: str) -> str:
    """Le modèle HTML (~240 Ko) ne change JAMAIS entre deux exécutions —
    seules les DONNÉES injectées ensuite changent. Avant, ce fichier était
    relu et redécodé du disque à CHAQUE interaction (changement de filtre,
    clic sur un bouton...), puisque Streamlit relance tout le script à
    chaque fois. Mis en cache séparément de l'injection des données, qui
    elle doit rester fraîche à chaque fois."""
    path = Path(__file__).resolve().parent.parent.parent / "assets" / asset_name
    return path.read_text(encoding="utf-8")


_dashboard_html = _load_dashboard_template(_ASSET_NAME)
_dashboard_html = _dashboard_html.replace("__CIE_RAW_DATA__", raw_data_json)
_dashboard_html = _dashboard_html.replace("__CIE_COLUMNS__", columns_json)

# Clé Gemini déjà configurée côté serveur (même source que l'Assistant et le
# Générateur de rapport) — injectée directement dans le HTML pour que le
# résumé des verbatims et le commentaire automatique des graphiques
# fonctionnent sans qu'aucun utilisateur n'ait à saisir ou voir de clé API.
# Chaîne vide si Gemini n'est pas configuré : les boutons IA du dashboard
# affichent alors un message clair au lieu d'échouer silencieusement.
_settings = get_settings()
_gemini_key = _settings.gemini_api_key if _settings.gemini_configured else ""
_dashboard_html = _dashboard_html.replace("__CIE_GEMINI_KEY__", _gemini_key)

# --- Composant avec canal de retour (au lieu d'un simple components.html) --
# Différence essentielle : components.html() est à SENS UNIQUE (Python vers
# JS seulement) — le Générateur de rapport ne pouvait donc jamais savoir
# quel type de graphique était réellement choisi ici (camembert, anneau,
# barres...), et reconstruisait des graphiques génériques qui ne
# correspondaient pas à ce qui est affiché à l'écran. Un composant déclaré
# (`declare_component`) ouvre un vrai canal RETOUR : le JS du dashboard
# envoie son état complet à chaque changement (voir saveDashboardState()
# dans dashboard_auto.html), et Python le reçoit ici, dans `dashboard_state`.
#
# Le composant lui-même est déclaré à part, dans viz/dashboard_bridge.py
# (module importé normalement) — le déclarer directement ici provoquait un
# crash sous st.navigation() : voir le commentaire de ce module pour le détail.
(_COMPONENT_DIR / "index.html").write_text(_dashboard_html, encoding="utf-8")

dashboard_state = dashboard_bridge(key="cie_dashboard_bridge", default=None)
if dashboard_state:
    # Partagé avec le Générateur de rapport (viz/report_ui.py / viz/report_charts.py)
    # pour qu'il applique EXACTEMENT les mêmes types de graphique que ceux
    # actifs ici, au lieu d'une reconstruction générique indépendante.
    # (En mode générique, le Générateur de rapport PDF/Word/PPTX ne
    # consomme pas encore cet état — voir la note plus bas.)
    st.session_state["dashboard_live_state"] = dashboard_state

# --- Générateur de rapport, en bas de cette même page ----------------------
# Second point d'accès au même générateur que la page 🗞️ Générateur de
# rapport (voir viz/report_ui.py) — pas une version séparée : une fois les
# graphiques et KPI ci-dessus personnalisés à l'écran, on peut générer le
# rapport PDF/Word/PowerPoint directement ici, sans changer de page. En
# mode générique, render_report_generator affiche lui-même le message
# adéquat (voir viz/report_ui.py) — pas besoin de dupliquer cette logique ici.
render_report_generator(df_all, key_prefix="dash_report", show_demandes_panel=False)
