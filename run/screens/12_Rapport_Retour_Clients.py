"""
Page — Générateur de rapport.

Reste un document téléchargeable (PDF / Word / PowerPoint) — jamais une
page HTML. La logique elle-même vit dans viz/report_ui.py, partagée avec
le second point d'accès situé en bas de la page 📊 Tableau de bord (même
moteur appelé deux fois, pas deux versions séparées qui risqueraient de
diverger).
"""
from __future__ import annotations

import streamlit as st

from config.theme import set_page_title
from data.state import require_dataframe_or_stop
from viz.report_ui import render_report_generator

set_page_title("🗞️ Générateur de rapport", "Export PDF, Word et PowerPoint")

# Neutralise l'espacement par défaut de Streamlit (gap:22px) entre
# éléments — sans ça, le bloc <style> invisible injecté par
# set_page_title() (hauteur 0) garde quand même sa marge par défaut, ce
# qui poussait le vrai contenu de la page loin sous la barre de menu.
# Même bug déjà rencontré et corrigé sur les pages Préparation et Tableau
# de bord — jamais appliqué ici jusqu'à présent.
st.markdown(
    "<style>"
    ".block-container > [data-testid=\"stVerticalBlock\"]{gap:0 !important;}"
    # Petit espace volontaire entre la barre de menu et la première case
    # (demande explicite : pas collé, juste une légère séparation) — sur
    # le premier enfant, PAS sur .block-container lui-même : son
    # padding-top est déjà piloté en JS par main.py (resynchronisé en
    # continu selon la hauteur de la barre), une règle CSS statique s'y
    # ferait écraser.
    ".block-container > [data-testid=\"stVerticalBlock\"] > [data-testid=\"stElementContainer\"]:first-child{margin-top:0.6rem !important;}"
    "</style>",
    unsafe_allow_html=True,
)

df_full = require_dataframe_or_stop()
render_report_generator(df_full, key_prefix="report", show_title=False)
