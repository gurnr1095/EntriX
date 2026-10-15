"""Run one load test against the local Docker Compose stack and record everything.

    python -m loadtests.run_loadtest --label cache-off --cache off
    python -m loadtests.run_loadtest --label cache-on  --cache on

For each run it: resets the database and Redis, restarts the API container in the requested
configuration, runs Locust headless, then checks the invariants. Everything lands in
loadtests/results/<label>_* (Locust CSV and HTML, environment.json, invariants.txt).
Numbers for LOADTEST.md come from these files via loadtests/summarize.py, never typed by hand.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "loadtests" / "results"
HOST = "http://localhost:8000"
TABLES = (
    "outbox, idempotency_keys, check_ins, registrations, team_members, teams, "
    "categories, events, users"
)


def sh(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, **kw)  # type: ignore[call-overload]


def powershell(command: str) -> str:
    out = sh(["powershell", "-NoProfile", "-Command", command])
    return out.stdout.strip()


def machine_info() -> dict[str, object]:
    info: dict[str, object] = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
    }
    if platform.system() == "Windows":
        info["cpu"] = powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name")
        ram = powershell("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")
        info["ram_gb"] = round(int(ram) / 1024**3, 1) if ram.isdigit() else None
    docker = sh(["docker", "info", "--format", "{{.ServerVersion}}|{{.NCPU}}|{{.MemTotal}}"])
    if docker.returncode == 0 and docker.stdout.count("|") == 2:
        version, ncpu, mem = docker.stdout.strip().split("|")
        info["docker_version"] = version
        info["docker_cpus"] = int(ncpu)
        info["docker_memory_gb"] = round(int(mem) / 1024**3, 1)
    locust = sh([sys.executable, "-m", "pip", "show", "locust"])
    info["locust"] = next(
        (line.split(": ")[1] for line in locust.stdout.splitlines() if line.startswith("Version")),
        None,
    )
    return info


def wait_for_api(timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{HOST}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise SystemExit("API did not become healthy in time")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--cache", choices=["on", "off"], required=True)
    parser.add_argument("--workers", type=int, default=1, help="uvicorn worker processes")
    parser.add_argument("--peak-users", type=int, default=300)
    parser.add_argument("--ramp-seconds", type=int, default=30)
    parser.add_argument("--run-seconds", type=int, default=120)
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    prefix = RESULTS / args.label

    # The knobs for this run. The per-IP rate limit is raised because every virtual user shares
    # this laptop's address; the limiter itself is covered by tests/test_rate_limit.py.
    api_config = {
        "CACHE_ENABLED": "true" if args.cache == "on" else "false",
        "RATE_LIMIT_IP_PER_MIN": "1000000",
        "RATE_LIMIT_USER_PER_MIN": "10",
        "WEB_CONCURRENCY": str(args.workers),
        "DB_POOL_SIZE": "20",
        "DB_MAX_OVERFLOW": "20",
        "AUTH_MODE": "dev",
    }
    environment = {
        "label": args.label,
        "machine": machine_info(),
        "api_config": api_config,
        "load": {
            "peak_users": args.peak_users,
            "ramp_seconds": args.ramp_seconds,
            "run_seconds": args.run_seconds,
            "browse_to_launch_user_ratio": "4:1",
        },
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
    }
    (RESULTS / f"{args.label}_environment.json").write_text(
        json.dumps(environment, indent=2), encoding="utf-8"
    )

    print(f"[{args.label}] resetting database and Redis")
    sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "sportreg", "-d", "sportreg",
        "-c", f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"], check=True)
    sh(["docker", "compose", "exec", "-T", "redis", "redis-cli", "FLUSHDB"], check=True)
    sh(["curl", "-s", "-X", "DELETE", "http://localhost:8025/api/v1/messages"])

    print(f"[{args.label}] restarting the API with {api_config}")
    sh(
        ["docker", "compose", "up", "-d", "--force-recreate", "api"],
        env={**os.environ, **api_config},
        check=True,
    )
    wait_for_api()

    # Seed first and wait: Locust must not start sending traffic until the data exists.
    seed_file = f"{prefix}_seed.json"
    print(f"[{args.label}] seeding data")
    subprocess.run(
        [sys.executable, "-m", "loadtests.seed", seed_file, "--host", HOST], cwd=ROOT, check=True
    )

    print(f"[{args.label}] running Locust for {args.run_seconds}s")
    locust = subprocess.run(
        [
            sys.executable, "-m", "locust", "-f", "loadtests/locustfile.py", "--headless",
            "--host", HOST, "--csv", str(prefix), "--html", f"{prefix}_report.html",
            "--only-summary",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "LT_SEED_FILE": seed_file,
            "LT_PEAK_USERS": str(args.peak_users),
            "LT_RAMP_SECONDS": str(args.ramp_seconds),
            "LT_RUN_SECONDS": str(args.run_seconds),
        },
    )

    print(f"[{args.label}] checking invariants")
    checked = subprocess.run(
        [sys.executable, "-m", "loadtests.check_invariants", f"{prefix}_invariants.txt"], cwd=ROOT
    )
    environment["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")
    environment["locust_exit_code"] = locust.returncode
    environment["invariants_exit_code"] = checked.returncode
    (RESULTS / f"{args.label}_environment.json").write_text(
        json.dumps(environment, indent=2), encoding="utf-8"
    )
    return checked.returncode


if __name__ == "__main__":
    sys.exit(main())
