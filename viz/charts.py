"""
Génération de graphiques adaptés au type des colonnes sélectionnées.
Retourne toujours (figure_plotly, stats_summary) — stats_summary est une
structure légère réutilisée par le moteur de commentaire automatique
(viz.comments), pour éviter de renvoyer les données brutes au commentaire.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config.settings import CIE_BLUE, CIE_DARK, CIE_GREEN, CIE_ORANGE, CIE_YELLOW

# Palette de l'app : couleurs volontairement éloignées les unes des autres
# (teinte ET luminosité) pour rester lisibles même avec 5-6 modalités sur un
# même graphique — contrairement à un dégradé orange/jaune/blanc, qui se
# confond facilement. Orange et vert d'abord (identité CIE / drapeau
# ivoirien), puis bleu, jaune, violet, rouge pour les cas à plus de
# modalités (ex : tranches d'âge).
_PALETTE = [CIE_ORANGE, CIE_GREEN, CIE_BLUE, CIE_YELLOW, "#9333EA", "#DC2626"]
# Alias public : les pages qui construisent leurs graphiques directement
# (ex : 5_TCD.py, dont les croisements ne passent pas par ce module)
# réutilisent la même palette plutôt que d'en redéfinir une localement.
CHART_PALETTE = _PALETTE

# Habillage commun à tous les graphiques : fond blanc, texte noir/anthracite,
# grille grise discrète — lisible quel que soit le thème (clair ou sombre)
# de la page qui l'entoure, plutôt que d'hériter d'un fond transparent qui
# se fond dans le fond bleu marine de l'application.
_GRID_COLOR = "#E5E7EB"


def apply_readable_style(fig):
    fig.update_layout(
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color=CIE_DARK, size=18),
        title_font=dict(color=CIE_DARK, size=22),
        legend=dict(font=dict(color=CIE_DARK, size=16)),
    )
    # Quadrillage retiré sur tous les graphiques (dashboard, tableaux, rapports...) —
    # seul l'axe lui-même reste visible, pour un rendu plus épuré. Taille de
    # police augmentée : les graphiques sont exportés en image (Word/PDF/PPTX)
    # à taille réduite sur la page, donc un texte trop petit à la source
    # devient illisible une fois inséré — mieux vaut partir large.
    fig.update_xaxes(color=CIE_DARK, tickfont=dict(color=CIE_DARK, size=16), title_font=dict(color=CIE_DARK, size=18),
                      showgrid=False, linecolor=_GRID_COLOR)
    fig.update_yaxes(color=CIE_DARK, tickfont=dict(color=CIE_DARK, size=16), title_font=dict(color=CIE_DARK, size=18),
                      showgrid=False, linecolor=_GRID_COLOR)
    return fig


def bar_chart(df: pd.DataFrame, cat_col: str, top_n: int = 12):
    counts = df[cat_col].astype(str).value_counts().head(top_n)
    fig = px.bar(
        x=counts.index, y=counts.values,
        labels={"x": cat_col, "y": "Effectif"},
        title=f"Répartition — {cat_col}",
        color_discrete_sequence=[CIE_ORANGE],
    )
    fig.update_layout(showlegend=False)
    apply_readable_style(fig)

    total = df[cat_col].dropna().shape[0]
    top_modality = counts.index[0] if len(counts) else None
    top_share = round(counts.iloc[0] / total * 100, 1) if len(counts) and total else 0.0
    summary = {
        "type": "categorical",
        "column": cat_col,
        "n_modalities": int(df[cat_col].nunique()),
        "top_modality": top_modality,
        "top_share": top_share,
        "total": total,
        "missing_rate": round(df[cat_col].isna().mean() * 100, 1),
    }
    return fig, summary


def pie_chart(df: pd.DataFrame, cat_col: str, top_n: int = 8):
    counts = df[cat_col].astype(str).value_counts().head(top_n)
    fig = px.pie(
        names=counts.index, values=counts.values,
        title=f"Répartition — {cat_col}",
        color_discrete_sequence=_PALETTE,
    )
    apply_readable_style(fig)
    total = df[cat_col].dropna().shape[0]
    summary = {
        "type": "categorical",
        "column": cat_col,
        "n_modalities": int(df[cat_col].nunique()),
        "top_modality": counts.index[0] if len(counts) else None,
        "top_share": round(counts.iloc[0] / total * 100, 1) if len(counts) and total else 0.0,
        "total": total,
        "missing_rate": round(df[cat_col].isna().mean() * 100, 1),
    }
    return fig, summary


def histogram(df: pd.DataFrame, num_col: str, nbins: int = 30):
    series = pd.to_numeric(df[num_col], errors="coerce").dropna()
    fig = px.histogram(series, nbins=nbins, title=f"Distribution — {num_col}", color_discrete_sequence=[CIE_ORANGE])
    fig.update_layout(showlegend=False, xaxis_title=num_col, yaxis_title="Effectif")
    apply_readable_style(fig)

    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    outliers = series[(series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)]
    summary = {
        "type": "numeric",
        "column": num_col,
        "mean": round(series.mean(), 2) if len(series) else None,
        "median": round(series.median(), 2) if len(series) else None,
        "std": round(series.std(), 2) if len(series) else None,
        "min": round(series.min(), 2) if len(series) else None,
        "max": round(series.max(), 2) if len(series) else None,
        "n_outliers": int(len(outliers)),
        "missing_rate": round(df[num_col].isna().mean() * 100, 1),
    }
    return fig, summary


def grouped_bar_chart(df: pd.DataFrame, cat_col: str, num_col: str, agg: str = "mean", top_n: int = 15):
    """Compare un indicateur numérique par catégorie sous forme de barres
    triées (ex : moyenne du nombre de réponses par agence). Choisi à la
    place d'une boîte à moustaches, plus simple à lire pour un public non
    statisticien tout en répondant au même besoin de comparaison."""
    agg_func = {"mean": "mean", "somme": "sum", "médiane": "median", "min": "min", "max": "max"}.get(agg, "mean")
    grouped = df.groupby(cat_col)[num_col].agg(agg_func).sort_values(ascending=False).head(top_n)

    agg_label = {"mean": "Moyenne", "somme": "Somme", "médiane": "Médiane", "min": "Min", "max": "Max"}.get(agg, "Moyenne")
    fig = px.bar(
        x=grouped.index.astype(str), y=grouped.values,
        labels={"x": cat_col, "y": f"{agg_label} de {num_col}"},
        title=f"{agg_label} de « {num_col} » par « {cat_col} »",
        color_discrete_sequence=[CIE_ORANGE],
    )
    fig.update_layout(showlegend=False)
    apply_readable_style(fig)

    summary = {
        "type": "grouped_numeric",
        "column": num_col,
        "group_column": cat_col,
        "highest_group": grouped.index[0] if len(grouped) else None,
        "highest_value": round(grouped.iloc[0], 2) if len(grouped) else None,
        "lowest_group": grouped.index[-1] if len(grouped) else None,
        "lowest_value": round(grouped.iloc[-1], 2) if len(grouped) else None,
    }
    return fig, summary


def time_series(df: pd.DataFrame, date_col: str, value_col: str | None = None, freq: str = "D", smooth: bool = True):
    """Trace l'évolution dans le temps. `smooth=True` (par défaut) affiche
    une courbe lissée (spline) plutôt que des segments de droite : plus
    lisible pour observer une tendance sur plusieurs années, comme demandé
    — on peut repasser à des droites avec `smooth=False`."""
    series = df.copy()
    series[date_col] = pd.to_datetime(series[date_col], errors="coerce")
    series = series.dropna(subset=[date_col])

    if value_col is None:
        grouped = series.set_index(date_col).resample(freq).size()
        y_label = "Nombre de réponses"
    else:
        grouped = series.set_index(date_col)[value_col].apply(pd.to_numeric, errors="coerce").resample(freq).sum()
        y_label = value_col

    fig = px.line(x=grouped.index, y=grouped.values, title=f"Évolution dans le temps — {y_label}",
                   color_discrete_sequence=[CIE_ORANGE], markers=True)
    fig.update_layout(xaxis_title="Date", yaxis_title=y_label)
    if smooth and len(grouped) >= 3:
        fig.update_traces(line_shape="spline", line_smoothing=0.6)
    fig.update_traces(line=dict(width=3), marker=dict(size=7, line=dict(width=1, color=CIE_DARK)))
    fig.update_layout(yaxis=dict(gridcolor=_GRID_COLOR, zeroline=False), xaxis=dict(showgrid=False))
    apply_readable_style(fig)

    if len(grouped) >= 2:
        first_half = grouped.iloc[: len(grouped) // 2].mean()
        second_half = grouped.iloc[len(grouped) // 2:].mean()
        variation_pct = round((second_half - first_half) / first_half * 100, 1) if first_half else 0.0
        peak_idx = grouped.idxmax()
    else:
        variation_pct = 0.0
        peak_idx = grouped.index[0] if len(grouped) else None

    summary = {
        "type": "timeseries",
        "column": y_label,
        "variation_pct": variation_pct,
        "peak_date": str(peak_idx.date()) if peak_idx is not None else None,
        "peak_value": round(grouped.max(), 2) if len(grouped) else None,
        "trend": "hausse" if variation_pct > 5 else ("baisse" if variation_pct < -5 else "stable"),
    }
    return fig, summary


def scatter(df: pd.DataFrame, x_col: str, y_col: str, color_col: str | None = None):
    fig = px.scatter(df, x=x_col, y=y_col, color=color_col, title=f"{y_col} en fonction de {x_col}",
                      color_discrete_sequence=_PALETTE)
    apply_readable_style(fig)

    x = pd.to_numeric(df[x_col], errors="coerce")
    y = pd.to_numeric(df[y_col], errors="coerce")
    valid = x.notna() & y.notna()
    corr = round(x[valid].corr(y[valid]), 2) if valid.sum() > 2 else None

    summary = {
        "type": "scatter",
        "x": x_col,
        "y": y_col,
        "correlation": corr,
    }
    return fig, summary


def correlation_heatmap(df: pd.DataFrame, numeric_cols: list[str]):
    if len(numeric_cols) < 2:
        return None, {"type": "correlation", "error": "Pas assez de colonnes numériques."}

    corr = df[numeric_cols].corr(numeric_only=True).round(2)
    fig = px.imshow(corr, text_auto=True, color_continuous_scale=[CIE_GREEN, "#FFFFFF", CIE_ORANGE],
                     title="Matrice de corrélation")
    apply_readable_style(fig)

    corr_no_diag = corr.copy()
    np.fill_diagonal(corr_no_diag.values, np.nan)
    strongest = corr_no_diag.abs().stack().idxmax() if corr_no_diag.abs().stack().notna().any() else (None, None)
    strongest_value = corr_no_diag.loc[strongest] if strongest[0] else None

    summary = {
        "type": "correlation",
        "strongest_pair": strongest,
        "strongest_value": round(strongest_value, 2) if strongest_value is not None else None,
    }
    return fig, summary


def crosstab_bar_chart(df: pd.DataFrame, cat_col1: str, cat_col2: str, top_n: int = 8):
    """Croise deux variables catégorielles : barres groupées par
    modalité de `cat_col1`, colorées par modalité de `cat_col2` — pour
    répondre au besoin de « croiser les variables de son choix »."""
    top1 = df[cat_col1].astype(str).value_counts().head(top_n).index.tolist()
    top2 = df[cat_col2].astype(str).value_counts().head(6).index.tolist()
    sub = df[df[cat_col1].astype(str).isin(top1) & df[cat_col2].astype(str).isin(top2)].copy()
    sub[cat_col1] = sub[cat_col1].astype(str)
    sub[cat_col2] = sub[cat_col2].astype(str)
    cross = sub.groupby([cat_col1, cat_col2]).size().reset_index(name="Effectif")

    fig = px.bar(
        cross, x=cat_col1, y="Effectif", color=cat_col2, barmode="group",
        title=f"Croisement — {cat_col1} × {cat_col2}",
        color_discrete_sequence=_PALETTE,
    )
    apply_readable_style(fig)

    summary = {
        "type": "crosstab",
        "column": cat_col1,
        "group_column": cat_col2,
        "n_combinations": int(cross.shape[0]),
        "total": int(cross["Effectif"].sum()),
    }
    return fig, summary


def _apply_comparison_style(fig, n_series: int):
    """Style commun aux graphiques d'évolution « plusieurs courbes à
    comparer » : marqueurs visibles, lignes épaisses, légende horizontale
    sous le graphique, grille horizontale légère — pour faciliter la
    comparaison visuelle entre plusieurs séries sur la même période."""
    fig.update_traces(line=dict(width=3), marker=dict(size=7, line=dict(width=1, color=CIE_DARK)))
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=-0.28, xanchor="center", x=0.5, title=None),
        yaxis=dict(gridcolor=_GRID_COLOR, zeroline=False),
        xaxis=dict(showgrid=False),
        hovermode="x unified",
    )
    apply_readable_style(fig)
    return fig


def time_series_by_category(df: pd.DataFrame, date_col: str, cat_col: str, freq: str = "ME", top_n: int = 5, smooth: bool = True):
    """Évolution dans le temps, une courbe par modalité (les `top_n` les
    plus fréquentes) de `cat_col` — pour croiser une date avec une
    variable catégorielle et comparer facilement plusieurs séries entre
    elles sur la même période (un peu comme un graphique Excel à
    plusieurs séries)."""
    work = df.copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    top_modalities = work[cat_col].astype(str).value_counts().head(top_n).index.tolist()
    work = work[work[cat_col].astype(str).isin(top_modalities)]
    work[cat_col] = work[cat_col].astype(str)

    grouped = (
        work.groupby([cat_col, pd.Grouper(key=date_col, freq=freq)]).size().rename("Effectif").reset_index()
    )

    fig = px.line(
        grouped, x=date_col, y="Effectif", color=cat_col, markers=True,
        title=f"Évolution dans le temps — {cat_col}",
        color_discrete_sequence=_PALETTE,
    )
    if smooth:
        fig.update_traces(line_shape="spline", line_smoothing=0.6)
    fig.update_layout(xaxis_title="Date", yaxis_title="Effectif")
    _apply_comparison_style(fig, len(top_modalities))

    summary = {
        "type": "timeseries_by_category",
        "column": cat_col,
        "date_column": date_col,
        "n_modalities_shown": len(top_modalities),
    }
    return fig, summary


def time_series_multi_numeric(
    df: pd.DataFrame, date_col: str, value_cols: list[str], freq: str = "ME", agg: str = "mean", smooth: bool = True,
):
    """Évolution dans le temps de PLUSIEURS colonnes numériques à
    comparer, chacune sous forme de courbe distincte sur le même repère —
    pour comparer par exemple plusieurs indicateurs (CA, coûts, volumes...)
    sur la même période, façon graphique Excel multi-séries."""
    value_cols = [c for c in value_cols if c in df.columns]
    if not value_cols:
        return None, {"type": "timeseries_multi", "error": "Aucune colonne numérique valide."}

    work = df.copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    if work.empty:
        return None, {"type": "timeseries_multi", "error": "Aucune date exploitable."}

    agg_func = {"mean": "mean", "somme": "sum", "médiane": "median", "min": "min", "max": "max"}.get(agg, "mean")

    frames = []
    for c in value_cols:
        s = pd.to_numeric(work[c], errors="coerce")
        series = pd.DataFrame({date_col: work[date_col], c: s}).dropna()
        if series.empty:
            continue
        g = series.set_index(date_col)[c].resample(freq).agg(agg_func).dropna()
        frames.append(pd.DataFrame({date_col: g.index, "Valeur": g.values, "Série": c}))

    if not frames:
        return None, {"type": "timeseries_multi", "error": "Aucune valeur numérique exploitable sur ces colonnes."}

    long_df = pd.concat(frames, ignore_index=True)
    agg_label = {"mean": "Moyenne", "somme": "Somme", "médiane": "Médiane", "min": "Min", "max": "Max"}.get(agg, "Moyenne")
    fig = px.line(
        long_df, x=date_col, y="Valeur", color="Série", markers=True,
        title=f"Évolution comparée — {agg_label} de {len(value_cols)} mesure(s)",
        color_discrete_sequence=_PALETTE,
    )
    if smooth:
        fig.update_traces(line_shape="spline", line_smoothing=0.6)
    fig.update_layout(xaxis_title="Date", yaxis_title=agg_label)
    _apply_comparison_style(fig, len(value_cols))

    summary = {
        "type": "timeseries_multi",
        "columns": value_cols,
        "date_column": date_col,
        "agg": agg,
        "n_series": len(frames),
    }
    return fig, summary
