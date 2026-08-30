"""Page 10 — Assistant CIE Analytics (chat).

Assistant conversationnel intégré à l'application, pour aider les
utilisateurs à s'orienter dans les modules (import, préparation,
statistiques, TCD, comparaisons, visualisation, export) et à interpréter
leurs résultats. Utilise l'API Gemini (clé gratuite, voir .env.example).

Les conversations sont sauvegardées en base (par utilisateur, comme les
comptes de auth/database.py) : historique visible dans la barre latérale,
bouton "Nouvelle conversation", reprise d'une ancienne conversation,
suppression. Chaque utilisateur ne voit que ses propres conversations.
"""
from __future__ import annotations
from config.theme import set_page_title

import io

import pandas as pd
import streamlit as st
from PIL import Image

from auth.auth_utils import current_user_label
from auth.database import (
    add_conversation_message,
    close_conversation,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversation_messages,
    list_conversations,
    reopen_conversation,
)
from ai.gemini_client import DEFAULT_MODEL_CHAIN, call_gemini
from config.settings import get_settings
from data.state import (
    get_analysis_log,
    get_current_dataframe,
    get_current_source,
    get_current_types,
    get_pipeline_history,
    has_current_dataframe,
)

ACTIVE_CONV_KEY = "assistant_active_conversation_id"

# Nombre max de lignes du tableau envoyées à l'API en une fois (au-delà,
# on tronque et on le signale — pour rester dans une taille de contexte
# raisonnable, pas pour cacher des données à l'assistant).
MAX_ROWS_IN_CONTEXT = 3000

ASSISTANT_SYSTEM_PROMPT = """Tu es l'assistant intégré de CIE Analytics, l'application de reporting \
de la Direction Marketing de la Compagnie Ivoirienne d'Électricité (CIE).

## Ton rôle
Tu as un accès complet, en contexte, à l'état actuel de la session de l'utilisateur : le tableau \
de données chargé (au format CSV, éventuellement tronqué s'il est très volumineux), la structure \
des colonnes, l'historique des étapes de préparation appliquées, et tous les résultats d'analyse \
(statistiques, tests, régressions, graphiques) déjà produits dans l'application. Utilise ces \
éléments pour :
- répondre à des questions précises sur les données et les résultats déjà calculés ;
- effectuer toi-même de nouvelles analyses statistiques (moyennes, écarts, comparaisons, \
corrélations, tendances...) directement à partir du tableau CSV fourni en contexte ;
- interpréter une pièce jointe (image : graphique, capture d'écran, tableau — ou document PDF) \
si l'utilisateur en envoie une ;
- aider à s'orienter dans les modules de l'application (Import, Préparation, Statistiques, TCD, \
Comparaisons, Tableaux, Générateur de rapport).

## Rigueur
- Base tes calculs et affirmations strictement sur les données et résultats fournis en contexte. \
Si le tableau a été tronqué (indiqué dans le contexte), précise que ton calcul porte sur \
l'échantillon fourni et non la totalité, si c'est pertinent.
- N'invente jamais de chiffre absent du contexte ou de la conversation.
- Signale les limites : effectif faible, valeurs manquantes, résultat non significatif.
- Pour toute question totalement hors sujet (sans lien avec l'application ou les données), \
réponds brièvement puis recentre la conversation sur ce périmètre.

## Ton style
Français, professionnel, concis, sans jargon non expliqué. Format Markdown pour structurer si utile.
"""


def _build_context_note() -> str:
    """Construit le contexte complet envoyé à chaque appel : structure et
    contenu du tableau courant, historique de préparation, et tous les
    résultats d'analyse déjà produits dans la session."""
    if not has_current_dataframe():
        return "Contexte : aucune donnée n'est chargée dans la session actuelle."

    df = get_current_dataframe()
    types = get_current_types()
    parts = [
        f"Source des données : {get_current_source()}",
        f"Dimensions du tableau : {df.shape[0]} lignes x {df.shape[1]} colonnes",
        "Colonnes et types détectés : " + ", ".join(f"{c} ({t})" for c, t in types.items()),
    ]

    pipeline = get_pipeline_history()
    if pipeline:
        steps = "; ".join(f"{s.get('label', s.get('kind', '?'))}" for s in pipeline)
        parts.append(f"Étapes de préparation déjà appliquées : {steps}")

    analyses = get_analysis_log()
    if analyses:
        import json
        parts.append(
            "Résultats d'analyse déjà produits dans cette session (JSON, un par ligne) :\n"
            + "\n".join(json.dumps(a, ensure_ascii=False, default=str) for a in analyses)
        )

    truncated = len(df) > MAX_ROWS_IN_CONTEXT
    df_for_context = df.head(MAX_ROWS_IN_CONTEXT) if truncated else df
    csv_text = df_for_context.to_csv(index=False)
    if truncated:
        parts.append(
            f"⚠️ Tableau tronqué aux {MAX_ROWS_IN_CONTEXT} premières lignes sur {len(df)} "
            "pour tenir dans le contexte (contenu CSV complet ci-dessous jusqu'à cette limite) :"
        )
    else:
        parts.append("Contenu intégral du tableau (CSV) :")
    parts.append(csv_text)

    return "\n\n".join(parts)


