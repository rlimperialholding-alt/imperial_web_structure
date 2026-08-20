"""Fail closed unless the platform migration graph has its one expected head."""

from alembic.config import Config
from alembic.script import ScriptDirectory


EXPECTED_HEAD = "20260816_0072"


def main() -> int:
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    if heads != [EXPECTED_HEAD]:
        raise SystemExit(
            f"Alembic head mismatch: expected exactly {EXPECTED_HEAD}, observed {heads!r}."
        )
    print(f"Alembic head PASS: {EXPECTED_HEAD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
