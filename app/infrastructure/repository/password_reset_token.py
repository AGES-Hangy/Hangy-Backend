from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.entities import PasswordResetToken
from app.infrastructure.repository.models import PasswordResetTokenModel, UserModel

__all__ = ["SqlAlchemyPasswordResetTokenRepository"]


class SqlAlchemyPasswordResetTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_user_id_by_email(self, email: str) -> UUID | None:
        return self.db.scalar(
            select(UserModel.user_id).where(
                UserModel.email == email,
                UserModel.deleted_at.is_(None),
            )
        )

    def expire_unverified_codes(self, user_id: UUID, expired_at: datetime) -> None:
        self.db.execute(
            update(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.user_id == user_id,
                PasswordResetTokenModel.verified_at.is_(None),
                PasswordResetTokenModel.used_at.is_(None),
            )
            .values(expires_at=expired_at)
        )

    def create(self, token: PasswordResetToken) -> PasswordResetToken:
        model = PasswordResetTokenModel(
            token_id=token.token_id,
            user_id=token.user_id,
            code_hash=token.code_hash,
            attempts=token.attempts,
            verified_at=token.verified_at,
            expires_at=token.expires_at,
            used_at=token.used_at,
            created_at=token.created_at,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: PasswordResetTokenModel) -> PasswordResetToken:
        return PasswordResetToken(
            token_id=model.token_id,
            user_id=model.user_id,
            code_hash=model.code_hash,
            attempts=model.attempts,
            verified_at=model.verified_at,
            expires_at=model.expires_at,
            used_at=model.used_at,
            created_at=model.created_at,
        )