def _call_assistant(history: list[dict], attachments: list | None = None) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.gemini_configured:
        return False, "Clé API Gemini non configurée — l'assistant n'est pas disponible pour le moment."

    # Gemini utilise le rôle "model" (et non "assistant") pour les réponses IA.
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [m["content"]]}
        for m in history
    ]
    # Les pièces jointes (si fournies) sont ajoutées aux parts du tout
    # dernier message utilisateur — c'est celui auquel elles se rapportent.
    # Chaque élément est soit une image PIL, soit un dict
    # {"mime_type": "application/pdf", "data": bytes} pour un PDF —
    # les deux formats sont acceptés tels quels par le SDK Gemini.
    if attachments and contents and contents[-1]["role"] == "user":
        contents[-1]["parts"].extend(attachments)

    ok, text, model_used = call_gemini(
        contents,
        system_instruction=ASSISTANT_SYSTEM_PROMPT + "\n\n" + _build_context_note(),
        generation_config={"max_output_tokens": 4096},
    )
    if ok and model_used and model_used != DEFAULT_MODEL_CHAIN[0]:
        # Signale discrètement qu'on a basculé sur un modèle de secours,
        # utile pour comprendre une éventuelle baisse de qualité de réponse.
        text += f"\n\n*(via le modèle de secours {model_used})*"
    return ok, text


def _auto_title(first_message: str) -> str:
    text = " ".join(first_message.strip().split())
    return text[:60] + ("…" if len(text) > 60 else "")


set_page_title("💬 Assistant", "Questions en langage naturel sur vos données")

st.markdown(
    "<style>"
    ".block-container{padding-top:1rem;padding-bottom:5rem;padding-left:0.5rem;padding-right:0.5rem;max-width:100%;}"
    # Neutralise l'espacement par défaut de Streamlit (gap:22px) entre
    # éléments — même bug déjà rencontré et corrigé sur les pages
    # Préparation et Tableau de bord.
    ".block-container > [data-testid=\"stVerticalBlock\"]{gap:0 !important;}"
    "</style>",
    unsafe_allow_html=True,
)

settings = get_settings()
if not settings.gemini_configured:
    st.info(
        "L'assistant conversationnel nécessite une clé API Gemini (gratuite). "
        "Configure `GEMINI_API_KEY` dans le fichier `.env` (voir `.env.example`)."
    )
    st.stop()

user_id = st.session_state["auth_user_id"]

