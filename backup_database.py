import argparse
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="manual")
    args = parser.parse_args()

    source = Path("/opt/backend-cicd/products.db")
    backup_dir = Path(__file__).resolve().parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    if not source.is_file():
        raise FileNotFoundError(f"Database not found: {source}")

    safe_run_id = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in args.run_id
    )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = backup_dir / f"products-{timestamp}-{safe_run_id}.db"
    temporary = target.with_suffix(".partial")

    deadline = time.monotonic() + 120

    def check_timeout(*_):
        if time.monotonic() > deadline:
            raise TimeoutError("Database backup exceeded 120 seconds")

    try:
        source_uri = source.resolve().as_uri() + "?mode=ro"

        with closing(
            sqlite3.connect(source_uri, uri=True, timeout=10)
        ) as original:
            with closing(sqlite3.connect(temporary)) as backup:
                original.backup(
                    backup,
                    pages=100,
                    progress=check_timeout,
                    sleep=0.1,
                )

                checks = [
                    row[0]
                    for row in backup.execute("PRAGMA integrity_check")
                ]

                if checks != ["ok"]:
                    raise RuntimeError(
                        f"Backup integrity check failed: {checks}"
                    )

                product_count = backup.execute(
                    "SELECT COUNT(*) FROM products"
                ).fetchone()[0]

        temporary.replace(target)

        print("Backup completed successfully")
        print("Integrity check: ok")
        print("Products:", product_count)
        print("Backup file:", target)

    except Exception:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()