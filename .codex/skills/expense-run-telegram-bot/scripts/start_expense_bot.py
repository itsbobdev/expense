#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the expense tracker Telegram bot in the background."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
        help="Path to the repository root.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port used by the FastAPI app and bot health endpoint.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Seconds to wait for the health check after launch.",
    )
    parser.add_argument(
        "--force-restart",
        action="store_true",
        help="Stop the PID from the pid file first, then start a fresh instance.",
    )
    return parser.parse_args()


def healthcheck(port: int) -> dict | None:
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def run_powershell_json(script: str) -> object:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and not result.stdout.strip():
        return []
    output = result.stdout.strip()
    if not output:
        return []
    return json.loads(output)


def list_run_py_processes() -> list[dict]:
    script = r"""
$items = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*run.py*' } |
    Select-Object ProcessId, CommandLine, ExecutablePath
if ($items) {
    $items | ConvertTo-Json -Compress
}
"""
    data = run_powershell_json(script)
    if isinstance(data, dict):
        return [data]
    return data


def get_listening_port_owner(port: int) -> int | None:
    script = rf"""
$item = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1 LocalAddress, LocalPort, OwningProcess
if ($item) {{
    $item | ConvertTo-Json -Compress
}}
"""
    data = run_powershell_json(script)
    if isinstance(data, dict):
        return int(data["OwningProcess"])
    return None


def kill_pid(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        check=False,
        capture_output=True,
        text=True,
    )


def stop_existing_processes(pid_file: Path, port: int) -> list[int]:
    killed: list[int] = []
    pid_file.unlink(missing_ok=True)

    run_py_processes = list_run_py_processes()
    port_owner = get_listening_port_owner(port)

    pids_to_kill = {int(proc["ProcessId"]) for proc in run_py_processes}
    if port_owner is not None:
        pids_to_kill.add(port_owner)

    for pid in sorted(pids_to_kill):
        kill_pid(pid)
        killed.append(pid)

    time.sleep(2)
    return killed


def tail_text(path: Path, lines: int = 20) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def start_process(backend_dir: Path, stdout_log: Path, stderr_log: Path) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    stdout_handle = stdout_log.open("a", encoding="utf-8")
    stderr_handle = stderr_log.open("a", encoding="utf-8")

    try:
        process = subprocess.Popen(
            [sys.executable, "run.py"],
            cwd=backend_dir,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()

    return process


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    backend_dir = repo_root / "backend"
    stdout_log = backend_dir / "bot_stdout.log"
    stderr_log = backend_dir / "bot_stderr.log"
    pid_file = backend_dir / "telegram_bot.pid"

    if not backend_dir.exists():
        print(f"Backend directory not found: {backend_dir}", file=sys.stderr)
        return 1

    run_py_processes = list_run_py_processes()
    port_owner = get_listening_port_owner(args.port)
    live_run_py_pids = [int(proc["ProcessId"]) for proc in run_py_processes]

    if not args.force_restart:
        status = healthcheck(args.port)
        if (
            status
            and status.get("bot") == "running"
            and len(live_run_py_pids) == 1
            and port_owner in live_run_py_pids
        ):
            print(
                json.dumps(
                    {
                        "status": "already-running",
                        "repo_root": str(repo_root),
                        "backend_dir": str(backend_dir),
                        "health": status,
                        "pid": live_run_py_pids[0],
                        "run_py_pids": live_run_py_pids,
                        "port_owner_pid": port_owner,
                        "stdout_log": str(stdout_log),
                        "stderr_log": str(stderr_log),
                    }
                )
            )
            return 0

    killed_pids: list[int] = []
    if args.force_restart:
        killed_pids = stop_existing_processes(pid_file, args.port)

    process = start_process(backend_dir, stdout_log, stderr_log)
    pid_file.write_text(str(process.pid), encoding="utf-8")

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        status = healthcheck(args.port)
        current_run_py_processes = list_run_py_processes()
        current_run_py_pids = [int(proc["ProcessId"]) for proc in current_run_py_processes]
        current_port_owner = get_listening_port_owner(args.port)
        if (
            status
            and status.get("bot") == "running"
            and len(current_run_py_pids) == 1
            and current_port_owner == process.pid
        ):
            print(
                json.dumps(
                    {
                        "status": "started",
                        "pid": process.pid,
                        "killed_pids": killed_pids,
                        "repo_root": str(repo_root),
                        "backend_dir": str(backend_dir),
                        "health": status,
                        "run_py_pids": current_run_py_pids,
                        "port_owner_pid": current_port_owner,
                        "stdout_log": str(stdout_log),
                        "stderr_log": str(stderr_log),
                    }
                )
            )
            return 0
        time.sleep(1)

    print(
        json.dumps(
            {
                "status": "failed",
                "pid": process.pid,
                "killed_pids": killed_pids,
                "repo_root": str(repo_root),
                "backend_dir": str(backend_dir),
                "run_py_pids": [int(proc["ProcessId"]) for proc in list_run_py_processes()],
                "port_owner_pid": get_listening_port_owner(args.port),
                "stdout_log": str(stdout_log),
                "stderr_log": str(stderr_log),
                "stderr_tail": tail_text(stderr_log),
                "stdout_tail": tail_text(stdout_log),
            }
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
