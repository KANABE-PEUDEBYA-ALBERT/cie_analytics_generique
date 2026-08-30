"""Page — Aide."""
from __future__ import annotations
from config.theme import set_page_title

import streamlit as st

from auth.auth_utils import current_role

set_page_title("Aide", "Présentation de l'application")

st.markdown(
    """
    <style>
    .block-container > [data-testid="stVerticalBlock"]{gap:0 !important;}
    .st-key-aide_box_fait, .st-key-aide_box_organisation, .st-key-aide_box_indicateurs {
        background:#FFFFFF; border:1px solid #E5E1DC; border-radius:14px;
        padding:20px 24px 24px; margin-bottom:22px;
        box-shadow: 0 12px 30px rgba(0,0,0,.16), 0 4px 9px rgba(0,0,0,.09);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="aide_box_fait"):
    st.markdown("### **Ce que fait l'application**")
    st.markdown(
        "CIE Analytics centralise et analyse les questionnaires de satisfaction "
        "collectés en agence après chaque visite client. Elle fusionne "
        "automatiquement les fichiers de plusieurs agences, calcule les "
        "indicateurs de satisfaction et de performance, et produit des rapports "
        "PDF, Word et PowerPoint prêts à diffuser."
    )

with st.container(key="aide_box_organisation"):
    st.markdown("### **Organisation de l'application**")
    menu_admin = "\nAdministration : gestion des comptes utilisateurs (réservé aux administrateurs)." if current_role() == "administrateur" else ""
    st.markdown(
        f"""
    Accueil : vue d'ensemble et statut des données chargées.

    Préparation : import et fusion des fichiers de questionnaires.

    Tableau de bord : indicateurs et graphiques de satisfaction, globaux et par agence.

    Générateur de rapport : export PDF, Word et PowerPoint par agence ou combiné.

    Assistant : questions en langage naturel sur les données chargées.{menu_admin}
    """
    )

with st.container(key="aide_box_indicateurs"):
    st.markdown("### **Les 13 indicateurs**")
    # Chaque indicateur : nom en gras, VRAIE fraction (barre horizontale,
    # via st.latex — demande explicite : "des vraies fractions... pas des
    # a/b ou a÷b"), puis une explication en français simple, sans jargon
    # non expliqué, avec ":" pour introduire l'explication (jamais de
    # tiret, qui peut être confondu avec un signe moins — demande
    # explicite).

    st.markdown("**Nombre de répondants**")
    st.markdown("Le nombre total de personnes ayant répondu au questionnaire.")

    st.markdown("**Taux de réponse**")
    st.latex(r"\frac{\text{Nombre de répondants}}{\text{Nombre de demandes enregistrées}} \times 100")
    st.markdown("Sur toutes les personnes qui auraient dû répondre, combien l'ont fait réellement.")

    st.markdown("**Taux de satisfaction**")
    st.latex(r"\frac{\text{Très satisfait} + \text{Satisfait}}{\text{Nombre de répondants}} \times 100")
    st.markdown("Sur 100 répondants, combien ont dit être satisfaits ou très satisfaits.")

    st.markdown("**Taux de très satisfaction**")
    st.latex(r"\frac{\text{Très satisfait}}{\text{Nombre de répondants}} \times 100")
    st.markdown("Sur 100 répondants, combien ont donné la meilleure note possible.")

    st.markdown("**Taux d'insatisfaction**")
    st.latex(r"\frac{\text{Très insatisfait} + \text{Insatisfait}}{\text{Nombre de répondants}} \times 100")
    st.markdown("Sur 100 répondants, combien ont dit être insatisfaits ou très insatisfaits.")

    st.markdown("**Taux de neutralité**")
    st.latex(r"\frac{\text{Neutre}}{\text{Nombre de répondants}} \times 100")
    st.markdown("Sur 100 répondants, combien n'ont exprimé ni satisfaction ni insatisfaction.")

    st.markdown("**Score moyen de satisfaction (/5)**")
    st.latex(r"\frac{\text{Somme de toutes les notes}}{\text{Nombre de répondants}}")
    st.markdown("La moyenne des notes données, sur une échelle de 1 (très insatisfait) à 5 (très satisfait).")

    st.markdown("**Indice de satisfaction net**")
    st.latex(r"\text{Taux de satisfaction} - \text{Taux d'insatisfaction}")
    st.markdown("Le taux de satisfaction moins le taux d'insatisfaction. Un résultat positif veut dire qu'il y a plus de clients satisfaits que d'insatisfaits.")

    st.markdown("**Taux de résolution**")
    st.latex(r"\frac{\text{Demandes résolues}}{\text{Nombre de répondants}} \times 100")
    st.markdown("Sur 100 répondants, combien ont vu leur demande résolue.")

    st.markdown("**Résolution parmi les insatisfaits**")
    st.latex(r"\frac{\text{Demandes résolues chez les insatisfaits}}{\text{Nombre total d'insatisfaits}} \times 100")
    st.markdown("Parmi les clients insatisfaits, combien ont quand même vu leur demande résolue.")

    st.markdown("**Clients à risque**")
    st.latex(r"\frac{\text{Insatisfaits ET non résolus}}{\text{Nombre de répondants}} \times 100")
    st.markdown("Sur 100 répondants, combien sont à la fois insatisfaits et n'ont pas eu de solution à leur problème. Ce sont les clients les plus urgents à recontacter.")

    st.markdown("**CSAT (Customer Satisfaction Score)**")
    st.markdown("Le nom professionnel, utilisé dans le secteur, du taux de satisfaction : c'est exactement le même calcul, présenté sous ce nom pour les comparaisons avec d'autres entreprises.")

    st.markdown("**CES estimé**")
    st.latex(r"\text{CES estimé} = \text{Taux de résolution}")
    st.markdown("Une estimation de l'effort que le client a dû fournir pour obtenir une solution. Le questionnaire actuel ne pose pas directement cette question, donc le taux de résolution est utilisé à la place : une demande résolue rapidement suppose un effort plus faible pour le client.")

    st.markdown("**NPS estimé**")
    st.latex(r"\text{NPS estimé} = \%\text{(note 5)} - \%\text{(notes 1 et 2)}")
    st.markdown(
        "Une estimation de la probabilité que les clients recommandent la CIE : le pourcentage de clients ayant "
        "donné la meilleure note (5 sur 5) moins le pourcentage de ceux ayant donné une des 2 notes les plus basses "
        "(1 ou 2 sur 5). Important : ce n'est qu'une estimation, pas un vrai NPS. Un vrai NPS repose sur une "
        "question différente, qui demande directement si le client recommanderait l'entreprise, notée de 0 à 10 — "
        "le questionnaire actuel ne pose pas cette question."
    )
