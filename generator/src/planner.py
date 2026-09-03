"""Brief -> structured plan, via gpt-5.5.

This is the *only* place an LLM's freeform output enters the system, and
its output is never trusted directly -- it's parsed as JSON and validated
against schema.Plan (field-level) then semantic checks (model_validator
on Plan, e.g. scenes must fit the runtime). See PLANNING.md §4 for the
two distinct "model returned garbage" cases this guards against.

gpt-5.5 is a reasoning model: it spends tokens thinking before writing,
which comes out of max_tokens. We set it generously (4000) per the task
brief's own warning, since a too-low budget produces an empty reply that
looks exactly like an auth failure.
"""
from __future__ import annotations

import json
import re

from openai import OpenAI
from pydantic import ValidationError

from .schema import Plan, BLUEPRINTS, MOTIONS

MAX_PLAN_ATTEMPTS = 2
MAX_TOKENS = 4000

SYSTEM_PROMPT = f"""You are a motion-graphics producer turning a plain-language \
brief into a structured scene plan for an automated video renderer.

You must respond with ONLY a single JSON object -- no prose, no markdown \
code fences, nothing before or after it.

The JSON object has this exact shape:
{{
  "title": string,
  "aspect": "landscape" | "portrait",
  "fps": 30,
  "total_duration": number (seconds, matches what the brief asks for),
  "palette": {{"background": "#hex", "text": "#hex", "accent": "#hex"}},
  "scenes": [
    {{
      "id": string (short, unique, e.g. "s1"),
      "blueprint": one of {sorted(BLUEPRINTS)},
      "start": number (seconds from video start),
      "duration": number (seconds),
      "track_index": 0,
      "heading": string or null,
      "body": string or null,
      "image_brief": string or null (REQUIRED for blueprint "image_panel", \
a concrete visual description for an image generator -- describe the \
image itself, not text to render on it),
      "motion": one of {sorted(MOTIONS)}
    }}
  ]
}}

Rules:
- Use ONLY the blueprints listed above. Do not invent new ones.
- Scenes should be sequential and non-overlapping on the same track_index \
  (this renderer does not composite overlapping full-screen scenes).
- The last scene in the plan should almost always be "cta_end" if the \
  brief implies a call to action.
- "feature_callout" scenes are for short, punchy one-idea-per-scene beats \
  -- if the brief asks for N feature callouts, emit exactly N \
  feature_callout scenes, each with a distinct heading/body.
- Keep heading text under ~40 characters and body text under ~90 \
  characters -- this is rendered at video scale, not read as a document.
- Ensure the last scene's start + duration is close to total_duration \
  (within half a second).
- Pick a background/text color pair with strong contrast (e.g. a very \
  dark background with a near-white text color, or vice versa) -- this \
  will be checked automatically and low-contrast plans will be rejected.
"""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text


def build_plan(brief: str, client: OpenAI, model: str = "gpt-5.5") -> Plan:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": brief},
    ]

    last_error: str | None = None
    for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
        if last_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was invalid: "
                        f"{last_error}\n\nRespond again with ONLY the "
                        "corrected JSON object."
                    ),
                }
            )

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        if not content.strip():
            last_error = (
                "empty response -- if this repeats, max_tokens is likely too "
                "low for this reasoning model's thinking budget"
            )
            continue

        raw = _strip_code_fence(content)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"response was not valid JSON: {e}"
            continue

        try:
            return Plan.model_validate(data)
        except ValidationError as e:
            last_error = str(e)
            continue

    raise PlannerError(
        f"could not obtain a valid plan after {MAX_PLAN_ATTEMPTS} attempts. "
        f"Last error: {last_error}"
    )


class PlannerError(RuntimeError):
    """Raised when the model cannot produce a schema-valid, semantically
    sane plan within the attempt budget. This is the 'model returned
    something unusable' case for the planning stage -- the pipeline
    aborts before any HTML/assets/render work happens, which keeps the
    failure cheap."""
