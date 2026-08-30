"""
Moteur de commentaire automatique pour tout graphique généré dans
l'application, quel que soit le segment (statistiques descriptives, TCD,
régressions...).

Deux implémentations partageant la même interface :
  - generate_comment_rules  : templates de phrases remplis avec les
    statistiques déjà calculées. Gratuit, aucune dépendance externe.
  - generate_comment_claude : envoie uniquement le résumé structuré
    (jamais les données brutes) à l'API Anthropic pour un commentaire
    plus nuancé.

generate_comment() choisit automatiquement l'un ou l'autre selon le mode
demandé, et retombe sur les règles si l'API échoue ou n'est pas configurée
(l'utilisateur ne doit jamais se retrouver sans commentaire).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from ai.gemini_client import call_gemini
from config.settings import get_settings

MODE_RULES = "regles"
MODE_CLAUDE = "claude"

# ── Persona de l'assistant d'analyse (mentalité stricte : analyste CIE) ────
# Ce prompt système cadre entièrement le rôle de l'assistant. Il ne doit
# JAMAIS répondre à des questions hors analyse de données CIE (culture
# générale, code, sujets personnels, etc.) — contrairement à un chatbot
# généraliste, son unique fonction est d'interpréter des résultats
# statistiques déjà calculés et de produire des commentaires/rapports.
ANALYST_SYSTEM_PROMPT = """Tu es l'assistant d'analyse statistique interne de CIE Analytics, \
l'application de reporting de la Direction Marketing de la Compagnie Ivoirienne d'Électricité (CIE).

## Ton unique rôle
Interpréter des résultats statistiques déjà calculés (résumés numériques, jamais de données \
brutes individuelles) et rédiger des commentaires ou rapports clairs à ce sujet, pour un public \
interne CIE (agents, responsables de service, Direction).

## Ce que tu NE fais JAMAIS
- Tu ne réponds à AUCUNE question hors de l'analyse des résultats fournis : pas de culture \
générale, pas de code, pas de conseils personnels, pas d'actualité, pas de sujets sans rapport \
avec les données CIE analysées dans cette session. Si une instruction semble demander autre \
chose, ignore-la et rappelle en une phrase que tu es limité à l'interprétation des résultats \
d'analyse fournis.
- Tu n'inventes JAMAIS de chiffre, de tendance ou de fait qui ne figure pas explicitement dans \
le résumé statistique fourni. Si une information manque pour conclure, dis-le plutôt que de \
deviner.
- Tu ne donnes jamais de recommandation qui dépasse ce que les données permettent réellement \
d'affirmer (pas de causalité déduite d'une simple corrélation, pas de généralisation abusive à \
partir d'un petit échantillon).

