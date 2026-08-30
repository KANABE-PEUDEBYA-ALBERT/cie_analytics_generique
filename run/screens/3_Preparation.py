"""
Page 3 — Préparation des données.

Équivalent applicatif du flux KNIME : import de plusieurs fichiers, tag
d'une valeur constante par fichier (ex: Codexp), fusion (Concatenate),
puis un pipeline d'opérations pas-à-pas (Column Filter, Row Filter, Cell
Splitter + Ungroup, Rule Engine / Constant Value Column, GroupBy...),
chacune affichant son nombre de lignes avant/après comme un nœud exécuté.
"""
from __future__ import annotations
from config.theme import set_page_title

import json
import textwrap

import pandas as pd
import streamlit as st

from auth.auth_utils import logout
from data.loader import load_uploaded_file
from data.state import (
    add_raw_import,
    append_new_extract,
    apply_pipeline_step,
    clear_raw_imports,
    DATA_KIND_GENERIC,
    get_current_dataframe,
    get_current_types,
    get_pipeline_history,
    has_current_dataframe,
    list_raw_imports,
    remove_raw_import,
    reset_pipeline_to_original,
    set_current_dataframe,
)
from pipeline.transformations import (
    STEP_LABELS,
    add_computed_column,
    add_constant_column,
    bin_numeric,
    clean_missing,
    clip_numeric,
    column_arithmetic,
    combine_date_time,
    concat_datasets,
    concatenate_columns,
    convert_type,
    date_difference,
    drop_columns,
    drop_duplicates,
    extract_date_part,
    filter_columns,
    filter_rows,
    groupby_aggregate,
    melt_to_long,
    normalize_numeric,
    one_hot_encode,
    rank_rows,
    regex_extract,
    rename_columns,
    reorder_columns,
    replace_values,
    round_numeric,
    sample_rows,
    sort_rows,
    split_multivalue_to_rows,
    text_case,
    trim_whitespace,
)

set_page_title("Accueil", "Importation et fusion de fichiers")

