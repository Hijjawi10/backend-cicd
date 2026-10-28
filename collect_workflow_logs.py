import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
TARGETS = {
    "FDS_Backup_DB",
    "FDS_Deploy_Backend",
    "FDS_Verify_Backend",
    "FDS_Airflow_Inventory_Report",
    "FDS_Check_Reports_DB",
}

parser = argparse.ArgumentParser()
parser.add_argument("--folder-id", required=True)
parser.add_argument("--ctm-path")
parser.add_argument("--timeout-minutes", type=int, default=15)
args = parser.parse_args()

folder_id = args.folder_id

safe_folder_id = "".join(
    character if character.isalnum() or character in "-_" else "_"
    for character in folder_id
)

timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
run_dir = PROJECT_DIR / "logs" / f"{timestamp}_{safe_folder_id}"
run_dir.mkdir(parents=True, exist_ok=True)


os.environ["PATH"] = (
    str(Path.home() / ".local/bin")
    + os.pathsep
    + os.environ.get("PATH", "")
)

ctm_path = args.ctm_path or shutil.which("ctm")


def write_json(filename, content):
    destination = run_dir / filename
    temporary = destination.with_suffix(".tmp")

    temporary.write_text(SuperAdmin@123
        json.dumps(content, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def execute_ctm(*arguments):
    if not ctm_path:
        raise RuntimeError(
            "Control-M CLI not found. Use --ctm-path with its full path."
        )

    response = subprocess.run(
        [ctm_path, *arguments],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if response.returncode != 0:
        raise RuntimeError(
            response.stderr.strip()
            or response.stdout.strip()
            or f"CLI exit code: {response.returncode}"
        )

    output = response.stdout

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict) and parsed.get("errors"):
        raise RuntimeError(json.dumps(parsed["errors"], ensure_ascii=False))

    return output



def fetch_jobs():
    output = execute_ctm(
        "run",
        "jobs:status::get",
        "10000",
        "-s",
        "server=IN01&folder=FDS_Jenkins",
    )

    data = json.loads(output)
    statuses = data.get("statuses")

    if not isinstance(statuses, list):
        raise RuntimeError("Unexpected API response: statuses is missing")

    if (
        len(statuses) >= 10000
        or int(data.get("total", len(statuses))) > len(statuses)
    ):
        raise RuntimeError(
            "Status query may be truncated; narrow the query before collecting."
        )

    return [
        job
        for job in statuses
        if job.get("folderId") == folder_id
        and job.get("name") in TARGETS
    ]


def save_details(jobs):
    retrieval_errors = []

    for job in jobs:
        job_id = job["jobId"]
        safe_job_id = job_id.replace(":", "_")
        prefix = f"{job['name']}-{safe_job_id}"

        for kind in ("output", "log"):
            filename = run_dir / f"{prefix}-{kind}.txt"
            last_error = None

            for attempt in range(3):
                try:
                    content = execute_ctm(
                        "run",
                        f"job:{kind}::get",
                        job_id,
                    )
                    filename.write_text(content, encoding="utf-8")
                    last_error = None
                    break

                except Exception as error:
                    last_error = str(error)
                    if attempt < 2:
                        time.sleep(3)

            if last_error is not None:
                filename.write_text(
                    f"Could not retrieve {kind} for {job_id}\n"
                    f"{last_error}\n",
                    encoding="utf-8",
                )
                retrieval_errors.append({
                    "jobId": job_id,
                    "kind": kind,
                    "error": last_error,
                })

            print("Saved:", filename, flush=True)

    return retrieval_errors


def main():
    print("Logs folder:", run_dir, flush=True)

    deadline = time.monotonic() + args.timeout_minutes * 60
    jobs = []
    last_api_error = None

    while True:
        try:
            jobs = fetch_jobs()
            last_api_error = None
        except Exception as error:
            last_api_error = str(error)
            print("Status query failed:", last_api_error, flush=True)

        failed = (
            last_api_error is None
            and any(job.get("status") == "Ended Not OK" for job in jobs)
        )

        succeeded = (
            last_api_error is None
            and {job["name"] for job in jobs} == TARGETS
            and all(job.get("status") == "Ended OK" for job in jobs)
        )

        expired = time.monotonic() >= deadline

        if failed:
            outcome = "FAILURE_DETECTED"
        elif succeeded:
            outcome = "SUCCESS"
        elif expired:
            outcome = "TIMEOUT"
        else:
            outcome = "MONITORING"

        summary = {
            "folderId": folder_id,
            "capturedAt": datetime.now().astimezone().isoformat(),
            "outcome": outcome,
            "lastApiError": last_api_error,
            "missingJobs": sorted(TARGETS - {j["name"] for j in jobs}),
            "jobs": jobs,
        }

        write_json("summary.json", summary)

        if failed or succeeded or expired:
            errors = save_details(jobs)
            summary["retrievalErrors"] = errors
            write_json("summary.json", summary)

            print("Outcome:", outcome, flush=True)
            print("Logs saved to:", run_dir, flush=True)

            return 1 if expired or errors else 0

        time.sleep(10)


try:
    sys_exit_code = main()
except Exception as error:
    (run_dir / "collector-error.txt").write_text(
        str(error),
        encoding="utf-8",
    )
    raise
else:
    raise SystemExit(sys_exit_code)