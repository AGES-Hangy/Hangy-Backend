from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.entities import UserCredentials
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserTypeEnum,
)
from app.domain.services import AuthService
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    UserModel,
    event_tag,
    user_tag,
)
from app.infrastructure.repository.session import SessionLocal
from app.infrastructure.repository.user import SqlAlchemyUserRepository

SEED_USERS = (
    UserCredentials(
        email="user@hangy.com",
        password="user-password",
        user_type=UserTypeEnum.PERSONAL,
    ),
    UserCredentials(
        email="admin@hangy.com",
        password="admin-password",
        user_type=UserTypeEnum.BUSINESS,
    ),
    UserCredentials(
        email="maria@hangy.com",
        password="maria-password",
        user_type=UserTypeEnum.PERSONAL,
    ),
    UserCredentials(
        email="joao@hangy.com",
        password="joao-password",
        user_type=UserTypeEnum.PERSONAL,
    ),
)

# Macro tag (no parent) mapped to the micro tags that hang below it. The feed
# groups by the macro tag, so every micro tag here must roll up to one.
SEED_TAGS: dict[str, tuple[str, ...]] = {
    "Esportes": ("Futebol", "Corrida"),
    "Música": ("Rock", "Samba", "Sertanejo"),
    "Gastronomia": ("Churrasco", "Culinária Italiana", "Confeitaria"),
    "Arte e Cultura": ("Teatro", "Cinema"),
}

# admin@hangy.com is a BUSINESS user and stays without interests, which makes it
# the account to check the empty feed with.
SEED_INTERESTS: dict[str, tuple[str, ...]] = {
    "user@hangy.com": ("Futebol", "Corrida", "Rock"),
    "maria@hangy.com": ("Samba",),
}

EVENT_DURATION = timedelta(hours=3)
# Porto Alegre, roughly around Parque da Redenção.
EVENT_LATITUDE = -30.0368
EVENT_LONGITUDE = -51.2090


@dataclass(frozen=True, slots=True)
class SeedEvent:
    title: str
    tag_name: str
    creator_email: str
    # Days from "now", so a restart always leaves the feed with future events.
    starts_in_days: int
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC
    event_status: EventStatusEnum = EventStatusEnum.CREATED
    cover_photo_url: str | None = None
    confirmed_emails: tuple[str, ...] = field(default_factory=tuple)
    pending_emails: tuple[str, ...] = field(default_factory=tuple)


SEED_EVENTS = (
    # Visible in the feed of user@hangy.com, under "Esportes".
    SeedEvent(
        title="Pelada no Parcão",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=1,
        cover_photo_url="https://picsum.photos/seed/pelada/800/450",
        confirmed_emails=("maria@hangy.com", "joao@hangy.com"),
    ),
    SeedEvent(
        title="Corrida da Redenção",
        tag_name="Corrida",
        creator_email="admin@hangy.com",
        starts_in_days=4,
        confirmed_emails=("maria@hangy.com",),
        pending_emails=("joao@hangy.com",),
    ),
    # Visible, but without event_date and location_name.
    SeedEvent(
        title="Aniversário da Maria",
        tag_name="Futebol",
        creator_email="maria@hangy.com",
        starts_in_days=2,
        privacy=EventPrivacyEnum.PRIVATE,
        pending_emails=("joao@hangy.com",),
    ),
    # Never visible: reachable only through its invite link.
    SeedEvent(
        title="Rachão fechado",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=3,
        privacy=EventPrivacyEnum.INVITE_ONLY,
    ),
    # Visible, under "Música".
    SeedEvent(
        title="Show de rock no Opinião",
        tag_name="Rock",
        creator_email="admin@hangy.com",
        starts_in_days=5,
        cover_photo_url="https://picsum.photos/seed/rock/800/450",
        pending_emails=("maria@hangy.com",),
    ),
    # Invisible: user@hangy.com has no interest in these tags.
    SeedEvent(
        title="Roda de samba na Cidade Baixa",
        tag_name="Samba",
        creator_email="maria@hangy.com",
        starts_in_days=6,
    ),
    SeedEvent(
        title="Churrasco do bairro",
        tag_name="Churrasco",
        creator_email="joao@hangy.com",
        starts_in_days=7,
    ),
    # Invisible: already happened, or never published.
    SeedEvent(
        title="Pelada de ontem",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=-1,
    ),
    SeedEvent(
        title="Pelada em rascunho",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=8,
        event_status=EventStatusEnum.DRAFT,
    ),
    SeedEvent(
        title="Pelada cancelada",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=9,
        event_status=EventStatusEnum.CANCELLED,
    ),
)


