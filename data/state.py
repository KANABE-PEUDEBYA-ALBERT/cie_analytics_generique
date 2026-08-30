"""
Accès partagé aux données courantes de la session utilisateur.

Comme chaque utilisateur connecté a son propre st.session_state (Streamlit
isole les sessions par navigateur/onglet), le jeu de données chargé par
l'un n'est jamais visible par un autre — pas d'interférence entre
utilisateurs connectés simultanément.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from data.loader import detect_column_types

DF_KEY = "current_df"
TYPES_KEY = "current_types"
SOURCE_KEY = "current_source"
RAW_IMPORTS_KEY = "raw_imports"
PIPELINE_HISTORY_KEY = "pipeline_history"
ORIGINAL_DF_KEY = "original_df"
# Indicateur invisible (jamais affiché à l'écran) qui retient si les données
# actuelles viennent du flux "Questionnaires satisfaction" (structure connue,
# colonnes standardisées : Agence, Satisfaction, Resolu...) ou d'un import
# générique ("Fichier brut quelconque" / démo / base externe). Le Tableau de
# bord, le Générateur de rapport et les Tableaux s'appuient dessus pour
# savoir quel moteur activer, SANS que rien ne change visuellement pour le
# flux questionnaire habituel — c'est la seule chose qui bascule.
DATA_KIND_KEY = "current_data_kind"
DATA_KIND_QUESTIONNAIRE = "questionnaire"
DATA_KIND_GENERIC = "generic"


def set_current_dataframe(
    df: pd.DataFrame,
    source_label: str,
    reset_pipeline: bool = True,
    data_kind: str = DATA_KIND_GENERIC,
) -> None:
    st.session_state[DF_KEY] = df
    st.session_state[TYPES_KEY] = detect_column_types(df)
    st.session_state[SOURCE_KEY] = source_label
    st.session_state[DATA_KIND_KEY] = data_kind
    if reset_pipeline:
        st.session_state[ORIGINAL_DF_KEY] = df.copy()
        st.session_state[PIPELINE_HISTORY_KEY] = []


def get_current_data_kind() -> str:
    """Retourne DATA_KIND_QUESTIONNAIRE ou DATA_KIND_GENERIC. Par défaut
    'generic' si jamais renseigné (comportement le plus prudent : un moteur
    générique sur des données qu'on ne reconnaît pas plutôt qu'un moteur
    CIE qui planterait sur des colonnes absentes)."""
    return st.session_state.get(DATA_KIND_KEY, DATA_KIND_GENERIC)


def is_questionnaire_data() -> bool:
    return get_current_data_kind() == DATA_KIND_QUESTIONNAIRE


def reset_pipeline_to_original() -> None:
    """Restaure les données telles qu'elles étaient juste après import/fusion,
    et efface l'historique des étapes appliquées depuis."""
    original = st.session_state.get(ORIGINAL_DF_KEY)
    if original is not None:
        st.session_state[DF_KEY] = original.copy()
        st.session_state[TYPES_KEY] = detect_column_types(st.session_state[DF_KEY])
    st.session_state[PIPELINE_HISTORY_KEY] = []


def has_current_dataframe() -> bool:
    return DF_KEY in st.session_state and st.session_state[DF_KEY] is not None


def get_current_dataframe() -> pd.DataFrame | None:
    return st.session_state.get(DF_KEY)


def get_current_types() -> dict[str, str]:
    return st.session_state.get(TYPES_KEY, {})


def get_current_source() -> str:
    return st.session_state.get(SOURCE_KEY, "")


def apply_pipeline_step(new_df: pd.DataFrame, step_kind: str, label: str, result) -> None:
    """Met à jour les données courantes après l'exécution d'une étape de
    pipeline, et enregistre l'étape dans l'historique (façon log de
    nœuds KNIME exécutés, avec compteur de lignes avant/après)."""
    st.session_state[DF_KEY] = new_df
    st.session_state[TYPES_KEY] = detect_column_types(new_df)
    push_pipeline_step({
        "kind": step_kind,
        "label": label,
        "ok": result.ok,
        "message": result.message,
        "rows_before": result.rows_before,
        "rows_after": result.rows_after,
        "cols_before": result.cols_before,
        "cols_after": result.cols_after,
    })


def push_pipeline_step(step_def: dict) -> None:
    """Ajoute une étape à l'historique du pipeline (pour affichage type
    'nœuds exécutés' et pour pouvoir sauvegarder/rejouer l'enchaînement)."""
    history = st.session_state.setdefault(PIPELINE_HISTORY_KEY, [])
    history.append(step_def)


def get_pipeline_history() -> list[dict]:
    return st.session_state.get(PIPELINE_HISTORY_KEY, [])


def clear_pipeline_history() -> None:
    st.session_state[PIPELINE_HISTORY_KEY] = []


def pop_last_pipeline_step() -> dict | None:
    history = st.session_state.get(PIPELINE_HISTORY_KEY, [])
    if history:
        return history.pop()
    return None


# --- Imports multiples (avant fusion) --------------------------------

def add_raw_import(name: str, df: pd.DataFrame) -> None:
    imports = st.session_state.setdefault(RAW_IMPORTS_KEY, [])
    imports.append({"name": name, "df": df, "tag_column": "", "tag_value": ""})


