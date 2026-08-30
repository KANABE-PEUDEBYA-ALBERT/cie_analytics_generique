"""
Base de données des comptes utilisateurs (SQLite en développement,
migrable vers PostgreSQL ou la base CIE en changeant simplement
USERS_DB_URL dans le .env — le code ORM ne change pas).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from config.settings import get_settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50))  # administrateur / direction / responsable / utilisateur
    service: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class Conversation(Base):
    """Une conversation de l'Assistant, propre à un utilisateur (comme les
    'projets'/fils de discussion d'un assistant IA classique)."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Nouvelle conversation")
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class ConversationMessage(Base):
    """Un message (utilisateur ou assistant) d'une conversation."""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" ou "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.users_db_url.startswith("sqlite") else {}
        _engine = create_engine(settings.users_db_url, connect_args=connect_args)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def init_db() -> None:
    """Crée les tables si elles n'existent pas encore, et applique les
    petites migrations de schéma nécessaires (ajout de colonnes) sur une
    base déjà existante — sans jamais toucher aux données déjà présentes."""
    Base.metadata.create_all(get_engine())
    _migrate_add_missing_columns()


def _migrate_add_missing_columns() -> None:
    """Ajoute les colonnes manquantes sur des tables déjà créées par une
    version antérieure de l'application (SQLite ne le fait pas tout seul
    via create_all, qui ne crée que les tables absentes)."""
    from sqlalchemy import inspect, text

    engine = get_engine()
    inspector = inspect(engine)
    if "conversations" not in inspector.get_table_names():
        return
    existing_cols = {col["name"] for col in inspector.get_columns("conversations")}
    if "is_closed" not in existing_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN is_closed BOOLEAN DEFAULT 0"))


def get_session() -> Session:
    return get_session_factory()()


def get_user_by_email(email: str) -> User | None:
    with get_session() as session:
        stmt = select(User).where(User.email == email.strip().lower())
        return session.scalar(stmt)


def list_users() -> list[User]:
    with get_session() as session:
        return list(session.scalars(select(User).order_by(User.created_at)))


def count_users() -> int:
    with get_session() as session:
        return len(list(session.scalars(select(User))))


# --- Conversations de l'Assistant -------------------------------------

def create_conversation(user_id: int, title: str = "Nouvelle conversation") -> Conversation:
    with get_session() as session:
        conv = Conversation(user_id=user_id, title=title)
        session.add(conv)
        session.commit()
        session.refresh(conv)
        return conv


def list_conversations(user_id: int) -> list[Conversation]:
    with get_session() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(session.scalars(stmt))


def get_conversation(conversation_id: int, user_id: int) -> Conversation | None:
    """Récupère une conversation en vérifiant qu'elle appartient bien à
    l'utilisateur (pas d'accès croisé entre comptes)."""
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            return None
        return conv


def rename_conversation(conversation_id: int, title: str) -> None:
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv:
            conv.title = title[:255]
            session.commit()


def close_conversation(conversation_id: int, user_id: int) -> None:
    """Marque la conversation comme terminée : reste visible et consultable
    dans l'historique, mais n'accepte plus de nouveaux messages tant
    qu'elle n'est pas rouverte."""
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv and conv.user_id == user_id:
            conv.is_closed = True
            session.commit()


def reopen_conversation(conversation_id: int, user_id: int) -> None:
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv and conv.user_id == user_id:
            conv.is_closed = False
            session.commit()


def touch_conversation(conversation_id: int) -> None:
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = dt.datetime.utcnow()
            session.commit()


def delete_conversation(conversation_id: int, user_id: int) -> None:
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            return
        stmt = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
        for msg in session.scalars(stmt):
            session.delete(msg)
        session.delete(conv)
        session.commit()


def add_conversation_message(conversation_id: int, role: str, content: str) -> None:
    with get_session() as session:
        session.add(ConversationMessage(conversation_id=conversation_id, role=role, content=content))
        conv = session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = dt.datetime.utcnow()
        session.commit()


def list_conversation_messages(conversation_id: int) -> list[ConversationMessage]:
    with get_session() as session:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
        )
        return list(session.scalars(stmt))
