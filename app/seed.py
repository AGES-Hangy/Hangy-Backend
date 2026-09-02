from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.entities import UserCredentials
from app.domain.enums import UserTypeEnum
from app.domain.services import AuthService
from app.infrastructure.repository.models import TagModel
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
)

SEED_TAGS = {
    "Esportes": ("Futebol", "Corrida"),
    "Música": ("Rock", "Sertanejo"),
    "Gastronomia": ("Culinária Italiana", "Confeitaria"),
    "Arte e Cultura": ("Teatro", "Cinema"),
}


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


def main() -> None:
    with SessionLocal() as db:
        seed_users(db)
        seed_tags(db)


if __name__ == "__main__":
    main()
