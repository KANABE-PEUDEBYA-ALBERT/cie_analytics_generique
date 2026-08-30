"""
Point d'entrée RÉEL de l'application CIE Analytics — à lancer avec :

    streamlit run run/main.py

--------------------------------------------------------------------------
POURQUOI CE FICHIER (et pas app.py à la racine) ?
--------------------------------------------------------------------------
Streamlit a un comportement historique : s'il détecte un dossier nommé
EXACTEMENT "pages" juste à côté du script lancé, il bascule automatiquement
en mode "multipage classique" et affiche TOUTES les pages de ce dossier
dans la barre latérale — y compris avant toute connexion, et même les
fichiers non utilisés (fichiers relégués depuis les versions précédentes).
Ce comportement est déclenché au niveau du framework, avant même que le
code de app.py ne s'exécute : impossible à corriger en modifiant app.py
lui-même tant qu'un dossier "pages" existe à sa racine.

C'est exactement le bug que tu as vu (menu visible avant connexion, page
"Régressions" fantôme). La solution robuste : déplacer le point d'entrée
dans un dossier qui n'a pas de "pages" à côté de lui. Ici, `run/main.py`
a pour voisin `run/screens/` (et non `run/pages/`) — le mode automatique
ne se déclenche donc jamais.

`pages/` et `app.py` à la racine du projet sont conservés pour l'historique
mais ne doivent plus être utilisés pour lancer l'application.
--------------------------------------------------------------------------
"""
from __future__ import annotations

import sys
import base64
import textwrap
from pathlib import Path

# Rend le dossier racine du projet (contenant data/, auth/, config/, stats/,
# viz/, pipeline/) importable, quel que soit l'endroit d'où Streamlit est
# lancé.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from auth.auth_utils import (
    attempt_login,
    current_role,
    current_user_label,
    ensure_bootstrap_admin,
    is_authenticated,
    self_register,
    validate_password_strength,
)
from config.settings import BASE_DIR, CIE_DARK, CIE_GREEN, CIE_ORANGE, CIE_WHITE, LOGO_PATH, ROLE_LABELS, get_settings
from config.theme import inject_custom_css

# Icône de la page (favicon de l'onglet navigateur) — le vrai logo créé
# pour l'application (éclair + barres, couleurs CIE), le même que celui
# utilisé pour l'icône de l'exécutable desktop, pour une identité visuelle
# cohérente sur les deux versions. Repli sur l'emoji si le fichier est
# absent (ne devrait jamais arriver, mais reste robuste).
_APP_ICON_PATH = BASE_DIR / "assets" / "logo_cie_analytics_icon.png"
st.set_page_config(
    page_title="CIE Analytics",
    page_icon=str(_APP_ICON_PATH) if _APP_ICON_PATH.exists() else "📊",
    layout="wide",
    initial_sidebar_state="auto",
)

# Crée un compte administrateur par défaut si la base est vide (premier lancement)
ensure_bootstrap_admin()

# --- Connexion active -------------------------------------------------------
# L'écran de connexion (mot de passe requis) est actif par défaut. Pour
# désactiver temporairement à des fins de développement local uniquement,
# mettre DISABLE_LOGIN=true dans .env — jamais en production.
import os
if os.environ.get("DISABLE_LOGIN", "false").strip().lower() in ("1", "true", "oui", "yes"):
    from auth.database import User, get_session
    if "auth_user_id" not in st.session_state:
        with get_session() as _session:
            _admin = _session.query(User).filter(User.role == "administrateur").first()
        if _admin is not None:
            st.session_state["auth_user_id"] = _admin.id
            st.session_state["auth_email"] = _admin.email
            st.session_state["auth_full_name"] = _admin.full_name
            st.session_state["auth_role"] = _admin.role
            st.session_state["auth_service"] = _admin.service

inject_custom_css(dark=False)


_FEATURES = [
    ("🧹", "Préparation guidée", "Nettoyage, fusion et transformation des données sans écrire de code."),
    ("📊", "Statistiques en clair", "Chiffres clés et écarts expliqués en phrases, pas en jargon."),
    ("🔀", "Tableaux croisés", "Croisements façon Excel, mis à jour en un clic."),
    ("🖊️", "Commentaire automatique", "Chaque graphique est interprété automatiquement."),
]


