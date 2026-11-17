"""The deploy runs `alembic upgrade head`, which fails when there are two heads.

The test suite builds the schema with `create_all`, so nothing else would catch
a second head: two PRs branching from the same revision merge cleanly in git.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def test_migrations_have_a_single_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"Alembic tem mais de uma ponta: {sorted(heads)}"
