"""The structured plan contract.

This is the artifact gpt-5.5 must produce, and the only thing gpt-5.5's
output is trusted for. Everything downstream (HTML, timing, layout) is
generated deterministically by our own code from this validated plan --
see builder.py and PLANNING.md section 3 for why.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# The fixed set of scene types the Composition Builder knows how to render.
# The planner's system prompt is given exactly this list and must not
# invent others -- schema validation rejects anything outside it.
BLUEPRINTS = {
    "title_card",      # full-bleed heading, optional subheading. Openers.
    "feature_callout",  # short heading + one line of body text, one of N
                        # laid out in sequence -- "three feature callouts".
    "image_panel",      # generated image background + text overlay w/ scrim
    "cta_end",          # closing card: big CTA line + optional subtext
}

MOTIONS = {"fade_in", "slide_up", "scale_in", "none"}
ASPECTS = {"landscape", "portrait"}

RESOLUTIONS = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
}


class Palette(BaseModel):
    background: str = Field(..., description="Hex color, e.g. #0B0B12")
    text: str = Field(..., description="Hex color for primary text")
    accent: str = Field(..., description="Hex color for accents/CTA")

    @field_validator("background", "text", "accent")
    @classmethod
    def _is_hex(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("#") and len(v) in (4, 7)):
            raise ValueError(f"not a hex color: {v!r}")
        return v


class Scene(BaseModel):
    id: str
    blueprint: str
    start: float = Field(..., ge=0)
    duration: float = Field(..., gt=0)
    track_index: int = Field(0, ge=0)
    heading: Optional[str] = None
    body: Optional[str] = None
    image_brief: Optional[str] = Field(
        None, description="Prompt for gpt-image-2, required for image_panel"
    )
    motion: str = "fade_in"

    # Not set by the planner. These exist only for the repair loop to
    # adjust a single scene deterministically (contrast fix, overflow fix)
    # without touching the global palette or re-calling the model. See
    # repair.py. Kept optional/None so a fresh plan never has them.
    font_scale: float = Field(1.0, gt=0.2, le=1.5)
    text_color_override: Optional[str] = None
    background_color_override: Optional[str] = None
    image_available: bool = Field(
        True, description="Set false by the pipeline if asset generation failed"
    )

    @field_validator("blueprint")
    @classmethod
    def _known_blueprint(cls, v: str) -> str:
        if v not in BLUEPRINTS:
            raise ValueError(f"unknown blueprint {v!r}, must be one of {BLUEPRINTS}")
        return v

    @field_validator("motion")
    @classmethod
    def _known_motion(cls, v: str) -> str:
        if v not in MOTIONS:
            raise ValueError(f"unknown motion {v!r}, must be one of {MOTIONS}")
        return v

    @model_validator(mode="after")
    def _blueprint_requirements(self) -> "Scene":
        if self.blueprint == "image_panel" and not self.image_brief:
            raise ValueError("image_panel scenes require image_brief")
        if self.blueprint in ("title_card", "feature_callout", "cta_end") and not (
            self.heading or self.body
        ):
            raise ValueError(f"{self.blueprint} scenes require heading and/or body")
        return self


class Plan(BaseModel):
    title: str
    aspect: str
    fps: int = 30
    total_duration: float = Field(..., gt=0)
    palette: Palette
    scenes: list[Scene]

    @field_validator("aspect")
    @classmethod
    def _known_aspect(cls, v: str) -> str:
        if v not in ASPECTS:
            raise ValueError(f"unknown aspect {v!r}, must be one of {ASPECTS}")
        return v

    @property
    def resolution(self) -> tuple[int, int]:
        return RESOLUTIONS[self.aspect]

    @model_validator(mode="after")
    def _scenes_fit_duration(self) -> "Plan":
        if not self.scenes:
            raise ValueError("plan has no scenes")
        # Semantic check beyond field-level schema validity: does the plan
        # actually cover the requested runtime without wildly overshooting
        # it? A small tolerance (0.5s) absorbs rounding from the planner.
        latest_end = max(s.start + s.duration for s in self.scenes)
        if latest_end > self.total_duration + 0.5:
            raise ValueError(
                f"scenes extend to {latest_end}s, past total_duration "
                f"{self.total_duration}s"
            )
        ids = [s.id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scene ids in plan")
        return self
