"""
Interface Streamlit du Générateur de rapport (PDF/Word/PowerPoint) —
factorisée ici pour être appelée depuis DEUX endroits sans dupliquer le
code : la page dédiée « 🗞️ Générateur de rapport » ET le bas de la page
« 📊 Tableau de bord ».

Flux AGENCE PAR AGENCE (et non plus "toutes les agences d'un coup avec un
seul réglage global") : le Tableau de bord ne configure jamais qu'UNE seule
agence à la fois (celle actuellement filtrée) — types de graphique,
commentaires, résumé des verbatims. Pour que chaque agence du rapport final
puisse avoir SES PROPRES types de graphique (ex : camembert pour l'une,
anneau pour l'autre), on ACCUMULE les agences une par une :

    1. Configure le Tableau de bord pour l'agence A (type de graphique,
       commentaires, verbatims résumés).
    2. Reviens ici, choisis « A » dans la liste, clique « ➕ Ajouter ».
    3. Retourne au Tableau de bord, filtre sur l'agence B, configure-la
       différemment.
    4. Reviens ici, choisis « B », clique « ➕ Ajouter » — la progression
       passe à 2 agences.
    5. Répète pour chaque agence, puis génère UN SEUL fichier final qui les
       contient toutes, chacune avec sa configuration propre.

`key_prefix` distingue les clés de widgets/session_state d'un appel à
l'autre (page dédiée + bas du Tableau de bord) pour éviter toute collision
de clé Streamlit.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

from config.settings import get_settings
from data.state import is_questionnaire_data
from viz.comments import generate_fallback_comment, generate_statistician_comment, strip_emoji_for_reports, summarize_agency_verbatims, summarize_generic_verbatims
from viz.report_builder import (
    build_agency_report_pdf, build_agency_report_pptx, build_agency_report_word,
    build_generic_report_pdf, build_generic_report_word,
    prerender_agency_page_images,
)
from viz.report_charts import CHART_ID_TO_TITLE, build_agency_full_charts, compute_agency_kpis

KPI_CHOICES = {
    "nbre_repondant": "Nombre de répondants",
    "taux_reponse": "Taux de réponse",
    "taux_satisfaction": "Taux de satisfaction",
    "taux_insatisfaction": "Taux d'insatisfaction",
    "taux_resolution": "Taux de résolution",
    # Remplacement demandé explicitement : "Score moyen (/5)" → CSAT,
    # "Taux de neutres" → CES, "Taux de commentaires laissés" → NPS. Les
    # anciennes clés (taux_neutre, score_moyen, taux_commentaires) restent
    # calculées dans compute_agency_kpis (pour ne rien casser ailleurs dans
    # le code qui s'y référerait encore), mais ne sont plus proposées au
    # choix ici — remplacées par les 3 nouvelles.
    "csat": "CSAT (Customer Satisfaction Score)",
    "ces_estime": "CES estimé (proxy résolution)",
    "nps_estime": "NPS estimé (approximation)",
}

# Sélection par défaut : uniquement les indicateurs "essentiels" habituels —
# les 5 autres restent disponibles mais l'utilisateur doit les ajouter
# lui-même s'il les veut (checkbox déjà cochée pour ceux-ci uniquement).
DEFAULT_KPI_KEYS = [
    "nbre_repondant", "taux_satisfaction", "taux_insatisfaction", "taux_resolution",
]


def render_report_generator(df_full: pd.DataFrame, key_prefix: str = "report", show_title: bool = True,
                             show_demandes_panel: bool = True) -> None:
    if show_title:
        st.markdown("## 🗞️ Générateur de rapport")

    # Les 3 grandes étapes ci-dessous sont chacune dans une case avec ombre
    # marquée (même ombre que le Tableau de bord) — demande explicite pour
    # bien les distinguer visuellement. st.container(key=...) est la SEULE
    # méthode fiable pour cibler du CSS sur un bloc Streamlit réel (un <div>
    # injecté par st.markdown n'enveloppe jamais les widgets qui suivent).
    st.markdown(
        """
        <style>
        .st-key-report_box_1, .st-key-report_box_2, .st-key-report_box_3 {
            background:#FFFFFF; border:1px solid #E5E1DC; border-radius:14px;
            padding:20px 24px 24px; margin-bottom:28px;
            box-shadow: 0 12px 30px rgba(0,0,0,.22), 0 4px 9px rgba(0,0,0,.13);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    settings = get_settings()
    try:
        import matplotlib  # noqa: F401
        _matplotlib_ok = True
    except ImportError:
        _matplotlib_ok = False

    if not _matplotlib_ok:
        st.warning(
            "⚠️ La dépendance `matplotlib` n'est pas installée sur ce déploiement — les graphiques "
            "du rapport utiliseront un moteur de secours plus lent, mais tout reste fonctionnel."
        )

    if not settings.gemini_configured:
        st.info("ℹ️ Ce générateur nécessite la clé API Gemini — non configurée par l'administrateur.")
        return

    # Application "fichiers bruts quelconques" — plus de notion d'agence,
    # ni de questionnaire (demande explicite : "c'est comme si c'est la
    # même appli mais cette fois c'est pas pour questionnaire"). Le
    # générateur de rapport générique (ci-dessous) est désormais le seul
    # chemin utilisé, systématiquement — pas de bouton "Ajouter une
    # agence" ni de case "Indicateurs à afficher" : tout est piloté par ce
    # qui est déjà configuré dans le Tableau de bord.
    _render_generic_report_generator(key_prefix, df_full)
    return

    # --- Demandes/réclamations enregistrées par agence ----------------------
    # Interface volontairement retirée (saturait l'espace) — la structure de
    # données reste en place (dict vide par défaut) pour que le calcul du
    # taux de réponse ailleurs dans ce fichier continue de fonctionner sans
    # erreur ; simplement plus aucune saisie manuelle proposée à l'écran.
    DEMANDES_KEY = "demandes_par_agence"
    if DEMANDES_KEY not in st.session_state:
        st.session_state[DEMANDES_KEY] = {}

    # --- Case 1 : Indicateurs à afficher ------------------------------------
    _box1 = st.container(key="report_box_1")
    with _box1:
        st.markdown("### 1️⃣ **Indicateurs à afficher**")
        # Liste simple de cases à cocher : un indicateur = une case. Aucun
        # multiselect, aucune pastille, aucune couleur — même principe que
        # "Personnaliser le menu" (barre latérale), pour éviter le rouge
        # imposé par Streamlit/BaseWeb sur les pastilles de multiselect.
        kpis_choisis = []
        _kpi_cols = st.columns(2)
        for _kpi_idx, _kpi_key in enumerate(KPI_CHOICES.keys()):
            with _kpi_cols[_kpi_idx % 2]:
                _kpi_checked = st.checkbox(
                    KPI_CHOICES[_kpi_key],
                    value=_kpi_key in DEFAULT_KPI_KEYS,
                    key=f"{key_prefix}_kpi_check_{_kpi_key}",
                )
                if _kpi_checked:
                    kpis_choisis.append(_kpi_key)
    # --- Commentaires par graphique + verbatims résumés : TOUJOURS activés,
    # sur les deux flux (questionnaire et fichier brut), pour tous les
    # rapports (par agence, global) — plus une option qu'on pourrait
    # décocher par erreur et se retrouver avec un rapport incomplet.
    include_verbatims = True
    include_chart_comments = True

    # --- Accumulateur : une entrée déjà construite par agence ajoutée ------
    ACC_KEY = f"_{key_prefix}_report_accumulator"
    if ACC_KEY not in st.session_state:
        st.session_state[ACC_KEY] = {}
    accumulated = st.session_state[ACC_KEY]

    live_state = st.session_state.get("dashboard_live_state") or {}
    # Seuls chart_type_override et l'état de figeage du Tableau de bord sont
    # encore lus depuis là-bas — les commentaires et le résumé des verbatims
    # sont désormais TOUJOURS régénérés fraîchement pour l'agence en cours
    # d'ajout (voir _build_agency_entry ci-dessous), donc plus besoin de
    # préparer quoi que ce soit au préalable dans le Tableau de bord.
    chart_type_override = live_state.get("chartTypeOverride") or {}
    dashboard_agence_globale = live_state.get("agenceGlobale") or "__ALL__"
    dashboard_locked = bool(live_state.get("dashboardLocked"))

    # --- Marqueur spécial pour le rapport GLOBAL (toutes agences combinées,
    # comme UNE SEULE entité — jamais de ventilation par agence, jamais de
    # nom d'agence affiché). Clé technique interne, jamais un vrai nom
    # d'agence, donc aucun risque de collision.
    GLOBAL_KEY = "__GLOBAL_REPORT__"
    GLOBAL_LABEL = "🌍 Toutes les agences (rapport global — combinées en une seule page)"

    def _comment_all_charts(all_charts: list[dict], scope_label: str) -> int:
        """Génère le commentaire de CHAQUE graphique EN PARALLÈLE (pas en
        séquence) — avant, une agence avec 9 graphiques faisait 9 appels
        Gemini l'un après l'autre (jusqu'à plusieurs minutes cumulées avec
        plusieurs agences ajoutées) ; sur un hébergement qui coupe les
        connexions trop longues, le processus pouvait être interrompu
        avant la fin, laissant certains graphiques sans commentaire — ou
        même le rapport entier sans fichier à télécharger. Corrigé comme
        pour le rapport générique : tous les appels partent en même temps,
        un échec isolé (réseau, quota...) ne fait perdre que SON commentaire,
        jamais les autres ni le rapport lui-même.
        Renvoie le nombre d'échecs (0 = tout est passé) — jamais silencieux,
        affiché ensuite à l'utilisateur (voir st.session_state ci-dessous)."""
        chartables = [c for c in all_charts if c.get("data_summary")]
        if not chartables:
            return 0

        def _one(chart: dict) -> tuple[int, str | None, str | None]:
            try:
                ok, text = generate_statistician_comment(chart["title"], chart["data_summary"], scope_label)
                return id(chart), (text if ok else None), (None if ok else text)
            except Exception as exc:  # noqa: BLE001
                return id(chart), None, str(exc)

        # Réduit de 8 à 4 appels simultanés — bursts moins agressifs contre
        # le quota Gemini gratuit (par minute), qui s'épuisait souvent après
        # la 1ère ou les 2 premières agences ajoutées (confirmé par le
        # journal des échecs juste en dessous, qui affiche la vraie raison).
        with ThreadPoolExecutor(max_workers=min(4, len(chartables)) or 1) as executor:
            futures = [executor.submit(_one, c) for c in chartables]
            results = {r[0]: (r[1], r[2]) for r in (f.result() for f in as_completed(futures))}
        n_failed = 0
        failures_log = st.session_state.setdefault(f"_{key_prefix}_comment_failures", [])
        for chart in chartables:
            comment, error = results.get(id(chart), (None, None))
            if comment is None:
                # Repli à base de règles (sans IA, donc jamais soumis au
                # quota) — demande explicite : "tous les graphiques
                # doivent avoir des commentaires". Avant, un échec Gemini
                # (quota atteint, souvent dès la 2e-3e agence ajoutée au
                # même rapport) laissait le graphique SANS AUCUN
                # commentaire dans le rapport final — d'où l'incohérence
                # observée entre agences (la première, traitée avant
                # l'épuisement du quota, avait ses commentaires ; les
                # suivantes non).
                comment = generate_fallback_comment(chart.get("data_summary") or {})
                n_failed += 1
                failures_log.append((f"{scope_label} — {chart['title']}", error or "raison inconnue"))
            # Émojis retirés ici, quelle que soit la source du commentaire
            # (Gemini ou repli) — demande explicite : "je ne veux pas ces
            # émojis dans le rapport... enlève même les points noirs qui
            # les représentent". Gemini reçoit le résumé chiffré AVEC les
            # émojis dedans (ex: "😃 Très satisfait" dans data_summary) et
            # peut les recopier tels quels dans sa réponse — la police du
            # PDF/Word ne les affiche pas et ils apparaissent comme des
            # carrés noirs.
            chart["comment"] = strip_emoji_for_reports(comment) if comment else comment
        return n_failed

    def _raw_verbatims_fallback(sub, max_each: int = 4) -> dict:
        """Repli SANS IA : quelques vraies citations brutes (non résumées),
        classées positif/négatif avec la même règle que le résumé Gemini —
        utilisé UNIQUEMENT si le résumé IA échoue, pour que le rapport ait
        TOUJOURS des verbatims quand des commentaires existent réellement
        dans les données, même quand Gemini est indisponible (quota...)."""
        if "Commentaire" not in sub.columns:
            return {"positifs": [], "negatifs": []}
        sat_col = sub["Satisfaction"] if "Satisfaction" in sub.columns else None
        resolu_col = sub["Resolu"] if "Resolu" in sub.columns else None
        motif_col = sub["Motif_insatisfaction"] if "Motif_insatisfaction" in sub.columns else None
        positifs, negatifs = [], []
        for idx, texte in sub["Commentaire"].items():
            texte = str(texte).strip() if texte is not None else ""
            if not texte or texte.lower() == "nan":
                continue
            sat = str(sat_col.loc[idx]) if sat_col is not None and idx in sat_col.index else ""
            resolu = str(resolu_col.loc[idx]).strip() if resolu_col is not None and idx in resolu_col.index else ""
            motif = str(motif_col.loc[idx]).strip() if motif_col is not None and idx in motif_col.index else ""
            est_negatif = ("insatisfait" in sat.lower()) or resolu.lower().startswith("non") or (motif and motif.lower() != "nan")
            if est_negatif:
                negatifs.append(texte)
            elif "satisfait" in sat.lower() and "insatisfait" not in sat.lower():
                positifs.append(texte)
        return {"positifs": positifs[:max_each], "negatifs": negatifs[:max_each]}

    def _summarize_verbatims_checked(sub, scope_label: str) -> dict:
        """Enveloppe `summarize_agency_verbatims` pour détecter un échec
        Gemini silencieux : si la colonne « Commentaire » contient bien du
        texte brut mais que le résumé revient totalement vide, ce n'est pas
        « pas de verbatims » mais un échec de résumé (quota, réseau...) —
        journalisé comme pour les commentaires, jamais silencieux.
        Repli sur des citations BRUTES (non résumées) dans ce cas précis :
        le rapport ne doit JAMAIS se retrouver sans aucun verbatim quand il
        en existe réellement dans les données, même si Gemini est en
        panne — testé avec un vrai cas de quota Gemini épuisé."""
        result = summarize_agency_verbatims(sub)
        has_raw_text = "Commentaire" in sub.columns and sub["Commentaire"].astype(str).str.strip().replace("nan", "").ne("").any()
        if has_raw_text and not result.get("positifs") and not result.get("negatifs"):
            failures_log = st.session_state.setdefault(f"_{key_prefix}_comment_failures", [])
            failures_log.append((f"{scope_label} — Résumé des verbatims", "Échec du résumé IA (souvent : quota Gemini atteint) — citations brutes affichées à la place"))
            return _raw_verbatims_fallback(sub)
        return result

    def _build_agency_entry(agence: str) -> dict:
        """Construit l'entrée accumulée d'UNE agence — même logique utilisée
        pour l'ajout individuel et pour l'ajout groupé "toutes les agences",
        pour qu'il n'y ait jamais deux chemins qui pourraient diverger."""
        sub = df_full[df_full["Agence"] == agence]
        demandes = st.session_state.get(DEMANDES_KEY, {})
        kpis = compute_agency_kpis(sub, demandes.get(agence))
        periode = None
        if "Horodatage" in sub.columns and sub["Horodatage"].notna().any():
            dts = pd.to_datetime(sub["Horodatage"], errors="coerce").dropna()
            if len(dts):
                periode = (dts.min(), dts.max())

        all_charts = build_agency_full_charts(sub, chart_type_override=chart_type_override)
        # RÉGÉNÉRÉ SYSTÉMATIQUEMENT pour CETTE agence — ne jamais réutiliser
        # dashboard_comments (indexé par type de graphique "sat-dist"/
        # "apprecie"/... mais PAS par agence) : avec le bouton "Ajouter LES N
        # agences d'un coup" notamment, un seul commentaire capturé une fois
        # dans le Tableau de bord se retrouvait appliqué identique à TOUTES
        # les agences ajoutées — bug réel confirmé (12 agences aux effectifs
        # de 3 à 100 répondants, toutes affichant le même commentaire et les
        # mêmes chiffres, ceux d'une seule agence ou d'une vue globale).
        #
        # Commentaires des graphiques ET résumé des verbatims lancés EN
        # MÊME TEMPS (pas l'un après l'autre) : les deux sont totalement
        # indépendants (l'un lit les graphiques, l'autre les commentaires
        # texte libre), donc les faire attendre l'un l'autre doublait le
        # temps total pour rien — cause probable du "ça tourne longtemps
        # après avoir cliqué Ajouter une agence".
        verbatims = None
        with ThreadPoolExecutor(max_workers=2) as _outer_pool:
            _fut_comments = _outer_pool.submit(_comment_all_charts, all_charts, agence) if include_chart_comments else None
            _fut_verbatims = _outer_pool.submit(_summarize_verbatims_checked, sub, agence) if include_verbatims else None
            if _fut_comments is not None:
                _fut_comments.result()
            if _fut_verbatims is not None:
                verbatims = _fut_verbatims.result()

        return {"agence": agence, "kpis": kpis, "periode": periode, "all_charts": all_charts, "verbatims": verbatims}

    def _build_global_entry() -> dict:
        """Construit UNE SEULE entrée combinant TOUTES les agences ensemble
        — la somme/l'ensemble des données, comme si c'était une seule
        entité. Aucune ventilation par agence, aucun nom d'agence affiché :
        c'est un rapport global, pas un rapport « toutes les agences les
        unes après les autres » (ce que faisait l'ancien bouton groupé)."""
        demandes = st.session_state.get(DEMANDES_KEY, {})
        # Somme des demandes enregistrées de toutes les agences — seulement
        # si TOUTES l'ont renseignée (sinon le total serait faux, sous-
        # évalué silencieusement par les agences oubliées).
        toutes_renseignees = all(demandes.get(a) for a in agences_dispo)
        demandes_total = sum(demandes.get(a, 0) for a in agences_dispo) if toutes_renseignees else None

        kpis = compute_agency_kpis(df_full, demandes_total)
        periode = None
        if "Horodatage" in df_full.columns and df_full["Horodatage"].notna().any():
            dts = pd.to_datetime(df_full["Horodatage"], errors="coerce").dropna()
            if len(dts):
                periode = (dts.min(), dts.max())

        all_charts = build_agency_full_charts(df_full, chart_type_override=chart_type_override)
        verbatims = None
        with ThreadPoolExecutor(max_workers=2) as _outer_pool:
            _fut_comments = _outer_pool.submit(_comment_all_charts, all_charts, "toutes les agences confondues") if include_chart_comments else None
            _fut_verbatims = _outer_pool.submit(_summarize_verbatims_checked, df_full, "toutes les agences confondues") if include_verbatims else None
            if _fut_comments is not None:
                _fut_comments.result()
            if _fut_verbatims is not None:
                verbatims = _fut_verbatims.result()

        return {"agence": "Toutes les agences (rapport global)", "kpis": kpis, "periode": periode,
                "all_charts": all_charts, "verbatims": verbatims}

    _box2 = st.container(key="report_box_2")
    with _box2:
        st.markdown("### 2️⃣ Ajoute les agences")

        add_col, btn_col = st.columns([3, 2])
        with add_col:
            selection = st.selectbox(
                "Agence actuellement configurée dans le Tableau de bord",
                agences_dispo + [GLOBAL_LABEL], key=f"{key_prefix}_agence_to_add",
            )
        is_global_selected = selection == GLOBAL_LABEL
        with btn_col:
            st.markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)
            btn_label = "➕ Ajouter le rapport global" if is_global_selected else f"➕ Ajouter « {selection} »"
            if st.button(btn_label, type="primary",
                         key=f"{key_prefix}_add_agency_btn", use_container_width=True):
                # Nombre RÉEL de graphiques qui seront commentés — affiché
                # explicitement, comme demandé (avant : message générique sans
                # aucun chiffre, impossible de savoir si ça avance ou combien
                # de temps ça va prendre).
                _preview_df = df_full if is_global_selected else df_full[df_full["Agence"] == selection]
                _preview_charts = build_agency_full_charts(_preview_df, chart_type_override=chart_type_override)
                _n_commentables = len([c for c in _preview_charts if c.get("data_summary")])
                with st.spinner(f"{_n_commentables} graphique(s) à commenter, verbatims en cours (parallélisés)..."):
                    if is_global_selected:
                        accumulated[GLOBAL_KEY] = _build_global_entry()
                    else:
                        accumulated[selection] = _build_agency_entry(selection)
                st.session_state.pop(f"_{key_prefix}_final_report_bytes", None)
                st.rerun()

        # --- Ajout groupé : repensé — ne crée plus 15 pages séparées (une par
        # agence), mais ajoute directement LE rapport global (voir
        # _build_global_entry) — raccourci pour la même action que choisir
        # « Toutes les agences » dans la liste ci-dessus, disponible seulement
        # quand le Tableau de bord est VRAIMENT figé sur « Toutes les agences »
        # (sinon le type de graphique répliqué ne correspondrait à aucune
        # sélection délibérée).
        all_agencies_ready = dashboard_agence_globale == "__ALL__" and dashboard_locked
        if all_agencies_ready:
            if st.button("🌍 Générer le rapport GLOBAL (Tableau de bord figé sur « Toutes »)",
                         key=f"{key_prefix}_add_all_btn", use_container_width=True):
                _preview_charts = build_agency_full_charts(df_full, chart_type_override=chart_type_override)
                _n_commentables = len([c for c in _preview_charts if c.get("data_summary")])
                with st.spinner(f"{_n_commentables} graphique(s) à commenter, verbatims en cours (parallélisés)..."):
                    accumulated[GLOBAL_KEY] = _build_global_entry()
                st.session_state.pop(f"_{key_prefix}_final_report_bytes", None)
                st.rerun()

        # --- Agences déjà ajoutées : nom en texte simple (noir, 20px) +
        # petite croix rouge séparée pour retirer — les deux ne peuvent pas
        # partager la même règle de couleur puisqu'ils doivent avoir des
        # couleurs différentes (noir pour le nom, rouge pour la croix).
        if accumulated:
            st.markdown(
                """
                <style>
                [class*="st-key-cie_agency_name_row_"] p {
                    color:#111827 !important;
                    font-size:20px !important;
                    margin:0 !important;
                }
                /* theme.py force "color:#FFFFFF !important" sur TOUS les
                   descendants de bouton (".stButton > button *"), pensé
                   pour les boutons orange pleins — sans cette règle plus
                   spécifique ciblant directement le texte interne, la
                   croix de suppression restait blanche, donc invisible.
                   Bug réel trouvé et confirmé en lisant le CSS global
                   (theme.py, règle ".stButton > button *"). */
                [class*="st-key-cie_agency_remove_btn_"] .stButton button {
                    background:transparent !important;
                    border:none !important;
                    box-shadow:none !important;
                    padding:0 !important;
                    min-height:22px !important;
                    min-width:22px !important;
                }
                [class*="st-key-cie_agency_remove_btn_"] .stButton button p {
                    color:#DC2626 !important;
                    font-size:15px !important;
                    font-weight:700 !important;
                    line-height:1 !important;
                }
                [class*="st-key-cie_agency_remove_btn_"] .stButton button:hover {
                    background:#FEE2E2 !important;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            _agency_cols = st.columns(4)
            for _i, key in enumerate(list(accumulated.keys())):
                label = GLOBAL_LABEL if key == GLOBAL_KEY else key
                # Clé unique PAR agence — obligatoire (Streamlit interdit les
                # clés de conteneur dupliquées dans une boucle : même bug déjà
                # rencontré et corrigé une première fois sur cette même zone).
                _safe_key = "".join(c if c.isalnum() else "_" for c in key)
                with _agency_cols[_i % 4]:
                    # Croix D'ABORD, nom juste après (demande explicite :
                    # "mets juste avant le nom, pas éloigné") — évite tout
                    # le problème d'alignement/espacement rencontré en
                    # essayant de coller la croix APRÈS le nom.
                    _del_col, _name_col = st.columns([1, 6])
                    with _del_col:
                        with st.container(key=f"cie_agency_remove_btn_{_safe_key}"):
                            if st.button("✕", key=f"{key_prefix}_remove_{key}", help=f"Retirer {label}"):
                                del accumulated[key]
                                st.session_state.pop(f"_{key_prefix}_final_report_bytes", None)
                                st.rerun()
                    with _name_col:
                        with st.container(key=f"cie_agency_name_row_{_safe_key}"):
                            st.markdown(label)
        else:
            st.caption("Aucune agence ajoutée pour l'instant.")

    # --- 2. Génération du fichier final, toutes agences accumulées --------
    _box3 = st.container(key="report_box_3")
    with _box3:
        st.markdown("### 3️⃣ **Générer**")
        fmt_col, btn_col2 = st.columns([2, 3])
        with fmt_col:
            fmt = st.radio("Format du rapport", ["PDF", "Word", "PowerPoint"], horizontal=True, key=f"{key_prefix}_format_radio")

        REPORT_BYTES_KEY = f"_{key_prefix}_final_report_bytes"
        REPORT_ERROR_KEY = f"_{key_prefix}_final_report_error"

        with btn_col2:
            st.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
            generate_clicked = st.button("📄 Générer le fichier (toutes les agences ajoutées)", type="primary",
                                          disabled=not accumulated, key=f"{key_prefix}_generate_report_btn",
                                          use_container_width=True)
        if generate_clicked:
            st.session_state.pop(REPORT_ERROR_KEY, None)
            st.session_state.pop(REPORT_BYTES_KEY, None)
            try:
                pages = [accumulated[k] for k in sorted(accumulated.keys())]
                _n_total_charts = sum(len(p.get("all_charts") or []) for p in pages)
                progress = st.progress(0.0, text=f"Préparation de {_n_total_charts} graphique(s)...")

                if fmt in ("PDF", "Word"):
                    def _on_image_done(done, total, agence_label):
                        progress.progress(done / total if total else 1.0, text=f"Graphique {done}/{total} ({agence_label})...")
                    prerender_agency_page_images(pages, progress_callback=_on_image_done)

                progress.progress(0.9, text=f"Mise en page du {fmt}...")
                periode_globale = ""
                # Le rapport global couvre TOUJOURS l'intégralité des données —
                # pas la peine de filtrer sur des noms d'agences dans ce cas
                # (la clé technique GLOBAL_KEY n'en est pas une).
                all_dts = df_full if GLOBAL_KEY in accumulated else df_full[df_full["Agence"].isin(accumulated.keys())]
                if "Horodatage" in all_dts.columns and all_dts["Horodatage"].notna().any():
                    dts = pd.to_datetime(all_dts["Horodatage"], errors="coerce").dropna()
                    if len(dts):
                        periode_globale = f"{dts.min():%d %B} – {dts.max():%d %B %Y}"

                if fmt == "PDF":
                    ok, payload = build_agency_report_pdf(pages, meta={"periode_globale": periode_globale}, pill_keys=kpis_choisis)
                    fname, mime = "rapport_officiel_cie.pdf", "application/pdf"
                elif fmt == "Word":
                    ok, payload = build_agency_report_word(pages, meta={"periode_globale": periode_globale}, pill_keys=kpis_choisis)
                    fname, mime = "rapport_officiel_cie.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                else:
                    ok, payload = build_agency_report_pptx(pages, meta={"periode_globale": periode_globale}, pill_keys=kpis_choisis)
                    fname, mime = "rapport_officiel_cie.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"

                progress.progress(1.0, text="Terminé.")
                progress.empty()
                if ok:
                    st.session_state[REPORT_BYTES_KEY] = (payload, fname, mime)
                else:
                    st.session_state[REPORT_ERROR_KEY] = payload
            except Exception as exc:  # noqa: BLE001
                st.session_state[REPORT_ERROR_KEY] = str(exc)

        if st.session_state.get(REPORT_ERROR_KEY):
            st.error(f"La génération a échoué : {st.session_state[REPORT_ERROR_KEY]}")

        if st.session_state.get(REPORT_BYTES_KEY):
            payload, fname, mime = st.session_state[REPORT_BYTES_KEY]
            st.success("Rapport généré.")
            st.download_button(f"⬇️ Télécharger « {fname} »", data=payload, file_name=fname, mime=mime,
                                type="primary", key=f"{key_prefix}_download_btn")


# ============================================================================
# DÉSACTIVÉ (mode "questionnaire uniquement") — cette fonction gérait le
# rapport pour le mode "Fichier brut quelconque", qui ne concerne plus
# l'application. Commentée en bloc, pas supprimée, pour réactivation
# facile plus tard si besoin (retirer le "# " au début de chaque ligne).
# ============================================================================
def _render_generic_report_generator(key_prefix: str, df_full: pd.DataFrame) -> None:
    """Générateur de rapport pour les données GÉNÉRIQUES (import "Fichier
    brut quelconque") — même principe que pour les agences (PDF et Word,
    indicateurs + graphiques + commentaires + verbatims résumés), mais sans
    notion d'agence : un seul jeu d'indicateurs globaux (Lignes, Colonnes,
    Quanti, Quali...) et tous les graphiques actuellement configurés dans
    le Tableau de bord générique, reconstruits à partir de leur résumé
    chiffré déjà calculé côté JS (chartDataSummaries, reçu via le pont
    Streamlit Components) — jamais recalculés indépendamment. Chaque
    résumé transporte le VRAI type affiché à l'écran (`vizType` :
    barre-v/barre-h/camembert/anneau/courbe/boite/boite_precalc/scatter/
    groupedbar/stat).

    Commentaires ET verbatims sont TOUJOURS activés (pas une option qu'on
    pourrait décocher par erreur) — régénérés fraîchement à chaque
    génération, jamais depuis un cache potentiellement périmé."""
    st.caption(
        "Rapport basé sur ce qui est **actuellement affiché dans le 📊 Tableau de bord** — "
        "mêmes graphiques, mêmes types. Commentaires par graphique et verbatims résumés (s'il y en "
        "a une colonne de texte libre choisie) toujours inclus. Configure le Tableau de bord "
        "d'abord, reviens ici ensuite."
    )

    live_state = st.session_state.get("dashboard_live_state") or {}
    chart_summaries = live_state.get("chartDataSummaries") or {}
    dataset_kpis = live_state.get("datasetKpis") or {}
    verbatim_source_col = live_state.get("verbatimSourceCol")

    if not chart_summaries:
        st.warning(
            "⚠️ **Aucun graphique détecté.** Ouvre le **📊 Tableau de bord**, laisse-le construire "
            "ses graphiques, puis reviens ici."
        )
        return

    include_chart_comments = True

    titre = st.text_input("Titre du rapport (optionnel)", key=f"{key_prefix}_generic_titre",
                           placeholder="Ex : Analyse du fichier clients Q3 2026")

    REPORT_BYTES_KEY = f"_{key_prefix}_generic_report_bytes"
    REPORT_ERROR_KEY = f"_{key_prefix}_generic_report_error"

    fmt_col, btn_col = st.columns([2, 3])
    with fmt_col:
        fmt = st.radio("Format du rapport", ["PDF", "Word"], horizontal=True, key=f"{key_prefix}_generic_format_radio")
    with btn_col:
        st.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
        generate_clicked = st.button("📄 Générer le rapport", type="primary",
                                      key=f"{key_prefix}_generic_generate_btn", use_container_width=True)
    if generate_clicked:
        st.session_state.pop(REPORT_ERROR_KEY, None)
        st.session_state.pop(REPORT_BYTES_KEY, None)
        try:
            slot_ids = list(chart_summaries.keys())
            n_total = len(slot_ids)
            progress = st.progress(0.0, text=f"Préparation de {n_total} graphique(s)...")

            # --- Commentaires IA, TOUS EN PARALLÈLE (pas en séquence) ------
            # Avant : jusqu'à 10 appels Gemini l'un après l'autre, jusqu'à
            # 15 secondes chacun dans le pire cas — plus de 2 minutes au
            # total, sans le moindre signe visible pendant l'attente. Sur un
            # hébergement qui coupe les connexions trop longues, le
            # processus pouvait être interrompu avant la fin : les derniers
            # graphiques traités n'avaient jamais leur commentaire généré,
            # et parfois même AUCUN fichier n'était produit au bout du
            # compte — exactement les deux symptômes remontés. En
            # parallélisant, le temps total tombe à la durée du plus lent
            # appel individuel (quelques secondes), pas à leur somme.
            comments_by_slot: dict[str, str | None] = {}
            # Réinitialisée à CHAQUE génération de rapport — sans ça, les
            # échecs d'une tentative précédente (déjà résolus depuis, ou
            # sans rapport avec le graphique actuel) s'accumulaient
            # indéfiniment dans la session, jamais nettoyés.
            st.session_state[f"_{key_prefix}_generic_comment_failures"] = []
            if include_chart_comments:
                def _comment_for(slot_id: str) -> tuple[str, str | None]:
                    summary = chart_summaries[slot_id]
                    data_summary = {
                        "title": summary.get("title"),
                        "labels": summary.get("labels"),
                        "datasets": summary.get("datasets"),
                        "repartition_exacte": summary.get("repartition_exacte"),
                        "statValue": summary.get("statValue"),
                        "boxStats": summary.get("boxStats"),
                    }
                    try:
                        ok, text = generate_statistician_comment(summary.get("title", ""), data_summary, "",
                                                                  chart_type=summary.get("vizType"))
                        return slot_id, (text if ok else None), (None if ok else text)
                    except Exception as exc:  # noqa: BLE001
                        # Un échec isolé (réseau, quota...) ne doit JAMAIS
                        # faire perdre les autres commentaires déjà obtenus,
                        # ni empêcher le rapport de se générer quand même.
                        return slot_id, None, str(exc)

                done = 0
                with ThreadPoolExecutor(max_workers=min(8, n_total) or 1) as executor:
                    futures = [executor.submit(_comment_for, sid) for sid in slot_ids]
                    for future in as_completed(futures):
                        slot_id, comment, error = future.result()
                        comments_by_slot[slot_id] = comment
                        if comment is None:
                            title = chart_summaries.get(slot_id, {}).get("title", slot_id)
                            st.session_state.setdefault(f"_{key_prefix}_generic_comment_failures", []).append(
                                (title, error or "raison inconnue"))
                        done += 1
                        progress.progress(done / n_total if n_total else 1.0,
                                           text=f"Commentaire {done}/{n_total} généré...")

            # Échecs de génération affichés EXPLICITEMENT — avant, cette
            # liste était constituée puis jamais lue nulle part : un
            # commentaire manquant dans le rapport final passait totalement
            # inaperçu, sans la moindre explication ("certains commentaires
            # ne s'affichent pas" — signalé, cause enfin visible ici).
            _failures = st.session_state.get(f"_{key_prefix}_generic_comment_failures", [])
            if _failures:
                st.warning(
                    f"⚠️ {len(_failures)} commentaire(s) n'ont pas pu être générés et manqueront dans le "
                    f"rapport :\n" + "\n".join(f"- **{title}** : {reason}" for title, reason in _failures)
                )

            # --- Verbatims résumés, TOUJOURS inclus s'il y a une colonne de
            # texte libre choisie dans le Tableau de bord — recalculés ici,
            # jamais depuis le résumé déjà en mémoire côté client (pourrait
            # être périmé). Repris directement des VRAIES données (df_full),
            # pas d'un état JS qui pourrait diverger.
            verbatims = None
            if verbatim_source_col and verbatim_source_col in df_full.columns:
                progress.progress(min(0.9, done / n_total if n_total else 0.9), text="Résumé des verbatims...")
                texts = [str(v).strip() for v in df_full[verbatim_source_col].tolist()
                         if v is not None and str(v).strip() and str(v).strip().lower() != "nan"]
                verbatims = summarize_generic_verbatims(texts)

            charts = []
            for slot_id in slot_ids:
                summary = chart_summaries[slot_id]
                charts.append({
                    "title": summary.get("title", ""),
                    "labels": summary.get("labels"),
                    "datasets": summary.get("datasets"),
                    "comment": comments_by_slot.get(slot_id),
                    "chart_type": summary.get("vizType"),
                    "stat_value": summary.get("statValue"),
                    "box_stats": summary.get("boxStats"),
                    "axis_titles": summary.get("axisTitles"),
                })

            progress.progress(0.95, text=f"Mise en page du {fmt}...")
            meta = {"titre": titre} if titre else None
            if fmt == "PDF":
                ok, payload = build_generic_report_pdf(charts, dataset_kpis, meta=meta, verbatims=verbatims)
                fname, mime = "rapport_analyse_donnees.pdf", "application/pdf"
            else:
                ok, payload = build_generic_report_word(charts, dataset_kpis, meta=meta, verbatims=verbatims)
                fname, mime = "rapport_analyse_donnees.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

            progress.progress(1.0, text="Terminé.")
            progress.empty()

            if ok:
                st.session_state[REPORT_BYTES_KEY] = (payload, fname, mime)
            else:
                st.session_state[REPORT_ERROR_KEY] = payload
        except Exception as exc:  # noqa: BLE001
            st.session_state[REPORT_ERROR_KEY] = str(exc)

    if st.session_state.get(REPORT_ERROR_KEY):
        st.error(f"La génération a échoué : {st.session_state[REPORT_ERROR_KEY]}")

    if st.session_state.get(REPORT_BYTES_KEY):
        payload, fname, mime = st.session_state[REPORT_BYTES_KEY]
        st.success("Rapport généré.")
        st.download_button(f"⬇️ Télécharger « {fname} »", data=payload, file_name=fname, mime=mime,
                            type="primary", key=f"{key_prefix}_generic_download_btn")
#