"""
Fonctions d'authentification et de gestion des sessions Streamlit.

Mots de passe toujours hachés avec bcrypt (jamais stockés en clair).
Chaque utilisateur connecté a son propre st.session_state, donc ses
filtres/pipelines/historique restent indépendants des autres sessions.
"""
from __future__ import annotations

import bcrypt
import streamlit as st

from auth.database import User, get_session, get_user_by_email, init_db, count_users
from config.settings import get_settings


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Politique de mot de passe active pour TOUTE création/réinitialisation
    de mot de passe (inscription, création par un administrateur,
    réinitialisation) : au moins 8 caractères, une majuscule, une minuscule,
    un chiffre et un caractère spécial. Renvoie (valide, message d'erreur ou
    chaîne vide)."""
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."
    if not any(c.isupper() for c in password):
        return False, "Le mot de passe doit contenir au moins une majuscule."
    if not any(c.islower() for c in password):
        return False, "Le mot de passe doit contenir au moins une minuscule."
    if not any(c.isdigit() for c in password):
        return False, "Le mot de passe doit contenir au moins un chiffre."
    special_chars = "!@#$%^&*()-_=+[]{};:,.<>/?|~`'\""
    if not any(c in special_chars for c in password):
        return False, "Le mot de passe doit contenir au moins un caractère spécial (ex: ! @ # $ %)."
    return True, ""


def ensure_bootstrap_admin() -> None:
    """Crée un compte administrateur par défaut au tout premier lancement,
    si la base d'utilisateurs est vide. Permet de se connecter la première
    fois sans intervention manuelle en base."""
    init_db()
    if count_users() > 0:
        return
    settings = get_settings()
    with get_session() as session:
        admin = User(
            email=settings.bootstrap_admin_email.strip().lower(),
            full_name="Administrateur",
            password_hash=hash_password(settings.bootstrap_admin_password),
            role="administrateur",
            service="Direction Marketing",
            is_active=True,
        )
        session.add(admin)
        session.commit()


def create_user(email: str, full_name: str, password: str, role: str, service: str = "") -> tuple[bool, str]:
    if get_user_by_email(email):
        return False, "Un compte existe déjà avec cet email."
    with get_session() as session:
        user = User(
            email=email.strip().lower(),
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            role=role,
            service=service,
            is_active=True,
        )
        session.add(user)
        session.commit()
    return True, "Compte créé avec succès."


def set_user_active(user_id: int, is_active: bool) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        if user:
            user.is_active = is_active
            session.commit()


def update_user_role(user_id: int, role: str) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        if user:
            user.role = role
            session.commit()


def reset_password(user_id: int, new_password: str) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        if user:
            user.password_hash = hash_password(new_password)
            session.commit()


def self_register(email: str, full_name: str, password: str, service: str = "") -> tuple[bool, str]:
    """Auto-inscription depuis l'onglet 'Créer un compte'.

    Le compte est créé mais INACTIF : il ne peut pas se connecter tant
    qu'un administrateur ne l'a pas activé (segment Administration). Ce
    compromis permet d'avoir un vrai onglet d'inscription visible côté
    utilisateur, sans ouvrir un accès immédiat non contrôlé aux données
    de la CIE.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return False, "Adresse email invalide."
    if get_user_by_email(email):
        return False, "Un compte existe déjà avec cet email."
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."
    with get_session() as session:
        user = User(
            email=email,
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            role="utilisateur",
            service=service.strip(),
            is_active=False,
        )
        session.add(user)
        session.commit()
    return True, "Compte créé. Un administrateur doit l'activer avant que tu puisses te connecter."


def attempt_login(email: str, password: str) -> tuple[bool, str]:
    user = get_user_by_email(email)
    if user is None or not verify_password(password, user.password_hash):
        return False, "Email ou mot de passe incorrect."
    if not user.is_active:
        return False, "Ce compte a été désactivé. Contacte un administrateur."

    st.session_state["auth_user_id"] = user.id
    st.session_state["auth_email"] = user.email
    st.session_state["auth_full_name"] = user.full_name
    st.session_state["auth_role"] = user.role
    st.session_state["auth_service"] = user.service
    return True, "Connexion réussie."


def logout() -> None:
    for key in ("auth_user_id", "auth_email", "auth_full_name", "auth_role", "auth_service"):
        st.session_state.pop(key, None)


def is_authenticated() -> bool:
    return "auth_user_id" in st.session_state


def current_role() -> str | None:
    return st.session_state.get("auth_role")


def current_user_label() -> str:
    return st.session_state.get("auth_full_name") or st.session_state.get("auth_email", "")


def require_role(*allowed_roles: str) -> bool:
    """Retourne True si le rôle courant est autorisé. À utiliser en tête
    de chaque page sensible (ex: Administration)."""
    return current_role() in allowed_roles
