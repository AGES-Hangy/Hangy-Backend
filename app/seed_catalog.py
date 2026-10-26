from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.repository.models import TagModel


def ensure_tags(db: Session, catalog: Mapping[str, Sequence[str]]) -> None:
    """Add missing tags by name and parent; the caller owns the transaction."""
    for macro_name, micro_names in catalog.items():
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
                existing_micro_names.add(micro_name)
    db.flush()
