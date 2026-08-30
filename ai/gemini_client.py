"""
Client Gemini centralisé, avec fallback automatique entre plusieurs modèles.

Pourquoi ce module existe
--------------------------
Les alias Google (`gemini-flash-latest`, `gemini-pro-latest`...) peuvent être
repointés du jour au lendemain vers un nouveau modèle dont le quota gratuit
est minuscule. C'est exactement ce qui s'est produit : `gemini-flash-latest`
pointait vers `gemini-3.6-flash`, plafonné à 20 requêtes/jour en free tier,
ce qui bloquait l'assistant après quelques messages.

Ce module règle ça une fois pour toutes :
  1. il épingle des noms de modèles précis (jamais uniquement un alias
     "-latest" en première position) ;
  2. à chaque appel, il essaie plusieurs modèles dans l'ordre et bascule
     automatiquement sur le suivant si le modèle courant renvoie un quota
     dépassé (429), une indisponibilité (503) ou une erreur de modèle
     inconnu (404) ;
  3. il centralise la détection des réponses vides / bloquées / tronquées
     (finish_reason, prompt_feedback), pour que toutes les pages de l'appli
     partagent exactement la même logique de robustesse au lieu de la
     dupliquer dans chaque fichier appelant.

⚠️ Les quotas exacts du free tier changent régulièrement côté Google — pour
les valeurs à jour sur TON projet, voir https://aistudio.google.com/rate-limit.
La liste ci-dessous privilégie les modèles réputés les plus généreux en free
tier (Flash-Lite) en premier, avec des modèles plus capables ensuite, et
l'alias mouvant en tout dernier recours seulement.
"""
from __future__ import annotations

import logging
from typing import Any

from config.settings import get_settings

logger = logging.getLogger(__name__)

# Ordre de fallback, du plus économe en quota gratuit au plus capable.
# Modifiable librement ici sans toucher au code appelant (10_Assistant.py,
# viz/comments.py...).
#
# ⚠️ gemini-2.5-flash-lite, gemini-3.1-flash-lite et gemini-2.5-flash ont été
# RETIRÉS par Google ("404 This model ... is no longer available to new
# users") — c'était la cause de fond de tous les "Commentaire indisponible"
# rencontrés dans toute l'application (Assistant, Tableau de bord,
# Générateur de rapport) : le code appelait des modèles qui n'existent
# simplement plus, pas un bug de logique. Google indique lui-même les noms
# de remplacement dans le message d'erreur — utilisés ci-dessous.
#
# ⚠️ Deuxième bug corrigé ici, plus subtil : la chaîne listait ensuite
# "gemini-3.6-flash" PUIS l'alias "gemini-flash-latest" comme ultime
# secours — sauf que cet alias POINTAIT VERS CE MÊME gemini-3.6-flash (vu
# dans un message d'erreur réel : quota gratuit plafonné à 20 requêtes/jour
# pour ce modèle précis). Résultat : le "secours" retombait sur le modèle
# déjà épuisé, doublant l'attente pour zéro bénéfice. Remplacé par
# gemini-3.7-flash (sorti le 13/08/2026), un modèle RÉELLEMENT différent,
# avec son propre quota séparé.
DEFAULT_MODEL_CHAIN: list[str] = [
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
]

# Fragments identifiant une erreur de quota/disponibilité (429, 503, 404...)
# après laquelle on bascule immédiatement sur le modèle suivant. Toute autre
# exception fait aussi basculer (mieux vaut essayer un autre modèle que de
# planter), mais ce sont les cas explicitement attendus.
_QUOTA_OR_AVAILABILITY_HINTS = (
    "429", "resourceexhausted", "quota",
    "503", "unavailable", "overloaded",
    "404", "notfound",
)


