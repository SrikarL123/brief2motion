"""Offline tests -- no network, no API key, no hyperframes CLI required.
Run with: python -m tests.test_schema_and_repair   (from repo root)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError

from src.schema import Plan
from src.repair import apply_rule_based_repairs, _relative_luminance
from src.builder import build_composition


def _base_plan_dict():
    return {
        "title": "T",
        "aspect": "landscape",
        "total_duration": 6,
        "palette": {"background": "#000000", "text": "#FFFFFF", "accent": "#8B5CF6"},
        "scenes": [
            {
                "id": "s1",
                "blueprint": "title_card",
                "start": 0,
                "duration": 3,
                "heading": "Hello",
            },
            {
                "id": "s2",
                "blueprint": "cta_end",
                "start": 3,
                "duration": 3,
                "heading": "Go",
            },
        ],
    }


def test_valid_plan_parses():
    plan = Plan.model_validate(_base_plan_dict())
    assert plan.resolution == (1920, 1080)


def test_unknown_blueprint_rejected():
    d = _base_plan_dict()
    d["scenes"][0]["blueprint"] = "not_a_real_blueprint"
    try:
        Plan.model_validate(d)
        assert False, "expected ValidationError"
    except ValidationError:
        pass


def test_image_panel_requires_image_brief():
    d = _base_plan_dict()
    d["scenes"][0]["blueprint"] = "image_panel"
    # no image_brief set -- should fail
    try:
        Plan.model_validate(d)
        assert False, "expected ValidationError"
    except ValidationError:
        pass


def test_scenes_overrunning_duration_rejected():
    d = _base_plan_dict()
    d["scenes"][1]["duration"] = 30  # way past total_duration=6
    try:
        Plan.model_validate(d)
        assert False, "expected ValidationError"
    except ValidationError:
        pass


def test_duplicate_scene_ids_rejected():
    d = _base_plan_dict()
    d["scenes"][1]["id"] = "s1"
    try:
        Plan.model_validate(d)
        assert False, "expected ValidationError"
    except ValidationError:
        pass


def test_contrast_repair_picks_higher_contrast_option():
    plan = Plan.model_validate(_base_plan_dict())
    scene = plan.scenes[0]  # background #000000
    finding = {
        "code": "contrast_aa_failure",
        "severity": "error",
        "selector": f"#{scene.id}",
        "message": "contrast too low",
    }
    outcome = apply_rule_based_repairs(plan, [finding])
    assert outcome.applied_rule_fixes, outcome.unhandled_findings
    assert scene.text_color_override == "#FFFFFF"  # white on black is the clear winner


def test_overflow_repair_shrinks_font_scale():
    plan = Plan.model_validate(_base_plan_dict())
    scene = plan.scenes[0]
    original = scene.font_scale
    finding = {
        "code": "text_box_overflow",
        "severity": "error",
        "selector": f"#{scene.id}",
        "message": "text overflowed its box",
    }
    outcome = apply_rule_based_repairs(plan, [finding])
    assert outcome.applied_rule_fixes
    assert scene.font_scale < original


def test_warning_severity_findings_are_not_acted_on():
    plan = Plan.model_validate(_base_plan_dict())
    scene = plan.scenes[0]
    finding = {
        "code": "text_box_overflow",
        "severity": "warning",  # not "error" -- shouldn't consume a repair
        "selector": f"#{scene.id}",
    }
    outcome = apply_rule_based_repairs(plan, [finding])
    assert not outcome.applied_rule_fixes
    assert scene.font_scale == 1.0


def test_unknown_finding_code_is_unhandled_not_silently_dropped():
    plan = Plan.model_validate(_base_plan_dict())
    finding = {"code": "some_future_check_code", "severity": "error", "selector": "#s1"}
    outcome = apply_rule_based_repairs(plan, [finding])
    assert not outcome.applied_rule_fixes
    assert outcome.unhandled_findings == [finding]


def test_luminance_black_and_white_extremes():
    assert _relative_luminance("#000000") == 0.0
    assert round(_relative_luminance("#FFFFFF"), 3) == 1.0


def test_builder_produces_deterministic_html():
    plan = Plan.model_validate(_base_plan_dict())
    out1 = Path("/tmp/hf_test_1")
    out2 = Path("/tmp/hf_test_2")
    p1 = build_composition(plan, out1)
    p2 = build_composition(plan, out2)
    assert p1.read_text() == p2.read_text(), "same plan must build identical HTML"


def test_no_math_random_in_generated_composition():
    plan = Plan.model_validate(_base_plan_dict())
    out = Path("/tmp/hf_test_norandom")
    path = build_composition(plan, out)
    assert "Math.random" not in path.read_text()


if __name__ == "__main__":
    import traceback

    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_")]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(1 if failures else 0)