st.markdown(
    """
    <style>
    /* Neutralise l'espacement par défaut de Streamlit entre éléments vides
       (ex: les balises <style> injectées par st.markdown, qui n'ont aucun
       contenu visible mais gardent quand même une marge) — sans ça, ces
       marges s'accumulent en haut de page et créent un grand vide avant
       le premier vrai contenu visible ("je déteste les espaces vides"). */
    /* Le vrai responsable de l'accumulation de vide en haut : le
       conteneur parent (stVerticalBlock) applique un "gap" flex de 22px
       ENTRE CHAQUE enfant, y compris les balises <style> invisibles —
       impossible à neutraliser en ciblant les enfants eux-mêmes (le gap
       est une propriété du parent). Mis à zéro ici ; l'espacement entre
       les vrais éléments visibles reste géré par leurs propres marges
       (ex: .cie-step-header a déjà "margin: 1.35rem 0 0.55rem 0"). */
    .block-container > [data-testid="stVerticalBlock"] {
        gap: 0 !important;
    }
    .cie-step-header { display:flex; align-items:center; gap:12px; margin: 1.35rem 0 1.6rem 0; }
    .cie-step-number { background:#FF6B00; color:#FFFFFF; font-weight:700; width:30px; height:30px;
        border-radius:5px; display:flex; align-items:center; justify-content:center; font-size:22px; flex-shrink:0; }
    .cie-step-title { font-size:24px; font-weight:700; color:#151515; }

    /* Carte d'import : uniquement disposition/couleurs de la maquette.
       On cible le bloc Streamlit qui contient le file_uploader, sans
       l'envelopper dans un conteneur Streamlit à clé (compatibilité). */
    [data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) {
        border:1px solid #ECE4DA !important;
        border-radius:12px !important;
        background:#FFFFFF !important;
        padding:12px 16px !important;
        margin:0 0 1.45rem 0 !important;
        align-items:center !important;
        /* Pointillés remplacés par une ombre marquée — demande explicite,
           mieux pour distinguer la case visuellement. */
        box-shadow: 0 12px 30px rgba(0,0,0,.16), 0 4px 9px rgba(0,0,0,.09) !important;
    }
    [data-testid="stFileUploader"] { background:#FFFFFF !important; width:100% !important; }
    [data-testid="stFileUploaderDropzone"] {
        min-height:100px !important; border:0 !important; background:#FFFFFF !important;
        padding:4px 8px !important; box-shadow:none !important;
        display:flex !important; flex-direction:column !important; align-items:center !important;
    }
    /* Ordre visuel demandé : "Choisir un fichier" (bouton) en HAUT,
       "ou glisser déposer" (texte d'instructions) EN DESSOUS — le DOM
       natif de Streamlit place le bouton après le texte ; on inverse
       l'affichage avec `order` (flex), sans toucher au DOM. */
    [data-testid="stFileUploaderDropzoneInstructions"] { order:2 !important; }
    [data-testid="stFileUploaderDropzone"] button { order:1 !important; }
    [data-testid="stFileUploaderDropzoneInstructions"] { color:#171717 !important; }
    /* L'icône native de Streamlit ("upload") est masquée — remplacée par
       une icône personnalisée, plus jolie et plus grande, sans le mot
       "upload" qui apparaissait en infobulle native au survol. */
    [data-testid="stFileUploaderDropzoneInstructions"] svg {
        display:none !important;
    }
    [data-testid="stFileUploaderDropzoneInstructions"]::before {
        content:"";
        display:block;
        width:40px; height:40px; margin:0 auto 6px;
        background-color:#FF6B00;
        -webkit-mask-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/></svg>');
        mask-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/></svg>');
        -webkit-mask-repeat:no-repeat; mask-repeat:no-repeat;
        -webkit-mask-position:center; mask-position:center;
        -webkit-mask-size:contain; mask-size:contain;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] span {
        color:#171717 !important; font-size:0 !important;
        line-height:1.35 !important;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] span::after {
        content:"ou glisser-déposer par ici";
        color:#171717 !important;
        font-size:22px !important;
        font-weight:500 !important;
    }
    [data-testid="stFileUploaderDropzone"] button {
        background:#FF6B00 !important; border:1px solid #E85F00 !important;
        color:#FFFFFF !important; border-radius:6px !important; font-weight:700 !important;
        min-height:42px !important; padding:0.45rem 1.25rem !important;
        box-shadow:0 2px 5px rgba(255,107,0,.18) !important;
        font-size:0 !important;
    }
    /* Le bouton natif peut contenir sa propre icône + son propre libellé
       ("Upload" ou autre selon la version de Streamlit) dans des enfants
       (svg + span) : on les masque tous explicitement, pour ne garder
       que notre texte injecté via ::after ci-dessous. */
    [data-testid="stFileUploaderDropzone"] button svg { display:none !important; }
    [data-testid="stFileUploaderDropzone"] button * { font-size:0 !important; line-height:0 !important; }
    [data-testid="stFileUploaderDropzone"] button::after {
        content:"Choisir des fichiers";
        color:#FFFFFF !important;
        font-size:22px !important;
        line-height:normal !important;
        font-weight:700 !important;
    }
    [data-testid="stFileUploaderDropzone"] button:hover { background:#E85F00 !important; }
    [data-testid="stFileUploaderDropzone"] small { font-size:0 !important; }

    /* Après sélection, on conserve la liste des fichiers et on masque
       UNIQUEMENT le bouton et les instructions "Choisir des fichiers".
       Le masquage est activé par JS sur le file_uploader qui possède des
       fichiers, car les data-testid des lignes de fichiers changent selon
       les versions de Streamlit. */
    [data-testid="stFileUploader"].cie-has-files [data-testid="stFileUploaderDropzone"] button,
    [data-testid="stFileUploader"].cie-has-files [data-testid="stFileUploaderDropzoneInstructions"] {
        display:none !important;
    }
    [data-testid="stFileUploader"].cie-has-files [data-testid="stFileUploaderDropzone"] {
        min-height:0 !important;
        height:auto !important;
        padding:0 !important;
        justify-content:flex-start !important;
    }
    [data-baseweb="tab-list"] { gap:18px !important; border-bottom:none !important; }
    [data-baseweb="tab"] {
        font-size:22px !important; font-weight:700 !important;
        background:#FFFFFF !important;
        border:1px solid #ECE4DA !important;
        border-radius:12px !important;
        padding:14px 24px !important;
        box-shadow: 0 8px 18px rgba(0,0,0,.14), 0 2px 6px rgba(0,0,0,.08) !important;
        transition:all .15s ease;
    }
    [data-baseweb="tab"]:hover {
        background:#FFF7EF !important;
        border-color:#E8B98D !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        color:#FF6B00 !important;
        border-color:#FFB380 !important;
        background:#FFF0E6 !important;
        box-shadow: 0 10px 22px rgba(0,0,0,.18), 0 3px 8px rgba(0,0,0,.1) !important;
    }
    [data-baseweb="tab-highlight"] { display:none !important; }
    [data-baseweb="tab-border"] { display:none !important; }
    .cie-upload-side { display:flex; align-items:center; justify-content:space-between; gap:22px; min-height:100px; padding:0 8px; }
    .cie-upload-rules { list-style:none; display:flex; flex-direction:column; gap:12px; padding:0; margin:0; flex:1; }
    .cie-upload-rules li { display:flex; align-items:center; gap:9px; font-size:22px; color:#171717; font-weight:600; white-space:nowrap; }
    .cie-upload-rules svg { width:17px; height:17px; fill:#B88A58; flex-shrink:0; }
    .cie-folder-illustration { width:108px; height:82px; flex-shrink:0; }
    .cie-upload-label { font-size:22px; font-weight:600; color:#161616; margin:0.15rem 0 0.35rem; }
    .cie-current-result { margin:0.8rem 0 1rem; font-size:22px; color:#171717; }
    [data-testid="stFileUploader"] > label { color:#161616 !important; font-weight:600 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Streamlit recrée parfois le DOM du file_uploader après chaque sélection.
# On observe donc le DOM et on masque seulement le bouton/instruction si
# l'input HTML contient au moins un fichier. La liste des fichiers reste intacte.
st.components.v1.html(
    """
    <script>
    (function () {
      const doc = window.parent.document;
      function syncUploaders() {
        doc.querySelectorAll('[data-testid="stFileUploader"]').forEach(function (uploader) {
          const input = uploader.querySelector('input[type="file"]');
          const hasFiles = !!(input && input.files && input.files.length > 0);
          uploader.classList.toggle('cie-has-files', hasFiles);
        });
      }
      syncUploaders();
      new MutationObserver(syncUploaders).observe(doc.body, {childList:true, subtree:true});
    })();
    </script>
    """,
    height=0,
)

_CIE_CHECK_SVG = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>'
_CIE_FOLDER_SVG = """<svg class="cie-folder-illustration" viewBox="0 0 120 90" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M20 30 C20 25, 25 20, 30 20 L50 20 L60 28 L100 28 C105 28, 110 33, 110 38 L110 75 C110 80, 105 85, 100 85 L30 85 C25 85, 20 80, 20 75 Z" fill="#FFB380"/>
  <path d="M10 40 C10 35, 15 30, 20 30 L90 30 C95 30, 100 35, 100 40 L100 78 C100 83, 95 88, 90 88 L20 88 C15 88, 10 83, 10 78 Z" fill="#FF6B00"/>
  <rect x="35" y="15" width="40" height="50" rx="3" fill="#FFFFFF" stroke="#E5E7EB" stroke-width="2"/>
  <line x1="42" y1="25" x2="68" y2="25" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round"/>
  <line x1="42" y1="33" x2="68" y2="33" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round"/>
  <line x1="42" y1="41" x2="58" y2="41" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round"/>
</svg>"""


def render_upload_side() -> None:
    """Panneau latéral décoratif affiché à droite de la zone de dépôt.

    Application "fichiers bruts" — pas de notion d'agence : le
    récapitulatif se limite au nombre de lignes et de variables (colonnes),
    sans aucune autre phrase (demande explicite : "rien d'autre, pas de
    phrases de bavardage inutiles").

    `textwrap.dedent(...)` est indispensable ici : sans lui, l'indentation
    Python normale de ce bloc (8 espaces, function body) est interprétée
    par Markdown comme un BLOC DE CODE (4+ espaces d'indentation en début
    de ligne = bloc de code en Markdown), et tout le HTML s'affichait tel
    quel, en texte brut, au lieu d'être interprété — bug réel confirmé."""
    current_result_html = ""
    if has_current_dataframe():
        cur = get_current_dataframe()
        current_result_html = (
            f"<li>{_CIE_CHECK_SVG} <strong>{len(cur)} ligne(s)</strong>, "
            f"<strong>{cur.shape[1]} variable(s)</strong>.</li>"
        )
    st.markdown(
        '<div class="cie-upload-side"><ul class="cie-upload-rules">'
        + current_result_html
        + f'<li>{_CIE_CHECK_SVG} Formats acceptés : XLSX, XLS, CSV</li>'
        + '</ul></div>',
        unsafe_allow_html=True,
    )


# ============================================================
# SECTION A — Import multiple + fusion (Excel Reader ×N + Concatenate)
# ============================================================
st.markdown(
    '<div class="cie-step-header"><div class="cie-step-number">1</div>'
    '<div class="cie-step-title" style="font-weight:600 !important;font-size:35px !important;">'
    'Importer plusieurs types de fichiers et les fusionner</div></div>',
    unsafe_allow_html=True,
)

# Application "fichiers bruts quelconques" — plus de notion de
# questionnaire ni d'agence (demande explicite : "c'est comme si c'est la
# même appli mais cette fois c'est pas pour questionnaire"). Un seul
# bouton "Charger" qui importe ET fusionne directement (même principe que
# l'ancien flux questionnaire), sans étape de fusion séparée ni de
# colonne-étiquette manuelle.
if True:
    up_col, side_col = st.columns([2, 1])
    with up_col:
        raw_files = st.file_uploader(
            "Choisir les fichiers",
            type=["xlsx", "xls", "csv"],
            accept_multiple_files=True,
            key="raw_uploader",
            label_visibility="collapsed",
        )
    with side_col:
        render_upload_side()

    if raw_files:
        _merge_col, _clear_col = st.columns(2)
        with _merge_col:
            _do_merge = st.button("📥 Charger", type="primary", key="raw_merge_btn", use_container_width=True)
        with _clear_col:
            if has_current_dataframe():
                if st.button("🗑️ Vider les données actuellement chargées", key="raw_clear_btn", use_container_width=True):
                    set_current_dataframe(pd.DataFrame(), source_label="")
                    st.rerun()

        if _do_merge:
            loaded_dfs = []
            errors = []
            for f in raw_files:
                f.seek(0)
                res = load_uploaded_file(f)
                if res.ok:
                    loaded_dfs.append(res.df)
                else:
                    errors.append(res.message)

            if loaded_dfs:
                new_data, _ = concat_datasets(loaded_dfs)
                # Ajoute TOUJOURS aux données déjà chargées, jamais de
                # remplacement silencieux — même principe que le flux
                # questionnaire d'origine.
                append_new_extract(
                    new_data,
                    source_label=f"Fusion de {len(loaded_dfs)} fichier(s)",
                    data_kind=DATA_KIND_GENERIC,
                )
                st.rerun()
            elif errors:
                st.warning("Aucun fichier n'a pu être chargé — vérifie le format (XLSX, XLS ou CSV).")

# ============================================================
# SECTION B — Pipeline d'opérations sur les données courantes
# ============================================================
# SECTION B — Étapes de transformation : DÉSACTIVÉE (mode
# "questionnaire uniquement") — commentée en bloc, pas supprimée.
# ============================================================
# with st.expander("🔧 2. Étapes de transformation (optionnel — replié par défaut)", expanded=False):
#     # ============================================================
#     st.markdown("## 2. Étapes de transformation")
#
#     if not has_current_dataframe():
#         st.markdown("Aucune donnée courante. Fusionne des fichiers ci-dessus.")
#         st.stop()
#
#     df = get_current_dataframe()
#     types = get_current_types()
#
#     m1, m2, m3 = st.columns(3)
#     m1.metric("Lignes actuelles", f"{len(df):,}".replace(",", " "))
#     m2.metric("Colonnes actuelles", df.shape[1])
#     m3.metric("Étapes appliquées", len(get_pipeline_history()))
#
#     with st.expander("➕ Ajouter une étape", expanded=True):
#         search = st.text_input("🔎 Rechercher une opération", placeholder="ex: date, concatener, tri, doublon...", key="op_search")
#         all_kinds = list(STEP_LABELS.keys())
#         if search.strip():
#             needle = search.strip().lower()
#             matching_kinds = [k for k in all_kinds if needle in STEP_LABELS[k].lower() or needle in k.lower()]
#         else:
#             matching_kinds = all_kinds
#
#         if not matching_kinds:
#             st.warning("Aucune opération ne correspond à cette recherche.")
#             step_kind = None
#         else:
#             step_kind = st.selectbox("Opération", matching_kinds, format_func=lambda k: STEP_LABELS[k], key="op_select")
#         columns = list(df.columns)
#
#         if step_kind == "clean_missing":
#             cols = st.multiselect("Colonnes concernées (vide = toutes)", columns, key="cm_cols")
#             strategy = st.selectbox("Stratégie", ["drop_rows", "fill_zero", "fill_mean", "fill_mode"],
#                                      format_func=lambda s: {"drop_rows": "Supprimer les lignes concernées",
#                                                              "fill_zero": "Remplacer par 0",
#                                                              "fill_mean": "Remplacer par la moyenne (numérique)",
#                                                              "fill_mode": "Remplacer par la valeur la plus fréquente"}[s], key="cm_strategy")
#             if st.button("Appliquer", key="apply_missing"):
#                 new_df, res = clean_missing(df, cols or None, strategy)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "drop_duplicates":
#             cols = st.multiselect("Colonnes à comparer (vide = ligne entière)", columns, key="dd_dup_cols")
#             if st.button("Appliquer", key="apply_dupes"):
#                 new_df, res = drop_duplicates(df, cols or None)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "trim_whitespace":
#             cols = st.multiselect("Colonnes concernées (vide = toutes les colonnes texte)", columns, key="tw_cols")
#             if st.button("Appliquer", key="apply_trim"):
#                 new_df, res = trim_whitespace(df, cols or None)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "filter_rows":
#             c1, c2, c3 = st.columns(3)
#             col = c1.selectbox("Colonne", columns, key="fr_col")
#             op = c2.selectbox("Condition", ["=", "≠", ">", "<", ">=", "<=", "contient", "est vide", "n'est pas vide"], key="fr_op")
#             val = c3.text_input("Valeur", disabled=op in ("est vide", "n'est pas vide"), key="fr_val")
#             if st.button("Appliquer", key="apply_filter_rows"):
#                 new_df, res = filter_rows(df, col, op, val)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "filter_columns":
#             keep = st.multiselect("Colonnes à conserver", columns, default=columns, key="fc_keep")
#             if st.button("Appliquer", key="apply_filter_cols"):
#                 new_df, res = filter_columns(df, keep)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "rename_columns":
#             col_to_rename = st.selectbox("Colonne", columns, key="rn_col")
#             new_name = st.text_input("Nouveau nom", key="rn_new")
#             if st.button("Appliquer", key="apply_rename"):
#                 new_df, res = rename_columns(df, {col_to_rename: new_name})
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "split_multivalue":
#             c1, c2, c3 = st.columns(3)
#             col = c1.selectbox("Colonne à découper", columns, key="sm_col")
#             delim = c2.text_input("Délimiteur", value=";", key="sm_delim")
#             new_name = c3.text_input("Nouveau nom de colonne (optionnel)", value="", key="sm_new_name")
#             if st.button("Appliquer", key="apply_split"):
#                 new_df, res = split_multivalue_to_rows(df, col, delim, new_name or None)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "add_constant_column":
#             c1, c2, c3 = st.columns(3)
#             name = c1.text_input("Nom de la colonne", key="cc_name")
#             value = c2.text_input("Valeur", key="cc_value")
#             dtype = c3.selectbox("Type", ["texte", "nombre"], key="cc_type")
#             if st.button("Appliquer", key="apply_constant"):
#                 new_df, res = add_constant_column(df, name, value, dtype)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "add_computed_column":
#             name = st.text_input("Nom de la nouvelle colonne", key="comp_name")
#             expr = st.text_input(
#                 "Expression (colonnes avec espaces entre backticks)", key="comp_expr",
#                 placeholder="ex: `Nbre` * 2   ou   np.where(`Nbre` > 0, 'oui', 'non')",
#             )
#             if st.button("Appliquer", key="apply_computed"):
#                 new_df, res = add_computed_column(df, name, expr)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "groupby_aggregate":
#             c1, c2, c3 = st.columns(3)
#             group_cols = c1.multiselect("Regrouper par", columns, key="gb_group_cols")
#             agg_col = c2.selectbox("Colonne à agréger", columns, key="gb_agg_col")
#             agg_func = c3.selectbox("Fonction", ["comptage", "somme", "moyenne", "médiane", "min", "max", "écart-type"], key="gb_agg_func")
#             if st.button("Appliquer", key="apply_groupby"):
#                 if not group_cols:
#                     st.error("Choisis au moins une colonne de regroupement.")
#                 else:
#                     new_df, res = groupby_aggregate(df, group_cols, agg_col, agg_func)
#                     apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                     st.rerun()
#
#         elif step_kind == "reorder_columns":
#             order = st.multiselect("Ordre souhaité (les colonnes non citées suivent, dans leur ordre actuel)", columns, key="ro_order")
#             if st.button("Appliquer", key="apply_reorder"):
#                 new_df, res = reorder_columns(df, order)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "concatenate_columns":
#             cols_cc = st.multiselect("Colonnes à concaténer (au moins 2, dans l'ordre voulu)", columns, key="cc_cols")
#             c1, c2 = st.columns(2)
#             sep_cc = c1.text_input("Séparateur", value=" ", key="cc_sep")
#             new_name_cc = c2.text_input("Nom de la nouvelle colonne", key="cc_new_name")
#             if st.button("Appliquer", key="apply_concat_cols"):
#                 new_df, res = concatenate_columns(df, cols_cc, sep_cc, new_name_cc)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "drop_columns":
#             cols_drop = st.multiselect("Colonnes à supprimer", columns, key="dc_cols")
#             if st.button("Appliquer", key="apply_drop_cols"):
#                 new_df, res = drop_columns(df, cols_drop)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "convert_type":
#             c1, c2 = st.columns(2)
#             col_ct = c1.selectbox("Colonne", columns, key="ct_col")
#             target_ct = c2.selectbox("Nouveau type", ["texte", "nombre", "date"], key="ct_target")
#             if st.button("Appliquer", key="apply_convert_type"):
#                 new_df, res = convert_type(df, col_ct, target_ct)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "text_case":
#             cols_tc = st.multiselect("Colonnes concernées", columns, key="tc_cols")
#             mode_tc = st.selectbox("Transformation", ["majuscules", "minuscules", "première_lettre"], key="tc_mode",
#                                     format_func=lambda m: {"majuscules": "MAJUSCULES", "minuscules": "minuscules",
#                                                             "première_lettre": "Première Lettre En Majuscule"}[m])
#             if st.button("Appliquer", key="apply_text_case"):
#                 new_df, res = text_case(df, cols_tc, mode_tc)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "replace_values":
#             c1, c2, c3 = st.columns(3)
#             col_rv = c1.selectbox("Colonne", columns, key="rv_col")
#             old_rv = c2.text_input("Valeur à remplacer", key="rv_old")
#             new_rv = c3.text_input("Nouvelle valeur", key="rv_new")
#             whole_rv = st.checkbox("Uniquement si la cellule correspond exactement (sinon : remplace aussi dans un texte plus long)",
#                                     value=True, key="rv_whole")
#             if st.button("Appliquer", key="apply_replace_values"):
#                 new_df, res = replace_values(df, col_rv, old_rv, new_rv, whole_rv)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "regex_extract":
#             c1, c2, c3 = st.columns(3)
#             col_re = c1.selectbox("Colonne", columns, key="re_col")
#             pattern_re = c2.text_input("Expression régulière (motif entre parenthèses)", key="re_pattern",
#                                         placeholder=r"ex: (\d+)")
#             new_name_re = c3.text_input("Nom de la nouvelle colonne", key="re_new_name")
#             if st.button("Appliquer", key="apply_regex_extract"):
#                 new_df, res = regex_extract(df, col_re, pattern_re, new_name_re)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "extract_date_part":
#             c1, c2, c3 = st.columns(3)
#             col_dp = c1.selectbox("Colonne date", columns, key="dp_col")
#             part_dp = c2.selectbox("Partie à extraire",
#                                     ["année", "mois", "jour", "heure", "minute", "seconde", "jour_semaine", "trimestre", "semaine_année"],
#                                     key="dp_part")
#             new_name_dp = c3.text_input("Nom de la nouvelle colonne", key="dp_new_name")
#             if st.button("Appliquer", key="apply_extract_date_part"):
#                 new_df, res = extract_date_part(df, col_dp, part_dp, new_name_dp)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "date_difference":
#             c1, c2, c3, c4 = st.columns(4)
#             start_dd = c1.selectbox("Colonne de début", columns, key="dd_start")
#             end_dd = c2.selectbox("Colonne de fin", columns, key="dd_end")
#             unit_dd = c3.selectbox("Unité", ["jours", "heures", "minutes", "secondes"], key="dd_unit")
#             new_name_dd = c4.text_input("Nom de la nouvelle colonne", key="dd_new_name")
#             if st.button("Appliquer", key="apply_date_diff"):
#                 new_df, res = date_difference(df, start_dd, end_dd, unit_dd, new_name_dd)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "combine_date_time":
#             c1, c2, c3 = st.columns(3)
#             date_cdt = c1.selectbox("Colonne date", columns, key="cdt_date")
#             time_cdt = c2.selectbox("Colonne heure", columns, key="cdt_time")
#             new_name_cdt = c3.text_input("Nom de la nouvelle colonne", key="cdt_new_name")
#             if st.button("Appliquer", key="apply_combine_dt"):
#                 new_df, res = combine_date_time(df, date_cdt, time_cdt, new_name_cdt)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "round_numeric":
#             cols_rn = st.multiselect("Colonnes numériques", columns, key="rn_cols")
#             decimals_rn = st.number_input("Nombre de décimales", min_value=0, max_value=10, value=2, key="rn_decimals")
#             if st.button("Appliquer", key="apply_round"):
#                 new_df, res = round_numeric(df, cols_rn, int(decimals_rn))
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "clip_numeric":
#             c1, c2, c3 = st.columns(3)
#             col_cl = c1.selectbox("Colonne", columns, key="cl_col")
#             min_cl = c2.number_input("Minimum autorisé", value=0.0, key="cl_min")
#             max_cl = c3.number_input("Maximum autorisé", value=100.0, key="cl_max")
#             if st.button("Appliquer", key="apply_clip"):
#                 new_df, res = clip_numeric(df, col_cl, min_cl, max_cl)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "bin_numeric":
#             c1, c2, c3 = st.columns(3)
#             col_bn = c1.selectbox("Colonne numérique", columns, key="bn_col")
#             n_bins_bn = c2.number_input("Nombre de tranches", min_value=2, max_value=20, value=4, key="bn_nbins")
#             new_name_bn = c3.text_input("Nom de la nouvelle colonne", key="bn_new_name")
#             if st.button("Appliquer", key="apply_bin"):
#                 new_df, res = bin_numeric(df, col_bn, int(n_bins_bn), new_name_bn)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "normalize_numeric":
#             c1, c2, c3 = st.columns(3)
#             col_nn = c1.selectbox("Colonne numérique", columns, key="nn_col")
#             method_nn = c2.selectbox("Méthode", ["minmax", "zscore"], key="nn_method",
#                                       format_func=lambda m: {"minmax": "Min-max (0 à 1)", "zscore": "Centrée-réduite (z-score)"}[m])
#             new_name_nn = c3.text_input("Nom de la nouvelle colonne", key="nn_new_name")
#             if st.button("Appliquer", key="apply_normalize"):
#                 new_df, res = normalize_numeric(df, col_nn, method_nn, new_name_nn)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "rank_rows":
#             c1, c2, c3 = st.columns(3)
#             col_rk = c1.selectbox("Colonne numérique", columns, key="rk_col")
#             asc_rk = c2.selectbox("Ordre", [True, False], key="rk_asc",
#                                    format_func=lambda a: "Croissant (1 = plus petit)" if a else "Décroissant (1 = plus grand)")
#             new_name_rk = c3.text_input("Nom de la nouvelle colonne", key="rk_new_name")
#             if st.button("Appliquer", key="apply_rank"):
#                 new_df, res = rank_rows(df, col_rk, asc_rk, new_name_rk)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "column_arithmetic":
#             c1, c2, c3, c4 = st.columns(4)
#             col_a_ca = c1.selectbox("Colonne A", columns, key="ca_col_a")
#             op_ca = c2.selectbox("Opérateur", ["+", "-", "×", "÷"], key="ca_op")
#             operand_ca = c3.text_input("Colonne B ou nombre", key="ca_operand", placeholder="ex: Nbre_agents  ou  10")
#             new_name_ca = c4.text_input("Nom de la nouvelle colonne", key="ca_new_name")
#             if st.button("Appliquer", key="apply_arith"):
#                 new_df, res = column_arithmetic(df, col_a_ca, op_ca, operand_ca, new_name_ca)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "sort_rows":
#             cols_sr = st.multiselect("Trier par", columns, key="sr_cols")
#             asc_sr = st.selectbox("Ordre", [True, False], key="sr_asc",
#                                    format_func=lambda a: "Croissant" if a else "Décroissant")
#             if st.button("Appliquer", key="apply_sort"):
#                 new_df, res = sort_rows(df, cols_sr, asc_sr)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "sample_rows":
#             c1, c2 = st.columns(2)
#             n_sample = c1.number_input("Nombre de lignes", min_value=1, max_value=max(1, len(df)),
#                                         value=min(100, len(df)), key="smp_n")
#             method_sample = c2.selectbox("Méthode", ["aléatoire", "premières", "dernières"], key="smp_method")
#             if st.button("Appliquer", key="apply_sample"):
#                 new_df, res = sample_rows(df, int(n_sample), method_sample)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "melt_to_long":
#             id_vars_melt = st.multiselect("Colonnes à garder telles quelles (identifiants)", columns, key="melt_id")
#             value_vars_melt = st.multiselect("Colonnes à dépivoter (ex : une par année)", columns, key="melt_values")
#             c1, c2 = st.columns(2)
#             var_name_melt = c1.text_input("Nom de la colonne « variable »", value="Variable", key="melt_var_name")
#             value_name_melt = c2.text_input("Nom de la colonne « valeur »", value="Valeur", key="melt_value_name")
#             if st.button("Appliquer", key="apply_melt"):
#                 new_df, res = melt_to_long(df, id_vars_melt, value_vars_melt, var_name_melt, value_name_melt)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()
#
#         elif step_kind == "one_hot_encode":
#             col_ohe = st.selectbox("Colonne catégorielle", columns, key="ohe_col")
#             if st.button("Appliquer", key="apply_ohe"):
#                 new_df, res = one_hot_encode(df, col_ohe)
#                 apply_pipeline_step(new_df, step_kind, STEP_LABELS[step_kind], res)
#                 st.rerun()

st.markdown("### Aperçu des données courantes")
# `df` était auparavant défini à l'intérieur de la section "Étapes de
# transformation" ci-dessus (désormais commentée) — bug corrigé ici en le
# redéfinissant directement, avec garde-fou si aucune donnée n'est chargée
# (l'ancien `st.stop()` de cette section protégeait aussi cet aperçu final).
df = get_current_dataframe()
if df is not None and not df.empty:
    # Copie d'affichage uniquement — les "_" dans les noms de colonnes
    # (ex: "Score_satisfaction") ne doivent jamais apparaître à l'écran
    # (demande explicite), mais le DataFrame réel (avec les "_") reste
    # utilisé partout ailleurs dans l'app (graphiques, rapports...), donc
    # on ne renomme qu'une COPIE, jamais `df` lui-même.
    # Toutes les lignes affichées (demande explicite : "si on a 1000
    # lignes, on doit toutes les voir") — anciennement limité à .head(30).
    _df_display = df.rename(columns=lambda c: c.replace("_", " "))
    # st.dataframe (pas st.table) — bug réel trouvé et confirmé : avec un
    # gros fichier (20 000+ lignes), st.table crée un VRAI élément HTML par
    # ligne d'un coup, ce qui peut littéralement figer le navigateur
    # ("la page ne répond pas"). st.dataframe ne charge que les lignes
    # visibles à l'écran (défilement fluide même avec des dizaines de
    # milliers de lignes), au prix de la police Times New Roman qui ne
    # peut plus être imposée par CSS sur ce composant (rendu interne sur
    # un <canvas>, hors de portée du CSS) — un compromis nécessaire :
    # mieux vaut un aperçu qui s'affiche sans la bonne police qu'un
    # aperçu qui fige la page.
    st.dataframe(_df_display, use_container_width=True, height=600)
else:
    st.caption("Aucune donnée chargée pour l'instant.")

# Bouton "Se déconnecter" — tout en bas de la page, à gauche, en taille
# réduite (demande explicite : "mets le en bas à gauche, diminue sa
# taille"). N'occupe qu'une petite colonne étroite pour ne pas s'étirer
# sur toute la largeur.
st.markdown("<div style='margin-top:2rem;'></div>", unsafe_allow_html=True)
st.markdown(
    """
    <style>
    .st-key-cie_logout_bottom .stButton > button {
        font-size: 13px !important;
        padding: 2px 10px !important;
        min-height: 26px !important;
        color: #8A5A2B !important;
        background: transparent !important;
        border: 1px solid #E8B98D !important;
        box-shadow: none !important;
    }
    .st-key-cie_logout_bottom .stButton > button:hover {
        background: #FFF1E5 !important;
    }
    .st-key-cie_logout_bottom .stButton > button * {
        color: inherit !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
_logout_col = st.columns([1, 5])[0]
with _logout_col:
    with st.container(key="cie_logout_bottom"):
        if st.button("⇱ Se déconnecter", key="cie_logout_accueil"):
            logout()
            st.rerun()