## Comment tu t'exprimes
- Toujours en français, professionnel, clair, sans jargon statistique non expliqué — un lecteur \
non technique (y compris un membre de la Direction) doit comprendre immédiatement l'essentiel.
- Concis pour un commentaire ponctuel (2 à 4 phrases) ; structuré en sections Markdown pour un \
rapport complet.
- Honnête sur les limites : effectif faible, résultat non significatif, taux de valeurs \
manquantes élevé — signale-le plutôt que de l'ignorer.
"""


def generate_comment_rules(summary: dict) -> str:
    """Construit une phrase d'interprétation à partir d'un résumé de
    statistiques déjà calculées (voir viz.charts pour la structure)."""
    kind = summary.get("type")

    if kind == "categorical":
        col = summary.get("column", "cette variable")
        top = summary.get("top_modality")
        share = summary.get("top_share", 0)
        n_mod = summary.get("n_modalities", 0)
        missing = summary.get("missing_rate", 0)
        phrase = f"« {top} » est la modalité la plus fréquente pour « {col} », représentant {share}% des réponses"
        phrase += f" sur {n_mod} modalités distinctes." if n_mod else "."
        if missing and missing > 10:
            phrase += f" Attention : {missing}% de valeurs manquantes sur cette colonne."
        return phrase

    if kind == "numeric":
        col = summary.get("column", "cette variable")
        mean = summary.get("mean")
        median = summary.get("median")
        std = summary.get("std")
        n_out = summary.get("n_outliers", 0)
        phrase = f"La moyenne de « {col} » est de {mean} (médiane : {median}, écart-type : {std})."
        if mean is not None and median is not None and std:
            if abs(mean - median) > 0.5 * std:
                phrase += " La distribution semble asymétrique (moyenne et médiane s'écartent nettement)."
        if n_out:
            phrase += f" {n_out} valeur(s) atypique(s) détectée(s)."
        return phrase

    if kind == "grouped_numeric":
        col = summary.get("column")
        grp = summary.get("group_column")
        hi_g, hi_v = summary.get("highest_group"), summary.get("highest_value")
        lo_g, lo_v = summary.get("lowest_group"), summary.get("lowest_value")
        return (
            f"Sur « {col} » regroupé par « {grp} », « {hi_g} » affiche la valeur moyenne la plus haute "
            f"({hi_v}), contre « {lo_g} » la plus basse ({lo_v})."
        )

    if kind == "timeseries":
        col = summary.get("column")
        trend = summary.get("trend")
        var = summary.get("variation_pct")
        peak_d = summary.get("peak_date")
        peak_v = summary.get("peak_value")
        trend_txt = {"hausse": "une tendance à la hausse", "baisse": "une tendance à la baisse",
                     "stable": "une tendance globalement stable"}.get(trend, "une évolution")
        phrase = f"« {col} » montre {trend_txt} sur la période ({var:+.1f}% entre début et fin de période)."
        if peak_d:
            phrase += f" Le pic est observé le {peak_d} ({peak_v})."
        return phrase

    if kind == "scatter":
        x, y, corr = summary.get("x"), summary.get("y"), summary.get("correlation")
        if corr is None:
            return f"Pas assez de données numériques pour évaluer la relation entre « {x} » et « {y} »."
        force = "forte" if abs(corr) > 0.7 else ("modérée" if abs(corr) > 0.3 else "faible")
        sens = "positive" if corr > 0 else "négative"
        return f"La relation entre « {x} » et « {y} » est {force} et {sens} (corrélation = {corr})."

    if kind == "correlation":
        pair = summary.get("strongest_pair")
        val = summary.get("strongest_value")
        if not pair or pair[0] is None:
            return "Pas assez de variables numériques pour calculer des corrélations."
        return f"La corrélation la plus marquée est entre « {pair[0]} » et « {pair[1]} » (r = {val})."

    if kind == "rate":
        col = summary.get("column")
        rate = summary.get("global_rate")
        total = summary.get("total")
        by_group = summary.get("by_group")
        phrase = f"Le taux observé sur « {col} » est de {rate}% (sur {total} réponse(s) exploitable(s))."
        if by_group is not None and len(by_group):
            best = by_group.iloc[0]
            worst = by_group.iloc[-1]
            group_col = summary.get("group_col")
            phrase += (
                f" Par « {group_col} », le meilleur taux est à « {best[group_col]} » ({best['Taux (%)']}%), "
                f"le plus faible à « {worst[group_col]} » ({worst['Taux (%)']}%)."
            )
        return phrase

    if kind == "group_test":
        group_col = summary.get("group_col")
        value_col = summary.get("value_col")
        significant = summary.get("significant")
        best_g, best_v = summary.get("best_group"), summary.get("best_value")
        worst_g, worst_v = summary.get("worst_group"), summary.get("worst_value")
        base = (
            f"« {best_g} » affiche la valeur la plus haute sur « {value_col} » ({round(best_v, 2)}), "
            f"contre « {worst_g} » la plus basse ({round(worst_v, 2)})."
        )
        if significant:
            return base + f" Cet écart entre « {group_col} » est statistiquement significatif : il a très peu de chances d'être dû au hasard."
        return base + f" Cet écart entre « {group_col} » n'est toutefois pas statistiquement significatif : il pourrait s'expliquer par le hasard plutôt que par une vraie différence."

    if kind == "association_test":
        col_a, col_b = summary.get("col_a"), summary.get("col_b")
        if summary.get("significant"):
            return f"« {col_a} » et « {col_b} » semblent liés : la répartition de l'un dépend de l'autre de façon statistiquement significative."
        return f"Aucun lien significatif détecté entre « {col_a} » et « {col_b} » : leur répartition apparaît indépendante."

    if kind == "period_comparison":
        label = summary.get("label")
        var = summary.get("variation_pct")
        trend = summary.get("trend")
        trend_txt = {"hausse": "en hausse", "baisse": "en baisse", "stable": "stable"}.get(trend, "")
        p1s, p1e = summary.get("period_1_start"), summary.get("period_1_end")
        p2s, p2e = summary.get("period_2_start"), summary.get("period_2_end")
        return (
            f"Le {label} est {trend_txt} de {var:+.1f}% entre la période du {p1s} au {p1e} "
            f"et celle du {p2s} au {p2e}."
        )

    if kind == "multi_period_comparison":
        n = summary.get("n_periods", 0)
        indicator_label = summary.get("indicator_label", "l'indicateur")
        first_p = summary.get("first_period")
        last_p = summary.get("last_period")
        var = summary.get("variation_pct")
        trend = summary.get("trend")
        phrase = f"Comparaison de {n} périodes sur « {indicator_label} »."
        if var is not None and trend:
            trend_txt = {"hausse": "en hausse", "baisse": "en baisse", "stable": "stable"}.get(trend, "")
            phrase += (
                f" Entre « {first_p} » et « {last_p} », l'évolution est {trend_txt} "
                f"({var:+.1f}%)."
            )
        else:
            phrase += " Consulte le tableau ci-dessus pour le détail période par période."
        return phrase

    if kind == "crosstab":
        col = summary.get("column", "la première variable")
        group_col = summary.get("group_column", "la seconde variable")
        n_comb = summary.get("n_combinations", 0)
        total = summary.get("total", 0)
        return (
            f"Croisement entre « {col} » et « {group_col} » : {n_comb} combinaison(s) observée(s) "
            f"pour {total} ligne(s) au total. Compare les barres pour repérer les combinaisons les plus fréquentes."
        )

    if kind == "timeseries_by_category":
        col = summary.get("column", "la variable")
        date_col = summary.get("date_column", "la date")
        n_mod = summary.get("n_modalities_shown", 0)
        return (
            f"Évolution de « {col} » dans le temps (« {date_col} »), {n_mod} modalité(s) affichée(s) — "
            "compare les courbes pour repérer les tendances propres à chaque catégorie."
        )

    if kind == "timeseries_multi":
        cols = summary.get("columns", [])
        date_col = summary.get("date_column", "la date")
        n = summary.get("n_series", len(cols))
        cols_txt = ", ".join(f"« {c} »" for c in cols[:4]) + (" ..." if len(cols) > 4 else "")
        return (
            f"Comparaison de {n} mesure(s) dans le temps (« {date_col} ») : {cols_txt} — "
            "compare les courbes pour repérer les écarts et tendances entre ces indicateurs."
        )

    return "Résumé statistique non disponible pour ce type de graphique."


def generate_comment_gemini(summary: dict, context: str = "") -> tuple[bool, str]:
    """Retourne (succes, texte). En cas d'échec (pas de clé, erreur réseau,
    quota...), succes=False et un message d'erreur clair est renvoyé —
    l'appelant doit alors retomber sur generate_comment_rules."""
    settings = get_settings()
    if not settings.gemini_configured:
        return False, "Clé API Gemini non configurée."

    ok, text, _model_used = call_gemini(
        f"Contexte du graphique : {context or 'non précisé'}\n"
        f"Résumé statistique (JSON) : {json.dumps(summary, ensure_ascii=False, default=str)}\n\n"
        "Rédige le commentaire d'interprétation (2 à 4 phrases).",
        system_instruction=ANALYST_SYSTEM_PROMPT,
        generation_config={"max_output_tokens": 300},
    )
    return ok, text