st.markdown(
    """
    <style>
    /* Panneau de gauche façon vraie barre latérale (comme Claude) —
       collé au bord gauche de l'application, pleine hauteur (du haut au
       bas de la zone de contenu), séparation nette par une bordure fine
       plutôt qu'une grosse ombre, sans "carte" flottante au milieu.
       Demande explicite : "ne doit pas être au milieu", "collée au coin
       gauche", "du haut en bas", "pas trop d'ombre mais séparé quand
       même". */
    .block-container{padding-left:0 !important;}
    /* Avatars des messages (🤖 assistant, 🧑 utilisateur) masqués — demande
       explicite : "je ne veux pas voir ça". Pas de data-testid dédié sur
       l'avatar lui-même (vérifié par inspection du DOM réel) — c'est
       simplement le premier <div> enfant direct de chaque stChatMessage,
       ciblé ici par position. */
    [data-testid="stChatMessage"] > div:first-child {
        display: none !important;
    }
    .st-key-cie_assistant_sidebar_group {
        background:#FAF8F5 !important;
        border:none !important;
        border-right:1px solid #E5E1DC !important;
        border-radius:0 !important;
        padding:0.9rem 0.9rem 0.9rem 1.1rem !important;
        box-shadow:none !important;
        position: fixed !important;
        left: 0 !important;
        bottom: 0 !important;
        overflow-y: auto !important;
        z-index: 100 !important;
    }
    .st-key-cie_assistant_sidebar_group p,
    .st-key-cie_assistant_sidebar_group span,
    .st-key-cie_assistant_sidebar_group label {
        color:#111827 !important;
    }
    .st-key-cie_assistant_sidebar_group hr {
        border-color:#EADFD5 !important;
    }
    /* Bouton "Nouvelle conversation" — plus d'orange, blanc/texte noir,
       avec ombre sur sa case, comme demandé. */
    .st-key-cie_assistant_sidebar_group .st-key-cie_new_conv_wrap .stButton > button {
        background:#FFFFFF !important;
        color:#111827 !important;
        font-weight:700 !important;
        border:1px solid #E5E1DC !important;
        box-shadow: 0 6px 16px rgba(0,0,0,.14), 0 2px 5px rgba(0,0,0,.08) !important;
    }
    /* Boutons de CHAQUE conversation ("salut", "yo mec"...) — spécifications
       exactes demandées : police 13px/200 (très fin), hauteur min 20px,
       padding interne 0,20rem, espacement entre lignes 0,25px. */
    .st-key-cie_assistant_conv_list .stButton > button {
        background:transparent !important;
        border:none !important;
        box-shadow:none !important;
        color:#111827 !important;
        font-size:22px !important;
        font-weight:400 !important;
        min-height:20px !important;
        padding:0.20rem !important;
        text-align:left !important;
        justify-content:flex-start !important;
    }
    .st-key-cie_assistant_conv_list .stButton > button:hover {
        background:#FFF1E5 !important;
    }
    .st-key-cie_assistant_conv_list .stButton > button * {
        color:#111827 !important;
        font-size:22px !important;
        font-weight:400 !important;
    }
    .st-key-cie_assistant_conv_list [data-testid="stHorizontalBlock"] {
        gap:0.4rem !important;
        margin-bottom:0.25px !important;
    }
    /* Croix rouge de suppression — petite, discrète (demande explicite :
       "mets juste petit une croix rouge", plus de grosse icône poubelle). */
    .st-key-cie_assistant_conv_list [data-testid="stColumn"]:last-child .stButton button {
        background:transparent !important;
        border:none !important;
        box-shadow:none !important;
        color:#DC2626 !important;
        font-size:15px !important;
        font-weight:700 !important;
        line-height:1 !important;
        min-height:18px !important;
        min-width:18px !important;
        padding:0 !important;
    }
    .st-key-cie_assistant_conv_list [data-testid="stColumn"]:last-child .stButton button p {
        color:#DC2626 !important;
    }
    .st-key-cie_assistant_conv_list [data-testid="stColumn"]:last-child .stButton button:hover {
        background:#FEE2E2 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

left_col, right_col = st.columns([1, 3])

# Panneau de gauche en position:fixed (voir CSS ci-dessus) — mesuré et
# resynchronisé en JS, seule méthode fiable dans ce projet pour "coller"
# un élément à un espace exact qui dépend d'autres éléments dynamiques
# (hauteur de la barre du haut, largeur réelle de la colonne). Demande
# explicite et répétée : "tout l'espace gauche du haut jusqu'en bas c'est
# réservé pour les conversations, tout !" — plus de simple min-height
# approximatif, positionnement exact du sommet de la page jusqu'à sa base,
# sans dépendre d'une estimation de hauteur de barre/pied de page qui
# pouvait être fausse.
st.components.v1.html(
    """
    <script>
    (function() {
        function syncSidebar() {
            const doc = window.parent.document;
            const panel = doc.querySelector('.st-key-cie_assistant_sidebar_group');
            if (!panel) return;
            const parentCol = panel.parentElement;
            const nav = doc.querySelector('.st-key-cie_topnav');
            const navBottom = nav ? nav.getBoundingClientRect().bottom : 0;
            const w = parentCol ? parentCol.getBoundingClientRect().width : 0;
            if (w > 0) panel.style.setProperty('width', w + 'px', 'important');
            panel.style.setProperty('top', navBottom + 'px', 'important');
            panel.style.setProperty('height', (window.innerHeight - navBottom) + 'px', 'important');
            // Le panneau étant en position:fixed (retiré du flux normal),
            // la barre de saisie tout en bas (son vrai conteneur :
            // stBottomBlockContainer, PAS la colonne de droite — la barre
            // de saisie vit dans un conteneur à part, collé en bas de
            // TOUTE la fenêtre) doit recevoir une marge égale à la largeur
            // du panneau, sinon elle se retrouve à moitié cachée derrière
            // lui — bug réel trouvé et confirmé visuellement (le "+" et le
            // début du texte n'étaient plus visibles).
            if (w > 0) {
                const bottomBar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
                if (bottomBar) {
                    bottomBar.style.setProperty('margin-left', w + 'px', 'important');
                    // Correction du bug précédent : ajouter une marge à
                    // gauche SANS réduire la largeur poussait tout le bloc
                    // vers la droite, faisant déborder son bord droit hors
                    // de l'écran de la largeur du panneau — le "+" et la
                    // flèche d'envoi disparaissaient, poussés hors champ.
                    // Confirmé par mesure : right=1568 pour un écran de
                    // 1400px de large.
                    bottomBar.style.setProperty('width', 'calc(100% - ' + w + 'px)', 'important');
                }
            }
        }
        syncSidebar();
        setInterval(syncSidebar, 400);
        window.parent.addEventListener('resize', syncSidebar);
    })();
    </script>
    """,
    height=0,
)

# --- Colonne gauche : historique des conversations (façon "projets") ------
# Anciennement dans st.sidebar (invisible depuis que la barre latérale est
# masquée, remplacée par le menu horizontal en haut) — déplacé ici, dans
# une vraie colonne à gauche du contenu principal, verticale comme avant.
with left_col:
    with st.container(key="cie_assistant_sidebar_group"):
        st.markdown("**💬 Conversations**")
        with st.container(key="cie_new_conv_wrap"):
            if st.button("➕ Nouvelle conversation", use_container_width=True):
                st.session_state.pop(ACTIVE_CONV_KEY, None)
                st.rerun()

        conversations = list_conversations(user_id)
        if not conversations:
            st.caption("Aucune conversation pour le moment.")
        else:
            with st.container(key="cie_assistant_conv_list"):
                for conv in conversations:
                    is_active = st.session_state.get(ACTIVE_CONV_KEY) == conv.id
                    row = st.columns([5, 1])
                    with row[0]:
                        marker = "🔒 " if conv.is_closed else ""
                        # Plus de boule verte 🟢 pour marquer la conversation
                        # active (demande explicite) — remplacée par un fond
                        # légèrement teinté sur le bouton lui-même, via une
                        # classe de conteneur dédiée par conversation.
                        with st.container(key=f"cie_conv_row_{conv.id}"):
                            if is_active:
                                st.markdown(
                                    f"<style>.st-key-cie_conv_row_{conv.id} .stButton button "
                                    "{ background:#FFF1E5 !important; border-color:#FFB380 !important; }</style>",
                                    unsafe_allow_html=True,
                                )
                            if st.button(marker + conv.title, key=f"conv_open_{conv.id}", use_container_width=True):
                                st.session_state[ACTIVE_CONV_KEY] = conv.id
                                st.rerun()
                    with row[1]:
                        if st.button("✕", key=f"conv_del_{conv.id}", help="Supprimer définitivement cette conversation"):
                            delete_conversation(conv.id, user_id)
                            if st.session_state.get(ACTIVE_CONV_KEY) == conv.id:
                                st.session_state.pop(ACTIVE_CONV_KEY, None)
                            st.rerun()

# --- Colonne droite : conversation active ------------------------------
with right_col:
    active_conv_id = st.session_state.get(ACTIVE_CONV_KEY)
    active_conv = get_conversation(active_conv_id, user_id) if active_conv_id else None

    if active_conv is None:
        history: list[dict] = []
    else:
        history = [{"role": m.role, "content": m.content} for m in list_conversation_messages(active_conv.id)]
        if active_conv.is_closed:
            st.caption("🔒 Conversation close — lecture seule.")

    for msg in history:
        with st.chat_message("user" if msg["role"] == "user" else "assistant", avatar="🧑" if msg["role"] == "user" else "🤖"):
            st.markdown(msg["content"])

    if active_conv is not None and active_conv.is_closed:
        st.info("Cette conversation est close. Clique sur **Rouvrir** ci-dessous pour continuer à discuter.")
        if st.button("🔓 Rouvrir la conversation"):
            reopen_conversation(active_conv.id, user_id)
            st.rerun()
        st.stop()

    # Bouton de clôture — déplacé ici, en bas, petit et discret (demande
    # explicite : "je ne veux pas voir le bouton en haut"). Renommé aussi :
    # "Terminer" laissait croire qu'il arrêtait la génération de réponse en
    # cours, alors qu'il clôt la conversation entière (lecture seule
    # ensuite). Une vraie interruption EN COURS de génération n'est pas
    # réalisable avec l'architecture actuelle : l'appel à Gemini
    # (_call_assistant) est un appel Python bloquant, synchrone — pendant
    # qu'il tourne, Streamlit ne peut traiter aucun clic, donc aucun
    # bouton ne peut interrompre une génération déjà lancée. Ce bouton clôt
    # seulement la conversation, une fois la réponse déjà reçue.
    if active_conv is not None and not active_conv.is_closed and history:
        _close_col = st.columns([5, 1])[1]
        with _close_col:
            if st.button("🔒 Clore", use_container_width=True, help="Clôture la conversation (lecture seule ensuite) — n'interrompt pas une réponse en cours de génération."):
                close_conversation(active_conv.id, user_id)
                st.rerun()

# Streamlit fait défiler automatiquement vers le BAS dès qu'un
# st.chat_input existe sur la page (comportement natif, pensé pour garder
# les derniers messages visibles) — bug réel trouvé et confirmé par
# inspection (l'élément stAppScrollToBottomContainer avait scrollTop=254
# même sans aucun message). Résultat : le haut de la page (barre de menu,
# "💬 Conversations") se retrouvait hors champ, ne laissant voir que le
# panneau de gauche vide, donnant l'impression d'un grand espace vide en
# haut. Corrigé ici : si la conversation est vide (rien à faire défiler
# vers), on force le retour en haut.
if not history:
    st.components.v1.html(
        """
        <script>
        (function() {
            function resetScroll() {
                const doc = window.parent.document;
                const box = doc.querySelector('[data-testid="stAppScrollToBottomContainer"]');
                if (box) box.scrollTop = 0;
            }
            resetScroll();
            setTimeout(resetScroll, 150);
            setTimeout(resetScroll, 500);
        })();
        </script>
        """,
        height=0,
    )

# --- Pièce jointe (image ou PDF, analysée par Gemini pour ce message) -----
# Intégrée directement dans la barre de saisie (bouton trombone à gauche,
# natif st.chat_input), comme dans les autres assistants IA — plus de zone
# séparée au-dessus du champ.
chat_value = st.chat_input(
    "Pose ta question à l'assistant CIE Analytics...",
    accept_file="multiple",
    file_type=["png", "jpg", "jpeg", "webp", "pdf"],
)

if chat_value:
    prompt = (chat_value.text or "").strip()
    attached_files = chat_value.files or []

    attachments: list = []
    attachment_notes: list[str] = []
    preview_images: list[Image.Image] = []
    for uf in attached_files:
        raw = uf.getvalue()
        is_pdf = (uf.type == "application/pdf") or uf.name.lower().endswith(".pdf")
        if is_pdf:
            attachments.append({"mime_type": "application/pdf", "data": raw})
            attachment_notes.append(f"📎 *(PDF joint : {uf.name})*")
        else:
            img = Image.open(io.BytesIO(raw))
            attachments.append(img)
            preview_images.append(img)
            attachment_notes.append(f"📎 *(image jointe : {uf.name})*")

    if not prompt and attachment_notes:
        prompt = "Peux-tu analyser le(s) fichier(s) joint(s) ?"
    stored_prompt = ("\n\n".join(attachment_notes) + "\n\n" + prompt) if attachment_notes else prompt

    if active_conv is None:
        active_conv = create_conversation(user_id, title=_auto_title(prompt))
        st.session_state[ACTIVE_CONV_KEY] = active_conv.id

    add_conversation_message(active_conv.id, "user", stored_prompt)
    history.append({"role": "user", "content": stored_prompt})
    with st.chat_message("user", avatar="🧑"):
        for img in preview_images:
            st.image(img, width=280)
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Réflexion en cours..."):
            ok, text = _call_assistant(history, attachments=attachments)
        if ok:
            st.markdown(text)
            add_conversation_message(active_conv.id, "assistant", text)
        else:
            st.error(text)
            st.stop()  # on garde l'erreur affichée : pas de rerun qui l'efface

    st.rerun()