def _render_login_page() -> None:
    """Écran de connexion — seule page visible tant que personne n'est
    authentifié (voir la note en tête de fichier). Fond bleu marine brillant,
    grande image CIE à gauche, formulaire Connexion / Inscription à droite.

    Bug corrigé ici (cause de tout le texte illisible et des onglets
    invisibles dans les versions précédentes) : `st.markdown("<div "
    "class='cieFormCard'>")` suivi d'autres appels Streamlit ne les
    encapsule PAS réellement dans ce <div> — Streamlit rend chaque élément
    dans son propre conteneur, ce <div> reste un élément FRÈRE isolé, pas un
    parent. Résultat : le fond blanc ne s'appliquait à rien de réel, et le
    texte pensé pour un fond blanc (couleurs foncées) s'affichait sur le
    fond bleu marine derrière — illisible. Corrigé en utilisant
    `st.container(key=...)`, qui crée un VRAI conteneur adressable en CSS
    (classe `.st-key-<key>`)."""
    st.markdown(
        f"""
        <style>
        [data-testid="stAppViewContainer"], .stApp {{
            background: linear-gradient(120deg, #061229, #0d2a5e, #123a78, #0a1e40) !important;
            background-size: 300% 300% !important;
            animation: cieLoginShine 10s ease-in-out infinite !important;
        }}
        @keyframes cieLoginShine {{
            0%   {{ background-position: 0% 50%; }}
            50%  {{ background-position: 100% 50%; }}
            100% {{ background-position: 0% 50%; }}
        }}
        [data-testid="stHeader"] {{
            background: transparent !important;
            height: 0 !important;
            min-height: 0 !important;
        }}
        /* Les barres du haut (icônes Streamlit) et du bas doivent être sur
           la même ligne que l'image — sans ça, un grand vide sépare la
           barre du haut du contenu. On resserre le padding par défaut, et
           on retire aussi l'espace que "stHeader" réservait pour lui-même
           malgré son fond transparent (bug corrigé ici — transparent ne
           veut pas dire "hauteur nulle", la barre gardait sa place réservée
           dans la mise en page même invisible, poussant tout le reste vers
           le bas). */
        /* Bug corrigé ici (cause réelle du grand vide en haut, prouvé par
           inspection directe du DOM) : la classe ".main" que ciblait la
           règle précédente n'existe plus dans cette version de Streamlit
           — la règle ne s'appliquait donc JAMAIS, et Streamlit gardait sa
           marge par défaut (132px). Corrigé en ciblant le bon sélecteur.
           ATTENTION — piège trouvé ici : forcer "align-items:flex-start"
           sur stMain (tenté dans une version précédente) CASSAIT le
           mécanisme d'égalité de hauteur des deux cartes plus bas (mesuré
           : 425px à gauche contre 531px à droite au lieu d'être égales),
           en empêchant le calcul de hauteur de se propager correctement
           jusqu'aux colonnes. Ne JAMAIS toucher à align-items sur stMain —
           seul le padding-top est à zéro, rien d'autre ici. */
        [data-testid="stAppViewContainer"] .block-container {{
            padding-top: 0 !important;
            padding-bottom: 0.8rem !important;
            max-width: 1500px;
        }}
        /* Les deux grandes cases (présentation CIE à gauche, formulaire à
           droite) doivent avoir EXACTEMENT la même hauteur, alignées en
           haut ET en bas — pas juste une hauteur MINIMALE chacune de son
           côté (ce qui les laissait grandir indépendamment selon leur
           propre contenu, sans jamais se synchroniser). La vraie solution :
           le conteneur qui les met côte à côte (la "ligne" créée par
           st.columns) doit étirer ses deux enfants à la même hauteur —
           celle du plus grand des deux — via align-items:stretch, comme un
           vrai flexbox. Chaque colonne devient elle-même un conteneur flex
           vertical pour que "height:100%" sur la carte à l'intérieur soit
           réellement respecté (un pourcentage de hauteur ne veut rien dire
           sans un parent qui a une hauteur définie). */
        [data-testid="stHorizontalBlock"]:has(.cieHeroBox),
        [data-testid="stHorizontalBlock"]:has(.st-key-cie_login_card) {{
            align-items: stretch !important;
        }}
        /* Bug corrigé ici (cause réelle du désalignement, malgré la
           tentative précédente ci-dessus) : Streamlit insère un niveau de
           conteneur supplémentaire ("element-container") entre la colonne
           et le <div> qui contient réellement la carte. La règle
           précédente ne mettait "flex:1 1 auto" que sur le PREMIER niveau
           (stVerticalBlock) — le element-container suivant, lui, restait
           en hauteur "auto" (sa taille naturelle), ce qui coupait la
           chaîne de propagation de la hauteur : height:100% sur .cieHeroBox
           se calculait alors par rapport à ce conteneur non étiré, pas par
           rapport à la vraie hauteur disponible. Corrigé en forçant
           "display:flex; flex-direction:column; flex:1 1 auto" à TOUS les
           niveaux intermédiaires (le sélecteur générique `> div` couvre
           chaque div, à n'importe quelle profondeur, entre la colonne et
           la carte). */
        [data-testid="stHorizontalBlock"]:has(.cieHeroBox) > [data-testid="stColumn"],
        [data-testid="stHorizontalBlock"]:has(.st-key-cie_login_card) > [data-testid="stColumn"] {{
            display: flex !important;
            flex-direction: column !important;
        }}
        [data-testid="stHorizontalBlock"]:has(.cieHeroBox) > [data-testid="stColumn"] div:has(> .cieHeroBox),
        [data-testid="stHorizontalBlock"]:has(.cieHeroBox) > [data-testid="stColumn"] div:has(.cieHeroBox),
        [data-testid="stHorizontalBlock"]:has(.st-key-cie_login_card) > [data-testid="stColumn"] div:has(.st-key-cie_login_card) {{
            display: flex !important;
            flex-direction: column !important;
            flex: 1 1 auto !important;
            min-height: 0 !important;
        }}
        [data-testid="stHorizontalBlock"]:has(.cieHeroBox) > [data-testid="stColumn"] .element-container:has(.cieLoginLogoWrap),
        [data-testid="stHorizontalBlock"]:has(.st-key-cie_login_card) > [data-testid="stColumn"] .element-container:has(.st-key-cie_login_card) {{
            display: flex !important;
            flex-direction: column !important;
            flex: 1 1 auto !important;
            min-height: 0 !important;
        }}
        .cieBigTitle {{
            color:#FF9900 !important; font-size:40px !important; font-weight:900 !important; text-align:center;
            letter-spacing:.04em; margin: 0 0 .8rem;
            text-shadow: 0 2px 14px rgba(0,0,0,.5);
        }}
        .cieLoginLogoWrap {{
            display:flex; flex-direction:column; align-items:center; justify-content:center;
            height:100%; padding: 0.3rem 1rem;
        }}
        .cieLoginTitle {{
            color:#FF9900; font-size:1.5rem; font-weight:800; text-align:center; margin-top:.7rem;
            text-shadow: 0 2px 12px rgba(0,0,0,.5);
        }}
        .cieLoginSub {{
            color:#FFB84D; font-size:22px; text-align:center; max-width:28rem; margin-top:.3rem;
            line-height: 1.4;
        }}
        /* --- Bloc de présentation CIE, à gauche de l'écran de connexion —
           height:100% (pas min-height) : remplit EXACTEMENT la hauteur
           étirée par le flexbox ci-dessus, ni plus ni moins, pour que les
           deux cases finissent toujours au même niveau en bas. Le contenu
           est réparti sur toute cette hauteur (space-around, pas center
           seul) pour qu'un grand espace vide ne s'accumule pas d'un côté
           si la case s'agrandit. --- */
        .cieHeroBox {{
            background:#fff; border-radius:16px; padding:1.4rem 2.2rem;
            box-shadow: 0 12px 40px rgba(0,0,0,.35);
            display:flex; flex-direction:column; align-items:center; justify-content:space-around;
            text-align:center;
            height:100%; box-sizing:border-box;
        }}
        .cieHeroTitle {{
            color:#0a1e40; font-size:1.15rem; font-weight:800; text-transform:uppercase;
            letter-spacing:.05em; margin:0 0 .4rem;
        }}
        .cieHeroDef {{
            color:#FF9900; font-size:1.35rem; font-weight:800; margin:0 0 .9rem; line-height:1.25;
        }}
        .cieHeroImages {{
            display:flex; align-items:center; justify-content:center; gap:1.8rem;
            flex-wrap:wrap; width:100%; flex:1 1 auto;
        }}
        .cieHeroImages img {{ filter: drop-shadow(0 4px 10px rgba(0,0,0,.18)); height:auto; }}
        /* Tailles en `clamp()` (mini, préférée-liée-à-la-hauteur-de-case,
           maxi) — au lieu d'un simple pourcentage de largeur qui ne
           bougeait jamais avec la hauteur de la case : maintenant, quand
           la case s'agrandit (colonne de droite plus haute), les images
           grandissent proportionnellement avec elle, sans jamais se
           déformer (max-width + height:auto conservent les proportions
           réelles du fichier source). */
        .cieHeroMap {{ max-width: min(46%, 260px); width:46%; }}
        /* Bug corrigé ici : le bouton natif "afficher/masquer le mot de
           passe" de Streamlit utilise une icône Material Symbols dont le
           texte brut est "visibility" — si cette police échoue à charger
           (même mécanisme déjà rencontré ailleurs dans ce projet avec
           "upload_file"), ce texte anglais brut s'affiche tel quel au lieu
           d'une icône. Masqué et remplacé par un vrai symbole d'œil
           fiable (emoji, jamais dépendant d'une police externe). */
        button[aria-label="Show password"] [data-testid="stIconMaterial"],
        button[aria-label="Hide password"] [data-testid="stIconMaterial"] {{
            font-size: 0 !important;
            color: transparent !important;
        }}
        button[aria-label="Show password"] [data-testid="stIconMaterial"]::after {{
            content: "👁️";
            font-size: 16px;
            color: initial;
        }}
        button[aria-label="Hide password"] [data-testid="stIconMaterial"]::after {{
            content: "🙈";
            font-size: 16px;
            color: initial;
        }}
        .cieHeroLogo {{ max-width: min(38%, 210px); width:38%; }}

        /* --- Carte du formulaire : VRAI conteneur (st.container(key=...)),
           donc ce sélecteur s'applique bien à ce qu'il contient réellement.
           height:100% (pas min-height), même logique que la case de
           gauche — les deux sont désormais TOUJOURS identiques en hauteur,
           imposée par le flexbox parent, jamais par un chiffre en dur des
           deux côtés qui pouvait diverger. --- */
        .st-key-cie_login_card {{
            background:#fff !important; border-radius:16px; padding:1.8rem 2.2rem;
            box-shadow: 0 12px 40px rgba(0,0,0,.35);
            height:100%; box-sizing:border-box;
            display:flex !important; flex-direction:column !important; justify-content:center !important;
        }}
        .st-key-cie_login_card label,
        .st-key-cie_login_card p,
        .st-key-cie_login_card .stCaption,
        .st-key-cie_login_card span {{
            color:#B85C00 !important;
        }}
        .st-key-cie_login_card h3 {{ color:#FF9900 !important; }}
        /* Texte du formulaire agrandi et plus gras — demande explicite,
           "pas trop visible" avant. */
        .st-key-cie_login_card label {{
            font-size:1.05rem !important; font-weight:700 !important;
        }}
        .st-key-cie_login_card input {{
            font-size:1.05rem !important;
        }}
        .st-key-cie_login_card .stButton > button,
        .st-key-cie_login_card .stFormSubmitButton > button {{
            font-size:1.15rem !important; font-weight:800 !important;
        }}

        /* Onglets "Se connecter" / "S'inscrire" — CSS globale (le bug ci-
           dessus rendait tout sélecteur scopé sous .cieFormCard inopérant,
           donc les onglets s'affichaient dans le style Streamlit par défaut
           — gris clair sur fond blanc — invisibles une fois relookés sur
           fond sombre). Couleur forte et permanente, quel que soit l'état
           actif/inactif : plus jamais un onglet qui "disparaît" au clic. */
        [data-baseweb="tab-list"] {{ gap: 0.75rem; }}
        [data-baseweb="tab"] {{
            color: #B85C00 !important;
            font-weight: 700 !important;
            font-size: 1.02rem !important;
            opacity: 1 !important;
        }}
        [data-baseweb="tab"] p {{ color: inherit !important; }}
        [data-baseweb="tab"][aria-selected="true"] {{
            color: #FF9900 !important;
        }}
        [data-baseweb="tab"][aria-selected="true"] p {{ color: #FF9900 !important; }}
        [data-baseweb="tab-highlight"] {{ background-color: #FF9900 !important; }}
        [data-baseweb="tab-border"] {{ background-color: rgba(255,153,0,.25) !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='cieBigTitle'>COMPAGNIE IVOIRIENNE D'ÉLECTRICITÉ</div>", unsafe_allow_html=True)

    left, right = st.columns([1.1, 1], gap="large")

    with left:
        # @st.cache_data : ces deux images (~380 Ko à elles deux) étaient
        # relues du disque ET ré-encodées en base64 à CHAQUE exécution du
        # script (Streamlit relance tout le script à chaque interaction,
        # y compris un simple "Se connecter" raté) — un vrai gaspillage
        # répété pour un résultat qui ne change jamais. Mis en cache : lu
        # et encodé une seule fois, réutilisé ensuite instantanément.
        @st.cache_data
        def _load_login_images_b64() -> tuple[str, str]:
            _map_path = Path(__file__).resolve().parent.parent / "assets" / "map_cote_ivoire.png"
            _logo_path = LOGO_PATH
            _map_b64 = base64.b64encode(_map_path.read_bytes()).decode() if _map_path.exists() else ""
            _logo_b64 = base64.b64encode(_logo_path.read_bytes()).decode() if _logo_path.exists() else ""
            return _map_b64, _logo_b64

        _map_b64, _logo_b64 = _load_login_images_b64()
        # Balises pré-calculées SÉPARÉMENT du bloc HTML ci-dessous : une
        # f-string imbriquée dans une autre f-string avec le même caractère
        # de guillemet ne compile qu'à partir de Python 3.12 (PEP 701).
        # Streamlit Cloud tourne en général sur une version antérieure —
        # c'était la cause de l'erreur de démarrage, invisible en local car
        # cet environnement de développement est en 3.12. Corrigé en sortant
        # les f-strings imbriquées.
        _map_img_tag = f"<img class='cieHeroMap' src='data:image/png;base64,{_map_b64}' />" if _map_b64 else ""
        _logo_img_tag = f"<img class='cieHeroLogo' src='data:image/png;base64,{_logo_b64}' />" if _logo_b64 else ""
        # UN SEUL bloc HTML bien formé pour toute la carte gauche — avant,
        # le titre "CIE Analytics" et un div d'habillage ("cieLoginLogoWrap")
        # étaient des appels st.markdown SÉPARÉS, rendus comme des éléments
        # FRÈRES du tout premier <div>, jamais réellement enfants de
        # .cieHeroBox — d'où le titre visuellement "décalé", en dehors de
        # la carte. Une balise </div> orpheline traînait même en trop,
        # sans la moindre ouverture correspondante. Tout est maintenant
        # imbriqué correctement, dans le bon ordre, en une seule fois.
        st.markdown(
            textwrap.dedent(f"""\
            <div class='cieHeroBox'>
                <p class='cieHeroTitle'>Un acteur historique de l'énergie ivoirienne</p>
                <p class='cieHeroDef'>Compagnie Ivoirienne d'Électricité</p>
                <div class='cieHeroImages'>
                    {_map_img_tag}
                    {_logo_img_tag}
                </div>
                <div class='cieLoginTitle'>CIE Analytics</div>
            </div>
            """),
            unsafe_allow_html=True,
        )

    with right:
        # st.container(key=...) : VRAI conteneur adressable en CSS via
        # .st-key-cie_login_card (voir le <style> ci-dessus) — remplace
        # l'ancien <div> injecté par st.markdown, qui n'enveloppait rien
        # réellement.
        with st.container(key="cie_login_card"):
            st.markdown(
                "<p style='text-align:center;font-weight:700;color:#FF9900;letter-spacing:0.03em;"
                "text-transform:uppercase;font-size:22px;margin-bottom:0;'>🔒 Accès réservé</p>",
                unsafe_allow_html=True,
            )

            tab_login, tab_register = st.tabs(["Se connecter", "S'inscrire"])

            with tab_login:
                with st.form("login_form"):
                    email = st.text_input("Email professionnel", placeholder="prenom.nom@cie.ci")
                    password = st.text_input("Mot de passe", type="password", placeholder="••••••••")
                    submitted = st.form_submit_button("Se connecter", use_container_width=True, type="primary")
                if submitted:
                    ok, message = attempt_login(email, password)
                    if ok:
                        st.rerun()
                    else:
                        st.error(message)

            with tab_register:
                # Formulaire d'inscription : identique au formulaire de
                # connexion — juste email et mot de passe, rien d'autre
                # (demande explicite : plus de nom, service/direction, ni
                # confirmation du mot de passe, ni texte de condition).
                with st.form("register_form"):
                    r_email = st.text_input("Email professionnel", placeholder="prenom.nom@cie.ci", key="r_email")
                    r_password = st.text_input("Mot de passe", type="password", key="r_pwd")
                    r_submitted = st.form_submit_button("S'inscrire", use_container_width=True)
                if r_submitted:
                    strong, pwd_message = validate_password_strength(r_password)
                    if not strong:
                        st.error(pwd_message)
                    else:
                        ok, message = self_register(r_email, r_email.split("@")[0], r_password, "")
                        if ok:
                            st.success(message)
                        else:
                            st.error(message)

    # Égalité de hauteur des deux cartes forcée en JAVASCRIPT, pas en CSS —
    # bug corrigé ici : le mécanisme flexbox (align-items:stretch en
    # cascade) s'est révélé trop fragile face aux particularités internes
    # du DOM généré par Streamlit (constaté : les deux cartes restaient
    # visiblement de tailles différentes malgré un CSS pourtant complet et
    # déjà testé avec succès une fois — signe que ce DOM peut varier d'un
    # rendu à l'autre). Solution robuste et déterministe : mesurer les deux
    # cartes réellement affichées, puis fixer explicitlement la plus petite
    # à la hauteur de la plus grande, en pixels — aucune ambiguïté flexbox
    # possible. Réagit aussi au redimensionnement de la fenêtre.
    st.components.v1.html(
        """
        <script>
        (function() {
            function syncHeights() {
                const doc = window.parent.document;
                const hero = doc.querySelector('.cieHeroBox');
                const card = doc.querySelector('.st-key-cie_login_card');
                if (!hero || !card) return;
                hero.style.setProperty('height', 'auto', 'important');
                card.style.setProperty('height', 'auto', 'important');
                const heroH = hero.getBoundingClientRect().height;
                const cardH = card.getBoundingClientRect().height;
                const maxH = Math.max(heroH, cardH);
                hero.style.setProperty('height', maxH + 'px', 'important');
                card.style.setProperty('height', maxH + 'px', 'important');
            }
            // Taille du titre "COMPAGNIE IVOIRIENNE D'ÉLECTRICITÉ" forcée en
            // JS elle aussi — bug corrigé ici : ni la règle CSS externe (même
            // avec !important) ni le style en ligne dans le HTML ne
            // s'appliquaient (Streamlit retire l'attribut style="" injecté
            // par st.markdown pour des raisons de sécurité, et une couche de
            // cascade CSS interne à Streamlit semble aussi neutraliser les
            // règles externes). Seule une modification directe du style via
            // JavaScript, après coup, contourne les deux problèmes.
            function syncTitleSize() {
                const doc = window.parent.document;
                const title = doc.querySelector('.cieBigTitle');
                if (!title) return;
                title.style.setProperty('font-size', '40px', 'important');
            }
            // Icône œil du champ mot de passe forcée en JS elle aussi, en
            // sécurité — au cas où le CSS ci-dessus soit contourné comme
            // ça a déjà été le cas pour le titre dans ce même fichier.
            function fixPasswordEyeIcon() {
                const doc = window.parent.document;
                doc.querySelectorAll('[data-testid="stIconMaterial"]').forEach(function(el) {
                    const txt = (el.textContent || '').trim();
                    if (txt === 'visibility') {
                        el.textContent = '👁️';
                        el.style.setProperty('font-size', '16px', 'important');
                    } else if (txt === 'visibility_off') {
                        el.textContent = '🙈';
                        el.style.setProperty('font-size', '16px', 'important');
                    }
                });
            }
            syncHeights();
            syncTitleSize();
            fixPasswordEyeIcon();
            setTimeout(syncHeights, 300);
            setTimeout(syncTitleSize, 300);
            setTimeout(fixPasswordEyeIcon, 300);
            setTimeout(syncHeights, 800);
            setTimeout(syncTitleSize, 800);
            setTimeout(fixPasswordEyeIcon, 800);
            window.parent.addEventListener('resize', syncHeights);
            const target = window.parent.document.body;
            new MutationObserver(function() { syncHeights(); syncTitleSize(); fixPasswordEyeIcon(); }).observe(target, {childList: true, subtree: true});
        })();
        </script>
        """,
        height=0,
    )


if not is_authenticated():
    # position="hidden" : sans ça, Streamlit affiche quand même un menu de
    # navigation dans la barre latérale contenant l'unique entrée "Connexion"
    # (c'était "l'onglet de connexion" visible avant identification). Avec
    # une seule page et position="hidden", aucun menu n'est rendu du tout.
    st.markdown(
        "<style>[data-testid='stSidebar']{display:none;}</style>",
        unsafe_allow_html=True,
    )
    st.navigation(
        [st.Page(_render_login_page, title="Connexion", icon="🔒")],
        position="hidden",
    ).run()
    st.stop()

# --- Barre latérale CIE -----------------------------------------------------
# La navigation native de Streamlit est masquée et remplacée par des
# `st.page_link` : cela permet de reproduire fidèlement la maquette (fond
# crème, titres, icônes, état actif) tout en gardant le vrai routage
# multipage de Streamlit.
st.markdown(
    """
    <style>
    /* Sidebar façon maquette CIE */
    section[data-testid="stSidebar"] {
        background: #FFE998 !important;
        border-right: 1px solid #E9D6C3 !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 0.3rem !important;
    }
    .cie-sidebar-title {
        display:flex;
        align-items:center;
        gap:12px;
        margin: 0.15rem 0 1.05rem 0.1rem;
    }
    .cie-menu-icon {
        width:46px;
        height:46px;
        border-radius:9px;
        display:flex;
        align-items:center;
        justify-content:center;
        background:#F7941D;
        color:white !important;
        font-size:27px;
        font-weight:800;
        /* Ombre resserrée et plus opaque — l'ancienne (large rayon, faible
           opacité) donnait un effet flou/délavé, demande explicite d'un
           orange qui "fait la différence", net et contrasté. */
        box-shadow:0 4px 10px rgba(0,0,0,.28);
        border:1px solid #D9760A;
    }
    .cie-menu-title {
        color:#111827 !important;
        font-size:34px;
        line-height:1;
        font-weight:800;
    }
    .cie-sidebar-section {
        margin: 0.15rem 0 0.65rem 0;
    }
    .cie-sidebar-logo {
        display:flex;
        justify-content:center;
        /* Même écart qu'entre les liens du menu (0,50px, réglé plus tôt) —
           avant, un grand espace (1.1rem) séparait le logo du dernier lien
           (Administration), le poussant beaucoup trop bas. */
        margin: 0.50px 0 0.7rem;
    }
    /* Élimine tout espace résiduel que Streamlit pourrait laisser autour du
       composant JS invisible (indicateur de page active) juste au-dessus
       du logo, même avec height=0. */
    section[data-testid="stSidebar"] iframe {
        margin:0 !important;
        display:block !important;
    }
    section[data-testid="stSidebar"] [data-testid="stCustomComponentV1"] {
        margin:0 !important;
    }
    .cie-sidebar-profile {
        margin-top:0.1rem;
        padding:0 0.2rem;
    }
    .cie-sidebar-profile-name {
        color:#111827 !important;
        font-size:22px;
        font-weight:700;
        margin:0;
    }
    .cie-sidebar-divider {
        height:1px;
        background:#EADFD5;
        margin:0.65rem 0 0.8rem;
    }
    /* Liens créés avec st.page_link — liste simple, sans case blanche
       autour de l'ensemble ; seul l'élément actif est mis en avant, en
       occupant TOUTE la largeur disponible avec un fond orange vif
       (et non plus une teinte pâle proche du blanc), comme demandé. */
    .st-key-cie_nav_group {
        padding:0 !important;
        margin:0 0 1rem 0 !important;
        border:none !important;
        box-shadow:none !important;
        background:transparent !important;
    }
    .st-key-cie_nav_group [data-testid="stPageLink"] {
        margin:0 0 0.50px 0 !important;
        width:100% !important;
    }
    .st-key-cie_nav_group [data-testid="stPageLink"] a {
        display:flex !important;
        width:100% !important;
        min-height:30px !important;
        padding:0.2rem 1rem !important;
        border:none !important;
        border-radius:10px !important;
        background:transparent !important;
        color:#111827 !important;
        font-size:24px !important;
        font-weight:600 !important;
        transition:all .15s ease;
        box-shadow:none !important;
    }
    .st-key-cie_nav_group [data-testid="stPageLink"] a p,
    .st-key-cie_nav_group [data-testid="stPageLink"] a span {
        font-size:24px !important;
        font-weight:600 !important;
    }
    .st-key-cie_nav_group [data-testid="stPageLink"] a:hover {
        background:#FFF1E5 !important;
        color:#FF6B00 !important;
    }
    .st-key-cie_nav_group [data-testid="stPageLink"] a[aria-current="page"] {
        background:#FFF7EF !important;
        color:#B85C00 !important;
        font-weight:800 !important;
        border:1.5px solid #FF6B00 !important;
        border-radius:10px !important;
        box-shadow:none !important;
    }
    .st-key-cie_nav_group [data-testid="stPageLink"] a span {
        color:inherit !important;
    }
    .st-key-cie_nav_group [data-testid="stPageLink"] svg {
        width:22px !important;
        height:22px !important;
        stroke-width:2px !important;
        color:inherit !important;
    }
    /* Bouton de déconnexion : texte noir, explicite et prioritaire sur
       toute règle générale de theme.py (spécificité + !important). Plus de
       rectangle/contour autour — juste le texte, comme demandé. */
    section[data-testid="stSidebar"] .st-key-cie_logout_wrap .stButton > button,
    section[data-testid="stSidebar"] .st-key-cie_logout_wrap .stButton > button * {
        background:transparent !important;
        color:#000000 !important;
        border:none !important;
        box-shadow:none !important;
        min-height:36px !important;
        font-size:22px !important;
        font-weight:600 !important;
        justify-content:flex-start !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_logout_wrap .stButton > button:hover {
        background:#FFF1E5 !important;
        border-radius:8px !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_toggle > button {
        background:transparent !important;
        border:none !important;
        color:#111827 !important;
        box-shadow:none !important;
        justify-content:flex-start !important;
        padding:0.35rem 0.2rem !important;
        font-size:22px !important;
        font-weight:500 !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_toggle > button:hover {
        color:#A96A38 !important;
        background:transparent !important;
    }
    /* Panneau "Personnaliser le menu" : UN SEUL contour propre sur le
       conteneur — avant, le contour natif du conteneur ET celui du champ
       multiselect à l'intérieur s'empilaient, donnant l'impression de
       plusieurs bordures imbriquées. */
    section[data-testid="stSidebar"] .st-key-cie_customize_panel {
        border:1px solid #E5DFD6 !important;
        border-radius:10px !important;
        padding:0.6rem 0.7rem !important;
        background:#FFFFFF !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-baseweb="select"] > div {
        border:none !important;
        box-shadow:none !important;
        background:transparent !important;
    }
    /* Le sélecteur de personnalisation doit rester lisible sur fond crème. */
    /* Nouvelle présentation des rubriques : cases à cocher simples,
       comme une liste de questionnaire. Aucun contour, aucune pastille,
       aucun fond coloré. Décocher retire simplement la rubrique. */
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-testid="stCheckbox"] {
        margin:0 !important;
        padding:2px 0 !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-testid="stCheckbox"] label {
        color:#111111 !important;
        font-size:22px !important;
        font-weight:500 !important;
        background:transparent !important;
        border:none !important;
        box-shadow:none !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-testid="stCheckbox"] label span {
        color:#111111 !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-testid="stCheckbox"] input {
        accent-color:#FF9A1F !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-testid="stCheckbox"] [data-testid="stWidgetLabel"] {
        color:#111111 !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-testid="stMultiSelect"] *,
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-baseweb="select"] *,
    section[data-testid="stSidebar"] .st-key-cie_customize_panel label,
    section[data-testid="stSidebar"] .st-key-cie_customize_panel p {
        color:#111827 !important;
    }
    /* Pastilles des menus cochés, DANS CE PANNEAU précis — bug corrigé ici :
       la règle transparente ci-dessus (sur [data-baseweb="select"] > div)
       est injectée APRÈS le correctif global du même problème dans
       theme.py, donc elle l'emportait dans la bataille de priorité CSS et
       laissait resurgir le rouge par défaut de BaseWeb sur les pastilles.
       Règle spécifique à ce panneau, la plus prioritaire de toutes :
       aucune couleur, juste une ombre légère et du texte noir, comme
       demandé. */
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-baseweb="tag"] {
        background:transparent !important;
        background-color:transparent !important;
        border:none !important;
        box-shadow:none !important;
        padding-left:0 !important;
        padding-right:0 !important;
    }
    section[data-testid="stSidebar"] .st-key-cie_customize_panel [data-baseweb="tag"] * {
        background:transparent !important;
        color:#000000 !important;
        fill:#000000 !important;
    }
    /* BaseWeb peut rendre la pastille comme div, span ou élément interne.
       On neutralise donc TOUT élément portant data-baseweb="tag" :
       aucun rouge, aucun fond coloré, uniquement du texte noir. */
    section[data-testid="stSidebar"] [data-baseweb="tag"],
    section[data-testid="stSidebar"] [data-baseweb="tag"] *,
    [data-testid="stMultiSelect"] [data-baseweb="tag"],
    [data-testid="stMultiSelect"] [data-baseweb="tag"] * {
        background:transparent !important;
        background-color:transparent !important;
        border-color:transparent !important;
        box-shadow:none !important;
        color:#000000 !important;
        fill:#000000 !important;
    }
    section[data-testid="stSidebar"] {
        overflow-y:auto !important;
        overflow-x:hidden !important;
        max-height:100vh !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Navigation dynamique selon le rôle, avec menus personnalisables ------
role = current_role()

_OPTIONAL_PAGE_DEFS = [
    # --- Pages désactivées (mode "questionnaire uniquement") -------------
    # Ne concernent pas le questionnaire de satisfaction CIE — commentées,
    # pas supprimées, pour pouvoir les réactiver facilement plus tard en
    # retirant simplement le "#" au début de chaque ligne concernée.
    # ("screens/2_Import.py", "Import de données", "📥"),
    
    # ("screens/4_Statistiques.py", "Statistiques descriptives", "📊"),
    # ("screens/7_Visualisation.py", "Tableaux", "📋"),
    ("screens/11_Tableau_de_Bord.py", "Tableau de bord", "📈"),
    # ("screens/5_TCD.py", "Tableaux croisés dynamiques (TCD)", "🔢"),
    ("screens/12_Rapport_Retour_Clients.py", "Générateur de rapport", "📄"),
    # ("screens/6_Comparaisons.py", "Comparaisons & tendances", "📉"),
    ("screens/10_Assistant.py", "Assistant", "💬"),
]
_ALL_OPTIONAL_TITLES = [t for _, t, _ in _OPTIONAL_PAGE_DEFS]
if role == "administrateur":
    _ALL_OPTIONAL_TITLES.append("Administration")
# "Aide" toujours en tout dernier, après Administration — nouveau menu qui
# reprend l'ancien contenu explicatif de la page Accueil (déplacé pour
# alléger cette dernière).
_ALL_OPTIONAL_TITLES.append("Aide")

_VISIBLE_PAGES_KEY = "visible_menu_titles"
_DEFAULT_VISIBLE_TITLES = [
    "Accueil",
    "Tableau de bord",
    "Générateur de rapport",
    "Assistant",
]
# "Personnaliser le menu" étant désactivé (voir plus bas), les rubriques
# restantes sont toujours toutes affichées — plus de case à cocher pour
# les masquer, il n'y a de toute façon plus que le strict nécessaire au
# questionnaire.
st.session_state[_VISIBLE_PAGES_KEY] = list(_ALL_OPTIONAL_TITLES)

# Nettoyage du choix si le rôle change.
st.session_state[_VISIBLE_PAGES_KEY] = [
    x for x in st.session_state[_VISIBLE_PAGES_KEY]
    if x in _ALL_OPTIONAL_TITLES
]

# Création des vrais objets Page. Ils servent à la fois au routeur caché
# et aux liens visibles dans notre menu.
_page_map = {
    # L'ancienne page Préparation est désormais la vraie page d'Accueil.
    "Accueil": st.Page("screens/3_Preparation.py", title="Accueil", icon="🏠", default=True)
}
for _path, _title, _icon in _OPTIONAL_PAGE_DEFS:
    _page_map[_title] = st.Page(_path, title=_title, icon=_icon)
if role == "administrateur":
    _page_map["Administration"] = st.Page(
        "screens/9_Administration.py", title="Administration", icon="⚙"
    )
_page_map["Aide"] = st.Page("screens/13_Aide.py", title="Aide", icon="❓")

st.markdown(
    """
    <style>
    /* Barre latérale entièrement masquée — demande du responsable :
       "menu horizontal en haut, plus de menu vertical". */
    section[data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }

    /* Barre native de Streamlit (contient "Deploy" et le menu ⋮) rendue
       transparente et fine — sans ça, elle laisse un espace vide au-dessus
       de notre propre barre, et les deux ne sont pas sur la même ligne
       comme demandé ("même ligne que share en haut"). */
    [data-testid="stHeader"] {
        background: transparent !important;
        height: 52px !important;
        min-height: 52px !important;
    }
    [data-testid="stAppViewContainer"] .block-container {
        padding-top: 52px !important;
    }

    /* --- Barre horizontale FIXE, fond orange plein (demande explicite :
       "au début il y avait une partie orange en haut", "le fond en
       orange", "jamais on doit les défiler, ils sont fixes et en haut,
       même ligne que share en haut"). position:fixed + top:0 = ne défile
       jamais avec le contenu, reste toujours visible, alignée avec la
       barre native de Streamlit au-dessus (même bande du haut). */
    .st-key-cie_topnav {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        right: 0 !important;
        z-index: 999999 !important;
        background: #FF6B00 !important;
        border-bottom: 1px solid #D9760A !important;
        box-shadow: 0 2px 10px rgba(0,0,0,.15) !important;
        padding: 14px 16px !important;
        margin: 0 !important;
        display: flex !important;
        align-items: stretch !important;
        justify-content: center !important;
        gap: 10px !important;
        min-height: 96px !important;
        overflow: hidden !important;
    }
    .st-key-cie_topnav [data-testid="stHorizontalBlock"] {
        gap: 10px !important;
        align-items: stretch !important;
        flex-wrap: nowrap !important;
        width: 100% !important;
    }
    /* Les 6 cases se répartissent sur TOUTE la largeur et TOUTE la hauteur
       de la barre orange (demande explicite : "doivent occuper pleinement
       l'espace orange"), au lieu d'être regroupées au centre avec du vide
       autour. flex:1 = chaque case prend une part égale de la largeur. */
    .st-key-cie_topnav [data-testid="stColumn"] {
        width: auto !important;
        flex: 1 1 auto !important;
        padding: 0 !important;
        display: flex !important;
    }
    .st-key-cie_topnav [data-testid="stPageLink"] {
        margin: 0 !important;
        width: 100% !important;
    }
    /* Chaque lien = une carte avec ombre, qui remplit toute la hauteur de
       la barre. Taille de police ajustée automatiquement en JS pour tenir
       sur une seule ligne (voir script plus bas) — la valeur ci-dessous
       n'est qu'un point de départ. */
    .st-key-cie_topnav [data-testid="stPageLink"] a {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        height: 100% !important;
        width: 100% !important;
        padding: 6px 10px !important;
        border: none !important;
        border-radius: 10px !important;
        background: #FFFFFF !important;
        box-shadow: 0 3px 8px rgba(0,0,0,.22) !important;
        color: #B85C00 !important;
        font-size: 22px !important;
        font-weight: 800 !important;
        text-transform: uppercase !important;
        white-space: nowrap !important;
    }
    .st-key-cie_topnav [data-testid="stPageLink"] a:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,.3) !important;
    }
    .st-key-cie_topnav [data-testid="stPageLink"] a span {
        color: inherit !important;
    }
    .st-key-cie_topnav [data-testid="stPageLink"] svg {
        width: 22px !important;
        height: 22px !important;
        color: inherit !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="cie_topnav"):
    # 6 menus au total, plus de "Se déconnecter" ici (déplacé sur la page
    # Accueil) — demande explicite.
    _nav_items = [("Accueil", "🏠")] + [
        (t, _page_map[t].icon) for t in _ALL_OPTIONAL_TITLES
        if t in st.session_state[_VISIBLE_PAGES_KEY]
    ]
    _cols = st.columns(len(_nav_items))
    for _col, (_title, _icon) in zip(_cols, _nav_items):
        with _col:
            st.page_link(_page_map[_title], label=_title, icon=_icon)

# Indicateur de page active — même mécanisme robuste que la version
# verticale précédente (vérification continue de l'URL réelle, pas
# d'aria-current qui ne se déclenchait pas de façon fiable), adapté à la
# nouvelle case ".st-key-cie_topnav".
st.components.v1.html(
    """
    <script>
    (function() {
        function applyActivePage() {
            const doc = window.parent.document;
            const path = window.parent.location.pathname.replace(/\\/$/, '').toLowerCase();
            const group = doc.querySelector('.st-key-cie_topnav');
            if (!group) return;
            const links = group.querySelectorAll('[data-testid="stPageLink"] a');
            // Cherche d'abord si un lien AUTRE qu'Accueil correspond
            // exactement au chemin actuel — plus robuste que de supposer que
            // "page racine" veut toujours dire chemin "" ou "/" (ça peut être
            // différent selon comment l'application est déployée : sous-
            // chemin, hébergement particulier...). Si aucun autre lien ne
            // correspond, c'est qu'on est sur Accueil (la page par défaut,
            // celle qui n'a pas de segment propre dans l'URL) — bug réel
            // trouvé : l'ancienne version supposait à tort que le chemin
            // racine valait toujours exactement "" ou "/", ce qui ne
            // fonctionnait pas dans tous les contextes de déploiement.
            let matchedHref = null;
            links.forEach(function(a) {
                const href = (a.getAttribute('href') || '').replace(/\\/$/, '').toLowerCase();
                if (href === '') return; // Accueil, examiné après
                // path === '' (chemin racine) : toute chaîne "se termine
                // par" une chaîne vide, donc href.endsWith(path) serait
                // TOUJOURS vrai ici par accident — condition explicite pour
                // exclure ce cas, sinon n'importe quel lien "gagnait" à tort
                // dès qu'on était sur Accueil (bug réel trouvé en testant :
                // plus aucun lien, pas même Accueil, ne s'allumait jamais).
                const matches = href === path ||
                    (path !== '' && path.endsWith(href)) ||
                    (path !== '' && href.endsWith(path));
                if (matches) matchedHref = href;
            });
            links.forEach(function(a) {
                const href = (a.getAttribute('href') || '').replace(/\\/$/, '').toLowerCase();
                const isAccueil = href === '';
                const isCurrent = isAccueil ? matchedHref === null : (href === matchedHref);
                if (isCurrent) {
                    // Orange pastel, demande explicite : "#ffe998".
                    a.style.setProperty('background', '#FFE998', 'important');
                    a.style.setProperty('color', '#7A4B00', 'important');
                } else {
                    a.style.removeProperty('background');
                    a.style.removeProperty('color');
                }
            });
        }
        // La barre est en position:fixed (ne défile jamais) — le contenu en
        // dessous reçoit toujours exactement sa hauteur réelle en
        // padding-top, ni plus (espace vide) ni moins (contenu caché).
        function syncNavPadding() {
            const doc = window.parent.document;
            const nav = doc.querySelector('.st-key-cie_topnav');
            const bc = doc.querySelector('.block-container');
            if (!nav || !bc) return;
            const h = nav.getBoundingClientRect().height;
            if (h > 0) {
                bc.style.setProperty('padding-top', h + 'px', 'important');
            }
        }
        // Ajuste la taille du texte des cartes pour qu'elles tiennent
        // TOUJOURS sur une seule ligne (demande explicite : "occupent
        // seulement une seule ligne pas de retour à la ligne", "mets leur
        // taille en fonction de l'espace") — réduit progressivement la
        // police jusqu'à ce que le total tienne dans la largeur de la
        // barre, sans jamais forcer un retour à la ligne.
        function fitNavOneLine() {
            const doc = window.parent.document;
            const nav = doc.querySelector('.st-key-cie_topnav');
            if (!nav) return;
            const links = nav.querySelectorAll('[data-testid="stPageLink"] a');
            if (links.length === 0) return;
            const row = nav.querySelector('[data-testid="stHorizontalBlock"]');
            if (!row) return;
            // Correctif : les colonnes respectent maintenant leur largeur de
            // contenu minimale (plus de min-width:0, qui provoquait un
            // texte tronqué net sans jamais déclencher de détection). Du
            // coup, si le total ne tient pas, c'est la LIGNE entière qui
            // déborde réellement de la barre — comparaison fiable.
            let size = 22;
            links.forEach(function(a) { a.style.setProperty('font-size', size + 'px', 'important'); });
            let guard = 0;
            while (row.scrollWidth > nav.clientWidth - 32 && size > 9 && guard < 30) {
                size -= 1;
                links.forEach(function(a) { a.style.setProperty('font-size', size + 'px', 'important'); });
                guard += 1;
            }
        }
        // Icônes Material qui échouent à charger et s'affichent en texte
        // brut au lieu du symbole ("visibility", "expand_more"...) — même
        // bug déjà rencontré et corrigé sur la page de connexion, mais ce
        // correctif n'était appliqué QUE là-bas, jamais sur les pages
        // internes une fois connecté (ex: "visibilité" affiché en toutes
        // lettres dans le champ mot de passe d'Administration, "expand_more"
        // affiché à la place de la flèche du popover "Réinitialiser mot de
        // passe"). Étendu ici pour s'appliquer partout, sur toutes les
        // pages connectées.
        function fixBrokenMaterialIcons() {
            const doc = window.parent.document;
            doc.querySelectorAll('[data-testid="stIconMaterial"]').forEach(function(el) {
                const txt = (el.textContent || '').trim();
                if (txt === 'visibility') {
                    el.textContent = '👁️';
                    el.style.setProperty('font-size', '16px', 'important');
                } else if (txt === 'visibility_off') {
                    el.textContent = '🙈';
                    el.style.setProperty('font-size', '16px', 'important');
                } else if (txt === 'expand_more') {
                    el.textContent = '⌄';
                } else if (txt === 'expand_less') {
                    el.textContent = '⌃';
                }
            });
        }
        applyActivePage();
        syncNavPadding();
        fitNavOneLine();
        fixBrokenMaterialIcons();
        setInterval(function() { applyActivePage(); syncNavPadding(); fitNavOneLine(); fixBrokenMaterialIcons(); }, 500);
        window.parent.addEventListener('resize', fitNavOneLine);
    })();
    </script>
    """,
    height=0,
)


settings = get_settings()
if not settings.gemini_configured:
    st.caption("ℹ️ Commentaires IA (Gemini) désactivés — clé API non configurée.")

# Navigation réelle, mais rendue invisible : les page_link ci-dessus pilotent
# exactement le même routeur Streamlit.
_navigation = st.navigation(list(_page_map.values()), position="hidden")
_navigation.run()