def seed_users(db: Session) -> None:
    repository = SqlAlchemyUserRepository(db)
    auth_service = AuthService(
        repository=repository,
        jwt_secret_key=settings.jwt_secret_key,
        jwt_algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )

    for credentials in SEED_USERS:
        if repository.get_by_email(credentials.email) is None:
            auth_service.register(credentials)


def seed_tags(db: Session) -> None:
    for macro_name, micro_names in SEED_TAGS.items():
        macro = db.scalar(
            select(TagModel).where(
                TagModel.tag_name == macro_name,
                TagModel.tag_parent_id.is_(None),
            )
        )
        if macro is None:
            macro = TagModel(tag_name=macro_name)
            db.add(macro)
            db.flush()

        existing_micro_names = set(
            db.scalars(
                select(TagModel.tag_name).where(TagModel.tag_parent_id == macro.tag_id)
            )
        )
        for micro_name in micro_names:
            if micro_name not in existing_micro_names:
                db.add(TagModel(tag_name=micro_name, tag_parent_id=macro.tag_id))

    db.commit()


def seed_user_interests(db: Session) -> None:
    users = _users_by_email(db)
    tags = _tags_by_name(db)

    for email, tag_names in SEED_INTERESTS.items():
        user = users.get(email)
        if user is None:
            continue
        for tag_name in tag_names:
            tag = tags.get(tag_name)
            if tag is None or _has_interest(db, user.user_id, tag.tag_id):
                continue
            db.execute(
                user_tag.insert().values(user_id=user.user_id, tag_id=tag.tag_id)
            )
    db.commit()


def seed_events(db: Session) -> None:
    users = _users_by_email(db)
    tags = _tags_by_name(db)
    now = datetime.now(UTC)

    for seed in SEED_EVENTS:
        creator = users.get(seed.creator_email)
        tag = tags.get(seed.tag_name)
        if creator is None or tag is None:
            continue

        starts_at = now + timedelta(days=seed.starts_in_days)
        event = db.scalar(
            select(EventModel).where(EventModel.event_title == seed.title)
        )
        if event is None:
            event = EventModel(
                event_creator_id=creator.user_id,
                event_title=seed.title,
                event_description=f"Evento de exemplo criado pelo seed: {seed.title}.",
                event_latitude=EVENT_LATITUDE,
                event_longitude=EVENT_LONGITUDE,
                starts_at=starts_at,
                ends_at=starts_at + EVENT_DURATION,
                event_status=seed.event_status,
                event_privacy=seed.privacy,
                cover_photo_url=seed.cover_photo_url,
            )
            db.add(event)
            db.flush()
            db.execute(
                event_tag.insert().values(event_id=event.event_id, tag_id=tag.tag_id)
            )
        else:
            # Slide the schedule forward so the feed keeps working after a
            # restart instead of slowly filling up with past events.
            event.starts_at = starts_at
            event.ends_at = starts_at + EVENT_DURATION

        _seed_participants(db, event, seed, users)
    db.commit()


def _seed_participants(
    db: Session,
    event: EventModel,
    seed: SeedEvent,
    users: dict[str, UserModel],
) -> None:
    participations = (
        (seed.confirmed_emails, EventParticipantStatusEnum.CONFIRMED),
        (seed.pending_emails, EventParticipantStatusEnum.PENDING),
    )
    for emails, status in participations:
        for email in emails:
            user = users.get(email)
            if user is None or _is_participant(db, event.event_id, user.user_id):
                continue
            db.add(
                EventParticipantModel(
                    event_id=event.event_id,
                    user_id=user.user_id,
                    status=status,
                )
            )


def _users_by_email(db: Session) -> dict[str, UserModel]:
    return {user.email: user for user in db.scalars(select(UserModel)).all()}


def _tags_by_name(db: Session) -> dict[str, TagModel]:
    return {tag.tag_name: tag for tag in db.scalars(select(TagModel)).all()}


def _has_interest(db: Session, user_id: UUID, tag_id: UUID) -> bool:
    return (
        db.execute(
            select(user_tag.c.user_id).where(
                user_tag.c.user_id == user_id,
                user_tag.c.tag_id == tag_id,
            )
        ).first()
        is not None
    )


def _is_participant(db: Session, event_id: UUID, user_id: UUID) -> bool:
    return (
        db.scalar(
            select(EventParticipantModel.participant_id).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == user_id,
            )
        )
        is not None
    )


def main() -> None:
    with SessionLocal() as db:
        seed_users(db)
        seed_tags(db)
        seed_user_interests(db)
        seed_events(db)


if __name__ == "__main__":
    main()