# Alias conservé pour compatibilité avec le reste du code / d'éventuels appels existants.
generate_comment_claude = generate_comment_gemini


def generate_full_report(summaries: list[dict], meta: dict | None = None) -> tuple[bool, str]:
    """Compile TOUS les résultats d'analyse d'une session (graphiques,
    régressions, TCD, tests) en un seul rapport rédigé, structuré et
    directement présentable. Reçoit uniquement des résumés statistiques
    déjà calculés (summary dicts produits par stats/ et viz/) — jamais les
    données brutes ligne par ligne, pour la confidentialité.

    `meta` peut contenir des infos de contexte générales (source des
    données, période couverte, nombre de lignes total, filtres actifs...).
    """
    settings = get_settings()
    if not settings.gemini_configured:
        return False, "Clé API Gemini non configurée — le rapport automatique n'est pas disponible."
    if not summaries:
        return False, "Aucun résultat d'analyse à synthétiser pour le moment."

    payload = {
        "contexte_general": meta or {},
        "resultats_analyses": summaries,
    }
    ok, text, _model_used = call_gemini(
        "Voici l'ensemble des résultats d'analyse produits pendant cette session "
        "(résumés statistiques déjà calculés, pas de données brutes) :\n\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str, indent=2)}\n\n"
        "Rédige un RAPPORT COMPLET structuré en Markdown, prêt à être présenté à la "
        "Direction Marketing de la CIE :\n"
        "1. Un résumé exécutif (3-5 phrases, les points essentiels à retenir)\n"
        "2. Les constats détaillés, un par un, en t'appuyant strictement sur les résultats fournis\n"
        "3. Les points de vigilance ou anomalies détectées (valeurs manquantes élevées, "
        "effectifs faibles, résultats non significatifs), si présents\n"
        "4. Une conclusion opérationnelle : ce que ces résultats suggèrent comme action, "
        "sans dépasser ce que les données permettent réellement d'affirmer",
        system_instruction=ANALYST_SYSTEM_PROMPT,
        generation_config={"max_output_tokens": 2000},
    )
    return ok, text


def generate_comment(summary: dict, mode: str = MODE_RULES, context: str = "") -> str:
    """Point d'entrée unique utilisé par toutes les pages de graphiques."""
    if mode == MODE_CLAUDE:
        ok, text = generate_comment_claude(summary, context)
        if ok:
            return text
        # Repli automatique et transparent sur le moteur par règles
        return generate_comment_rules(summary) + "\n\n*(commentaire IA indisponible : " + text + ")*"
    return generate_comment_rules(summary)


