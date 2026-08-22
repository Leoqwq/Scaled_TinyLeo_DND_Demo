"""Start and verify one SRv6 agent in every assigned TinyLEO namespace."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Callable


ACK_MARKER = "TINYLEO_SRV6_DEPLOY_ACK="


def _pid_map(workdir: Path) -> dict[str, str]:
    pid_path = workdir / "container_pid.txt"
    mapping: dict[str, str] = {}
    for line in pid_path.read_text(encoding="utf-8").splitlines():
        for entry in line.split():
            if entry == "NA":
                continue
            parts = entry.split(":", 1)
            if len(parts) != 2 or not parts[0] or not parts[1].isdigit():
                raise ValueError(f"malformed container PID entry: {entry!r}")
            if parts[0] in mapping:
                raise ValueError(f"duplicate container PID entry: {parts[0]}")
            mapping[parts[0]] = parts[1]
    if not mapping:
        raise RuntimeError("no assigned containers found for SRv6 deployment")
    return mapping


def deploy_agents(
    workdir: str | Path,
    python_executable: str,
    *,
    remote_id: int,
    process_factory: Callable = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
    startup_wait_s: float = 1.0,
) -> dict:
    """Start agents and return an acknowledgement only while all remain alive."""
    workdir = Path(workdir)
    if not python_executable:
        raise ValueError("python_executable must be nonempty")
    if startup_wait_s < 0:
        raise ValueError("startup_wait_s must be nonnegative")
    if isinstance(remote_id, bool) or not isinstance(remote_id, int) or remote_id < 0:
        raise ValueError("remote_id must be a nonnegative integer")
    mapping = _pid_map(workdir)
    agent_path = (
        workdir
        / "controller"
        / "geographic_srv6_anycast"
        / "srv6_agent.py"
    )
    if not agent_path.is_file():
        raise FileNotFoundError(f"SRv6 agent script does not exist: {agent_path}")
    processes = []
    for name, pid in sorted(mapping.items()):
        command = [
            "nsenter",
            "-u",
            "-i",
            "-n",
            "-p",
            "-t",
            pid,
            python_executable,
            str(agent_path),
        ]
        process = process_factory(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        processes.append((name, pid, process))
    sleeper(startup_wait_s)
    exited = []
    for name, pid, process in processes:
        returncode = process.poll()
        if returncode is not None:
            exited.append({"name": name, "pid": pid, "returncode": returncode})
    if exited:
        raise RuntimeError(f"SRv6 agent exited during startup: {exited}")
    return {
        "remote_id": remote_id,
        "expected_count": len(mapping),
        "started_count": len(processes),
        "agents": [
            {"name": name, "namespace_pid": int(pid)}
            for name, pid, _process in processes
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--python-executable", required=True)
    parser.add_argument("--remote-id", type=int, required=True)
    parser.add_argument("--startup-wait-s", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    acknowledgement = deploy_agents(
        args.workdir,
        args.python_executable,
        remote_id=args.remote_id,
        startup_wait_s=args.startup_wait_s,
    )
    print(ACK_MARKER + json.dumps(acknowledgement, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
