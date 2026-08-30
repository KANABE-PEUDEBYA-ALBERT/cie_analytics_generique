"""
Import de fichiers de structure variable (Excel/CSV) et détection
automatique du type logique de chaque colonne — numérique, catégoriel,
date/heure, texte libre, ou identifiant. Aucune hypothèse n'est faite sur
les noms ou le nombre de colonnes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

import numpy as np
import pandas as pd


@dataclass
class LoadResult:
    ok: bool
    message: str
    df: pd.DataFrame | None = None


def load_uploaded_file(uploaded_file) -> LoadResult:
    """Charge un fichier Streamlit UploadedFile (xlsx, xls ou csv) en
    DataFrame. Ne lève jamais d'exception non gérée : retourne toujours
    un LoadResult avec un message clair en cas d'échec."""
    if uploaded_file is None:
        return LoadResult(False, "Aucun fichier fourni.")

    name = uploaded_file.name.lower()
    raw = uploaded_file.read()

    try:
        if name.endswith((".xlsx", ".xls")):
            xls = pd.ExcelFile(BytesIO(raw))
            if len(xls.sheet_names) > 1:
                # Le choix de la feuille est géré côté page (sélecteur), on
                # charge la première par défaut ici.
                df = xls.parse(xls.sheet_names[0])
            else:
                df = xls.parse(xls.sheet_names[0])
        elif name.endswith(".csv"):
            df = _read_csv_robust(raw)
        else:
            return LoadResult(False, "Format non reconnu. Utilise un fichier .xlsx, .xls ou .csv.")
    except Exception as exc:  # noqa: BLE001 - on veut un message utilisateur, jamais un crash
        return LoadResult(False, f"Impossible de lire le fichier : {exc}")

    if df is None or df.empty:
        return LoadResult(False, "Le fichier a été lu mais ne contient aucune donnée exploitable.")

    df = _clean_column_names(df)
    return LoadResult(True, f"{len(df)} lignes et {len(df.columns)} colonnes chargées.", df)


def _read_csv_robust(raw: bytes) -> pd.DataFrame:
    """Essaie plusieurs séparateurs/encodages courants avant d'abandonner."""
    attempts = [
        {"sep": None, "engine": "python", "encoding": "utf-8"},
        {"sep": ";", "encoding": "utf-8"},
        {"sep": ",", "encoding": "utf-8"},
        {"sep": ";", "encoding": "latin-1"},
        {"sep": ",", "encoding": "latin-1"},
    ]
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            df = pd.read_csv(BytesIO(raw), **kwargs)
            if df.shape[1] > 1:  # une seule colonne = probablement mauvais séparateur
                return df
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise ValueError("Impossible de déterminer le séparateur du fichier CSV.")


def _clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


# --- Détection automatique du type logique de chaque colonne ------------

TYPE_NUMERIC = "numérique"
TYPE_CATEGORICAL = "catégoriel"
TYPE_DATETIME = "date/heure"
TYPE_TEXT = "texte libre"
TYPE_IDENTIFIER = "identifiant"


_ID_NAME_PATTERN = re.compile(
    r"(^|[_\s#/-])(id|identifiant|code|codexp|matricule|n[o°]|num[ée]ro|ref|r[ée]f[ée]rence)($|[_\s#/-])",
    re.IGNORECASE,
)


def _looks_like_identifier_name(col_name: str) -> bool:
    """Heuristique par nom de colonne : 'ID', 'Code', 'N°', 'Matricule'...
    évite par exemple de calculer une moyenne sur une colonne 'ID', même
    si celle-ci se répète après fusion de plusieurs fichiers (uniquement
    numérique en apparence, mais sémantiquement un identifiant)."""
    return bool(_ID_NAME_PATTERN.search(col_name.strip()))


