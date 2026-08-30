"""
Module dédié : questionnaires de satisfaction « Votre expérience en agence ».

Toute l'application est désormais recentrée sur UN SEUL type de source :
les exports Microsoft Forms du questionnaire de satisfaction déposé après
visite en agence — un fichier par agence (ex : « Questionnaire votre
expérience en agence ABOBO CENTRE »), à fusionner pour couvrir les ~15
agences et les différentes directions.

Ce module :
1. reconnaît la structure de ce questionnaire quelle que soit sa mise en
   page exacte dans le fichier (recherche par mots-clés d'en-tête, pas par
   position de colonne) ;
2. nettoie et normalise chaque réponse (score de satisfaction, résolution,
   durée de traitement, motif d'insatisfaction, item le plus apprécié...) ;
3. fusionne plusieurs fichiers agence en une seule base, en déduisant le
   nom de l'agence depuis le nom de fichier si aucune colonne « Agence »
   n'est présente ;
4. calcule plus d'une quinzaine d'indicateurs de satisfaction ET de
   performance, globaux et par agence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO

import numpy as np
import pandas as pd

# --- Reconnaissance des colonnes du questionnaire (par mots-clés) ----------

_HEADER_KEYWORDS: dict[str, list[str]] = {
    "horodatage_debut": ["heure de début", "heure de debut"],
    "horodatage_fin": ["heure de fin"],
    "satisfaction": ["comment évalueriez vous votre passage", "comment evalueriez vous votre passage"],
    "motif_insatisfaction": ["motif d'insatisfaction", "motif d insatisfaction"],
    "apprecie": ["plus apprécié", "plus apprecie"],
    "resolu": ["a t-elle été résolue", "a t elle ete resolue", "résolue", "resolue"],
    "commentaire": ["partager vos commentaires", "partagez vos commentaires", "merci de nous partager"],
    "nom_repondant": ["partagez- nous votre nom", "partagez-nous votre nom", "partagez votre nom"],
    "contact": ["contact téléphonique", "contact telephonique"],
}

# Colonnes de type "Points - ..." / "Feedback - ..." générées par Forms :
# sans valeur analytique ici (système de quiz), on les ignore explicitement.
_IGNORE_PREFIXES = ("points - ", "points-", "feedback - ", "feedback-", "quiz feedback", "total points", "id",
                     "adresse de messagerie")

# Échelle de satisfaction -> score numérique (1 à 5), pour pouvoir calculer
# une moyenne, une médiane, et détecter la tendance (pas seulement des %).
_SATISFACTION_SCALE: dict[str, int] = {
    # Ordre volontaire : les libellés les plus spécifiques/longs d'abord.
    # "satisfait" est un sous-mot de "très satisfait" ("insatisfait" aussi
    # le contient) — si on le teste en premier, TOUTE réponse "Très satisfait"
    # matche à tort "satisfait" et se retrouve notée 4 au lieu de 5 (bug
    # corrigé ici : les variantes "très ..." doivent être vérifiées avant
    # leur forme courte).
    "très insatisfait": 1,
    "tres insatisfait": 1,
    "très satisfait": 5,
    "tres satisfait": 5,
    "insatisfait": 2,
    "neutre": 3,
    "satisfait": 4,
}


def _norm(text: str) -> str:
    return str(text).strip().lower()


def _find_column(columns: list[str], keywords: list[str]) -> str | None:
    for col in columns:
        c = _norm(col)
        for kw in keywords:
            if kw in c:
                return col
    return None


def _satisfaction_to_score(raw: str | float) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = _norm(raw)
    # retire les émojis / ponctuation, ne garde que les mots
    text = re.sub(r"[^\wàâäéèêëïîôöùûüç\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    for label, score in _SATISFACTION_SCALE.items():
        if label in text:
            return score
    return None


def _score_to_label(score: float) -> str:
    mapping = {1: "😞 Très insatisfait", 2: "🙁 Insatisfait", 3: "😐 Neutre", 4: "🙂 Satisfait", 5: "😃 Très satisfait"}
    return mapping.get(round(score), "—")


def guess_agency_from_filename(filename: str) -> str:
    """Déduit un nom d'agence lisible depuis un nom de fichier d'export Forms,
    ex : « Questionnaire_votre_expérience_en_agence_abobo_centre_1-94_.xlsx »
    -> « ABOBO CENTRE ». Ne plante jamais : au pire renvoie le nom de fichier
    nettoyé."""
    name = re.sub(r"\.(xlsx|xls|csv)$", "", filename, flags=re.IGNORECASE)
    name = re.sub(r"^\d+[_\-]*", "", name)  # préfixe numérique d'upload éventuel
    name = re.sub(r"[\(\[].*?[\)\]]", " ", name)  # parenthèses/crochets
    name = re.sub(r"[_\-]+", " ", name)  # underscores/tirets -> espaces, AVANT recherche du marqueur
    name = re.sub(r"\s+", " ", name).strip()
    low = name.lower()
    marker = "en agence"
    idx = low.find(marker)
    if idx != -1:
        tail = name[idx + len(marker):]
    else:
        tail = name
    tail = re.sub(r"\b\d[\d ]*\b", " ", tail)  # plages "1 94" etc.
    tail = re.sub(r"\s+", " ", tail).strip(" -_.")
    if not tail:
        tail = name.strip()
    return tail.upper() if tail else "AGENCE INCONNUE"


@dataclass
class QuestionnaireLoadResult:
    ok: bool
    message: str
    df: pd.DataFrame | None = None
    n_rows: int = 0
    # DataFrame brut, TEL QUE dans le fichier Excel/CSV d'origine (avant
    # tout renommage ou colonne calculée) — demande explicite : "je n'ai
    # pas demandé d'inventer des variables... toutes les variables que tu
    # vois dans Excel doivent être ici, exactement comme si on avait
    # ouvert le fichier Excel". Conservé UNIQUEMENT pour l'aperçu affiché
    # à l'utilisateur ; le reste de l'application (graphiques, KPI,
    # rapports) continue d'utiliser `df` (la version standardisée), qui
    # reste indispensable à tous les calculs.
    raw_df: pd.DataFrame | None = None


def load_questionnaire_file(uploaded_file, agence_override: str | None = None) -> QuestionnaireLoadResult:
    """Lit UN export Forms (une agence) et retourne une base nettoyée avec
    des colonnes stables, quel que soit l'ordre des colonnes dans le fichier
    d'origine."""
    if uploaded_file is None:
        return QuestionnaireLoadResult(False, "Aucun fichier fourni.")

    name = uploaded_file.name
    raw = uploaded_file.read()

    try:
        if name.lower().endswith((".xlsx", ".xls")):
            xls = pd.ExcelFile(BytesIO(raw))
            raw_df = xls.parse(xls.sheet_names[0])
        elif name.lower().endswith(".csv"):
            raw_df = pd.read_csv(BytesIO(raw))
        else:
            return QuestionnaireLoadResult(False, f"« {name} » : format non reconnu (.xlsx/.xls/.csv attendu).")
    except Exception as exc:  # noqa: BLE001
        return QuestionnaireLoadResult(False, f"« {name} » : impossible à lire ({exc}).")

    if raw_df is None or raw_df.empty:
        return QuestionnaireLoadResult(False, f"« {name} » : fichier vide.")

    raw_df.columns = [str(c).strip() for c in raw_df.columns]
    cols = list(raw_df.columns)

    col_debut = _find_column(cols, _HEADER_KEYWORDS["horodatage_debut"])
    col_fin = _find_column(cols, _HEADER_KEYWORDS["horodatage_fin"])
    col_satisf = _find_column(cols, _HEADER_KEYWORDS["satisfaction"])
    col_motif = _find_column(cols, _HEADER_KEYWORDS["motif_insatisfaction"])
    col_apprecie = _find_column(cols, _HEADER_KEYWORDS["apprecie"])
    col_resolu = _find_column(cols, _HEADER_KEYWORDS["resolu"])
    col_commentaire = _find_column(cols, _HEADER_KEYWORDS["commentaire"])
    col_nom = _find_column(cols, _HEADER_KEYWORDS["nom_repondant"])
    col_contact = _find_column(cols, _HEADER_KEYWORDS["contact"])

    if col_satisf is None:
        return QuestionnaireLoadResult(
            False,
            f"« {name} » : colonne de satisfaction introuvable — ce fichier ne ressemble pas à un "
            "export du questionnaire « Votre expérience en agence ».",
        )

    agence = (agence_override or "").strip() or guess_agency_from_filename(name)

    # TOUTES les colonnes d'origine du fichier Excel/CSV sont conservées
    # telles quelles, sans exception — demande explicite : "les variables
    # que tu vois dans Excel doivent être ici, exactement comme ça". Avant,
    # cette fonction repartait d'un DataFrame VIDE et ne gardait QUE les
    # colonnes internes standardisées ci-dessous, perdant purement et
    # simplement tous les en-têtes et données d'origine du fichier déposé.
    #
    # Les colonnes ci-dessous (Agence, Satisfaction, Score_satisfaction,
    # Resolu...) restent nécessaires : tout le reste de l'application (
    # indicateurs, graphiques, Tableau de bord) les lit par ce nom précis.
    # Elles sont ajoutées EN PLUS des colonnes d'origine — jamais à la
    # place — et seulement si aucune colonne du fichier ne porte déjà
    # exactement ce nom (pour ne jamais écraser une vraie colonne du
    # fichier déposé par une valeur recalculée).
    out = raw_df.copy()
    computed: dict[str, object] = {}
    computed["Agence"] = [agence] * len(raw_df)

    if col_debut:
        computed["Horodatage"] = pd.to_datetime(raw_df[col_debut], errors="coerce")
    else:
        computed["Horodatage"] = pd.NaT

    if col_debut and col_fin:
        debut = pd.to_datetime(raw_df[col_debut], errors="coerce")
        fin = pd.to_datetime(raw_df[col_fin], errors="coerce")
        duree = (fin - debut).dt.total_seconds() / 60.0
        computed["Duree_reponse_min"] = duree.where(duree >= 0)
    else:
        computed["Duree_reponse_min"] = np.nan

    computed["Satisfaction"] = raw_df[col_satisf].astype(str).where(raw_df[col_satisf].notna())
    computed["Score_satisfaction"] = raw_df[col_satisf].apply(_satisfaction_to_score)

    if col_motif:
        computed["Motif_insatisfaction"] = raw_df[col_motif].astype(str).where(raw_df[col_motif].notna())
    else:
        computed["Motif_insatisfaction"] = np.nan

    if col_apprecie:
        apprecie_raw = raw_df[col_apprecie].astype(str).where(raw_df[col_apprecie].notna())
        computed["Apprecie_liste"] = apprecie_raw
        computed["Apprecie_principal"] = apprecie_raw.apply(
            lambda v: [x.strip() for x in str(v).split(";") if x.strip()][0] if isinstance(v, str) and v.strip() else None
        )
        computed["Nb_items_apprecies"] = apprecie_raw.apply(
            lambda v: len([x for x in str(v).split(";") if x.strip()]) if isinstance(v, str) and v.strip() else 0
        )
    else:
        computed["Apprecie_liste"] = np.nan
        computed["Apprecie_principal"] = np.nan
        computed["Nb_items_apprecies"] = 0

    if col_resolu:
        resolu_norm = raw_df[col_resolu].astype(str).str.strip().str.upper()
        computed["Resolu"] = resolu_norm.where(raw_df[col_resolu].notna())
    else:
        computed["Resolu"] = np.nan

    if col_commentaire:
        computed["Commentaire"] = raw_df[col_commentaire].astype(str).where(raw_df[col_commentaire].notna())
    else:
        computed["Commentaire"] = np.nan

    a_laisse_nom = raw_df[col_nom].notna() if col_nom else pd.Series([False] * len(raw_df))
    a_laisse_tel = raw_df[col_contact].notna() if col_contact else pd.Series([False] * len(raw_df))
    computed["A_laisse_nom"] = a_laisse_nom
    computed["A_laisse_telephone"] = a_laisse_tel
    computed["A_laisse_contact"] = (a_laisse_nom | a_laisse_tel)

    commentaire_col = computed.get("Commentaire")
    if commentaire_col is None:
        commentaire_col = out.get("Commentaire")
    if isinstance(commentaire_col, pd.Series):
        computed["A_commente"] = commentaire_col.notna() & (commentaire_col.astype(str).str.strip() != "")
    else:
        computed["A_commente"] = pd.Series([False] * len(raw_df))

    for col_name, values in computed.items():
        if col_name not in out.columns:
            out[col_name] = values

    return QuestionnaireLoadResult(True, f"« {name} » : {len(out)} réponse(s) — agence détectée « {agence} ».", out, len(out), raw_df=raw_df)


