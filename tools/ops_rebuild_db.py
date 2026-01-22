import argparse
import shutil
import time
from pathlib import Path

from hyperliquid.common.settings import load_settings
from hyperliquid.storage.db import init_db, assert_schema_version


def _default_backup_name(db_path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M")
    return db_path.with_suffix(db_path.suffix + f".bak-{stamp}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild SQLite DB with schema.")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    parser.add_argument("--schema", required=True, help="Path to schema.json")
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Backup existing DB before rebuild.",
    )
    parser.add_argument(
        "--backup-path",
        help="Explicit backup path (defaults to <db>.bak-YYYYMMDD-HHMM).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing DB before rebuild.",
    )
    args = parser.parse_args()

    settings = load_settings(Path(args.config), Path(args.schema))
    db_path = Path(settings.db_path)

    if db_path.exists():
        if args.backup:
            backup_path = Path(args.backup_path) if args.backup_path else _default_backup_name(db_path)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_path, backup_path)
            print(f"backup_path={backup_path}")
        if not args.force:
            raise SystemExit("DB exists; pass --force to rebuild after backup")
        db_path.unlink()

    conn = init_db(str(db_path))
    try:
        assert_schema_version(conn)
    finally:
        conn.close()
    print("db_rebuilt=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
