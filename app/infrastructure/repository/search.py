import unicodedata
from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    exists,
    func,
    literal_column,
    or_,
    select,
    text,
)
from sqlalchemy.orm import Session, aliased

from app.domain.entities import (
    SearchBusinessItem,
    SearchEventCandidate,
    SearchUserItem,
    Tag,
)
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserTypeEnum,
)
from app.infrastructure.repository.block import block_exists_between
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    EventModel,
    EventParticipantModel,
    PersonProfileModel,
    TagModel,
    UserModel,
    event_tag,
)

ACCENTED_LOWER = "áàãâäéèêëíìîïóòõôöúùûüçñ"
UNACCENTED_LOWER = "aaaaaeeeeiiiiooooouuuucn"
ACCENTED_ALL = ACCENTED_LOWER + ACCENTED_LOWER.upper()
UNACCENTED_ALL = UNACCENTED_LOWER + UNACCENTED_LOWER.upper()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _unaccent_str(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(char for char in nfkd if not unicodedata.combining(char))


def _unaccent_column_sqlite(col: ColumnElement[str | None]) -> ColumnElement[str]:
    expr: ColumnElement[str] = col  # type: ignore[assignment]
    for src, dst in zip(ACCENTED_ALL, UNACCENTED_ALL, strict=True):
        expr = func.replace(expr, src, dst)
    return expr


def viewer_confirmed_in_event(viewer_id: UUID) -> ColumnElement[bool]:
    """SQL predicate for whether `viewer_id` is CONFIRMED in `EventModel`."""
    return (
        exists()
        .where(
            EventParticipantModel.event_id == EventModel.event_id,
            EventParticipantModel.user_id == viewer_id,
            EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
        )
        .correlate(EventModel)
    )


def visible_events_filter(
    viewer_id: UUID,
    reference_time: datetime | None = None,
) -> tuple[ColumnElement[bool], ...]:
    """Single SQL visibility predicate shared by search, feed, and nearby queries.

    Enforces:
    - Active, PUBLISHED, future events (`deleted_at IS NULL`, `starts_at > now`)
    - Bilateral block exclusion between event creator and viewer
    - Privacy rules: PUBLIC and PRIVATE are discoverable; INVITE_ONLY is visible
      only when the viewer is the organizer or a CONFIRMED participant.
    """
    effective_time = reference_time if reference_time is not None else datetime.now(UTC)
    return (
        EventModel.deleted_at.is_(None),
        EventModel.event_status == EventStatusEnum.PUBLISHED,
        EventModel.starts_at > effective_time,
        ~block_exists_between(EventModel.event_creator_id, viewer_id),
        or_(
            EventModel.event_privacy.in_(
                (EventPrivacyEnum.PUBLIC, EventPrivacyEnum.PRIVATE)
            ),
            and_(
                EventModel.event_privacy == EventPrivacyEnum.INVITE_ONLY,
                or_(
                    EventModel.event_creator_id == viewer_id,
                    viewer_confirmed_in_event(viewer_id),
                ),
            ),
        ),
    )


def build_visible_events_query(
    user_id: UUID,
    reference_time: datetime | None = None,
) -> Select[tuple[EventModel]]:
    """Return a base `Select(EventModel)` filtered by `visible_events_filter`."""
    return select(EventModel).where(*visible_events_filter(user_id, reference_time))


visible_events_query = build_visible_events_query


class SqlAlchemySearchRepository:
    """Persistence queries for `/search`.

    Profile display names (`user.name`) live on the `user` table for both
    `PERSONAL` and `BUSINESS` accounts, while profile-specific details (`city`,
    `state` vs `address`, coordinates) live on `person_profile` and
    `business_profile`. We run two targeted queries (one for `BUSINESS`, one for
    `PERSONAL`) rather than a `UNION` because each block has its own independent
    `total` count, `has_more` flag, and profile join columns.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _text_match_condition(
        self,
        model: type[EventModel] | type[UserModel],
        column: ColumnElement[str | None],
        query: str,
    ) -> ColumnElement[bool]:
        escaped = _escape_like(_unaccent_str(query).lower())
        pattern = f"%{escaped}%"
        dialect = self.db.get_bind().dialect.name
        if dialect == "postgresql":
            normalized_col = func.translate(
                func.lower(column),
                ACCENTED_LOWER,
                UNACCENTED_LOWER,
            )
            return or_(
                column.ilike(f"%{_escape_like(query)}%", escape="\\"),
                normalized_col.like(pattern, escape="\\"),
            )

        table_name = model.__tablename__
        rowid_col = literal_column(f'"{table_name}".rowid')
        matching_rowids = (
            select(rowid_col)
            .select_from(model)
            .where(
                column.is_not(None),
                _unaccent_column_sqlite(column).ilike(pattern, escape="\\"),
            )
        )
        return rowid_col.in_(matching_rowids)

    def list_tags_by_ids(self, tag_ids: Collection[UUID]) -> list[Tag]:
        if not tag_ids:
            return []
        models = self.db.scalars(
            select(TagModel).where(TagModel.tag_id.in_(tag_ids))
        ).all()
        return [self._to_tag_entity(model) for model in models]

    def list_child_tags(self, parent_ids: Collection[UUID]) -> list[Tag]:
        if not parent_ids:
            return []
        models = self.db.scalars(
            select(TagModel).where(TagModel.tag_parent_id.in_(parent_ids))
        ).all()
        return [self._to_tag_entity(model) for model in models]

    def _events_search_conditions(
        self,
        viewer_id: UUID,
        *,
        query: str | None = None,
        tag_ids: Collection[UUID] = (),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        reference_time: datetime | None = None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = list(
            visible_events_filter(viewer_id, reference_time)
        )
        if query is not None:
            conditions.append(
                self._text_match_condition(EventModel, EventModel.event_title, query)
            )
        if tag_ids:
            tagged_events = select(event_tag.c.event_id).where(
                event_tag.c.tag_id.in_(tag_ids)
            )
            conditions.append(EventModel.event_id.in_(tagged_events))
        if date_from is not None:
            conditions.append(EventModel.starts_at >= date_from)
        if date_to is not None:
            conditions.append(EventModel.starts_at <= date_to)
        return conditions

    def build_events_search_statement(
        self,
        viewer_id: UUID,
        *,
        query: str | None = None,
        tag_ids: Collection[UUID] = (),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        reference_time: datetime | None = None,
    ) -> Select[tuple[EventModel]]:
        conditions = self._events_search_conditions(
            viewer_id,
            query=query,
            tag_ids=tag_ids,
            date_from=date_from,
            date_to=date_to,
            reference_time=reference_time,
        )
        return (
            select(EventModel)
            .where(*conditions)
            .order_by(EventModel.starts_at.asc(), EventModel.event_id.asc())
        )

    def explain_event_search_query(
        self,
        viewer_id: UUID,
        query: str,
    ) -> list[str]:
        stmt = self.build_events_search_statement(viewer_id, query=query).limit(5)
        bind = self.db.get_bind()
        compiled = str(stmt.compile(bind, compile_kwargs={"literal_binds": True}))
        prefix = (
            "EXPLAIN " if bind.dialect.name == "postgresql" else "EXPLAIN QUERY PLAN "
        )
        rows = self.db.execute(text(prefix + compiled)).fetchall()
        return [" ".join(str(col) for col in row) for row in rows]

    def search_events(
        self,
        viewer_id: UUID,
        *,
        query: str | None,
        tag_ids: Collection[UUID],
        date_from: datetime | None,
        date_to: datetime | None,
        reference_time: datetime,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[SearchEventCandidate], int]:
        conditions = self._events_search_conditions(
            viewer_id,
            query=query,
            tag_ids=tag_ids,
            date_from=date_from,
            date_to=date_to,
            reference_time=reference_time,
        )
        total = (
            self.db.scalar(
                select(func.count()).select_from(EventModel).where(*conditions)
            )
            or 0
        )
        if total == 0 or limit <= 0:
            return [], total

        participants_count = (
            select(func.count(EventParticipantModel.participant_id))
            .where(
                EventParticipantModel.event_id == EventModel.event_id,
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
            )
            .correlate(EventModel)
            .scalar_subquery()
        )
        viewer_participation = aliased(EventParticipantModel)

        rows = self.db.execute(
            select(
                EventModel,
                participants_count,
                viewer_participation.status,
            )
            .outerjoin(
                viewer_participation,
                and_(
                    viewer_participation.event_id == EventModel.event_id,
                    viewer_participation.user_id == viewer_id,
                ),
            )
            .where(*conditions)
            .order_by(EventModel.starts_at.asc(), EventModel.event_id.asc())
            .offset(offset)
            .limit(limit)
        ).all()

        return (
            [
                self._to_event_candidate(model, count or 0, participation_status)
                for model, count, participation_status in rows
            ],
            total,
        )

    def search_businesses(
        self,
        viewer_id: UUID,
        *,
        query: str,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[SearchBusinessItem], int]:
        conditions = (
            UserModel.deleted_at.is_(None),
            UserModel.user_type == UserTypeEnum.BUSINESS,
            ~block_exists_between(UserModel.user_id, viewer_id),
            self._text_match_condition(UserModel, UserModel.name, query),
        )
        total = (
            self.db.scalar(
                select(func.count()).select_from(UserModel).where(*conditions)
            )
            or 0
        )
        if total == 0 or limit <= 0:
            return [], total

        rows = self.db.execute(
            select(UserModel, BusinessProfileModel.address)
            .outerjoin(
                BusinessProfileModel,
                BusinessProfileModel.user_id == UserModel.user_id,
            )
            .where(*conditions)
            .order_by(UserModel.name.asc(), UserModel.user_id.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return (
            [self._to_business_entity(user, address) for user, address in rows],
            total,
        )

    def search_users(
        self,
        viewer_id: UUID,
        *,
        query: str,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[SearchUserItem], int]:
        conditions = (
            UserModel.deleted_at.is_(None),
            UserModel.user_type == UserTypeEnum.PERSONAL,
            ~block_exists_between(UserModel.user_id, viewer_id),
            self._text_match_condition(UserModel, UserModel.name, query),
        )
        total = (
            self.db.scalar(
                select(func.count()).select_from(UserModel).where(*conditions)
            )
            or 0
        )
        if total == 0 or limit <= 0:
            return [], total

        rows = self.db.execute(
            select(UserModel, PersonProfileModel.city, PersonProfileModel.state)
            .outerjoin(
                PersonProfileModel,
                PersonProfileModel.user_id == UserModel.user_id,
            )
            .where(*conditions)
            .order_by(UserModel.name.asc(), UserModel.user_id.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return (
            [
                self._to_user_entity(user, city=city, state=state)
                for user, city, state in rows
            ],
            total,
        )

    @staticmethod
    def _to_event_candidate(
        model: EventModel,
        participants_count: int,
        viewer_participation_status: EventParticipantStatusEnum | None,
    ) -> SearchEventCandidate:
        return SearchEventCandidate(
            event=SqlAlchemyEventRepository.to_entity(model),
            participants_count=participants_count,
            viewer_participation_status=viewer_participation_status,
        )

    @staticmethod
    def _to_business_entity(user: UserModel, address: str | None) -> SearchBusinessItem:
        return SearchBusinessItem(
            user_id=user.user_id,
            business_name=user.name,
            name=user.name,
            description=user.description,
            address=address,
            photo_url=user.profile_photo_url,
        )

    @staticmethod
    def _to_user_entity(
        user: UserModel,
        *,
        city: str | None,
        state: str | None,
    ) -> SearchUserItem:
        return SearchUserItem(
            user_id=user.user_id,
            name=user.name,
            description=user.description,
            city=city,
            state=state,
            photo_url=user.profile_photo_url,
        )

    @staticmethod
    def _to_tag_entity(model: TagModel) -> Tag:
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_parent_id=model.tag_parent_id,
        )


__all__ = [
    "SqlAlchemySearchRepository",
    "build_visible_events_query",
    "viewer_confirmed_in_event",
    "visible_events_filter",
    "visible_events_query",
]
