"""Generates imagery for image_panel scenes via gpt-image-2.

Per the task brief: gpt-image-2 returns base64 in b64_json (not a URL),
takes ~30s (longer at high quality), so the client timeout is set to
180s as instructed rather than left at a library default that would
abort mid-generation.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

from openai import OpenAI

from .schema import Plan

MAX_ATTEMPTS = 2
CLIENT_TIMEOUT_S = 180


def generate_assets(plan: Plan, out_dir: Path, client: OpenAI) -> list[str]:
    """Generates one PNG per image_panel scene. Mutates plan in place:
    sets scene.image_available = False for any scene whose generation
    failed after retries, so the builder renders the documented
    solid-panel fallback instead of a broken <img> reference.

    Returns the list of scene ids that fell back (empty on full success).
    """
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    fallbacks: list[str] = []

    for scene in plan.scenes:
        if scene.blueprint != "image_panel" or not scene.image_brief:
            continue

        ok = _generate_one(client, scene.image_brief, assets_dir / f"{scene.id}.png")
        if not ok:
            scene.image_available = False
            fallbacks.append(scene.id)

    return fallbacks


def _generate_one(client: OpenAI, prompt: str, dest: Path) -> bool:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.images.generate(
                model="gpt-image-2",
                prompt=prompt,
                size="1536x1024",
                timeout=CLIENT_TIMEOUT_S,
            )
            b64 = resp.data[0].b64_json
            if not b64:
                raise ValueError("response had no b64_json payload")
            dest.write_bytes(base64.b64decode(b64))
            return True
        except Exception as e:  # noqa: BLE001 - genuinely any failure mode here
            print(f"  [assets] attempt {attempt}/{MAX_ATTEMPTS} failed for "
                  f"{dest.name}: {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)
    return False
