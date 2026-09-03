"""Turns `check --json` findings into plan mutations.

Design (PLANNING.md §3): because the plan -> HTML step is a deterministic
template fill, not freeform LLM authorship, most repairs are just
adjusting a known parameter (font_scale, a color override, motion) on the
offending scene -- no model call needed, no risk of the "fix" breaking
something else in the markup. Only findings with no rule get escalated to
a *scoped* LLM patch: gpt-5.5 returns small {scene_id, field, value}
patches against the same schema fields repair.py itself would set, never
raw HTML. That keeps the fallback path inside the same architecture
instead of quietly reopening the freeform-authorship risk we designed
around.

Finding codes below are drawn from the installed hyperframes@0.8.27
package's own source (not guessed), scoped to the ones a plan built from
our four blueprints could plausibly trigger.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from openai import OpenAI

from .schema import Plan, Scene

SELECTOR_ID_RE = re.compile(r"#([A-Za-z0-9_-]+)")


def _scene_for_finding(plan: Plan, finding: dict) -> Scene | None:
    selector = finding.get("selector") or ""
    m = SELECTOR_ID_RE.search(selector)
    if not m:
        return None
    scene_id = m.group(1)
    for s in plan.scenes:
        if s.id == scene_id:
            return s
    return None


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _fix_contrast(plan: Plan, scene: Scene, finding: dict) -> bool:
    bg = scene.background_color_override or plan.palette.background
    # Pick whichever of pure white / near-black gives the larger contrast
    # against this scene's actual background -- deterministic, no guessing.
    white_contrast = (1.0 + 0.05) / (_relative_luminance(bg) + 0.05)
    black_contrast = (_relative_luminance(bg) + 0.05) / (0.0 + 0.05)
    scene.text_color_override = "#FFFFFF" if white_contrast >= black_contrast else "#0B0B0F"
    return True


def _fix_overflow(plan: Plan, scene: Scene, finding: dict) -> bool:
    new_scale = round(max(0.2, scene.font_scale * 0.82), 3)
    if new_scale == scene.font_scale:
        return False
    scene.font_scale = new_scale
    return True


def _fix_motion(plan: Plan, scene: Scene, finding: dict) -> bool:
    if scene.motion == "none":
        return False
    scene.motion = "none"
    return True


def _fix_missing_asset(plan: Plan, scene: Scene, finding: dict) -> bool:
    if not scene.image_available:
        return False
    scene.image_available = False
    return True


# code -> handler. Handlers receive the Scene the finding's selector
# resolved to (may be None) and return True if they changed anything.
RULES: dict[str, callable] = {
    "contrast_aa_failure": _fix_contrast,
    "text_box_overflow": _fix_overflow,
    "clipped_text": _fix_overflow,
    "container_overflow": _fix_overflow,
    "canvas_overflow": _fix_overflow,
    "text_occluded": _fix_overflow,
    "content_overlap": _fix_overflow,
    "frame_out_of_frame": _fix_overflow,
    "motion_frozen": _fix_motion,
    "motion_off_frame": _fix_motion,
    "motion_appears_late": _fix_motion,
    "motion_out_of_order": _fix_motion,
    "missing_local_asset": _fix_missing_asset,
    "media_missing_src": _fix_missing_asset,
    "inaccessible_media_url": _fix_missing_asset,
}


@dataclass
class RepairOutcome:
    applied_rule_fixes: list[str]
    unhandled_findings: list[dict]
    llm_patched: bool = False


def apply_rule_based_repairs(plan: Plan, findings: list[dict]) -> RepairOutcome:
    applied: list[str] = []
    unhandled: list[dict] = []

    # Only errors block the gate (warnings/info don't flip `ok` to false --
    # confirmed against the real CLI, see PLANNING.md). Don't spend a
    # repair action on non-blocking findings.
    blocking = [f for f in findings if f.get("severity") == "error"]

    for finding in blocking:
        code = finding.get("code", "")
        handler = RULES.get(code)
        if handler is None:
            unhandled.append(finding)
            continue
        scene = _scene_for_finding(plan, finding)
        if scene is None:
            unhandled.append(finding)
            continue
        if handler(plan, scene, finding):
            applied.append(f"{code} on {scene.id}")
        else:
            unhandled.append(finding)

    return RepairOutcome(applied_rule_fixes=applied, unhandled_findings=unhandled)


PATCH_SYSTEM_PROMPT = """You are repairing a motion-graphics scene plan that \
failed automated verification. You will be given the current plan (JSON) and \
a list of verification issues that a deterministic rule set could not fix.

Respond with ONLY a JSON array of patch objects, each shaped:
{"scene_id": string, "field": "motion" | "font_scale" | "heading" | "body", \
"value": <new value, matching that field's type>}

Only patch fields listed above, only on scene ids that exist in the given \
plan, and only to address the specific issues listed. Do not add prose. If \
no fix is applicable, respond with an empty array: []
"""


def apply_llm_patch(
    plan: Plan, unhandled_findings: list[dict], client: OpenAI, model: str = "gpt-5.5"
) -> bool:
    """Scoped fallback for findings the rule table doesn't cover. Still
    constrained to the same schema fields the rule-based repairs use --
    never raw HTML -- see module docstring."""
    if not unhandled_findings:
        return False

    payload = {
        "plan": json.loads(plan.model_dump_json()),
        "issues": [
            {"code": f.get("code"), "message": f.get("message"), "selector": f.get("selector")}
            for f in unhandled_findings
        ],
    }
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": PATCH_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
        max_tokens=2000,
        temperature=0,
    )
    content = (resp.choices[0].message.content or "").strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL)
    try:
        patches = json.loads(content)
    except json.JSONDecodeError:
        return False

    scenes_by_id = {s.id: s for s in plan.scenes}
    changed = False
    allowed_fields = {"motion", "font_scale", "heading", "body"}
    for patch in patches if isinstance(patches, list) else []:
        scene = scenes_by_id.get(patch.get("scene_id"))
        field = patch.get("field")
        if scene is None or field not in allowed_fields:
            continue
        try:
            setattr(scene, field, patch["value"])
            changed = True
        except Exception:  # noqa: BLE001 - pydantic validation error on bad value
            continue

    if changed:
        # Re-validate the whole plan; if the patch produced something
        # invalid (e.g. blows the duration bound), reject it wholesale
        # rather than shipping a half-mutated plan.
        try:
            Plan.model_validate(json.loads(plan.model_dump_json()))
        except Exception:
            return False
    return changed
