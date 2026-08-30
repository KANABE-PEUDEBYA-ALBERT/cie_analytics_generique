"""
Chargement centralisé de la configuration de l'application.

Toutes les valeurs sensibles (clés, mots de passe, identifiants de base de
données) viennent de variables d'environnement (via un fichier .env local,
jamais commité) — rien n'est écrit en dur dans le code source.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_STORE_DIR = BASE_DIR / "data_store"
DATA_STORE_DIR.mkdir(exist_ok=True)

# Charge le fichier .env s'il existe (développement local). En production,
# les variables d'environnement peuvent être injectées directement par le
# serveur/l'orchestrateur, sans fichier .env.
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    """Lit une variable de config, en cherchant dans cet ordre :
    1. os.environ (fichier .env en local, ou variables injectées par un
       serveur classique)
    2. st.secrets (Streamlit Community Cloud) — le panneau "Secrets" du
       Cloud n'injecte PAS automatiquement dans os.environ, donc sans ce
       fallback, tout identifiant configuré uniquement là-bas est
       silencieusement ignoré (c'est ce qui provoquait une connexion
       admin refusée malgré des identifiants a priori corrects).
    """
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


@dataclass(frozen=True)
class Settings:
    app_secret_key: str
    users_db_url: str
    anthropic_api_key: str
    gemini_api_key: str
    bootstrap_admin_email: str
    bootstrap_admin_password: str

    external_db_type: str
    external_db_host: str
    external_db_port: str
    external_db_name: str
    external_db_user: str
    external_db_password: str

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def external_db_configured(self) -> bool:
        return bool(self.external_db_type.strip() and self.external_db_host.strip())


def get_settings() -> Settings:
    """Retourne la configuration courante, lue à chaque appel (permet de
    changer le .env et de relancer l'app sans modifier le code)."""
    return Settings(
        app_secret_key=_get("APP_SECRET_KEY", "dev-only-not-secure"),
        users_db_url=_get("USERS_DB_URL", f"sqlite:///{DATA_STORE_DIR / 'users.db'}"),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        gemini_api_key=_get("GEMINI_API_KEY"),
        bootstrap_admin_email=_get("BOOTSTRAP_ADMIN_EMAIL", "admin@cie.ci"),
        bootstrap_admin_password=_get("BOOTSTRAP_ADMIN_PASSWORD", "ChangeMoi123!"),
        external_db_type=_get("EXTERNAL_DB_TYPE"),
        external_db_host=_get("EXTERNAL_DB_HOST"),
        external_db_port=_get("EXTERNAL_DB_PORT"),
        external_db_name=_get("EXTERNAL_DB_NAME"),
        external_db_user=_get("EXTERNAL_DB_USER"),
        external_db_password=_get("EXTERNAL_DB_PASSWORD"),
    )


# --- Identité visuelle CIE ---------------------------------------------
CIE_ORANGE = "#F7941D"
CIE_GREEN = "#009A44"
CIE_YELLOW = "#FFC72C"
CIE_BLUE = "#1A73E8"
CIE_WHITE = "#FFFFFF"
CIE_DARK = "#1A1A1A"
LOGO_PATH = BASE_DIR / "assets" / "logo_cie.png"

ROLES = ("administrateur", "direction", "responsable", "utilisateur")

ROLE_LABELS = {
    "administrateur": "Administrateur",
    "direction": "Direction",
    "responsable": "Responsable de service",
    "utilisateur": "Utilisateur standard",
}
