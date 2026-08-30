"""Page 9 — Administration (gestion des comptes). Visible uniquement par les administrateurs."""
from __future__ import annotations
from config.theme import set_page_title

import streamlit as st

from auth.auth_utils import (
    create_user,
    require_role,
    reset_password,
    set_user_active,
    update_user_role,
    validate_password_strength,
)
from auth.database import list_users
from config.settings import ROLE_LABELS, ROLES

set_page_title("⚙️ Administration", "Gestion des comptes et des droits")
if not require_role("administrateur"):
    st.error("Accès réservé aux administrateurs.")
    st.stop()

st.markdown(
    "<style>.block-container > [data-testid=\"stVerticalBlock\"]{gap:0 !important;}</style>",
    unsafe_allow_html=True,
)

st.markdown("### Créer un compte")
# Simplifié — juste email + mot de passe, exactement comme l'onglet
# "S'inscrire" de l'écran de connexion (demande explicite : "on a juste
# besoin du mail et du mot de passe... supprime les autres [nom, rôle,
# service]"). Rôle par défaut : "utilisateur" (le plus bas niveau de
# droits, même valeur que self_register), modifiable ensuite depuis la
# liste "Comptes existants" plus bas si besoin.
with st.form("create_user_form", clear_on_submit=True):
    email = st.text_input("Email professionnel")
    password = st.text_input("Mot de passe temporaire", type="password")
    submitted = st.form_submit_button("Créer le compte", type="primary")

if submitted:
    if not email or not password:
        st.error("Email et mot de passe sont obligatoires.")
    else:
        strong, pwd_message = validate_password_strength(password)
        if not strong:
            st.error(pwd_message)
        else:
            ok, message = create_user(email, "", password, "utilisateur", "")
            (st.success if ok else st.error)(message)


pending = [u for u in list_users() if not u.is_active]
if pending:
    st.warning(
        f"🔔 {len(pending)} compte(s) en attente de validation (créés via l'onglet "
        "« Créer un compte » de l'écran de connexion)."
    )

st.markdown("### Comptes existants")
users = list_users()
if not users:
    st.caption("Aucun utilisateur.")
else:
    for user in users:
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([2.5, 2, 1.5, 1, 1.5])
            c1.markdown(f"**{user.full_name or '—'}**  \n{user.email}")
            c2.caption(user.service or "—")

            new_role = c3.selectbox(
                "Rôle", ROLES, index=ROLES.index(user.role) if user.role in ROLES else 0,
                key=f"role_{user.id}", label_visibility="collapsed",
                format_func=lambda r: ROLE_LABELS.get(r, r),
            )
            if new_role != user.role:
                update_user_role(user.id, new_role)
                st.rerun()

            active_label = "Actif ✅" if user.is_active else "Désactivé ⛔"
            if c4.button(active_label, key=f"toggle_{user.id}"):
                set_user_active(user.id, not user.is_active)
                st.rerun()

            with c5.popover("Réinitialiser mot de passe"):
                new_pw = st.text_input("Nouveau mot de passe", type="password", key=f"pw_{user.id}")
                if st.button("Valider", key=f"pw_btn_{user.id}"):
                    if not new_pw:
                        st.error("Le mot de passe est requis.")
                    else:
                        strong, pwd_message = validate_password_strength(new_pw)
                        if not strong:
                            st.error(pwd_message)
                        else:
                            reset_password(user.id, new_pw)
                            st.success("Mot de passe mis à jour.")
