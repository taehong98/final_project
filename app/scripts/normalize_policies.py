from __future__ import annotations

import argparse

from app.db.base import Base
from app.db import models  # noqa: F401
from app.db.session import SessionLocal, engine
from app.normalizers.policies import normalize_bokjiro, normalize_gov24


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize raw policy data into serving tables.")
    parser.add_argument("--source", choices=("gov24", "bokjiro", "all"), default="all")
    parser.add_argument("--init-tables", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.init_tables:
        Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if args.source in ("gov24", "all"):
            count = normalize_gov24(db)
            print(f"[normalize] gov24 policies={count}")
        if args.source in ("bokjiro", "all"):
            count = normalize_bokjiro(db)
            print(f"[normalize] bokjiro policies={count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
