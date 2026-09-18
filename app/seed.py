from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import BusinessRegistration, PersonRegistration
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)
from app.domain.services import RegisterBusinessService, RegisterPersonalService
from app.infrastructure.repository.business_profile import (
    SqlAlchemyBusinessRegistrationRepository,
)
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    UserModel,
    event_tag,
    user_tag,
)
from app.infrastructure.repository.person_profile import (
    SqlAlchemyPersonRegistrationRepository,
)
from app.infrastructure.repository.session import SessionLocal
from app.infrastructure.repository.user import SqlAlchemyUserRepository

SEED_TERMS_VERSION = "2026-08-01"

SEED_USERS: tuple[PersonRegistration | BusinessRegistration, ...] = (
    PersonRegistration(
        email="user@hangy.com",
        password="user-password",
        name="Usuário Hangy",
        cpf="52998224725",
        date_of_birth=date(1995, 4, 12),
        country="BR",
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    BusinessRegistration(
        email="admin@hangy.com",
        password="admin-password",
        business_name="Admin Hangy",
        cnpj="11222333000181",
        address="Av. Independência, 100 — Porto Alegre",
        latitude=-30.0331,
        longitude=-51.23,
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    PersonRegistration(
        email="maria@hangy.com",
        password="maria-password",
        name="Maria Silva",
        cpf="11144477735",
        date_of_birth=date(1998, 8, 3),
        country="BR",
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    PersonRegistration(
        email="joao@hangy.com",
        password="joao-password",
        name="João Souza",
        cpf="46713890296",
        date_of_birth=date(2000, 1, 20),
        country="BR",
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
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
    location_name: str
    tag_name: str
    creator_email: str
    # Days from "now", so a restart always leaves the feed with future events.
    starts_in_days: int
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED
    cover_photo_url: str | None = None
    confirmed_emails: tuple[str, ...] = field(default_factory=tuple)
    pending_emails: tuple[str, ...] = field(default_factory=tuple)


SEED_EVENTS = (
    # Visible in the feed of user@hangy.com, under "Esportes".
    SeedEvent(
        title="Pelada no Parcão",
        location_name="Parque Moinhos de Vento (Parcão)",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=1,
        cover_photo_url="https://picsum.photos/seed/pelada/800/450",
        confirmed_emails=("maria@hangy.com", "joao@hangy.com"),
    ),
    # user@hangy.com's own event, kept PRIVATE on purpose: it's what makes
    # ManageEvent worth opening as user@hangy.com — a confirmed participant,
    # a pending request to approve, and the privacy badge/masking to check.
    SeedEvent(
        title="Corrida da Redenção",
        location_name="Parque Farroupilha (Redenção)",
        tag_name="Corrida",
        creator_email="user@hangy.com",
        starts_in_days=4,
        privacy=EventPrivacyEnum.PRIVATE,
        confirmed_emails=("maria@hangy.com",),
        pending_emails=("joao@hangy.com",),
    ),
    # Visible, but the feed hides event_date and location_name for PRIVATE events.
    SeedEvent(
        title="Aniversário da Maria",
        location_name="Casa da Maria",
        tag_name="Futebol",
        creator_email="maria@hangy.com",
        starts_in_days=2,
        privacy=EventPrivacyEnum.PRIVATE,
        pending_emails=("joao@hangy.com",),
    ),
    # Never visible: reachable only through its invite link.
    SeedEvent(
        title="Rachão fechado",
        location_name="Quadra do bairro",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=3,
        privacy=EventPrivacyEnum.INVITE_ONLY,
    ),
    # Visible, under "Música".
    SeedEvent(
        title="Show de rock no Opinião",
        location_name="Bar Opinião",
        tag_name="Rock",
        creator_email="admin@hangy.com",
        starts_in_days=5,
        cover_photo_url="https://picsum.photos/seed/rock/800/450",
        pending_emails=("maria@hangy.com",),
    ),
    # Invisible: user@hangy.com has no interest in these tags.
    SeedEvent(
        title="Roda de samba na Cidade Baixa",
        location_name="Cidade Baixa",
        tag_name="Samba",
        creator_email="maria@hangy.com",
        starts_in_days=6,
    ),
    SeedEvent(
        title="Churrasco do bairro",
        location_name="Salão de festas do bairro",
        tag_name="Churrasco",
        creator_email="joao@hangy.com",
        starts_in_days=7,
    ),
    # Invisible: already happened, or never published.
    SeedEvent(
        title="Pelada de ontem",
        location_name="Parque Moinhos de Vento (Parcão)",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=-1,
    ),
    SeedEvent(
        title="Pelada em rascunho",
        location_name="Parque Moinhos de Vento (Parcão)",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=8,
        event_status=EventStatusEnum.DRAFT,
    ),
    SeedEvent(
        title="Pelada cancelada",
        location_name="Parque Moinhos de Vento (Parcão)",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=9,
        event_status=EventStatusEnum.CANCELLED,
    ),
)


def seed_users(db: Session) -> None:
    user_repository = SqlAlchemyUserRepository(db)
    personal_service = RegisterPersonalService(
        SqlAlchemyPersonRegistrationRepository(db)
    )
    business_service = RegisterBusinessService(
        SqlAlchemyBusinessRegistrationRepository(db)
    )

    for registration in SEED_USERS:
        if user_repository.get_by_email(registration.email) is not None:
            continue
        if isinstance(registration, PersonRegistration):
            personal_service.register(registration)
        else:
            business_service.register(registration)


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
        # Titles are not unique and can belong to user-created events.
        event_id = uuid5(
            NAMESPACE_URL, f"hangy:seed:event:{seed.creator_email}:{seed.title}"
        )
        event = db.get(EventModel, event_id)
        if event is None:
            event = EventModel(
                event_id=event_id,
                event_creator_id=creator.user_id,
                event_title=seed.title,
                location_name=seed.location_name,
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
            if event.location_name is None:
                event.location_name = seed.location_name

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
