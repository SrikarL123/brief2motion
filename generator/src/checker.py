"""Thin, defensive wrapper around the `hyperframes` CLI.

Confirmed against a real `hyperframes@0.8.27` install (not guessed):
- `hyperframes lint --json` -> {ok, errorCount, warningCount, infoCount,
  findings[], filesScanned, _meta}. Runs with no browser required.
- `hyperframes check --json` -> {ok, strict, lint{}, runtime{}, layout{},
  motion{}, contrast{}, snapshots{}, _meta}. Each sub-section has its own
  ok/errorCount/findings[]. Needs headless Chrome (downloaded on first
  run, or pointed at an existing browser via HYPERFRAMES_BROWSER_PATH).
- `hyperframes render --output <path>` -> writes an MP4.

The CLI sometimes prints non-JSON lines (npm warnings, an `[INFO]`
compiler line) to stdout *before* the JSON payload even with --json
requested, and PR history for this project shows that has been a real,
previously-fixed bug class -- so we defensively locate the JSON object in
stdout rather than assuming stdout is pure JSON.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class HyperFramesCLIError(RuntimeError):
    """Raised when the CLI itself fails to run (not a check failure)."""


@dataclass
class CommandResult:
    ok: bool
    raw: dict
    stdout: str
    stderr: str
    returncode: int


def _extract_json(stdout: str) -> dict:
    """Find the first complete top-level JSON object in stdout.

    Handles stray log lines the CLI sometimes emits before the JSON
    payload (observed: an `[INFO] [Compiler] ...` line ahead of `check
    --json`'s output).
    """
    start = stdout.find("{")
    if start == -1:
        raise HyperFramesCLIError(f"no JSON object found in CLI output:\n{stdout[:2000]}")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(stdout, start)
    return obj


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[str, str, int]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise HyperFramesCLIError(
            f"`{' '.join(cmd)}` timed out after {timeout}s"
        ) from e
    return proc.stdout, proc.stderr, proc.returncode


def lint(project_dir: Path, timeout: int = 60) -> CommandResult:
    stdout, stderr, code = _run(
        ["npx", "hyperframes", "lint", "--json"], project_dir, timeout
    )
    data = _extract_json(stdout)
    return CommandResult(ok=bool(data.get("ok")), raw=data, stdout=stdout, stderr=stderr, returncode=code)


def check(project_dir: Path, timeout: int = 180) -> CommandResult:
    stdout, stderr, code = _run(
        ["npx.cmd", "hyperframes", "check", "--json"], project_dir, timeout
    )
    data = _extract_json(stdout)
    return CommandResult(ok=bool(data.get("ok")), raw=data, stdout=stdout, stderr=stderr, returncode=code)


def render(project_dir: Path, output: Path, timeout: int = 300) -> CommandResult:
    output.parent.mkdir(parents=True, exist_ok=True)
    stdout, stderr, code = _run(
        ["npx.cmd", "hyperframes", "render", "--output", str(output)], project_dir, timeout
    )
    ok = code == 0 and output.exists()
    return CommandResult(ok=ok, raw={"stdout": stdout}, stdout=stdout, stderr=stderr, returncode=code)


def all_findings(check_result: CommandResult) -> list[dict]:
    """Flatten findings from every sub-section of a `check --json` payload,
    tagging each with which section produced it (needed by repair.py to
    decide whether a finding is even actionable, e.g. runtime findings
    about a missing browser binary are an infra problem, not a repair)."""
    findings = []
    for section in ("lint", "runtime", "layout", "motion", "contrast"):
        sec = check_result.raw.get(section) or {}
        for f in sec.get("findings", []):
            f = dict(f)
            f["_section"] = section
            findings.append(f)
    return findings
