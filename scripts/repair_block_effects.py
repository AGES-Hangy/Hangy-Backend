"""Repair pre-fix blocks. Dry-run by default; never restores anything.

Run: python -m scripts.repair_block_effects [--apply]
Uses DATABASE_URL from the normal application configuration. Review the target
before --apply. Each pair is repaired atomically; rerunning is safe.
"""

import argparse

from sqlalchemy import select

from app.domain.services.block import UserAlreadyBlockedError
from app.infrastructure.repository.block import SqlAlchemyBlockRepository
from app.infrastructure.repository.models import UserBlockModel
from app.infrastructure.repository.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        pairs = list(
            db.execute(select(UserBlockModel.blocker_id, UserBlockModel.blocked_id))
        )
        mode = "apply" if args.apply else "dry-run"
        print(f"{len(pairs)} existing blocks; mode: {mode}")
        if not args.apply:
            return
        for blocker, blocked in pairs:
            try:
                SqlAlchemyBlockRepository(db).create(blocker, blocked)
            except UserAlreadyBlockedError:
                # create commits repaired effects, then retains 409 semantics.
                pass
        print(f"Repaired {len(pairs)} blocks without restoring relationships.")


if __name__ == "__main__":
    main()
