"""
Moteur de pipeline de préparation des données — l'équivalent applicatif
des nœuds KNIME (Column Filter, Row Filter, Cell Splitter, Ungroup,
Rule Engine / Constant Value Column, GroupBy, Joiner, Concatenate...).

Chaque opération est une fonction pure : (DataFrame, paramètres) ->
(nouveau DataFrame, StepResult). StepResult porte toujours le nombre de
lignes avant/après, pour un affichage type "exécution de nœud".

Une étape de pipeline est représentée par un dict sérialisable en JSON
(kind + params), ce qui permet de sauvegarder l'enchaînement des étapes
et de le rejouer sur un nouveau fichier.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class StepResult:
    ok: bool
    message: str
    rows_before: int
    rows_after: int
    cols_before: int
    cols_after: int


def _wrap(df_before: pd.DataFrame, df_after: pd.DataFrame, message: str, ok: bool = True) -> StepResult:
    return StepResult(
        ok=ok,
        message=message,
        rows_before=len(df_before),
        rows_after=len(df_after),
        cols_before=df_before.shape[1],
        cols_after=df_after.shape[1],
    )


# --- Nettoyage --------------------------------------------------------

def clean_missing(df: pd.DataFrame, columns: list[str] | None, strategy: str) -> tuple[pd.DataFrame, StepResult]:
    """strategy: 'drop_rows' | 'fill_zero' | 'fill_mean' | 'fill_mode' | 'fill_value'"""
    cols = columns or list(df.columns)
    out = df.copy()
    if strategy == "drop_rows":
        out = out.dropna(subset=cols)
    elif strategy == "fill_zero":
        out[cols] = out[cols].fillna(0)
    elif strategy == "fill_mean":
        for c in cols:
            if pd.api.types.is_numeric_dtype(out[c]):
                out[c] = out[c].fillna(out[c].mean())
    elif strategy == "fill_mode":
        for c in cols:
            mode = out[c].mode(dropna=True)
            if not mode.empty:
                out[c] = out[c].fillna(mode.iloc[0])
    msg = f"Valeurs manquantes traitées ({strategy}) sur {len(cols)} colonne(s)."
    return out, _wrap(df, out, msg)


def drop_duplicates(df: pd.DataFrame, columns: list[str] | None) -> tuple[pd.DataFrame, StepResult]:
    out = df.drop_duplicates(subset=columns or None)
    return out, _wrap(df, out, f"{len(df) - len(out)} doublon(s) supprimé(s).")


def trim_whitespace(df: pd.DataFrame, columns: list[str] | None) -> tuple[pd.DataFrame, StepResult]:
    out = df.copy()
    cols = columns or out.select_dtypes(include="object").columns.tolist()
    for c in cols:
        out[c] = out[c].astype(str).str.strip().where(out[c].notna(), out[c])
    return out, _wrap(df, out, f"Espaces superflus supprimés sur {len(cols)} colonne(s).")


# --- Filtrage -----------------------------------------------------------

_OPS = {
    "=": lambda s, v: s.astype(str) == str(v),
    "≠": lambda s, v: s.astype(str) != str(v),
    ">": lambda s, v: pd.to_numeric(s, errors="coerce") > float(v),
    "<": lambda s, v: pd.to_numeric(s, errors="coerce") < float(v),
    ">=": lambda s, v: pd.to_numeric(s, errors="coerce") >= float(v),
    "<=": lambda s, v: pd.to_numeric(s, errors="coerce") <= float(v),
    "contient": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False),
    "est vide": lambda s, v: s.isna() | (s.astype(str).str.strip() == ""),
    "n'est pas vide": lambda s, v: s.notna() & (s.astype(str).str.strip() != ""),
}


def filter_rows(df: pd.DataFrame, column: str, operator: str, value: str = "") -> tuple[pd.DataFrame, StepResult]:
    if column not in df.columns or operator not in _OPS:
        return df, _wrap(df, df, "Filtre ignoré (colonne ou opérateur invalide).", ok=False)
    try:
        mask = _OPS[operator](df[column], value)
    except Exception as exc:  # noqa: BLE001
        return df, _wrap(df, df, f"Filtre non appliqué : {exc}", ok=False)
    out = df[mask]
    return out, _wrap(df, out, f"Filtre « {column} {operator} {value} » : {len(out)} ligne(s) conservée(s).")


def filter_columns(df: pd.DataFrame, keep: list[str]) -> tuple[pd.DataFrame, StepResult]:
    keep = [c for c in keep if c in df.columns]
    out = df[keep]
    return out, _wrap(df, out, f"{len(keep)} colonne(s) conservée(s) sur {df.shape[1]}.")


# --- Renommage / réorganisation -----------------------------------------

def rename_columns(df: pd.DataFrame, mapping: dict[str, str]) -> tuple[pd.DataFrame, StepResult]:
    mapping = {k: v for k, v in mapping.items() if k in df.columns and v.strip()}
    out = df.rename(columns=mapping)
    return out, _wrap(df, out, f"{len(mapping)} colonne(s) renommée(s).")


def reorder_columns(df: pd.DataFrame, order: list[str]) -> tuple[pd.DataFrame, StepResult]:
    order = [c for c in order if c in df.columns]
    remaining = [c for c in df.columns if c not in order]
    out = df[order + remaining]
    return out, _wrap(df, out, "Colonnes réorganisées.")


# --- Découpage de colonnes multi-valeurs (Cell Splitter + Ungroup) ------

def split_multivalue_to_rows(
    df: pd.DataFrame, column: str, delimiter: str = ";", new_column: str | None = None, drop_empty: bool = True
) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Cell Splitter (sortie liste) + Ungroup de KNIME : éclate
    une colonne à valeurs multiples séparées par un délimiteur en une
    ligne par valeur."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)

    out = df.copy()
    target = new_column.strip() if new_column and new_column.strip() else column
    out[target] = out[column].astype(str).str.split(delimiter)
    out = out.explode(target, ignore_index=True)
    out[target] = out[target].astype(str).str.strip()
    if drop_empty:
        out = out[out[target] != ""]
        out = out[out[target].str.lower() != "nan"]
    return out, _wrap(df, out, f"« {column} » éclaté sur « {delimiter} » : {len(df)} → {len(out)} ligne(s).")


# --- Colonnes calculées / constantes (Rule Engine / Constant Value Column)

def add_constant_column(df: pd.DataFrame, column: str, value, dtype: str = "texte") -> tuple[pd.DataFrame, StepResult]:
    out = df.copy()
    if dtype == "nombre":
        try:
            value = float(value)
            if value.is_integer():
                value = int(value)
        except (TypeError, ValueError):
            pass
    out[column] = value
    return out, _wrap(df, out, f"Colonne constante « {column} » = {value} ajoutée.")


import re as _re

_IDENTIFIER_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def add_computed_column(df: pd.DataFrame, column: str, expression: str) -> tuple[pd.DataFrame, StepResult]:
    """Colonne calculée à partir d'une expression Python restreinte, ex :
    "Nbre * 2", "np.where(Nbre > 1, 'haut', 'bas')". Les noms de colonnes
    contenant des espaces doivent être entre backticks : `Heure de début`.
    L'évaluation se fait dans un environnement sans accès aux fonctions
    Python natives dangereuses (builtins désactivés), seules les colonnes
    du tableau, numpy (np) et pandas (pd) sont accessibles."""
    out = df.copy()
    local_vars: dict = {"np": np, "pd": pd}

    safe_expr = expression
    for col_name in _re.findall(r"`([^`]+)`", expression):
        if col_name not in out.columns:
            return df, _wrap(df, df, f"Colonne inconnue dans l'expression : « {col_name} »", ok=False)
        safe_name = f"_col_{abs(hash(col_name)) % 10**8}"
        safe_expr = safe_expr.replace(f"`{col_name}`", safe_name)
        local_vars[safe_name] = out[col_name]

    for col_name in out.columns:
        if _IDENTIFIER_RE.match(str(col_name)) and str(col_name) not in local_vars:
            local_vars[str(col_name)] = out[col_name]

    try:
        result = eval(safe_expr, {"__builtins__": {}}, local_vars)  # noqa: S307 - namespace restreint volontairement
    except Exception as exc:  # noqa: BLE001
        return df, _wrap(df, df, f"Expression invalide : {exc}", ok=False)

    out[column] = result
    return out, _wrap(df, out, f"Colonne calculée « {column} » ajoutée.")


# --- Agrégation (GroupBy) ------------------------------------------------

_AGG_FUNCS = {"somme": "sum", "moyenne": "mean", "comptage": "count", "min": "min", "max": "max",
              "médiane": "median", "écart-type": "std"}


def groupby_aggregate(
    df: pd.DataFrame, group_cols: list[str], agg_col: str, agg_func: str
) -> tuple[pd.DataFrame, StepResult]:
    func = _AGG_FUNCS.get(agg_func, "count")
    try:
        out = df.groupby(group_cols, dropna=False)[agg_col].agg(func).reset_index()
        out = out.rename(columns={agg_col: f"{agg_col} ({agg_func})"})
    except Exception as exc:  # noqa: BLE001
        return df, _wrap(df, df, f"Agrégation impossible : {exc}", ok=False)
    return out, _wrap(df, out, f"Regroupement par {group_cols} : {len(out)} groupe(s) obtenu(s).")


# --- Fusion / Jointure (Concatenate / Joiner) ----------------------------

def concat_datasets(dfs: list[pd.DataFrame]) -> tuple[pd.DataFrame, StepResult]:
    if not dfs:
        return pd.DataFrame(), StepResult(False, "Aucun jeu de données à fusionner.", 0, 0, 0, 0)
    total_before = sum(len(d) for d in dfs)
    out = pd.concat(dfs, ignore_index=True, sort=False)
    result = StepResult(
        ok=True,
        message=f"{len(dfs)} jeux fusionnés — {total_before} lignes au total ({len(out)} après fusion).",
        rows_before=total_before,
        rows_after=len(out),
        cols_before=max((d.shape[1] for d in dfs), default=0),
        cols_after=out.shape[1],
    )
    return out, result


def join_datasets(
    left: pd.DataFrame, right: pd.DataFrame, on: str, how: str = "left"
) -> tuple[pd.DataFrame, StepResult]:
    try:
        out = left.merge(right, on=on, how=how, suffixes=("", "_droite"))
    except Exception as exc:  # noqa: BLE001
        return left, _wrap(left, left, f"Jointure impossible : {exc}", ok=False)
    return out, _wrap(left, out, f"Jointure ({how}) sur « {on} » : {len(out)} ligne(s) résultantes.")


# --- Registre des opérations, pour piloter l'UI dynamiquement -----------

STEP_LABELS = {
    "clean_missing": "🧽 Nettoyer les valeurs manquantes",
    "drop_duplicates": "🗑️ Supprimer les doublons",
    "trim_whitespace": "✂️ Supprimer les espaces superflus",
    "filter_rows": "🔎 Filtrer des lignes",
    "filter_columns": "📐 Filtrer des colonnes",
    "rename_columns": "🏷️ Renommer des colonnes",
    "split_multivalue": "✂️ Découper une colonne multi-valeurs en lignes",
    "add_constant_column": "➕ Ajouter une colonne constante",
    "add_computed_column": "🧮 Ajouter une colonne calculée",
    "groupby_aggregate": "Σ Regrouper / agréger",
}


# ==========================================================================
# Opérations supplémentaires — complètent le moteur ci-dessus pour couvrir
# davantage de nœuds KNIME courants (hors régression, jugée non utile ici).
# ==========================================================================

# --- Colonnes : concaténation, suppression, réorganisation --------------

def concatenate_columns(
    df: pd.DataFrame, columns: list[str], separator: str, new_column: str
) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Column Combiner / String Manipulation (join) : fusionne
    plusieurs colonnes texte en une seule, séparées par `separator`."""
    cols = [c for c in columns if c in df.columns]
    if len(cols) < 2 or not new_column.strip():
        return df, _wrap(df, df, "Choisis au moins 2 colonnes et un nom de colonne de sortie.", ok=False)
    out = df.copy()
    out[new_column] = out[cols].astype(str).agg(separator.join, axis=1)
    return out, _wrap(df, out, f"« {new_column} » = concaténation de {len(cols)} colonne(s).")