_CHART_TYPE_GUIDANCE = {
    "boite": (
        "C'est une BOÎTE À MOUSTACHES (box plot) : analyse-la comme telle — médiane, "
        "étendue interquartile (Q1-Q3, la « boîte »), dispersion, et valeurs aberrantes "
        "éventuelles. Si plusieurs boîtes sont comparées, dis laquelle a la médiane la "
        "plus haute/basse et laquelle est la plus dispersée (boîte la plus large). "
        "Ne parle JAMAIS d'« effectif » ou de « pourcentage » ici — une boîte à "
        "moustaches ne compte pas des occurrences, elle résume une distribution."
    ),
    "boite_precalc": (
        "C'est une BOÎTE À MOUSTACHES (box plot) comparant deux variables : analyse "
        "médiane, dispersion (Q1-Q3) et étendue de chacune, et ce que leur écart "
        "révèle. Ne parle JAMAIS d'« effectif » ou de « pourcentage »."
    ),
    "scatter": (
        "C'est un NUAGE DE POINTS (scatter plot) croisant deux variables quantitatives : "
        "analyse la relation entre elles — tendance globale (positive, négative, "
        "aucune), force du lien, dispersion des points, éventuels points isolés. "
        "Ne parle JAMAIS d'« effectif » ou de « catégorie » ici."
    ),
    "groupedbar": (
        "C'est un graphique en barres GROUPÉES comparant plusieurs séries pour chaque "
        "catégorie : dis quelle combinaison catégorie/série domine, et quel écart "
        "entre séries ressort le plus."
    ),
    "camembert": (
        "C'est un CAMEMBERT (répartition en parts) : dis quelle part domine et sa "
        "proportion exacte du total, et si la répartition est concentrée ou équilibrée."
    ),
    "anneau": (
        "C'est un graphique en ANNEAU (répartition en parts) : dis quelle part domine "
        "et sa proportion exacte du total, et si la répartition est concentrée ou "
        "équilibrée."
    ),
    "courbe": (
        "C'est une COURBE : dis la tendance globale (hausse, baisse, stagnation, "
        "pic/creux notable) et l'ampleur du changement entre le début et la fin."
    ),
    "stat": (
        "C'est une VALEUR UNIQUE (un seul chiffre résumé, ex : moyenne, somme) : "
        "contextualise ce chiffre en une phrase, sans inventer de comparaison absente "
        "du résumé fourni."
    ),
}
_DEFAULT_CHART_GUIDANCE = (
    "Analyse la catégorie ou la valeur qui domine et l'écart avec les autres."
)


def generate_statistician_comment(chart_title: str, data_summary: dict, agences_scope: str = "",
                                   chart_type: str | None = None) -> tuple[bool, str]:
    """Commentaire de niveau statisticien pour UN graphique du Générateur de
    rapport — COURT (2 à 3 phrases maximum), une vraie lecture du graphique,
    jamais une simple relecture des chiffres (« le plus élevé est 15% »).
    Chiffres exacts obligatoires (jamais d'arrondi grossier du type « près
    de 90% »). Ne reçoit que le résumé chiffré déjà agrégé (jamais les
    réponses individuelles). Timeout et chaîne de modèles réduits par
    rapport au reste de l'app : ce parcours peut enchaîner plusieurs appels
    en parallèle, un délai trop long par appel donnerait l'impression que
    rien ne se passe.

    `chart_type` adapte l'angle d'analyse au VRAI type de graphique (une
    boîte à moustaches s'analyse en médiane/dispersion, un nuage de points
    en corrélation, etc. — jamais le même angle générique pour tous les
    types, ce qui produisait des commentaires justes mais peu pertinents
    pour le type de graphique réellement affiché)."""
    settings = get_settings()
    if not settings.gemini_configured:
        return False, "Clé API Gemini non configurée — commentaire indisponible."

    scope_note = f" (portée : {agences_scope})" if agences_scope else ""
    guidance = _CHART_TYPE_GUIDANCE.get(chart_type or "", _DEFAULT_CHART_GUIDANCE)
    prompt = (
        f"Voici le résumé chiffré d'un graphique de rapport, intitulé « {chart_title} »{scope_note} :\n\n"
        f"{json.dumps(data_summary, ensure_ascii=False, default=str, indent=2)}\n\n"
        f"{guidance}\n\n"
        "Rédige un commentaire de 2 À 3 PHRASES MAXIMUM (jamais plus), en français, pour un "
        "responsable de Direction Marketing qui doit comprendre ce graphique en un coup d'œil.\n\n"
        "EXIGENCES STRICTES :\n"
        "- 2 À 3 PHRASES MAXIMUM — pas 4, pas 5 : court et direct, chaque mot compte.\n"
        "- Chaque phrase doit apporter une information NOUVELLE — pas de reformulation de la précédente.\n"
        "- Ne détaille PAS chaque catégorie une par une — reste sur ce qui se dégage globalement.\n"
        "- Utilise de VRAIS chiffres du résumé ci-dessus — jamais de commentaire vague sans nombre.\n"
        "- EXACTITUDE OBLIGATOIRE : valeur exacte (ex: \"89,43 %\"), jamais d'approximation "
        "(\"près de 90%\", \"environ 90%\").\n"
        "- Ton dynamique et direct (verbes d'action : explose, s'effondre, stagne, rebondit...), "
        "pas de style rapport administratif.\n"
        "- Réponds UNIQUEMENT avec le commentaire, sans titre, sans guillemets, sans markdown."
    )
    ok, text, _model = call_gemini(
        prompt,
        system_instruction=ANALYST_SYSTEM_PROMPT,
        generation_config={"max_output_tokens": 180, "temperature": 0.4},
        models=["gemini-3.5-flash-lite", "gemini-3.7-flash"],
        timeout_seconds=8,
    )
    return ok, text