def _is_expected_fallback_case(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(hint in text for hint in _QUOTA_OR_AVAILABILITY_HINTS)


def _is_timeout_exception(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "timeout" in text or "deadline" in text


def _extract_text(response: Any) -> tuple[bool, str]:
    """Distingue une vraie réponse texte d'un blocage/troncature, avec un
    message clair dans le second cas plutôt qu'une erreur brute."""
    try:
        text = (response.text or "").strip()
    except Exception:
        text = ""
    if text:
        return True, text

    reason = None
    if getattr(response, "candidates", None):
        reason = getattr(response.candidates[0], "finish_reason", None)
    feedback = getattr(response, "prompt_feedback", None)
    if feedback and getattr(feedback, "block_reason", None):
        return False, f"Réponse bloquée par Gemini (motif : {feedback.block_reason})."
    if reason is not None and str(reason) not in ("1", "STOP"):
        if str(reason) in ("2", "MAX_TOKENS"):
            return False, (
                "Réponse tronquée car le modèle a épuisé son budget de tokens en réflexion "
                "interne avant d'écrire la réponse. Réessaie, ou pose une question plus courte."
            )
        return False, f"Réponse interrompue par Gemini (finish_reason={reason}). Réessaie ou reformule."
    return False, "Réponse vide de l'API."


def call_gemini(
    contents: Any,
    system_instruction: str,
    generation_config: dict | None = None,
    models: list[str] | None = None,
    timeout_seconds: int = 25,
) -> tuple[bool, str, str]:
    """Appelle Gemini avec fallback automatique de modèles.

    `contents` : tout ce qu'accepte `GenerativeModel.generate_content`
    (chaîne simple, ou liste de messages {"role": ..., "parts": [...]}).

    `timeout_seconds` : délai max par modèle avant d'abandonner et de
    basculer sur le suivant. Sans ça, un modèle qui ne répond jamais (réseau
    lent, appel bloqué côté Google) fige l'application indéfiniment, sans
    la moindre erreur affichée — c'est le bug historique corrigé ici.

    Retourne (succès, texte_ou_message_d'erreur, nom_du_modèle_utilisé).
    Le nom de modèle vaut "" uniquement si TOUS les modèles ont échoué.
    """
    settings = get_settings()
    if not settings.gemini_configured:
        return False, "Clé API Gemini non configurée.", ""

    try:
        import google.generativeai as genai
    except ImportError:
        return False, "Le package 'google-generativeai' n'est pas installé (pip install google-generativeai).", ""

    genai.configure(api_key=settings.gemini_api_key)

    chain = models or DEFAULT_MODEL_CHAIN
    errors: list[str] = []

    for i, model_name in enumerate(chain):
        is_last = i == len(chain) - 1
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_instruction,
            )
            response = model.generate_content(
                contents,
                generation_config=generation_config or {},
                request_options={"timeout": timeout_seconds},
            )
            ok, text = _extract_text(response)
            if ok and i > 0:
                logger.info("Gemini : bascule réussie sur le modèle de secours '%s'.", model_name)
            # Qu'elle réussisse ou qu'elle échoue "proprement" (bloquée,
            # tronquée, vide), la réponse n'est PAS un souci de quota/dispo :
            # inutile d'essayer un autre modèle, on la retourne telle quelle.
            return ok, text, model_name
        except Exception as exc:  # noqa: BLE001 - jamais planter l'app pour un souci réseau/API
            label = "TimeoutError" if _is_timeout_exception(exc) else type(exc).__name__
            errors.append(f"{model_name} → {label}: {exc}")
            if is_last:
                break
            if _is_timeout_exception(exc):
                logger.warning("Gemini : '%s' n'a pas répondu sous %ss, bascule sur le suivant.", model_name, timeout_seconds)
            elif _is_expected_fallback_case(exc):
                logger.warning("Gemini : '%s' indisponible ou quota dépassé, bascule sur le suivant.", model_name)
            else:
                logger.warning("Gemini : erreur inattendue sur '%s', tentative sur le suivant quand même.", model_name)
            continue

    detail = " | ".join(errors)
    return False, f"Tous les modèles Gemini configurés ont échoué. Détails : {detail}", ""