def detect_column_types(df: pd.DataFrame, categorical_threshold: int = 25) -> dict[str, str]:
    """Retourne, pour chaque colonne, un type logique parmi TYPE_*.

    Règles, dans cet ordre de priorité :
    - le NOM de la colonne évoque un identifiant (ID, Code, N°...) ->
      identifiant, même si numérique et même après fusion de fichiers
      (où l'unicité peut chuter, ex: "ID" qui repart de 1 dans chaque
      fichier concaténé) — évite les statistiques dénuées de sens
      (ex: moyenne d'un ID)
    - déjà numérique et quasi toutes les valeurs uniques -> identifiant
    - déjà numérique -> numérique
    - convertible en date sur >80% des valeurs non nulles -> date/heure
    - nombre de valeurs distinctes faible par rapport au nombre de lignes
      -> catégoriel
    - beaucoup de valeurs uniques + texte long -> texte libre
    - beaucoup de valeurs uniques + texte court/numérique -> identifiant
    """
    result: dict[str, str] = {}
    n = len(df)

    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        if non_null.empty:
            result[col] = TYPE_TEXT
            continue

        n_unique = non_null.nunique()
        uniqueness_ratio = n_unique / max(len(non_null), 1)

        if pd.api.types.is_numeric_dtype(series):
            if _looks_like_identifier_name(str(col)):
                result[col] = TYPE_IDENTIFIER
            elif uniqueness_ratio > 0.98 and n > 20:
                result[col] = TYPE_IDENTIFIER
            else:
                result[col] = TYPE_NUMERIC
            continue

        if pd.api.types.is_datetime64_any_dtype(series):
            result[col] = TYPE_DATETIME
            continue

        # Tente une conversion date sur un échantillon
        sample = non_null.astype(str).head(200)
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        if parsed.notna().mean() > 0.8:
            result[col] = TYPE_DATETIME
            continue

        avg_len = non_null.astype(str).str.len().mean()

        if n_unique <= categorical_threshold or uniqueness_ratio < 0.05:
            result[col] = TYPE_CATEGORICAL
        elif uniqueness_ratio > 0.9 and avg_len < 20:
            result[col] = TYPE_IDENTIFIER
        else:
            result[col] = TYPE_TEXT

    return result


def type_badge_color(col_type: str) -> str:
    return {
        TYPE_NUMERIC: "#F7941D",
        TYPE_CATEGORICAL: "#009A44",
        TYPE_DATETIME: "#1A73E8",
        TYPE_TEXT: "#6B7280",
        TYPE_IDENTIFIER: "#9333EA",
    }.get(col_type, "#6B7280")


def numeric_columns(df: pd.DataFrame, types: dict[str, str]) -> list[str]:
    return [c for c, t in types.items() if t == TYPE_NUMERIC]


def categorical_columns(df: pd.DataFrame, types: dict[str, str]) -> list[str]:
    return [c for c, t in types.items() if t == TYPE_CATEGORICAL]


def datetime_columns(df: pd.DataFrame, types: dict[str, str]) -> list[str]:
    return [c for c, t in types.items() if t == TYPE_DATETIME]


def group_columns_by_theme(columns: list[str], min_group_size: int = 2) -> tuple[dict[str, list[str]], list[str]]:
    """Regroupe des colonnes par thème, à partir d'un préfixe partagé avant
    le premier séparateur (« _ », «  », « - »), comme le fait naturellement
    un questionnaire bien nommé (ex : cont_sport, cont_films -> thème
    « Cont »). Ne suppose RIEN sur le domaine (marche sur n'importe quelle
    base) : si aucun préfixe partagé n'émerge, tout part dans « autres »,
    à charge pour l'appelant de se rabattre sur un autre découpage (ex :
    par type de colonne). Retourne (groupes_thématiques, colonnes_isolées)."""
    import re

    raw_groups: dict[str, list[str]] = {}
    isolated: list[str] = []
    for col in columns:
        m = re.split(r"[_\s\-]+", col.strip(), maxsplit=1)
        prefix = m[0].strip().lower() if len(m) > 1 and m[0].strip() else None
        if prefix:
            raw_groups.setdefault(prefix, []).append(col)
        else:
            isolated.append(col)

    themed = {k: v for k, v in raw_groups.items() if len(v) >= min_group_size}
    for k, v in raw_groups.items():
        if len(v) < min_group_size:
            isolated.extend(v)

    # Étiquette lisible : première lettre en majuscule.
    themed_pretty = {k.capitalize(): v for k, v in themed.items()}
    return themed_pretty, isolated
