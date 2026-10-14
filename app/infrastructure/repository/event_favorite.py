from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import EventFavorite
from app.infrastructure.repository.models import EventFavoriteModel


class SqlAlchemyEventFavoriteRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, favorite: EventFavorite) -> None:
        try:
            # The savepoint keeps a duplicate from poisoning the transaction:
            # two concurrent requests both pass any "already there?" check, so
            # the primary key is what makes a repeated favorite a no-op.
            with self.db.begin_nested():
                self.db.add(
                    EventFavoriteModel(
                        user_id=favorite.user_id, event_id=favorite.event_id
                    )
                )
        except IntegrityError:
            pass
        self.db.commit()

    def remove(self, favorite: EventFavorite) -> None:
        self.db.execute(
            delete(EventFavoriteModel).where(
                EventFavoriteModel.user_id == favorite.user_id,
                EventFavoriteModel.event_id == favorite.event_id,
            )
        )
        self.db.commit()
