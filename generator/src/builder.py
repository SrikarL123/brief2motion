"""Plan -> HyperFrames composition.

Matches the composition contract confirmed against a real
`hyperframes init --example blank` scaffold:

  <div id="root" data-composition-id="main" data-start="0"
       data-duration="<N>" data-width="<W>" data-height="<H>">
    ...clip elements, each class="clip" data-start data-duration
       data-track-index...
  </div>
  <script>
    window.__timelines = window.__timelines || {};
    const tl = gsap.timeline({ paused: true });
    ...tl.from(...) calls...
    window.__timelines["main"] = tl;
  </script>

Deliberately does not use Math.random anywhere in emitted JS -- the only
randomness in this system lives in Python (seed.py), applied at plan
time, never inside the rendered composition.
"""
from __future__ import annotations

from pathlib import Path

from .blueprints import render_scene
from .schema import Plan

COMPOSITION_ID = "main"


def build_composition(plan: Plan, out_dir: Path) -> Path:
    w, h = plan.resolution
    fragments: list[str] = []
    gsap_lines: list[str] = []

    for scene in sorted(plan.scenes, key=lambda s: (s.track_index, s.start)):
        html, gsap = render_scene(scene, plan.palette, w, h)
        fragments.append(html)
        if gsap:
            gsap_lines.append(gsap)

    scenes_html = "\n".join(fragments)
    gsap_html = "\n      ".join(gsap_lines)

    doc = f"""<!doctype html>
<html lang="en" data-resolution="{plan.aspect}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={w}, height={h}" />
    <title>{plan.title}</title>
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        margin: 0; width: {w}px; height: {h}px; overflow: hidden;
        background: {plan.palette.background};
      }}
      body {{ font-family: "Inter", sans-serif; }}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="{COMPOSITION_ID}"
      data-start="0"
      data-duration="{plan.total_duration}"
      data-width="{w}"
      data-height="{h}"
    >
      {scenes_html}
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {gsap_html}
      window.__timelines["{COMPOSITION_ID}"] = tl;
    </script>
  </body>
</html>
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.html"
    index_path.write_text(doc, encoding="utf-8")
    return index_path
