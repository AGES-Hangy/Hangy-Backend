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
    NotificationTypeEnum,
    UserConnectionStatusEnum,
)
from app.domain.services import RegisterBusinessService, RegisterPersonalService
from app.infrastructure.repository.business_profile import (
    SqlAlchemyBusinessRegistrationRepository,
)
from app.infrastructure.repository.models import (
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    NotificationModel,
    TagModel,
    UserConnectionModel,
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
# the account to check the empty feed with. For GET /users/me/tags,
# pedro@hangy.com has one tag in every macro, listed out of order on purpose so
# the response shows the macro-then-name ordering, and ana@hangy.com is a
# PERSONAL user without interests, which returns `{"tags": []}`.
SEED_INTERESTS: dict[str, tuple[str, ...]] = {
    "user@hangy.com": ("Futebol", "Corrida", "Rock"),
    "maria@hangy.com": ("Samba",),
    "pedro@hangy.com": ("Teatro", "Sertanejo", "Confeitaria", "Futebol", "Churrasco"),
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


SEED_EVENTS = (
    # Visible in the feed of user@hangy.com, under "Esportes". user@hangy.com is
    # a confirmed participant, which is what the "starting soon" and "event
    # updated" notifications are about.
    SeedEvent(
        title="Pelada no Parcão",
        location_name="Parque Moinhos de Vento (Parcão)",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=1,
        cover_photo_url="https://picsum.photos/seed/pelada/800/450",
        confirmed_emails=("maria@hangy.com", "joao@hangy.com", "user@hangy.com"),
    ),
    # user@hangy.com's own event, kept PRIVATE on purpose: it's what makes
    # ManageEvent worth opening as user@hangy.com — a confirmed participant,
    # a pending request to approve, one who cancelled, and the privacy
    # badge/masking to check.
    SeedEvent(
        title="Corrida da Redenção",
        location_name="Parque Farroupilha (Redenção)",
        tag_name="Corrida",
        creator_email="user@hangy.com",
        starts_in_days=4,
        privacy=EventPrivacyEnum.PRIVATE,
        confirmed_emails=("maria@hangy.com",),
        pending_emails=("joao@hangy.com",),
        cancelled_emails=("ana@hangy.com",),
    ),
    # Visible, but the feed hides event_date and location_name for PRIVATE events.
    # Maria approved user@hangy.com's request.
    SeedEvent(
        title="Aniversário da Maria",
        location_name="Casa da Maria",
        tag_name="Futebol",
        creator_email="maria@hangy.com",
        starts_in_days=2,
        privacy=EventPrivacyEnum.PRIVATE,
        confirmed_emails=("user@hangy.com",),
        pending_emails=("joao@hangy.com",),
    ),
    # admin@hangy.com's own event, PRIVATE and with no participant at all: the
    # empty ManageEvent state. Under "Esportes", so it also shows up (masked, as
    # any PRIVATE event) in user@hangy.com's feed, with zero participants.
    SeedEvent(
        title="Confraternização da equipe",
        location_name="Sede do Hangy",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=10,
        privacy=EventPrivacyEnum.PRIVATE,
    ),
    # Never visible: reachable only through its invite link.
    SeedEvent(
        title="Rachão fechado",
        location_name="Quadra do bairro",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=3,
        privacy=EventPrivacyEnum.INVITE_ONLY,
        invite_token="seed-invite-racha-fechado",
    ),
    # Visible, under "Música". The admin turned down user@hangy.com's request.
    SeedEvent(
        title="Show de rock no Opinião",
        location_name="Bar Opinião",
        tag_name="Rock",
        creator_email="admin@hangy.com",
        starts_in_days=5,
        cover_photo_url="https://picsum.photos/seed/rock/800/450",
        pending_emails=("maria@hangy.com",),
        rejected_emails=("user@hangy.com",),
    ),
    # Invisible: user@hangy.com has no interest in these tags.
    SeedEvent(
        title="Roda de samba na Cidade Baixa",
        location_name="Cidade Baixa",
        tag_name="Samba",
        creator_email="maria@hangy.com",
        starts_in_days=6,
    ),
    # João removed user@hangy.com, so they can't ask to join again.
    SeedEvent(
        title="Churrasco do bairro",
        location_name="Salão de festas do bairro",
        tag_name="Churrasco",
        creator_email="joao@hangy.com",
        starts_in_days=7,
        removed_emails=("user@hangy.com",),
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
        title="Pelada",
        location_name="Parque Moinhos de Vento (Parcão)",
        tag_name="Futebol",
        creator_email="admin@hangy.com",
        starts_in_days=9,
        event_status=EventStatusEnum.CANCELLED,
        confirmed_emails=("user@hangy.com",),
    ),
    # Already over and closed as FINISHED: out of the feed, but listed by
    # GET /users/{id}/events on both João's profile (creator) and Maria's
    # (confirmed participant).
    SeedEvent(
        title="Sarau de teatro",
        location_name="Teatro de Arena",
        tag_name="Teatro",
        creator_email="joao@hangy.com",
        starts_in_days=-5,
        event_status=EventStatusEnum.FINISHED,
        cover_photo_url="https://picsum.photos/seed/sarau/800/450",
        confirmed_emails=("maria@hangy.com",),
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
    # Titles are not unique and can belong to user-created events.
    return uuid5(NAMESPACE_URL, f"hangy:seed:event:{creator_email}:{title}")


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
        event=("user@hangy.com", "Corrida da Redenção"),
        participant_email="maria@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "starting-soon",
        NotificationTypeEnum.EVENT_STARTING_SOON,
        age=timedelta(minutes=45),
        read=True,
        event=("admin@hangy.com", "Pelada no Parcão"),
        participant_email="user@hangy.com",
    ),
    SeedNotification(
        "user@hangy.com",
        "event-updated",
        NotificationTypeEnum.EVENT_UPDATED,
        age=timedelta(hours=1),
        event=("admin@hangy.com", "Pelada no Parcão"),
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
        event=("admin@hangy.com", "Show de rock no Opinião"),
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
        event=("admin@hangy.com", "Pelada"),
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
        event=("admin@hangy.com", "Pelada no Parcão"),
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
        event_id = seed_event_id(seed.creator_email, seed.title)
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


def _seed_connection(
    db: Session, seed: SeedNotification, users: dict[str, UserModel]
) -> UserConnectionModel | None:
    assert seed.connection is not None
    requester = users.get(seed.connection[0])
    receiver = users.get(seed.connection[1])
    if requester is None or receiver is None:
        return None

    connection_id = seed_connection_id(*seed.connection)
    connection = db.get(UserConnectionModel, connection_id)
    if connection is None:
        connection = UserConnectionModel(
            connection_id=connection_id,
            requester_id=requester.user_id,
            receiver_id=receiver.user_id,
            status=(
                UserConnectionStatusEnum.PENDING
                if seed.type == NotificationTypeEnum.CONNECTION_REQUEST
                else UserConnectionStatusEnum.CONFIRMED
            ),
        )
        db.add(connection)
        db.flush()
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


if __name__ == "__main__":
    main()