def drop_columns(df: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Column Filter (mode exclusion) : retire les colonnes
    choisies plutôt que de devoir cocher toutes celles à garder."""
    cols = [c for c in columns if c in df.columns]
    out = df.drop(columns=cols)
    return out, _wrap(df, out, f"{len(cols)} colonne(s) supprimée(s) : {', '.join(cols) if cols else '(aucune)'}.")


# --- Types et texte -------------------------------------------------------

def convert_type(df: pd.DataFrame, column: str, target_type: str) -> tuple[pd.DataFrame, StepResult]:
    """target_type : 'texte' | 'nombre' | 'date'. Équivalent String to
    Number / Number to String / String to Date&Time de KNIME."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    try:
        if target_type == "nombre":
            out[column] = pd.to_numeric(out[column], errors="coerce")
        elif target_type == "date":
            out[column] = pd.to_datetime(out[column], errors="coerce")
        else:
            out[column] = out[column].astype(str)
    except Exception as exc:  # noqa: BLE001
        return df, _wrap(df, df, f"Conversion impossible : {exc}", ok=False)
    n_na = int(out[column].isna().sum()) if target_type != "texte" else 0
    msg = f"« {column} » converti(e) en {target_type}."
    if n_na:
        msg += f" {n_na} valeur(s) non convertible(s) devenue(s) manquante(s)."
    return out, _wrap(df, out, msg)


def text_case(df: pd.DataFrame, columns: list[str], mode: str) -> tuple[pd.DataFrame, StepResult]:
    """mode : 'majuscules' | 'minuscules' | 'première_lettre'. Équivalent
    String Manipulation (upperCase / lowerCase / capitalize)."""
    cols = [c for c in columns if c in df.columns]
    out = df.copy()
    for c in cols:
        series = out[c].astype(str)
        if mode == "majuscules":
            out[c] = series.str.upper()
        elif mode == "minuscules":
            out[c] = series.str.lower()
        else:
            out[c] = series.str.title()
    return out, _wrap(df, out, f"Casse du texte modifiée ({mode}) sur {len(cols)} colonne(s).")


def replace_values(
    df: pd.DataFrame, column: str, old_value: str, new_value: str, whole_match: bool = True
) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent String Replacer / Rule Engine simple : remplace une
    valeur par une autre dans une colonne. `whole_match=False` remplace
    aussi les occurrences à l'intérieur d'un texte plus long."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    series = out[column].astype(str)
    if whole_match:
        mask = series == old_value
        out.loc[mask, column] = new_value
        n = int(mask.sum())
    else:
        n = int(series.str.contains(old_value, regex=False, na=False).sum())
        out[column] = series.str.replace(old_value, new_value, regex=False)
    return out, _wrap(df, out, f"« {old_value} » → « {new_value} » : {n} valeur(s) remplacée(s) dans « {column} ».")


def regex_extract(df: pd.DataFrame, column: str, pattern: str, new_column: str) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Regex Extractor : extrait la première correspondance
    d'une expression régulière dans une nouvelle colonne."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    try:
        extracted = out[column].astype(str).str.extract(pattern, expand=False)
    except Exception as exc:  # noqa: BLE001
        return df, _wrap(df, df, f"Expression régulière invalide : {exc}", ok=False)
    out[new_column] = extracted
    n_found = int(extracted.notna().sum())
    return out, _wrap(df, out, f"« {new_column} » extrait de « {column} » : {n_found} correspondance(s) trouvée(s).")


# --- Dates et heures -------------------------------------------------------

_DATE_PARTS = {
    "année": lambda s: s.dt.year,
    "mois": lambda s: s.dt.month,
    "jour": lambda s: s.dt.day,
    "heure": lambda s: s.dt.hour,
    "minute": lambda s: s.dt.minute,
    "seconde": lambda s: s.dt.second,
    "jour_semaine": lambda s: s.dt.day_name(),
    "trimestre": lambda s: s.dt.quarter,
    "semaine_année": lambda s: s.dt.isocalendar().week,
}


def extract_date_part(df: pd.DataFrame, column: str, part: str, new_column: str) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Extract Date&Time Fields : isole année/mois/jour/heure/
    minute/seconde/jour de semaine/trimestre/semaine à partir d'une colonne
    date — utile pour comparer l'évolution d'un phénomène dans le temps."""
    if column not in df.columns or part not in _DATE_PARTS:
        return df, _wrap(df, df, "Colonne ou partie de date invalide.", ok=False)
    out = df.copy()
    dt_series = pd.to_datetime(out[column], errors="coerce")
    out[new_column] = _DATE_PARTS[part](dt_series)
    return out, _wrap(df, out, f"« {new_column} » = {part} extrait(e) de « {column} ».")


_DATE_DIFF_UNITS = {
    "jours": lambda delta: delta.dt.total_seconds() / 86400,
    "heures": lambda delta: delta.dt.total_seconds() / 3600,
    "minutes": lambda delta: delta.dt.total_seconds() / 60,
    "secondes": lambda delta: delta.dt.total_seconds(),
}


def date_difference(
    df: pd.DataFrame, start_col: str, end_col: str, unit: str, new_column: str
) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Date&Time Difference : calcule l'écart entre deux
    colonnes date/heure (jours, heures, minutes ou secondes)."""
    if start_col not in df.columns or end_col not in df.columns or unit not in _DATE_DIFF_UNITS:
        return df, _wrap(df, df, "Colonnes ou unité invalides.", ok=False)
    out = df.copy()
    start = pd.to_datetime(out[start_col], errors="coerce")
    end = pd.to_datetime(out[end_col], errors="coerce")
    delta = end - start
    out[new_column] = _DATE_DIFF_UNITS[unit](delta).round(2)
    return out, _wrap(df, out, f"« {new_column} » = « {end_col} » − « {start_col} » (en {unit}).")


def combine_date_time(
    df: pd.DataFrame, date_col: str, time_col: str, new_column: str
) -> tuple[pd.DataFrame, StepResult]:
    """Combine une colonne date et une colonne heure séparées en une seule
    colonne date/heure complète — utile quand un questionnaire enregistre
    la date et l'heure dans deux colonnes distinctes."""
    if date_col not in df.columns or time_col not in df.columns:
        return df, _wrap(df, df, "Colonnes introuvables.", ok=False)
    out = df.copy()
    date_part = pd.to_datetime(out[date_col], errors="coerce").dt.date.astype(str)
    time_part = out[time_col].astype(str)
    combined = pd.to_datetime(date_part + " " + time_part, errors="coerce")
    out[new_column] = combined
    n_ok = int(combined.notna().sum())
    return out, _wrap(df, out, f"« {new_column} » combine « {date_col} » et « {time_col} » : {n_ok} valeur(s) valide(s).")


# --- Numérique --------------------------------------------------------------

def round_numeric(df: pd.DataFrame, columns: list[str], decimals: int) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Round Double."""
    cols = [c for c in columns if c in df.columns]
    out = df.copy()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(decimals)
    return out, _wrap(df, out, f"{len(cols)} colonne(s) arrondie(s) à {decimals} décimale(s).")


def clip_numeric(df: pd.DataFrame, column: str, min_val: float | None, max_val: float | None) -> tuple[pd.DataFrame, StepResult]:
    """Plafonne une colonne numérique entre un minimum et un maximum —
    utile pour neutraliser des valeurs aberrantes de saisie sans supprimer
    les lignes concernées."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    series = pd.to_numeric(out[column], errors="coerce")
    n_clipped = int(((series < min_val) if min_val is not None else False).sum() if min_val is not None else 0)
    n_clipped += int(((series > max_val) if max_val is not None else False).sum() if max_val is not None else 0)
    out[column] = series.clip(lower=min_val, upper=max_val)
    return out, _wrap(df, out, f"« {column} » plafonnée entre {min_val} et {max_val} : {n_clipped} valeur(s) ajustée(s).")


def bin_numeric(
    df: pd.DataFrame, column: str, n_bins: int, new_column: str
) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Auto-Binner (largeur égale) : découpe une colonne
    numérique en `n_bins` tranches, pour l'analyser comme une variable
    catégorielle (ex : tranches d'âge)."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    series = pd.to_numeric(out[column], errors="coerce")
    try:
        out[new_column] = pd.cut(series, bins=n_bins).astype(str)
    except Exception as exc:  # noqa: BLE001
        return df, _wrap(df, df, f"Découpage impossible : {exc}", ok=False)
    return out, _wrap(df, out, f"« {new_column} » = « {column} » découpée en {n_bins} tranches.")


def normalize_numeric(df: pd.DataFrame, column: str, method: str, new_column: str) -> tuple[pd.DataFrame, StepResult]:
    """method : 'minmax' (0-1) | 'zscore' (centrée-réduite). Équivalent
    Normalizer."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    series = pd.to_numeric(out[column], errors="coerce")
    if method == "minmax":
        lo, hi = series.min(), series.max()
        out[new_column] = (series - lo) / (hi - lo) if hi != lo else 0.0
    else:
        mean, std = series.mean(), series.std()
        out[new_column] = (series - mean) / std if std else 0.0
    return out, _wrap(df, out, f"« {new_column} » = « {column} » normalisée ({method}).")


def rank_rows(df: pd.DataFrame, column: str, ascending: bool, new_column: str) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Rank : attribue un rang à chaque ligne selon une colonne
    numérique (1 = plus petite valeur, ou plus grande si ascending=False)."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    out[new_column] = pd.to_numeric(out[column], errors="coerce").rank(ascending=ascending, method="min").astype("Int64")
    return out, _wrap(df, out, f"« {new_column} » = rang selon « {column} » ({'croissant' if ascending else 'décroissant'}).")


def column_arithmetic(
    df: pd.DataFrame, col_a: str, operator: str, operand_b: str, new_column: str
) -> tuple[pd.DataFrame, StepResult]:
    """Opération arithmétique simple sans écrire de formule : colonne A
    (opérateur) colonne B OU une constante numérique. `operand_b` est soit
    le nom d'une colonne existante, soit un nombre saisi directement."""
    if col_a not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    out = df.copy()
    a = pd.to_numeric(out[col_a], errors="coerce")
    if operand_b in df.columns:
        b = pd.to_numeric(out[operand_b], errors="coerce")
        b_label = operand_b
    else:
        try:
            b = float(operand_b)
        except (TypeError, ValueError):
            return df, _wrap(df, df, f"« {operand_b} » n'est ni une colonne ni un nombre valide.", ok=False)
        b_label = operand_b
    try:
        if operator == "+":
            out[new_column] = a + b
        elif operator == "-":
            out[new_column] = a - b
        elif operator == "×":
            out[new_column] = a * b
        elif operator == "÷":
            out[new_column] = a / b.replace(0, np.nan) if hasattr(b, "replace") else (a / b if b else np.nan)
        else:
            return df, _wrap(df, df, "Opérateur invalide.", ok=False)
    except Exception as exc:  # noqa: BLE001
        return df, _wrap(df, df, f"Calcul impossible : {exc}", ok=False)
    return out, _wrap(df, out, f"« {new_column} » = « {col_a} » {operator} {b_label}.")


# --- Lignes -------------------------------------------------------------

def sort_rows(df: pd.DataFrame, columns: list[str], ascending: bool) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Sorter."""
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return df, _wrap(df, df, "Choisis au moins une colonne de tri.", ok=False)
    out = df.sort_values(by=cols, ascending=ascending).reset_index(drop=True)
    return out, _wrap(df, out, f"Trié par {', '.join(cols)} ({'croissant' if ascending else 'décroissant'}).")


def sample_rows(df: pd.DataFrame, n: int, method: str) -> tuple[pd.DataFrame, StepResult]:
    """method : 'aléatoire' | 'premières' | 'dernières'. Équivalent Row
    Sampling — utile pour travailler sur un extrait avant d'appliquer un
    traitement à l'ensemble des données."""
    n = max(1, min(n, len(df)))
    if method == "aléatoire":
        out = df.sample(n=n, random_state=42).reset_index(drop=True)
    elif method == "dernières":
        out = df.tail(n).reset_index(drop=True)
    else:
        out = df.head(n).reset_index(drop=True)
    return out, _wrap(df, out, f"Échantillon de {n} ligne(s) ({method}).")


# --- Restructuration (Pivot / Unpivot / One-to-Many) ---------------------

def melt_to_long(
    df: pd.DataFrame, id_vars: list[str], value_vars: list[str], var_name: str, value_name: str
) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent Unpivot : transforme plusieurs colonnes de valeurs (ex :
    une colonne par année d'enquête) en deux colonnes « variable » /
    « valeur », une ligne par combinaison — pratique pour comparer
    l'évolution d'un indicateur réparti sur plusieurs colonnes-périodes."""
    id_vars = [c for c in id_vars if c in df.columns]
    value_vars = [c for c in value_vars if c in df.columns]
    if not value_vars:
        return df, _wrap(df, df, "Choisis au moins une colonne à dépivoter.", ok=False)
    out = df.melt(id_vars=id_vars, value_vars=value_vars, var_name=var_name, value_name=value_name)
    return out, _wrap(df, out, f"Dépivoté : {len(value_vars)} colonne(s) → « {var_name} » / « {value_name} » ({len(out)} ligne(s)).")


def one_hot_encode(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, StepResult]:
    """Équivalent One to Many : transforme une colonne catégorielle en
    plusieurs colonnes 0/1, une par modalité."""
    if column not in df.columns:
        return df, _wrap(df, df, "Colonne introuvable.", ok=False)
    dummies = pd.get_dummies(df[column].astype(str), prefix=column).astype(int)
    out = pd.concat([df, dummies], axis=1)
    return out, _wrap(df, out, f"« {column} » encodée en {dummies.shape[1]} colonne(s) 0/1.")


# --- Registre complémentaire ----------------------------------------------

STEP_LABELS.update({
    "concatenate_columns": "🔗 Concaténer des colonnes",
    "drop_columns": "🚫 Supprimer des colonnes",
    "convert_type": "🔁 Convertir le type d'une colonne",
    "text_case": "🔠 Changer la casse du texte",
    "replace_values": "♻️ Remplacer une valeur",
    "regex_extract": "🧩 Extraire un motif (regex)",
    "extract_date_part": "📆 Extraire une partie de date",
    "date_difference": "⏱️ Calculer un écart de dates",
    "combine_date_time": "🕒 Combiner date + heure",
    "round_numeric": "🔢 Arrondir des nombres",
    "clip_numeric": "🧱 Plafonner des valeurs numériques",
    "bin_numeric": "📊 Découper en tranches (binning)",
    "normalize_numeric": "📐 Normaliser une colonne numérique",
    "rank_rows": "🏅 Calculer un rang",
    "column_arithmetic": "➗ Calcul simple entre colonnes",
    "sort_rows": "↕️ Trier les lignes",
    "sample_rows": "🎲 Échantillonner des lignes",
    "melt_to_long": "🔄 Dépivoter (colonnes → lignes)",
    "one_hot_encode": "🏷️ Encoder en colonnes 0/1",
    "reorder_columns": "↔️ Réorganiser les colonnes",
})