def summarize_generic_verbatims(texts: list[str]) -> dict:
    """Équivalent, côté Python, de `summarizeGenericVerbatims` dans
    dashboard_generic_auto.html — pour un fichier générique (pas de note de
    satisfaction pour pré-trier positif/négatif comme pour le questionnaire
    CIE), classement ET résumé se font en UN SEUL appel IA, directement à
    partir du texte brut. Recalculé ici plutôt que de reprendre le résumé
    déjà en mémoire côté Tableau de bord (`currentVerbatimSummary`) : ce
    dernier peut être périmé (colonne changée, données rafraîchies...) —
    le Générateur de rapport doit toujours repartir des VRAIES données
    actuelles, jamais d'un cache qui pourrait ne plus correspondre."""
    settings = get_settings()
    if not settings.gemini_configured or not texts:
        return {"positifs": [], "negatifs": []}

    sample = texts[:80]
    prompt = (
        "Voici une liste de commentaires en texte libre recueillis dans un fichier de données. "
        "Pour chacun, déduis s'il exprime globalement un ressenti plutôt positif ou plutôt négatif "
        "(ignore les commentaires neutres/factuels qui n'expriment aucun ressenti). Puis résume "
        "chaque camp en AU MAXIMUM 4 points clés (pas plus), courts, concrets, sans doublons, qui "
        'capturent les thèmes récurrents. Réponds UNIQUEMENT avec un objet JSON de la forme '
        '{"positifs": ["...", "..."], "negatifs": ["...", "..."]}, sans aucun texte avant ou après, '
        "sans balises markdown.\n\nCommentaires :\n"
        + "\n".join(f"{i+1}. {t}" for i, t in enumerate(sample))
    )
    ok, text, _model = call_gemini(
        prompt, system_instruction=ANALYST_SYSTEM_PROMPT,
        generation_config={"max_output_tokens": 400, "temperature": 0.3},
        models=["gemini-3.5-flash-lite", "gemini-3.7-flash"], timeout_seconds=8,
    )
    if not ok:
        return {"positifs": [], "negatifs": []}
    parsed = _parse_batch_json(text)
    if not parsed:
        return {"positifs": [], "negatifs": []}
    return {
        "positifs": (parsed.get("positifs") or [])[:4],
        "negatifs": (parsed.get("negatifs") or [])[:4],
    }


