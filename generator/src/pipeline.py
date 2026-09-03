"""End-to-end orchestration: brief -> plan -> composition -> verified MP4.

Ordering note: `hyperframes check` verifies the *composition* (it drives
its own headless-Chrome session), not the rendered MP4 -- confirmed
against a real install, where `check` ran successfully on a project that
had never been rendered. So the loop below checks first and only spends
time on `render` once the gate is already green, rather than
render-check-repair-render-check-repair each cycle. Rendering is the most
expensive step in the pipeline; there's no reason to pay for it before
the composition is known-good.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from . import assets, builder, checker, planner, repair
from .schema import Plan
from .seed import brief_hash

REPAIR_CAP = 3
HYPERFRAMES_JSON = """{
  "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
  "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
  "paths": { "blocks": "compositions", "components": "compositions/components", "assets": "assets" },
  "media": { "autoProxy": true }
}
"""


@dataclass
class PipelineResult:
    success: bool
    project_dir: Path
    mp4_path: Path | None
    plan: Plan
    attempts: int
    history: list[dict] = field(default_factory=list)
    fallback_assets: list[str] = field(default_factory=list)
    failure_reason: str | None = None


def _write_report(project_dir: Path, name: str, data: dict) -> None:
    (project_dir / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def run(
    brief: str,
    out_root: Path,
    client: OpenAI,
    cache_dir: Path,
    repair_cap: int = REPAIR_CAP,
    model: str = "gpt-5.5",
) -> PipelineResult:
    bh = brief_hash(brief)
    project_dir = out_root / bh
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)
    (project_dir / "hyperframes.json").write_text(HYPERFRAMES_JSON, encoding="utf-8")

    # --- Plan (cached by brief hash: same brief, same plan, no re-call) ---
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{bh}.json"
    if cache_file.exists():
        print(f"[pipeline] reusing cached plan for brief hash {bh}")
        plan = Plan.model_validate_json(cache_file.read_text(encoding="utf-8"))
    else:
        print("[pipeline] calling planner (gpt-5.5)...")
        plan = planner.build_plan(brief, client, model=model)
        cache_file.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    (project_dir / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    # --- Assets (only needs to run once; repairs never re-trigger image gen) ---
    print("[pipeline] generating image assets (gpt-image-2)...")
    fallback_scene_ids = assets.generate_assets(plan, project_dir, client)
    if fallback_scene_ids:
        print(f"[pipeline] asset generation fell back for scenes: {fallback_scene_ids}")

    # --- Build -> check -> repair loop ---
    history: list[dict] = []
    attempt = 0
    while True:
        attempt += 1
        builder.build_composition(plan, project_dir)
        print(f"[pipeline] attempt {attempt}: running check gate...")
        result = checker.check(project_dir)
        history.append(
            {
                "attempt": attempt,
                "ok": result.ok,
                "error_count": sum(
                    (result.raw.get(s) or {}).get("errorCount", 0)
                    for s in ("lint", "runtime", "layout", "motion", "contrast")
                ),
                "findings": checker.all_findings(result),
            }
        )

        if result.ok:
            print(f"[pipeline] check gate passed on attempt {attempt}.")
            break

        if attempt >= repair_cap:
            _write_report(
                project_dir,
                "failure-report.json",
                {"brief": brief, "reason": "repair cap reached", "history": history},
            )
            return PipelineResult(
                success=False,
                project_dir=project_dir,
                mp4_path=None,
                plan=plan,
                attempts=attempt,
                history=history,
                fallback_assets=fallback_scene_ids,
                failure_reason=f"check gate still failing after {repair_cap} attempts",
            )

        findings = checker.all_findings(result)
        outcome = repair.apply_rule_based_repairs(plan, findings)
        patched = False
        if outcome.unhandled_findings:
            patched = repair.apply_llm_patch(plan, outcome.unhandled_findings, client, model=model)

        print(
            f"[pipeline] attempt {attempt}: applied {len(outcome.applied_rule_fixes)} "
            f"rule fix(es), llm patch applied={patched}, "
            f"{len(outcome.unhandled_findings)} unhandled finding(s)"
        )

        if not outcome.applied_rule_fixes and not patched:
            # No repair action was possible at all -- looping further would
            # just reproduce the identical failure. Fail now rather than
            # burn the rest of the cap pretending to try. Still counts as
            # "fail loudly": the report says exactly why.
            _write_report(
                project_dir,
                "failure-report.json",
                {
                    "brief": brief,
                    "reason": "no repair action available for remaining findings",
                    "history": history,
                },
            )
            return PipelineResult(
                success=False,
                project_dir=project_dir,
                mp4_path=None,
                plan=plan,
                attempts=attempt,
                history=history,
                fallback_assets=fallback_scene_ids,
                failure_reason="no repair rule or LLM patch could address the remaining findings",
            )

    # --- Render (only once the gate is green) ---
    mp4_path = project_dir / "render" / "output.mp4"
    print("[pipeline] check passed -- rendering MP4...")
    render_result = checker.render(project_dir, mp4_path)
    if not render_result.ok:
        _write_report(
            project_dir,
            "failure-report.json",
            {
                "brief": brief,
                "reason": "render failed after check passed",
                "stderr": render_result.stderr[-4000:],
                "history": history,
            },
        )
        return PipelineResult(
            success=False,
            project_dir=project_dir,
            mp4_path=None,
            plan=plan,
            attempts=attempt,
            history=history,
            fallback_assets=fallback_scene_ids,
            failure_reason="hyperframes render exited non-zero or produced no file",
        )

    # Save the passing check output alongside the render, matching the
    # deliverable list in the task brief ("the check output for each,
    # showing the gate passing").
    final_check = checker.check(project_dir)
    _write_report(project_dir, "check-output.json", final_check.raw)

    return PipelineResult(
        success=True,
        project_dir=project_dir,
        mp4_path=mp4_path,
        plan=plan,
        attempts=attempt,
        history=history,
        fallback_assets=fallback_scene_ids,
    )