def merge_questionnaires(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Fusionne plusieurs bases agence déjà nettoyées en une seule, pour
    couvrir l'ensemble des agences et directions."""
    if not dfs:
        return pd.DataFrame()
    merged = pd.concat(dfs, ignore_index=True, sort=False)
    if "Horodatage" in merged.columns:
        merged = merged.sort_values("Horodatage", na_position="last").reset_index(drop=True)
    return merged


# --- Indicateurs -------------------------------------------------------

@dataclass
class Indicators:
    n_reponses: int = 0
    n_agences: int = 0
    periode_min: pd.Timestamp | None = None
    periode_max: pd.Timestamp | None = None

    taux_tres_satisfait: float = 0.0
    taux_satisfait: float = 0.0
    taux_neutre: float = 0.0
    taux_insatisfait: float = 0.0
    taux_tres_insatisfait: float = 0.0

    taux_satisfaction_global: float = 0.0     # Très satisfait + Satisfait
    taux_insatisfaction_global: float = 0.0   # Très insatisfait + Insatisfait
    score_moyen: float = 0.0                  # 1 à 5
    score_mediane: float = 0.0

    taux_resolution: float = 0.0
    n_non_resolu: int = 0

    duree_moyenne_min: float | None = None
    duree_mediane_min: float | None = None

    taux_completion_commentaire: float = 0.0
    taux_contact_partage: float = 0.0
    n_telephones: int = 0
    taux_telephone: float = 0.0
    n_noms: int = 0
    n_commentaires: int = 0
    n_verbatims_negatifs_estimes: int = 0
    n_reponses_tres_rapides: int = 0  # < 1 minute : réponses probablement peu réfléchies
    taux_multi_appreciation: float = 0.0  # part des répondants ayant coché plusieurs items appréciés

    item_plus_apprecie: str = "—"
    item_plus_apprecie_taux: float = 0.0
    motif_insatisfaction_principal: str = "—"
    motif_insatisfaction_taux: float = 0.0

    agence_top: str = "—"
    agence_top_score: float = 0.0
    agence_bottom: str = "—"
    agence_bottom_score: float = 0.0

    par_agence: pd.DataFrame = field(default_factory=pd.DataFrame)


def compute_indicators(df: pd.DataFrame) -> Indicators:
    """Calcule l'ensemble des indicateurs de satisfaction et de performance
    à partir de la base fusionnée et nettoyée."""
    ind = Indicators()
    if df is None or df.empty:
        return ind

    n = len(df)
    ind.n_reponses = n
    ind.n_agences = df["Agence"].nunique() if "Agence" in df.columns else 0

    if "Horodatage" in df.columns and df["Horodatage"].notna().any():
        ind.periode_min = df["Horodatage"].min()
        ind.periode_max = df["Horodatage"].max()

    scores = df["Score_satisfaction"].dropna() if "Score_satisfaction" in df.columns else pd.Series(dtype=float)
    n_scored = len(scores)
    if n_scored:
        counts = scores.value_counts()
        ind.taux_tres_insatisfait = 100 * counts.get(1, 0) / n_scored
        ind.taux_insatisfait = 100 * counts.get(2, 0) / n_scored
        ind.taux_neutre = 100 * counts.get(3, 0) / n_scored
        ind.taux_satisfait = 100 * counts.get(4, 0) / n_scored
        ind.taux_tres_satisfait = 100 * counts.get(5, 0) / n_scored
        ind.taux_satisfaction_global = ind.taux_satisfait + ind.taux_tres_satisfait
        ind.taux_insatisfaction_global = ind.taux_insatisfait + ind.taux_tres_insatisfait
        ind.score_moyen = float(scores.mean())
        ind.score_mediane = float(scores.median())

    if "Resolu" in df.columns:
        resolu = df["Resolu"].dropna()
        if len(resolu):
            ind.taux_resolution = 100 * (resolu == "OUI").sum() / len(resolu)
            ind.n_non_resolu = int((resolu == "NON").sum())

    if "Duree_reponse_min" in df.columns:
        durees = df["Duree_reponse_min"].dropna()
        durees = durees[durees < 24 * 60]  # écarte les valeurs aberrantes (>24h)
        if len(durees):
            ind.duree_moyenne_min = float(durees.mean())
            ind.duree_mediane_min = float(durees.median())

    if "A_commente" in df.columns:
        ind.taux_completion_commentaire = 100 * df["A_commente"].mean()
        ind.n_commentaires = int(df["A_commente"].sum())
    if "A_laisse_contact" in df.columns:
        ind.taux_contact_partage = 100 * df["A_laisse_contact"].mean()
    if "A_laisse_telephone" in df.columns:
        ind.n_telephones = int(df["A_laisse_telephone"].sum())
        ind.taux_telephone = 100 * df["A_laisse_telephone"].mean()
    if "A_laisse_nom" in df.columns:
        ind.n_noms = int(df["A_laisse_nom"].sum())
    if "Duree_reponse_min" in df.columns:
        durees_rapides = df["Duree_reponse_min"].dropna()
        ind.n_reponses_tres_rapides = int((durees_rapides < 1).sum())
    if "Nb_items_apprecies" in df.columns:
        nb_items = df["Nb_items_apprecies"].dropna()
        if len(nb_items):
            ind.taux_multi_appreciation = 100 * (nb_items >= 2).sum() / len(nb_items)
    if scores is not None and n_scored:
        ind.n_verbatims_negatifs_estimes = int((scores <= 2).sum())

    if "Apprecie_principal" in df.columns:
        apprecie = df["Apprecie_principal"].dropna()
        if len(apprecie):
            top = apprecie.value_counts().idxmax()
            ind.item_plus_apprecie = top
            ind.item_plus_apprecie_taux = 100 * (apprecie == top).sum() / len(apprecie)

    if "Motif_insatisfaction" in df.columns:
        motifs = df["Motif_insatisfaction"].dropna()
        motifs = motifs[motifs.astype(str).str.strip() != ""]
        if len(motifs):
            top = motifs.value_counts().idxmax()
            ind.motif_insatisfaction_principal = top
            ind.motif_insatisfaction_taux = 100 * (motifs == top).sum() / len(motifs)

    # --- Performance par agence -------------------------------------
    if "Agence" in df.columns and n_scored:
        rows = []
        for agence, g in df.groupby("Agence"):
            g_scores = g["Score_satisfaction"].dropna()
            g_resolu = g["Resolu"].dropna() if "Resolu" in g.columns else pd.Series(dtype=object)
            rows.append({
                "Agence": agence,
                "Répondants": len(g),
                "Taux satisfaction (%)": round(100 * (g_scores >= 4).sum() / len(g_scores), 1) if len(g_scores) else np.nan,
                "Taux insatisfaction (%)": round(100 * (g_scores <= 2).sum() / len(g_scores), 1) if len(g_scores) else np.nan,
                "Score moyen (/5)": round(float(g_scores.mean()), 2) if len(g_scores) else np.nan,
                "Taux résolution (%)": round(100 * (g_resolu == "OUI").sum() / len(g_resolu), 1) if len(g_resolu) else np.nan,
                "Commentaires (%)": round(100 * g["A_commente"].mean(), 1) if "A_commente" in g.columns else np.nan,
                "Téléphones laissés": int(g["A_laisse_telephone"].sum()) if "A_laisse_telephone" in g.columns else 0,
            })
        par_agence = pd.DataFrame(rows).sort_values("Score moyen (/5)", ascending=False, na_position="last").reset_index(drop=True)
        par_agence.insert(0, "Rang", range(1, len(par_agence) + 1))
        ind.par_agence = par_agence

        valid = par_agence.dropna(subset=["Score moyen (/5)"])
        if len(valid):
            best = valid.iloc[0]
            worst = valid.iloc[-1]
            ind.agence_top, ind.agence_top_score = best["Agence"], best["Score moyen (/5)"]
            ind.agence_bottom, ind.agence_bottom_score = worst["Agence"], worst["Score moyen (/5)"]

    return ind


def satisfaction_distribution_table(df: pd.DataFrame) -> pd.DataFrame:
    """Table Satisfaction (libellé complet) x effectif x %, prête pour un graphique."""
    if df is None or df.empty or "Satisfaction" not in df.columns:
        return pd.DataFrame(columns=["Satisfaction", "Effectif", "Part (%)"])
    order = ["😞 Très insatisfait", "🙁 Insatisfait", "😐 Neutre", "🙂 Satisfait", "😃 Très satisfait"]
    counts = df["Satisfaction"].dropna().value_counts()
    total = counts.sum()
    rows = [{"Satisfaction": k, "Effectif": int(counts.get(k, 0)), "Part (%)": round(100 * counts.get(k, 0) / total, 1) if total else 0}
            for k in order if k in counts.index]
    # ajoute les libellés non standard rencontrés (robustesse)
    for k in counts.index:
        if k not in order:
            rows.append({"Satisfaction": k, "Effectif": int(counts[k]), "Part (%)": round(100 * counts[k] / total, 1) if total else 0})
    return pd.DataFrame(rows)
