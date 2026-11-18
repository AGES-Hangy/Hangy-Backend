from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.entities import RefreshTokenRecord, User
from app.infrastructure.repository.models import RefreshTokenModel
from app.infrastructure.repository.user import SqlAlchemyUserRepository

__all__ = ["SqlAlchemyRefreshTokenRepository", "revoke_user_refresh_tokens"]


def revoke_user_refresh_tokens(
    db: Session, user_id: UUID, revoked_at: datetime
) -> None:
    """Revoke every live refresh token of a user, inside the caller's transaction."""
    db.execute(
        update(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == user_id,
            RefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
    )


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        family_id: UUID,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.db.add(
            RefreshTokenModel(
                token_id=token_id,
                user_id=user_id,
                family_id=family_id,
                token_hash=token_hash,
                created_at=created_at,
                expires_at=expires_at,
            )
        )

    def get_by_hash_for_update(self, token_hash: str) -> RefreshTokenRecord | None:
        # The row lock makes two concurrent refreshes with the same token
        # serialize: the second sees it revoked and ends the family.
        model = self.db.scalar(
            select(RefreshTokenModel)
            .where(RefreshTokenModel.token_hash == token_hash)
            .with_for_update()
        )
        if model is None:
            return None
        return RefreshTokenRecord(
            token_id=model.token_id,
            user_id=model.user_id,
            family_id=model.family_id,
            created_at=model.created_at,
            expires_at=model.expires_at,
            revoked_at=model.revoked_at,
        )

    def revoke(self, token_id: UUID, revoked_at: datetime) -> None:
        self.db.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.token_id == token_id)
            .values(revoked_at=revoked_at)
        )

    def revoke_family(self, family_id: UUID, revoked_at: datetime) -> None:
        self.db.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.family_id == family_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    def get_user(self, user_id: UUID) -> User | None:
        return SqlAlchemyUserRepository(self.db).get_by_id(user_id)

    def commit(self) -> None:
        self.db.commit()