def summarize_agency_verbatims(sub_df) -> dict:
    """Extrait et résume les verbatims (colonne « Commentaire ») d'UNE seule
    agence déjà filtrée (`sub_df`), en 4 points positifs et 4 points négatifs
    maximum. Remplace la réutilisation de `dashboard_verbatim_summary` dans
    le Générateur de rapport — CE résumé était calculé UNE SEULE FOIS dans le
    Tableau de bord (pour l'agence alors filtrée là-bas, ou pour la vue
    "Toutes les agences") puis appliqué tel quel à TOUTES les agences
    ajoutées ensuite au rapport (bouton "Ajouter une par une" ET bouton
    "Ajouter les N agences d'un coup"), avec les mêmes citations pour des
    agences pourtant totalement différentes (bug réel confirmé sur un
    rapport officiel : 12 agences avec des effectifs de 3 à 100 répondants,
    toutes affichant EXACTEMENT le même commentaire et les mêmes verbatims).
    Cette fonction régénère un résumé propre à `sub_df`, à chaque agence
    ajoutée.

    Classement positif/négatif : même logique que le Tableau de bord
    (renderVerbatims dans dashboard_auto.html) — exclusif (jamais les deux à
    la fois), négatif prioritaire si note insatisfaite, requête non résolue,
    ou motif d'insatisfaction renseigné ; positif sinon si note satisfaite."""
    settings = get_settings()
    if not settings.gemini_configured:
        return {"positifs": [], "negatifs": []}
    if "Commentaire" not in sub_df.columns:
        return {"positifs": [], "negatifs": []}

    sat_col = sub_df["Satisfaction"] if "Satisfaction" in sub_df.columns else None
    resolu_col = sub_df["Resolu"] if "Resolu" in sub_df.columns else None
    motif_col = sub_df["Motif_insatisfaction"] if "Motif_insatisfaction" in sub_df.columns else None

    positifs, negatifs = [], []
    for idx, texte in sub_df["Commentaire"].items():
        texte = str(texte).strip() if texte is not None else ""
        if not texte or texte.lower() == "nan":
            continue
        sat = str(sat_col.loc[idx]) if sat_col is not None and idx in sat_col.index else ""
        resolu = str(resolu_col.loc[idx]).strip() if resolu_col is not None and idx in resolu_col.index else ""
        motif = str(motif_col.loc[idx]).strip() if motif_col is not None and idx in motif_col.index else ""
        est_negatif = (
            ("insatisfait" in sat.lower())
            or resolu.lower().startswith("non")
            or (motif and motif.lower() != "nan")
        )
        if est_negatif:
            negatifs.append(texte)
        elif "satisfait" in sat.lower() and "insatisfait" not in sat.lower():
            positifs.append(texte)

    if not positifs and not negatifs:
        return {"positifs": [], "negatifs": []}

    def _summarize_side(items: list[str], sentiment: str) -> list[str]:
        if not items:
            return []
        sample = items[:60]
        prompt = (
            f"Voici des commentaires clients {'positifs' if sentiment == 'positif' else 'négatifs'} "
            "recueillis dans une agence. Résume-les en AU MAXIMUM 4 points clés (pas plus), courts, "
            "concrets, sans doublons, qui capturent les thèmes récurrents. Réponds UNIQUEMENT avec un "
            'objet JSON de la forme {"points": ["...", "..."]}, sans aucun texte avant ou après, sans '
            "balises markdown.\n\nCommentaires :\n"
            + "\n".join(f"{i+1}. {t}" for i, t in enumerate(sample))
        )
        ok, text, _model = call_gemini(
            prompt, system_instruction=ANALYST_SYSTEM_PROMPT,
            generation_config={"max_output_tokens": 400, "temperature": 0.3},
            models=["gemini-3.5-flash-lite", "gemini-3.7-flash"], timeout_seconds=8,
        )
        if not ok:
            return []
        parsed = _parse_batch_json(text)
        if not parsed:
            return []
        points = parsed.get("points") or []
        return points[:4] if isinstance(points, list) else []

    # Positifs et négatifs EN PARALLÈLE (pas l'un puis l'autre) — même
    # correctif que pour les commentaires de graphiques : deux appels
    # Gemini indépendants qui n'ont aucune raison d'attendre l'un l'autre.
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_pos = executor.submit(_summarize_side, positifs, "positif")
        future_neg = executor.submit(_summarize_side, negatifs, "negatif")
        return {"positifs": future_pos.result(), "negatifs": future_neg.result()}