def list_raw_imports() -> list[dict]:
    return st.session_state.get(RAW_IMPORTS_KEY, [])


def remove_raw_import(index: int) -> None:
    imports = st.session_state.get(RAW_IMPORTS_KEY, [])
    if 0 <= index < len(imports):
        imports.pop(index)


def clear_raw_imports() -> None:
    st.session_state[RAW_IMPORTS_KEY] = []


def require_dataframe_or_stop() -> pd.DataFrame:
    """À appeler en tête de chaque page qui a besoin de données. Affiche un
    message clair et arrête l'exécution de la page si rien n'est chargé,
    plutôt que de laisser une erreur technique apparaître."""
    if not has_current_dataframe():
        st.info(
            "Aucune donnée chargée pour le moment. "
            "Rends-toi sur la page **Préparation** pour importer un fichier "
            "ou générer un jeu de données de démonstration."
        )
        st.stop()
    return get_current_dataframe()


# --- Résumés d'analyse accumulés (pour le rapport global automatique) ------
ANALYSIS_LOG_KEY = "analysis_log"


def log_analysis_summary(summary: dict, source_page: str = "", fig=None) -> None:
    """Enregistre le résumé statistique d'un graphique/test déjà généré,
    pour que le rapport global (viz.comments.generate_full_report) puisse
    ensuite synthétiser TOUT ce qui a été produit pendant la session — sans
    jamais stocker les données brutes, seulement les résumés déjà calculés.

    Si `fig` (figure Plotly) est fourni, une image PNG est capturée et
    stockée avec le résumé (`_chart_image`), pour être ensuite intégrée au
    rapport Word (viz.report_builder.build_word_report). En cas d'échec de
    conversion (ex : kaleido absent), le résumé est quand même enregistré,
    simplement sans image — jamais de plantage pour ça.

    IMPORTANT — déduplication par `source_page` : Streamlit réexécute tout
    le script d'une page à CHAQUE interaction (changer un filtre, cliquer
    un onglet...). Sans déduplication, un simple appel inconditionnel à
    cette fonction dans le corps d'une page ajoutait un nouveau graphique
    (donc une nouvelle image PNG) à chaque rerun, sans jamais rien
    supprimer — la session accumulait des dizaines d'images en mémoire au
    fil d'une navigation pourtant normale, jusqu'à saturer la RAM allouée
    et figer l'application. On remplace donc l'entrée existante pour ce
    même `source_page` plutôt que d'en empiler une nouvelle à chaque fois."""
    log = st.session_state.setdefault(ANALYSIS_LOG_KEY, [])
    entry = dict(summary)
    entry["_source_page"] = source_page
    if fig is not None:
        try:
            from viz.report_builder import figure_to_png_bytes
            image_bytes = figure_to_png_bytes(fig)
            if image_bytes:
                entry["_chart_image"] = image_bytes
        except Exception:  # noqa: BLE001
            pass

    if source_page:
        # Retire toute entrée précédente pour ce même contexte (même page /
        # même graphique) avant d'ajouter la version à jour — évite
        # l'accumulation illimitée décrite ci-dessus.
        log[:] = [e for e in log if e.get("_source_page") != source_page]
    log.append(entry)

    # Filet de sécurité supplémentaire : même avec la déduplication ci-dessus,
    # on plafonne la taille totale du journal (cas où `source_page` ne serait
    # pas renseigné par un appelant) pour ne jamais laisser la mémoire de la
    # session croître sans limite.
    MAX_LOG_ENTRIES = 60
    if len(log) > MAX_LOG_ENTRIES:
        del log[: len(log) - MAX_LOG_ENTRIES]


def get_analysis_log() -> list[dict]:
    return st.session_state.get(ANALYSIS_LOG_KEY, [])


def clear_analysis_log() -> None:
    st.session_state[ANALYSIS_LOG_KEY] = []


def append_new_extract(df_new: pd.DataFrame, source_label: str, data_kind: str = DATA_KIND_QUESTIONNAIRE) -> tuple[int, int]:
    """Ajoute un nouvel extrait (ex : export du jour) aux données déjà
    chargées, pour un usage pluriannuel où l'on ne repart jamais de zéro —
    équivalent du bouton « Actualiser ». Les lignes strictement identiques
    à une ligne déjà présente sont ignorées (pas de doublon). Retourne
    (nombre de lignes réellement ajoutées, nombre de doublons ignorés)."""
    current = get_current_dataframe()
    if current is None or current.empty:
        set_current_dataframe(df_new, source_label=source_label, data_kind=data_kind)
        return len(df_new), 0

    combined = pd.concat([current, df_new], ignore_index=True, sort=False)
    n_before = len(combined)
    combined = combined.drop_duplicates(keep="first").reset_index(drop=True)
    n_after = len(combined)
    n_dupes = n_before - n_after
    n_added = len(df_new) - n_dupes

    new_source = f"{get_current_source()} + {source_label}" if get_current_source() else source_label
    set_current_dataframe(combined, source_label=new_source, reset_pipeline=True, data_kind=data_kind)
    return n_added, n_dupes
