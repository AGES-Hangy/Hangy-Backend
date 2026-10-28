"""Production bootstrap: the approved tag catalog and one business administrator."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.domain.services.auth import password_hash
from app.infrastructure.repository.models import BusinessProfileModel, UserModel
from app.infrastructure.repository.session import SessionLocal
from app.seed_catalog import ensure_tags

ADMIN_EMAIL = "admin@hangy.com"
ADMIN_ID = uuid5(NAMESPACE_URL, "hangy:production:admin")
# Exported from tagsHangy.xlsx, Planilha1!A1:H30. Each column is one macro tag.
PRODUCTION_TAGS: dict[str, list[str]] = json.loads(
    Path(__file__).with_name("production_tags.json").read_text(encoding="utf-8")
)


class ProductionSeedError(Exception):
    """Raised when bootstrap cannot proceed without changing an existing account."""


def seed_production(db: Session, admin_password: str) -> None:
    """Run inside a transaction; never reset passwords or promote existing users."""
    if not 8 <= len(admin_password) <= 128 or not admin_password.strip():
        raise ProductionSeedError(
            "PRODUCTION_ADMIN_PASSWORD must contain 8 to 128 characters "
            "and cannot be blank."
        )

    existing = db.scalars(
        select(UserModel).where(
            or_(UserModel.user_id == ADMIN_ID, UserModel.email == ADMIN_EMAIL)
        )
    ).all()
    if existing:
        if (
            len(existing) != 1
            or existing[0].user_id != ADMIN_ID
            or existing[0].email != ADMIN_EMAIL
            or existing[0].deleted_at is not None
            or existing[0].role != UserRoleEnum.ADMIN
            or existing[0].user_type != UserTypeEnum.BUSINESS
            or existing[0].business_profile is None
        ):
            raise ProductionSeedError(
                "Production admin conflicts with an existing or deleted account. "
                "Resolve the account explicitly before retrying deployment."
            )
    else:
        now = datetime.now(UTC)
        # Direct persistence keeps tags, user, role and profile in one transaction;
        # the public registration repository commits before assigning an admin role.
        db.add(
            UserModel(
                user_id=ADMIN_ID,
                email=ADMIN_EMAIL,
                user_type=UserTypeEnum.BUSINESS,
                role=UserRoleEnum.ADMIN,
                name="Admin Hangy",
                password_hash=password_hash.hash(admin_password),
                password_changed_at=now,
                accepted_terms_at=now,
                accepted_terms_version="2026-08-01",
                business_profile=BusinessProfileModel(
                    cnpj="11222333000181",
                    address="Av. Independência, 100 — Porto Alegre",
                    business_latitude=-30.0331,
                    business_longitude=-51.23,
                ),
            )
        )
    ensure_tags(db, PRODUCTION_TAGS)


def main() -> None:
    try:
        with SessionLocal.begin() as db:
            seed_production(db, os.getenv("PRODUCTION_ADMIN_PASSWORD", ""))
    except ProductionSeedError as error:
        raise SystemExit(str(error)) from None
    print("Production tags and administrator are ready.")


if __name__ == "__main__":
    main()
