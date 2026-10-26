import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Column, Table, delete, select, update
from sqlalchemy.orm import Session, aliased

from app.domain.entities import BusinessRegistration, PersonRegistration
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserConnectionStatusEnum,
    UserRoleEnum,
)
from app.domain.services import RegisterBusinessService, RegisterPersonalService
from app.infrastructure.repository.business_profile import (
    SqlAlchemyBusinessRegistrationRepository,
)
from app.infrastructure.repository.models import (
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventExperienceModel,
    EventFavoriteModel,
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    ExperienceImagesModel,
    NotificationModel,
    TagModel,
    UserBlockModel,
    UserConnectionModel,
    UserFollowModel,
    UserModel,
    event_tag,
    user_tag,
)
from app.infrastructure.repository.person_profile import (
    SqlAlchemyPersonRegistrationRepository,
)
from app.infrastructure.repository.session import SessionLocal
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.seed_catalog import ensure_tags

SEED_TERMS_VERSION = "2026-08-01"

# The moderation account, with role ADMIN like in production. It owns no events
# or followers: the demo business is BUSINESS_EMAIL.
ADMIN_EMAIL = "admin@hangy.com"
BUSINESS_EMAIL = "estabelecimento@hangy.com"

SEED_USERS: tuple[PersonRegistration | BusinessRegistration, ...] = (
    PersonRegistration(
        email="user@hangy.com",
        password="user-password",
        name="Usuário Hangy",
        cpf="52998224725",
        date_of_birth=date(1995, 4, 12),
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    # Same account and profile as the production seed (app/seed_production.py).
    BusinessRegistration(
        email=ADMIN_EMAIL,
        password="admin-password",
        business_name="Admin Hangy",
        cnpj="11222333000181",
        address="Av. Independência, 100 — Porto Alegre",
        latitude=-30.0331,
        longitude=-51.23,
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    BusinessRegistration(
        email=BUSINESS_EMAIL,
        password="estabelecimento-password",
        business_name="Bar do Parcão",
        cnpj="45678123000114",
        address="Rua Mostardeiro, 200 — Porto Alegre",
        latitude=-30.0277,
        longitude=-51.2045,
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    PersonRegistration(
        email="maria@hangy.com",
        password="maria-password",
        name="Maria Silva",
        cpf="11144477735",
        date_of_birth=date(1998, 8, 3),
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
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    # The three below exist to send connection requests to user@hangy.com.
    PersonRegistration(
        email="ana@hangy.com",
        password="ana-password",
        name="Ana Costa",
        cpf="12345678909",
        date_of_birth=date(1997, 6, 15),
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    PersonRegistration(
        email="pedro@hangy.com",
        password="pedro-password",
        name="Pedro Lima",
        cpf="39053344705",
        date_of_birth=date(1993, 11, 2),
        state="RS",
        city="Canoas",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    PersonRegistration(
        email="carla@hangy.com",
        password="carla-password",
        name="Carla Dias",
        cpf="16899535009",
        date_of_birth=date(2001, 3, 27),
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    # These two are the ones that accepted a request sent by user@hangy.com.
    PersonRegistration(
        email="lucas@hangy.com",
        password="lucas-password",
        name="Lucas Rocha",
        cpf="93541134780",
        date_of_birth=date(1996, 9, 8),
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    PersonRegistration(
        email="bia@hangy.com",
        password="bia-password",
        name="Bia Martins",
        cpf="80853372071",
        date_of_birth=date(1999, 12, 19),
        state="RS",
        city="Gravataí",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
    # Blocked by user@hangy.com: fills GET /users/me/blocked and is the one to
    # unblock with DELETE /users/{user_id}/block.
    PersonRegistration(
        email="rafael@hangy.com",
        password="rafael-password",
        name="Rafael Nunes",
        cpf="71428793860",
        date_of_birth=date(1994, 2, 11),
        state="RS",
        city="Porto Alegre",
        accepted_terms_version=SEED_TERMS_VERSION,
    ),
)

# Macro tag (no parent) mapped to the micro tags that hang below it: the same
# catalog production uses, so the demo shows the tags the app really offers.
# The feed groups by the macro tag, so every micro tag must roll up to one.
SEED_TAGS: dict[str, list[str]] = json.loads(
    Path(__file__).with_name("production_tags.json").read_text(encoding="utf-8")
)

# Micro tags are referenced as (macro, micro): names such as "Corrida" and
# "Indie" exist under more than one macro.
TagKey = tuple[str, str]

# Tags of the earlier demo catalog and their production replacement. A database
# seeded before keeps the users and events that used them, moved to the new tag.
LEGACY_SEED_TAGS: dict[TagKey, TagKey] = {
    ("Música", "Rock"): ("Vida Social", "Rock"),
    ("Música", "Samba"): ("Vida Social", "Samba"),
    ("Música", "Sertanejo"): ("Vida Social", "Sertanejo"),
    ("Gastronomia", "Culinária Italiana"): ("Gastronomia", "Italiana"),
    ("Gastronomia", "Confeitaria"): ("Gastronomia", "Doces"),
    ("Arte e Cultura", "Teatro"): ("Arte & Cultura", "Teatro"),
    ("Arte e Cultura", "Cinema"): ("Arte & Cultura", "Cinema"),
}
# Dropped once no micro tag hangs below them.
LEGACY_SEED_MACROS = ("Música", "Arte e Cultura")

# estabelecimento@hangy.com is a BUSINESS user and stays without interests,
# which makes it the account to check the empty feed with. For GET /users/me/tags,
# pedro@hangy.com has tags in four macros, listed out of order on purpose so
# the response shows the macro-then-name ordering, and ana@hangy.com is a
# PERSONAL user without interests, which returns `{"tags": []}`.
SEED_INTERESTS: dict[str, tuple[TagKey, ...]] = {
    "user@hangy.com": (
        ("Esportes", "Futebol"),
        ("Esportes", "Corrida"),
        ("Vida Social", "Rock"),
    ),
    "maria@hangy.com": (("Vida Social", "Samba"),),
    "pedro@hangy.com": (
        ("Arte & Cultura", "Teatro"),
        ("Vida Social", "Sertanejo"),
        ("Gastronomia", "Doces"),
        ("Esportes", "Futebol"),
        ("Gastronomia", "Churrasco"),
    ),
}

EVENT_DURATION = timedelta(hours=3)
# Porto Alegre, roughly around Parque da Redenção.
EVENT_LATITUDE = -30.0368
EVENT_LONGITUDE = -51.2090


@dataclass(frozen=True, slots=True)
class SeedEvent:
    title: str
    location_name: str
    # What a PRIVATE event shows to whoever was not approved yet.
    location_neighborhood: str
    tag: TagKey
    creator_email: str
    # Days from "now", so a restart always leaves the feed with future events.
    starts_in_days: int
    # Added to starts_in_days, for an event that starts within the hour.
    starts_in_minutes: int = 0
    location_city: str = "Porto Alegre"
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED
    cover_photo_url: str | None = None
    invite_token: str | None = None
    # The participants below back the seeded notifications: each status is the
    # one the notification about that person implies.
    confirmed_emails: tuple[str, ...] = field(default_factory=tuple)
    pending_emails: tuple[str, ...] = field(default_factory=tuple)
    rejected_emails: tuple[str, ...] = field(default_factory=tuple)
    # Gave up on going: no longer on the participant list.
    cancelled_emails: tuple[str, ...] = field(default_factory=tuple)
    # Taken out by the creator, who must not be asked to let them back in.
    removed_emails: tuple[str, ...] = field(default_factory=tuple)
    # Personal accounts that marked the event as an interest: what fills the
    # `interests` tab of GET /users/{user_id}/events.
    favorited_emails: tuple[str, ...] = field(default_factory=tuple)


SEED_EVENTS = (
    # Visible in the feed of user@hangy.com, under "Esportes". user@hangy.com is
    # a confirmed participant, which is what the "event updated" notification
    # is about.
    SeedEvent(
        title="Pelada no Parcão",
        location_name="Parque Moinhos de Vento (Parcão)",
        location_neighborhood="Moinhos de Vento",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=1,
        cover_photo_url="https://picsum.photos/seed/pelada/800/450",
        confirmed_emails=("maria@hangy.com", "joao@hangy.com", "user@hangy.com"),
    ),
    # Starts within the window of the EVENT_STARTING_SOON job (60 minutes), which
    # is what user@hangy.com's "starting soon" notification is about.
    SeedEvent(
        title="Fut society no fim de tarde",
        location_name="Arena Society Menino Deus",
        location_neighborhood="Menino Deus",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=0,
        starts_in_minutes=45,
        confirmed_emails=("joao@hangy.com", "user@hangy.com"),
    ),
    # PUBLIC and without user@hangy.com: joining confirms right away
    # (POST /events/{event_id}/participation).
    SeedEvent(
        title="Corrida noturna na Orla",
        location_name="Orla do Guaíba",
        location_neighborhood="Centro Histórico",
        tag=("Esportes", "Corrida"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=6,
        cover_photo_url="https://picsum.photos/seed/orla/800/450",
        confirmed_emails=("maria@hangy.com", "ana@hangy.com"),
    ),
    # user@hangy.com's own PUBLIC event: Maria joined it directly, which is the
    # only way the app sends EVENT_PARTICIPANT_JOINED.
    SeedEvent(
        title="Treino de corrida no Gasômetro",
        location_name="Usina do Gasômetro",
        location_neighborhood="Centro Histórico",
        tag=("Esportes", "Corrida"),
        creator_email="user@hangy.com",
        starts_in_days=12,
        confirmed_emails=("maria@hangy.com", "lucas@hangy.com"),
    ),
    # user@hangy.com's own event, kept PRIVATE on purpose: it's what makes
    # ManageEvent worth opening as user@hangy.com — a confirmed participant,
    # a pending request to approve, one who cancelled, and the privacy
    # badge/masking to check.
    SeedEvent(
        title="Corrida da Redenção",
        location_name="Parque Farroupilha (Redenção)",
        location_neighborhood="Farroupilha",
        tag=("Esportes", "Corrida"),
        creator_email="user@hangy.com",
        starts_in_days=4,
        privacy=EventPrivacyEnum.PRIVATE,
        confirmed_emails=("maria@hangy.com",),
        pending_emails=("joao@hangy.com",),
        cancelled_emails=("ana@hangy.com",),
    ),
    # Visible, but the feed hides event_date and shows only the neighborhood of
    # PRIVATE events to whoever was not approved.
    # Maria approved user@hangy.com's request.
    SeedEvent(
        title="Aniversário da Maria",
        location_name="Casa da Maria",
        location_neighborhood="Bom Fim",
        tag=("Esportes", "Futebol"),
        creator_email="maria@hangy.com",
        starts_in_days=2,
        privacy=EventPrivacyEnum.PRIVATE,
        confirmed_emails=("user@hangy.com",),
        pending_emails=("joao@hangy.com",),
    ),
    # estabelecimento@hangy.com's own event, PRIVATE and with no participant at
    # all: the empty ManageEvent state. Under "Esportes", so it also shows up
    # (masked, as any PRIVATE event) in user@hangy.com's feed, with zero
    # participants.
    SeedEvent(
        title="Confraternização da equipe",
        location_name="Sede do Hangy",
        location_neighborhood="Partenon",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=10,
        privacy=EventPrivacyEnum.PRIVATE,
    ),
    # Never visible: reachable only through its invite link.
    SeedEvent(
        title="Rachão fechado",
        location_name="Quadra do bairro",
        location_neighborhood="Santana",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=3,
        privacy=EventPrivacyEnum.INVITE_ONLY,
        invite_token="seed-invite-racha-fechado",
    ),
    # user@hangy.com's request is still waiting for João: the one to withdraw
    # with DELETE /events/{event_id}/participation.
    SeedEvent(
        title="Jam de rock no apê do João",
        location_name="Apartamento do João",
        location_neighborhood="Santana",
        tag=("Vida Social", "Rock"),
        creator_email="joao@hangy.com",
        starts_in_days=9,
        privacy=EventPrivacyEnum.PRIVATE,
        confirmed_emails=("maria@hangy.com",),
        pending_emails=("user@hangy.com",),
    ),
    # Visible, under "Vida Social". The business turned down user@hangy.com's request.
    SeedEvent(
        title="Show de rock no Opinião",
        location_name="Bar Opinião",
        location_neighborhood="Cidade Baixa",
        tag=("Vida Social", "Rock"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=5,
        cover_photo_url="https://picsum.photos/seed/rock/800/450",
        pending_emails=("maria@hangy.com",),
        rejected_emails=("user@hangy.com",),
        favorited_emails=("user@hangy.com",),
    ),
    # Invisible: user@hangy.com has no interest in these tags.
    SeedEvent(
        title="Roda de samba na Cidade Baixa",
        location_name="Cidade Baixa",
        location_neighborhood="Cidade Baixa",
        tag=("Vida Social", "Samba"),
        creator_email="maria@hangy.com",
        starts_in_days=6,
        favorited_emails=("user@hangy.com", "joao@hangy.com"),
    ),
    # João removed user@hangy.com, so they can't ask to join again.
    SeedEvent(
        title="Churrasco do bairro",
        location_name="Salão de festas do bairro",
        location_neighborhood="Santana",
        tag=("Gastronomia", "Churrasco"),
        creator_email="joao@hangy.com",
        starts_in_days=7,
        removed_emails=("user@hangy.com",),
    ),
    # Invisible: already happened, or never published.
    SeedEvent(
        title="Pelada de ontem",
        location_name="Parque Moinhos de Vento (Parcão)",
        location_neighborhood="Moinhos de Vento",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=-1,
    ),
    # A finished event with a confirmed demo participant for testing
    # POST /events/{event_id}/experiences.
    SeedEvent(
        title="Evento encerrado para teste de experiência",
        location_name="Parque Moinhos de Vento (Parcão)",
        location_neighborhood="Moinhos de Vento",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=-2,
        confirmed_emails=("user@hangy.com",),
    ),
    SeedEvent(
        title="Pelada em rascunho",
        location_name="Parque Moinhos de Vento (Parcão)",
        location_neighborhood="Moinhos de Vento",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=8,
        event_status=EventStatusEnum.DRAFT,
    ),
    SeedEvent(
        title="Pelada",
        location_name="Parque Moinhos de Vento (Parcão)",
        location_neighborhood="Moinhos de Vento",
        tag=("Esportes", "Futebol"),
        creator_email=BUSINESS_EMAIL,
        starts_in_days=9,
        event_status=EventStatusEnum.CANCELLED,
        confirmed_emails=("user@hangy.com",),
    ),
    # Already over and closed as FINISHED: out of the feed, but on the
    # `history` tab of GET /users/{id}/events for João (creator) and for the
    # confirmed participants, user@hangy.com included.
    SeedEvent(
        title="Sarau de teatro",
        location_name="Teatro de Arena",
        location_neighborhood="Centro Histórico",
        tag=("Arte & Cultura", "Teatro"),
        creator_email="joao@hangy.com",
        starts_in_days=-5,
        event_status=EventStatusEnum.FINISHED,
        cover_photo_url="https://picsum.photos/seed/sarau/800/450",
        confirmed_emails=("maria@hangy.com", "user@hangy.com"),
    ),
)


@dataclass(frozen=True, slots=True)
class SeedNotification:
    user_email: str
    # Only tells notifications of the same user and type apart, so each one
    # keeps a stable id across restarts.
    key: str
    type: NotificationTypeEnum
    # How long before "now" it arrived. created_at is recomputed on every run,
    # so the list always looks recent and keeps the same order.
    age: timedelta
    read: bool = False
    # Put back as unread on every run, so a demo that marks it as read can be
    # repeated after a restart.
    reset_on_seed: bool = False
    # The rows that fill the payload; which ones apply depends on the type.
    # (requester_email, receiver_email) of a CONNECTION_* notification.
    connection: tuple[str, str] | None = None
    # (creator_email, title) of the seeded event the notification is about.
    event: tuple[str, str] | None = None
    # Whose participation in `event` the notification refers to; unset for
    # notifications that point at the event alone.
    participant_email: str | None = None


def seed_notification_id(user_email: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"hangy:seed:notification:{user_email}:{key}")


def seed_event_id(creator_email: str, title: str) -> UUID:
    # Titles are not unique and can belong to user-created events. The business
    # events were first seeded under admin@hangy.com and keep that id, so a
    # database seeded before is updated in place instead of duplicated.
    id_owner = ADMIN_EMAIL if creator_email == BUSINESS_EMAIL else creator_email
    return uuid5(NAMESPACE_URL, f"hangy:seed:event:{id_owner}:{title}")


def seed_connection_id(requester_email: str, receiver_email: str) -> UUID:
    return uuid5(
        NAMESPACE_URL, f"hangy:seed:connection:{requester_email}:{receiver_email}"
    )


# user@hangy.com has every one of the 11 types, with five connection requests
# and two acceptances: 10 unread and 6 read, so the bell badge shows 10. Each
# one matches what the database says: a pending request has a PENDING
# participant, a removed one a REMOVED participant, and so on.
# maria@hangy.com's unread one must never leak
# into that count, and is the one to try PATCH /notifications/{id}/read with as
# another user (403). joao@hangy.com's single notification is the one to mark as
# read (204).
SEED_NOTIFICATIONS = (
    SeedNotification(
        "user@hangy.com",
        "participation-request",
        NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
        age=timedelta(minutes=2),
        event=("user@hangy.com", "Corrida da Redenção"),
        participant_email="joao@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "connection-request",
        NotificationTypeEnum.CONNECTION_REQUEST,
        age=timedelta(minutes=10),
        connection=("maria@hangy.com", "user@hangy.com"),
    ),
    SeedNotification(
        "user@hangy.com",
        "connection-request-joao",
        NotificationTypeEnum.CONNECTION_REQUEST,
        age=timedelta(minutes=18),
        connection=("joao@hangy.com", "user@hangy.com"),
    ),
    SeedNotification(
        "user@hangy.com",
        "connection-request-ana",
        NotificationTypeEnum.CONNECTION_REQUEST,
        age=timedelta(minutes=6),
        connection=("ana@hangy.com", "user@hangy.com"),
    ),
    SeedNotification(
        "user@hangy.com",
        "connection-request-pedro",
        NotificationTypeEnum.CONNECTION_REQUEST,
        age=timedelta(minutes=50),
        connection=("pedro@hangy.com", "user@hangy.com"),
    ),
    SeedNotification(
        "user@hangy.com",
        "connection-request-carla",
        NotificationTypeEnum.CONNECTION_REQUEST,
        age=timedelta(hours=7),
        read=True,
        connection=("carla@hangy.com", "user@hangy.com"),
    ),
    SeedNotification(
        "user@hangy.com",
        "connection-accepted-bia",
        NotificationTypeEnum.CONNECTION_ACCEPTED,
        age=timedelta(hours=9),
        read=True,
        connection=("user@hangy.com", "bia@hangy.com"),
    ),
    SeedNotification(
        "user@hangy.com",
        "participant-joined",
        NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
        age=timedelta(minutes=25),
        event=("user@hangy.com", "Treino de corrida no Gasômetro"),
        participant_email="maria@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "starting-soon",
        NotificationTypeEnum.EVENT_STARTING_SOON,
        age=timedelta(minutes=10),
        read=True,
        event=(BUSINESS_EMAIL, "Fut society no fim de tarde"),
        participant_email="user@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "event-updated",
        NotificationTypeEnum.EVENT_UPDATED,
        age=timedelta(hours=1),
        event=(BUSINESS_EMAIL, "Pelada no Parcão"),
    ),
    SeedNotification(
        "user@hangy.com",
        "connection-accepted",
        NotificationTypeEnum.CONNECTION_ACCEPTED,
        age=timedelta(hours=3),
        connection=("user@hangy.com", "lucas@hangy.com"),
    ),
    SeedNotification(
        "user@hangy.com",
        "request-approved",
        NotificationTypeEnum.EVENT_REQUEST_APPROVED,
        age=timedelta(hours=5),
        read=True,
        event=("maria@hangy.com", "Aniversário da Maria"),
        participant_email="user@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "request-rejected",
        NotificationTypeEnum.EVENT_REQUEST_REJECTED,
        age=timedelta(days=1),
        event=(BUSINESS_EMAIL, "Show de rock no Opinião"),
        participant_email="user@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "participant-cancelled",
        NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED,
        age=timedelta(days=2),
        read=True,
        event=("user@hangy.com", "Corrida da Redenção"),
        participant_email="ana@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "participant-removed",
        NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED,
        age=timedelta(days=3),
        read=True,
        event=("joao@hangy.com", "Churrasco do bairro"),
        participant_email="user@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "event-cancelled",
        NotificationTypeEnum.EVENT_CANCELLED,
        age=timedelta(days=4),
        event=(BUSINESS_EMAIL, "Pelada"),
    ),
    SeedNotification(
        "maria@hangy.com",
        "connection-accepted",
        NotificationTypeEnum.CONNECTION_ACCEPTED,
        age=timedelta(hours=2),
        connection=("maria@hangy.com", "joao@hangy.com"),
    ),
    SeedNotification(
        "joao@hangy.com",
        "mark-as-read",
        NotificationTypeEnum.EVENT_REQUEST_APPROVED,
        age=timedelta(minutes=30),
        reset_on_seed=True,
        event=(BUSINESS_EMAIL, "Pelada no Parcão"),
        participant_email="joao@hangy.com",
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

    users = _users_by_email(db)
    admin = users.get(ADMIN_EMAIL)
    business = users.get(BUSINESS_EMAIL)
    if admin is not None and admin.deleted_at is None:
        # Put back on every run, like the participants: a demotion made while
        # testing can be undone with a restart.
        admin.role = UserRoleEnum.ADMIN
        if business is not None:
            _hand_over_business_data(db, admin, business)
    db.commit()


def _hand_over_business_data(
    db: Session, admin: UserModel, business: UserModel
) -> None:
    """Move what admin@hangy.com owned before it became ADMIN to the business.

    Databases seeded before have the demo events, their invite links and the
    followers under admin@hangy.com, plus whatever was created with that
    account while testing. Everything moves, with the same ids.
    """
    db.execute(
        update(EventModel)
        .where(EventModel.event_creator_id == admin.user_id)
        .values(event_creator_id=business.user_id)
    )
    db.execute(
        update(EventInviteLinkModel)
        .where(EventInviteLinkModel.created_by == admin.user_id)
        .values(created_by=business.user_id)
    )
    # A follower of both only loses the duplicate follow.
    db.execute(
        delete(UserFollowModel).where(
            UserFollowModel.followed_business_id == admin.user_id,
            UserFollowModel.follower_id.in_(
                select(UserFollowModel.follower_id).where(
                    UserFollowModel.followed_business_id == business.user_id
                )
            ),
        )
    )
    db.execute(
        update(UserFollowModel)
        .where(UserFollowModel.followed_business_id == admin.user_id)
        .values(followed_business_id=business.user_id)
    )


def seed_tags(db: Session) -> None:
    ensure_tags(db, SEED_TAGS)
    _retire_legacy_tags(db)
    db.commit()


def _retire_legacy_tags(db: Session) -> None:
    tags = _micro_tags(db)
    for legacy_key, replacement_key in LEGACY_SEED_TAGS.items():
        legacy = tags.get(legacy_key)
        if legacy is None:
            continue
        replacement = tags[replacement_key]
        _move_tag_links(db, user_tag, user_tag.c.user_id, legacy, replacement)
        _move_tag_links(db, event_tag, event_tag.c.event_id, legacy, replacement)
        db.execute(delete(TagModel).where(TagModel.tag_id == legacy.tag_id))

    for macro_name in LEGACY_SEED_MACROS:
        macro_id = db.scalar(
            select(TagModel.tag_id).where(
                TagModel.tag_name == macro_name,
                TagModel.tag_parent_id.is_(None),
            )
        )
        if macro_id is None:
            continue
        has_micros = db.scalar(
            select(TagModel.tag_id).where(TagModel.tag_parent_id == macro_id).limit(1)
        )
        if has_micros is None:
            db.execute(delete(TagModel).where(TagModel.tag_id == macro_id))
    db.expire_all()


def _move_tag_links(
    db: Session,
    table: Table,
    owner_column: Column[UUID],
    legacy: TagModel,
    replacement: TagModel,
) -> None:
    # Whoever already has the replacement only loses the duplicate link.
    db.execute(
        delete(table).where(
            table.c.tag_id == legacy.tag_id,
            owner_column.in_(
                select(owner_column).where(table.c.tag_id == replacement.tag_id)
            ),
        )
    )
    db.execute(
        update(table)
        .where(table.c.tag_id == legacy.tag_id)
        .values(tag_id=replacement.tag_id)
    )


def seed_user_interests(db: Session) -> None:
    users = _users_by_email(db)
    tags = _micro_tags(db)

    for email, tag_keys in SEED_INTERESTS.items():
        user = users.get(email)
        if user is None:
            continue
        for tag_key in tag_keys:
            tag = tags.get(tag_key)
            if tag is None or _has_interest(db, user.user_id, tag.tag_id):
                continue
            db.execute(
                user_tag.insert().values(user_id=user.user_id, tag_id=tag.tag_id)
            )
    db.commit()


def seed_events(db: Session) -> None:
    users = _users_by_email(db)
    tags = _micro_tags(db)
    now = datetime.now(UTC)

    for seed in SEED_EVENTS:
        creator = users.get(seed.creator_email)
        tag = tags.get(seed.tag)
        if creator is None or tag is None:
            continue

        starts_at = now + timedelta(
            days=seed.starts_in_days, minutes=seed.starts_in_minutes
        )
        event_id = seed_event_id(seed.creator_email, seed.title)
        event = db.get(EventModel, event_id)
        if event is None:
            event = EventModel(
                event_id=event_id,
                event_creator_id=creator.user_id,
                event_title=seed.title,
                location_name=seed.location_name,
                location_neighborhood=seed.location_neighborhood,
                location_city=seed.location_city,
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
            event.event_creator_id = creator.user_id
            # Slide the schedule forward so the feed keeps working after a
            # restart instead of slowly filling up with past events.
            event.starts_at = starts_at
            event.ends_at = starts_at + EVENT_DURATION
            if event.location_name is None:
                event.location_name = seed.location_name
            if event.location_neighborhood is None:
                event.location_neighborhood = seed.location_neighborhood
            if event.location_city is None:
                event.location_city = seed.location_city

        _seed_participants(db, event, seed, users)
        _seed_favorites(db, event, seed, users)
        _seed_invite_link(db, event, seed)
    db.commit()


def seed_notifications(db: Session) -> None:
    users = _users_by_email(db)
    now = datetime.now(UTC)

    for seed in SEED_NOTIFICATIONS:
        user = users.get(seed.user_email)
        if user is None:
            continue

        notification_id = seed_notification_id(seed.user_email, seed.key)
        created_at = now - seed.age
        notification = db.get(NotificationModel, notification_id)
        if notification is None:
            notification = NotificationModel(
                notification_id=notification_id,
                user_id=user.user_id,
                type=seed.type,
                read=seed.read,
                created_at=created_at,
            )
            db.add(notification)
            db.flush()
        else:
            notification.created_at = created_at
            if seed.reset_on_seed:
                notification.read = seed.read
            # Any other existing one keeps its read flag: the user may have
            # read it since.
        # Also runs for existing rows, which older seeds created without them.
        _seed_notification_detail(db, seed, notification_id, users)
    db.commit()


def _seed_notification_detail(
    db: Session,
    seed: SeedNotification,
    notification_id: UUID,
    users: dict[str, UserModel],
) -> None:
    # An existing detail follows the seed if it now points somewhere else.
    if seed.connection is not None:
        connection = _seed_connection(db, seed, users)
        if connection is None:
            return
        detail = db.get(ConnectionNotificationModel, notification_id)
        if detail is None:
            db.add(
                ConnectionNotificationModel(
                    notification_id=notification_id,
                    connection_id=connection.connection_id,
                )
            )
        else:
            detail.connection_id = connection.connection_id
        return

    if seed.event is None:
        return
    event_id = seed_event_id(*seed.event)

    if seed.participant_email is None:
        if db.get(EventModel, event_id) is None:
            return
        detail = db.get(EventCancelledNotificationModel, notification_id)
        if detail is None:
            db.add(
                EventCancelledNotificationModel(
                    notification_id=notification_id, event_id=event_id
                )
            )
        else:
            detail.event_id = event_id
        return

    participant = users.get(seed.participant_email)
    participant_id = (
        _participant_id(db, event_id, participant.user_id) if participant else None
    )
    if participant_id is None:
        return
    detail = db.get(EventParticipantNotificationModel, notification_id)
    if detail is None:
        db.add(
            EventParticipantNotificationModel(
                notification_id=notification_id, participant_id=participant_id
            )
        )
    else:
        detail.participant_id = participant_id


@dataclass(frozen=True, slots=True)
class SeedExperience:
    # Confirmed participant of the seeded event (creator_email, title).
    user_email: str
    event: tuple[str, str]
    description: str
    photo_urls: tuple[str, ...]


# The followers of estabelecimento@hangy.com (GET /businesses/me/followers).
# user@hangy.com is one, so their profile shows `is_following` and can be
# unfollowed.
SEED_FOLLOWS: dict[str, tuple[str, ...]] = {
    BUSINESS_EMAIL: ("user@hangy.com", "maria@hangy.com", "joao@hangy.com"),
}

# (blocker_email, blocked_email)
SEED_BLOCKS = (("user@hangy.com", "rafael@hangy.com"),)

# Fill GET /events/{event_id}/photos and GET /users/me/photos. Only on "Sarau de
# teatro": "Evento encerrado para teste de experiência" stays without one, so
# POST /events/{event_id}/experiences can still be tried there.
SEED_EXPERIENCES = (
    SeedExperience(
        user_email="user@hangy.com",
        event=("joao@hangy.com", "Sarau de teatro"),
        description="Noite incrível, as apresentações foram ótimas!",
        photo_urls=(
            "https://picsum.photos/seed/sarau-1/800/600",
            "https://picsum.photos/seed/sarau-2/800/600",
        ),
    ),
    SeedExperience(
        user_email="maria@hangy.com",
        event=("joao@hangy.com", "Sarau de teatro"),
        description="Adorei conhecer a galera do teatro.",
        photo_urls=("https://picsum.photos/seed/sarau-3/800/600",),
    ),
)


def seed_photo_id(user_email: str, photo_url: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"hangy:seed:photo:{user_email}:{photo_url}")


def seed_social(db: Session) -> None:
    users = _users_by_email(db)

    # Put back on every run, like the favorites: an unfollow or unblock made
    # while testing can be repeated after a restart.
    for business_email, follower_emails in SEED_FOLLOWS.items():
        business = users.get(business_email)
        if business is None:
            continue
        for follower_email in follower_emails:
            follower = users.get(follower_email)
            if follower is None:
                continue
            key = (follower.user_id, business.user_id)
            if db.get(UserFollowModel, key) is None:
                db.add(
                    UserFollowModel(
                        follower_id=follower.user_id,
                        followed_business_id=business.user_id,
                    )
                )

    for blocker_email, blocked_email in SEED_BLOCKS:
        blocker = users.get(blocker_email)
        blocked = users.get(blocked_email)
        if blocker is None or blocked is None:
            continue
        if db.get(UserBlockModel, (blocker.user_id, blocked.user_id)) is None:
            db.add(
                UserBlockModel(blocker_id=blocker.user_id, blocked_id=blocked.user_id)
            )
    db.commit()


def seed_experiences(db: Session) -> None:
    users = _users_by_email(db)

    for seed in SEED_EXPERIENCES:
        user = users.get(seed.user_email)
        participant_id = (
            _participant_id(db, seed_event_id(*seed.event), user.user_id)
            if user is not None
            else None
        )
        if participant_id is None:
            continue

        experience = db.scalar(
            select(EventExperienceModel).where(
                EventExperienceModel.event_participant_id == participant_id
            )
        )
        if experience is None:
            experience = EventExperienceModel(
                event_participant_id=participant_id, description=seed.description
            )
            db.add(experience)
            db.flush()
        # Brought back if deleted while testing, so the photo tabs never
        # start empty after a restart.
        experience.deleted_at = None

        for photo_url in seed.photo_urls:
            photo_id = seed_photo_id(seed.user_email, photo_url)
            photo = db.get(ExperienceImagesModel, photo_id)
            if photo is None:
                db.add(
                    ExperienceImagesModel(
                        photo_id=photo_id,
                        experience_id=experience.experience_id,
                        photo_url=photo_url,
                    )
                )
            else:
                photo.deleted_at = None
    db.commit()


def _seed_connection(
    db: Session, seed: SeedNotification, users: dict[str, UserModel]
) -> UserConnectionModel | None:
    assert seed.connection is not None
    requester = users.get(seed.connection[0])
    receiver = users.get(seed.connection[1])
    if requester is None or receiver is None:
        return None

    status = (
        UserConnectionStatusEnum.PENDING
        if seed.type == NotificationTypeEnum.CONNECTION_REQUEST
        else UserConnectionStatusEnum.CONFIRMED
    )
    connection_id = seed_connection_id(*seed.connection)
    connection = db.get(UserConnectionModel, connection_id)
    if connection is None:
        connection = UserConnectionModel(
            connection_id=connection_id,
            requester_id=requester.user_id,
            receiver_id=receiver.user_id,
            status=status,
        )
        db.add(connection)
        db.flush()
    else:
        # Put back on every run, like the participants: accepting a request
        # while testing must not leave a request notification with no pending
        # request behind it.
        connection.status = status
    return connection


def _seed_participants(
    db: Session,
    event: EventModel,
    seed: SeedEvent,
    users: dict[str, UserModel],
) -> None:
    participations = (
        (seed.confirmed_emails, EventParticipantStatusEnum.CONFIRMED),
        (seed.pending_emails, EventParticipantStatusEnum.PENDING),
        (seed.rejected_emails, EventParticipantStatusEnum.REJECTED),
        (seed.cancelled_emails, EventParticipantStatusEnum.CANCELLED),
        (seed.removed_emails, EventParticipantStatusEnum.REMOVED),
    )
    for emails, status in participations:
        for email in emails:
            user = users.get(email)
            if user is None:
                continue
            participant = db.scalar(
                select(EventParticipantModel).where(
                    EventParticipantModel.event_id == event.event_id,
                    EventParticipantModel.user_id == user.user_id,
                )
            )
            if participant is None:
                db.add(
                    EventParticipantModel(
                        event_id=event.event_id,
                        user_id=user.user_id,
                        status=status,
                    )
                )
            else:
                # Put back on every run: the notifications describe this state,
                # so approving or removing someone while testing must not leave
                # a "wants to join" notification with no pending request behind.
                participant.status = status


def _seed_favorites(
    db: Session,
    event: EventModel,
    seed: SeedEvent,
    users: dict[str, UserModel],
) -> None:
    for email in seed.favorited_emails:
        user = users.get(email)
        if user is None:
            continue
        # Put back on every run, like the participants: a demo that
        # unfavorites the event can be repeated after a restart.
        if db.get(EventFavoriteModel, (user.user_id, event.event_id)) is None:
            db.add(EventFavoriteModel(user_id=user.user_id, event_id=event.event_id))


def _seed_invite_link(db: Session, event: EventModel, seed: SeedEvent) -> None:
    if seed.invite_token is None:
        return

    invite_link = db.scalar(
        select(EventInviteLinkModel).where(
            EventInviteLinkModel.event_id == event.event_id,
            EventInviteLinkModel.token == seed.invite_token,
        )
    )
    if invite_link is None:
        db.add(
            EventInviteLinkModel(
                event_id=event.event_id,
                created_by=event.event_creator_id,
                token=seed.invite_token,
                expires_at=event.starts_at,
            )
        )
    else:
        # Keep the link valid after a local environment is restarted.
        invite_link.expires_at = event.starts_at


def _users_by_email(db: Session) -> dict[str, UserModel]:
    return {user.email: user for user in db.scalars(select(UserModel)).all()}


def _micro_tags(db: Session) -> dict[TagKey, TagModel]:
    macro = aliased(TagModel)
    rows = db.execute(
        select(macro.tag_name, TagModel).join(
            macro, TagModel.tag_parent_id == macro.tag_id
        )
    ).all()
    return {(macro_name, tag.tag_name): tag for macro_name, tag in rows}


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


def _participant_id(db: Session, event_id: UUID, user_id: UUID) -> UUID | None:
    return db.scalar(
        select(EventParticipantModel.participant_id).where(
            EventParticipantModel.event_id == event_id,
            EventParticipantModel.user_id == user_id,
        )
    )


def main() -> None:
    with SessionLocal() as db:
        seed_users(db)
        seed_tags(db)
        seed_user_interests(db)
        seed_events(db)
        seed_notifications(db)
        seed_social(db)
        seed_experiences(db)


if __name__ == "__main__":
    main()
