import argparse
import json
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path


CONTAINER_BACKUP_CODE = """
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from main import DB_PATH

source = Path(DB_PATH)
target = Path(sys.argv[1])

if not source.is_file():
    raise FileNotFoundError(f"Database not found: {source}")

deadline = time.monotonic() + 120

def check_timeout(*_):
    if time.monotonic() > deadline:
        raise TimeoutError("Database backup exceeded 120 seconds")

source_uri = source.resolve().as_uri() + "?mode=ro"

with closing(
    sqlite3.connect(source_uri, uri=True, timeout=10)
) as original:
    with closing(sqlite3.connect(target)) as backup:
        original.backup(
            backup,
            pages=100,
            progress=check_timeout,
            sleep=0.1,
        )

print(f"Source database: {source}")
"""


def run_command(command, timeout=30):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Command failed: {' '.join(command[:3])}\n{message}"
        )

    return result.stdout.strip()


def validate_backup(path):
    uri = path.resolve().as_uri() + "?mode=ro"

    with closing(
        sqlite3.connect(uri, uri=True, timeout=10)
    ) as connection:
        checks = [
            row[0]
            for row in connection.execute("PRAGMA integrity_check")
        ]

        if checks != ["ok"]:
            raise RuntimeError(
                f"Backup integrity check failed: {checks}"
            )

        product_count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

    return product_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="manual")
    parser.add_argument(
        "--container",
        default="fds-backend-persistent",
    )
    args = parser.parse_args()

    docker = shutil.which("docker")

    if docker is None:
        raise RuntimeError("Docker CLI not found")

    # Use the container ID so a rename cannot change the backup source.
    details = json.loads(
        run_command([docker, "inspect", args.container])
    )[0]

    if not details["State"]["Running"]:
        raise RuntimeError(
            f"Container is not running: {args.container}"
        )

    container_id = details["Id"]

    backup_dir = Path(__file__).resolve().parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    safe_run_id = "".join(
        character
        if character.isalnum() or character in "-_"
        else "_"
        for character in args.run_id
    )[:80] or "manual"

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    unique_id = uuid.uuid4().hex

    target = backup_dir / (
        f"products-docker-{timestamp}-{safe_run_id}-{unique_id[:8]}.db"
    )
    temporary = target.with_suffix(".partial")

    container_temporary = f"/tmp/fds-backup-{unique_id}.db"

    try:
        # Create a consistent snapshot inside the running container.
        source_info = run_command(
            [
                docker,
                "exec",
                container_id,
                "python",
                "-c",
                CONTAINER_BACKUP_CODE,
                container_temporary,
            ],
            timeout=135,
        )

        # Copy the finished snapshot, not the live database file.
        run_command(
            [
                docker,
                "cp",
                f"{container_id}:{container_temporary}",
                str(temporary),
            ],
            timeout=120,
        )

        product_count = validate_backup(temporary)

        # Publish the backup only after validation succeeds.
        temporary.replace(target)

        print("Backup completed successfully")
        print("Container:", args.container)
        print("Container ID:", container_id[:12])
        print(source_info)
        print("Integrity check: ok")
        print("Products:", product_count)
        print("Backup file:", target)

    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    finally:
        # Clean up only this operation's temporary container file.
        try:
            run_command(
                [
                    docker,
                    "exec",
                    container_id,
                    "python",
                    "-c",
                    (
                        "from pathlib import Path; import sys; "
                        "Path(sys.argv[1]).unlink(missing_ok=True)"
                    ),
                    container_temporary,
                ],
                timeout=15,
            )
        except Exception as error:
            print(
                "Warning: could not remove temporary container backup:",
                error,
            )


if __name__ == "__main__":
    main()