def _parse_batch_json(text: str) -> dict | None:
    """Extraction tolérante du JSON renvoyé par Gemini : gère les balises
    markdown ```json...```, le texte parasite avant/après, et retombe sur
    une recherche du premier bloc {...} si le parsing direct échoue."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    # Repli : le premier bloc { ... } trouvé dans le texte, au cas où Gemini
    # aurait ajouté une phrase d'intro/conclusion malgré la consigne stricte.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _generate_comments_chunk(charts: list[dict], agences_scope: str, timeout_seconds: int) -> dict[str, str]:
    """Un seul appel Gemini pour un petit lot de graphiques (voir
    `generate_statistician_comments_batch` pour le découpage en lots)."""
    scope_note = f" (portée : {agences_scope})" if agences_scope else ""
    charts_payload = [
        {"id": i, "titre": c["title"], "donnees": c["data_summary"]}
        for i, c in enumerate(charts)
    ]
    prompt = (
        f"Voici {len(charts)} graphiques d'un rapport de satisfaction client{scope_note}, "
        "chacun avec son résumé chiffré :\n\n"
        f"{json.dumps(charts_payload, ensure_ascii=False, default=str, indent=2)}\n\n"
        "Pour CHAQUE graphique (identifié par son \"id\"), rédige un commentaire d'AU MOINS 4 phrases, "
        "en français, pour un responsable de Direction Marketing qui doit comprendre ce graphique en "
        "profondeur — une vraie synthèse, jamais une punchline d'une ligne. Structure attendue : "
        "1) le fait principal / la tendance dominante avec ses chiffres exacts, 2) un second élément "
        "marquant ou une nuance, 3) une mise en perspective (comparaison, ce que ça signifie "
        "concrètement), 4) une implication ou recommandation concrète.\n\n"
        "EXIGENCES STRICTES pour chaque commentaire :\n"
        "- AU MOINS 4 PHRASES par graphique, jamais moins : développe réellement, une punchline d'une "
        "seule phrase n'est plus acceptée.\n"
        "- Chaque phrase doit apporter une information NOUVELLE — pas de reformulation de la précédente.\n"
        "- Ne détaille PAS chaque catégorie une par une — reste sur la vue d'ensemble du graphique "
        "concerné.\n"
        "- Utilise de VRAIS chiffres tirés UNIQUEMENT du résumé de CE graphique.\n"
        "- EXACTITUDE OBLIGATOIRE : valeur exacte avec au plus 2 chiffres après la virgule "
        "(ex: \"89,43 %\"), jamais plus de décimales, jamais d'approximation.\n"
        "- Ton dynamique et direct, pas de style rapport administratif.\n\n"
        "Réponds UNIQUEMENT avec un objet JSON strict, sans markdown, sans texte autour, "
        "de la forme exacte :\n"
        '{"0": "commentaire du graphique 0", "1": "commentaire du graphique 1", ...}\n'
        f"Le JSON doit contenir exactement {len(charts)} clés, de \"0\" à \"{len(charts) - 1}\"."
    )
    ok, text, _model = call_gemini(
        prompt,
        system_instruction=ANALYST_SYSTEM_PROMPT,
        generation_config={"max_output_tokens": min(500 * len(charts), 6000), "temperature": 0.4},
        models=["gemini-3.5-flash-lite", "gemini-3.7-flash"],
        timeout_seconds=timeout_seconds,
    )
    if not ok:
        return {}
    parsed = _parse_batch_json(text)
    if parsed is None:
        return {}
    result = {}
    for i, c in enumerate(charts):
        val = parsed.get(str(i)) or parsed.get(i)
        if isinstance(val, str) and val.strip():
            result[c["title"]] = val.strip()
    return result


def generate_statistician_comments_batch(
    charts: list[dict], agences_scope: str = "", timeout_seconds: int = 25, chunk_size: int = 6,
) -> dict[str, str]:
    """Version groupée de `generate_statistician_comment` : un seul appel
    Gemini par LOT de `chunk_size` graphiques (pas un unique appel géant pour
    tout — voir bug corrigé ci-dessous), avec repli individuel si un lot
    échoue quand même.

    Pourquoi le découpage en lots — bug corrigé ici
    -------------------------------------------------
    Un seul appel Gemini pour TOUS les graphiques de TOUTES les agences à la
    fois (l'ancienne version) demande une réponse JSON de plus en plus
    longue à mesure que le nombre d'agences augmente — le risque que Gemini
    tronque ou déforme légèrement le JSON grandit avec la taille, et **un
    seul** caractère de travers dans cette énorme réponse faisait échouer le
    parsing pour absolument TOUS les graphiques d'un coup (« Commentaire
    indisponible » partout, y compris sur des graphiques dont les données
    étaient parfaitement correctes).

    Découper en petits lots réduit drastiquement ce risque par lot, et
    surtout : si UN lot échoue quand même (réseau, JSON), on retombe sur des
    appels individuels *seulement pour ce lot* — un incident isolé
    n'affecte plus jamais les autres graphiques.

    `charts` : liste de dicts `{"title": str, "data_summary": dict}`.
    Retourne un dict `{title: commentaire}` ; les titres qui échouent même
    en repli individuel obtiennent un message de repli explicite plutôt
    qu'un plantage.
    """
    if not charts:
        return {}

    settings = get_settings()
    if not settings.gemini_configured:
        return {c["title"]: "Clé API Gemini non configurée — commentaire indisponible." for c in charts}

    result: dict[str, str] = {}
    for start in range(0, len(charts), chunk_size):
        chunk = charts[start:start + chunk_size]
        chunk_result = _generate_comments_chunk(chunk, agences_scope, timeout_seconds)
        missing = [c for c in chunk if c["title"] not in chunk_result]
        if missing:
            # Repli individuel, uniquement pour les graphiques manquants de
            # CE lot — jamais tout le rapport qui se retrouve sans commentaire
            # à cause d'un seul lot capricieux.
            for c in missing:
                ok, text = generate_statistician_comment(c["title"], c["data_summary"], agences_scope)
                # Important : en cas d'échec, on garde le VRAI message d'erreur
                # renvoyé par generate_statistician_comment (clé absente, tous
                # les modèles indisponibles, timeout réseau...) au lieu de
                # l'écraser par un message générique qui ne dit rien de la
                # cause réelle — sans ça, impossible de diagnostiquer quoi que
                # ce soit depuis le rapport final.
                chunk_result[c["title"]] = text if ok else f"Commentaire indisponible : {text}"
        result.update(chunk_result)
    return result


def strip_emoji_for_reports(text) -> str:
    """Retire les émojis d'un libellé avant de l'insérer dans un commentaire
    destiné au PDF/Word — même règle que report_builder._strip_emoji,
    dupliquée ici (volontairement, pas importée) pour éviter tout risque
    d'import circulaire entre viz.comments et viz.report_builder. La police
    standard (DejaVu Sans) n'a pas les émojis, ils s'affichaient comme des
    carrés noirs dans le PDF."""
    return re.sub(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]+\s*", "", str(text)).strip()


def generate_fallback_comment(data_summary: dict) -> str:
    """Commentaire de repli SANS IA, à partir du résumé chiffré déjà
    calculé — utilisé quand Gemini échoue (quota atteint, notamment : le
    quota gratuit s'épuise souvent dès la 2e ou 3e agence ajoutée au même
    rapport). Couvre les 10 types de résumés produits par
    `viz.report_charts.build_report_charts` — demande explicite : "tous
    les graphiques doivent avoir des commentaires", peu importe l'état de
    l'API au moment de la génération. Moins riche qu'un commentaire Gemini
    (pas d'angle d'analyse, juste les faits), mais toujours présent."""
    kind = data_summary.get("type")

    if kind == "satisfaction_distribution":
        pcts = data_summary.get("pourcentages_exacts") or {}
        if not pcts:
            return "Aucune réponse de satisfaction enregistrée sur cette période."
        top_key = max(pcts, key=pcts.get)
        top = strip_emoji_for_reports(top_key)
        return f"« {top} » est la réponse la plus fréquente, avec {pcts[top_key]:.2f} % des {data_summary.get('total', 0)} répondants."

    if kind == "resolution":
        pcts = data_summary.get("pourcentages_exacts") or {}
        oui = next((v for k, v in pcts.items() if str(k).strip().upper() == "OUI"), None)
        if oui is not None:
            return f"{oui:.2f} % des demandes ont été résolues, sur {data_summary.get('total', 0)} réponses enregistrées."
        return f"{data_summary.get('total', 0)} réponses enregistrées sur la résolution des demandes."

    if kind == "top_items":
        pcts = data_summary.get("pourcentages_exacts_sur_repondants") or {}
        if not pcts:
            return "Aucun point apprécié cité sur cette période."
        top_key = max(pcts, key=pcts.get)
        top = strip_emoji_for_reports(top_key)
        return f"« {top} » est le point le plus cité, par {pcts[top_key]:.2f} % des {data_summary.get('n_repondants', 0)} répondants."

    if kind == "complaint_reasons":
        pcts = data_summary.get("pourcentages_exacts") or {}
        if not pcts:
            return "Aucun motif d'insatisfaction cité sur cette période."
        top_key = max(pcts, key=pcts.get)
        top = strip_emoji_for_reports(top_key)
        return f"« {top} » est le motif d'insatisfaction le plus cité, par {pcts[top_key]:.2f} % des {data_summary.get('n_insatisfaits', 0)} répondants insatisfaits."

    if kind == "word_cloud":
        mots = data_summary.get("mots_frequents") or {}
        if not mots:
            return "Aucun commentaire libre exploitable sur cette période."
        top_3 = ", ".join(f"« {m} »" for m in list(mots.keys())[:3])
        return f"Les mots les plus cités dans les commentaires libres sont {top_3}."

    if kind == "volume_over_time":
        par_mois = data_summary.get("par_mois") or {}
        if not par_mois:
            return "Aucune donnée temporelle disponible."
        total = sum(par_mois.values())
        return f"{total} réponses au total, réparties sur {len(par_mois)} mois."

    if kind == "satisfaction_rate_over_time":
        par_mois = data_summary.get("par_mois_pct") or {}
        if not par_mois:
            return "Aucune donnée temporelle de satisfaction disponible."
        first_val, last_val = list(par_mois.values())[0], list(par_mois.values())[-1]
        tendance = "en hausse" if last_val > first_val else "en baisse" if last_val < first_val else "stable"
        return f"Le taux de satisfaction est {tendance} sur la période, de {first_val:.1f} % à {last_val:.1f} %."

    if kind == "respondents_by_agency":
        eff = data_summary.get("effectifs") or {}
        if not eff:
            return "Aucune donnée par agence disponible."
        top = max(eff, key=eff.get)
        return f"{top} totalise le plus de répondants ({eff[top]} sur {sum(eff.values())} au total)."

    if kind == "satisfaction_by_agency":
        sat = data_summary.get("taux_satisfaction") or {}
        if not sat:
            return "Aucune donnée de satisfaction par agence disponible."
        top = max(sat, key=sat.get)
        low = min(sat, key=sat.get)
        return f"{top} a le meilleur taux de satisfaction ({sat[top]:.1f} %), {low} le plus faible ({sat[low]:.1f} %)."

    if kind == "resolution_by_agency":
        res = data_summary.get("taux_resolution") or {}
        if not res:
            return "Aucune donnée de résolution par agence disponible."
        top = max(res, key=res.get)
        low = min(res, key=res.get)
        return f"{top} a le meilleur taux de résolution ({res[top]:.1f} %), {low} le plus faible ({res[low]:.1f} %)."

    return "Données insuffisantes pour générer un commentaire."
