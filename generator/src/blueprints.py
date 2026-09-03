"""Scene blueprints: the fixed, deterministic HTML templates the builder
fills in from validated plan data. See PLANNING.md section 3 -- this is
the load-bearing design choice that keeps the repair loop tractable: the
LLM never writes markup, it only chooses parameters that fill these slots.

Each blueprint function returns (html_fragment, gsap_tween_lines).
gsap_tween_lines are appended into the single root GSAP timeline, keyed
to the scene's own start time, matching HyperFrames' composition
contract (one #root timeline registered in window.__timelines).

Every blueprint reads scene.font_scale / *_color_override / image_available
-- these are never set by the planner (see schema.py), only by repair.py,
so a fresh plan renders identically to how the fields' defaults describe,
and a repaired plan changes only what the repair rule touched.
"""
from __future__ import annotations

from html import escape

from .schema import Scene, Palette

_MOTION_FROM = {
    "fade_in": "{opacity: 0}",
    "slide_up": "{opacity: 0, y: 48}",
    "scale_in": "{opacity: 0, scale: 0.92}",
}


def _gsap_for(scene: Scene) -> str:
    if scene.motion == "none":
        return ""
    frm = _MOTION_FROM[scene.motion]
    return (
        f'tl.from("#{scene.id}", {{...{frm}, duration: 0.6, '
        f'ease: "power2.out"}}, {scene.start});'
    )


def _wrap(scene: Scene, inner: str, extra_style: str = "") -> str:
    return (
        f'<div id="{scene.id}" class="clip" '
        f'data-start="{scene.start}" data-duration="{scene.duration}" '
        f'data-track-index="{scene.track_index}" '
        f'style="position:absolute; inset:0; {extra_style}">\n{inner}\n</div>'
    )


def _text_color(scene: Scene, palette: Palette) -> str:
    return scene.text_color_override or palette.text


def _bg_color(scene: Scene, palette: Palette) -> str:
    return scene.background_color_override or palette.background


def _px(h: int, frac: float, scene: Scene) -> int:
    return int(h * frac * scene.font_scale)


def title_card(scene: Scene, palette: Palette, w: int, h: int) -> tuple[str, str]:
    heading = escape(scene.heading or "")
    text_color = _text_color(scene, palette)
    sub = (
        f'<div style="font-size:{_px(h, 0.03, scene)}px; color:{text_color}; '
        f'opacity:0.85; margin-top:{int(h*0.02)}px;">{escape(scene.body)}</div>'
        if scene.body
        else ""
    )
    inner = f"""
      <div style="display:flex; flex-direction:column; align-items:center;
                  justify-content:center; width:100%; height:100%;
                  text-align:center; padding: 0 8%;">
        <div style="font-size:{_px(h, 0.09, scene)}px; font-weight:700;
                    color:{text_color}; line-height:1.05;">{heading}</div>
        {sub}
      </div>
    """
    bg = _bg_color(scene, palette)
    return _wrap(scene, inner, extra_style=f"background:{bg};"), _gsap_for(scene)


def feature_callout(scene: Scene, palette: Palette, w: int, h: int) -> tuple[str, str]:
    heading = escape(scene.heading or "")
    body = escape(scene.body or "")
    accent = scene.text_color_override or palette.accent
    text_color = _text_color(scene, palette)
    inner = f"""
      <div style="display:flex; flex-direction:column; justify-content:center;
                  height:100%; padding: 0 10%; gap: {int(h*0.02)}px;">
        <div style="font-size:{_px(h, 0.055, scene)}px; font-weight:700;
                    color:{accent};">{heading}</div>
        <div style="font-size:{_px(h, 0.032, scene)}px; font-weight:400;
                    color:{text_color}; max-width:80%;">{body}</div>
      </div>
    """
    bg = _bg_color(scene, palette)
    return _wrap(scene, inner, extra_style=f"background:{bg};"), _gsap_for(scene)


def image_panel(scene: Scene, palette: Palette, w: int, h: int) -> tuple[str, str]:
    heading = escape(scene.heading or "")
    body = (
        f'<div style="font-size:{_px(h, 0.028, scene)}px; color:#FFFFFF; opacity:0.92;">'
        f"{escape(scene.body)}</div>"
        if scene.body
        else ""
    )

    if scene.image_available:
        # Scrim ensures WCAG contrast regardless of image content underneath
        # -- a pre-emptive fix for contrast_aa_failure, since text over an
        # arbitrary generated photo is the riskiest contrast case we have.
        media = f'<img src="assets/{scene.id}.png" style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover;" />'
        scrim = (
            '<div style="position:absolute; inset:0; '
            "background:linear-gradient(to top, rgba(0,0,0,0.72), rgba(0,0,0,0.15) 55%);\"></div>"
        )
    else:
        # Asset generation failed -- documented degradation (PLANNING.md
        # §2): fall back to a solid palette panel instead of a broken
        # <img> that would trip missing_local_asset in the gate.
        media = ""
        scrim = f'<div style="position:absolute; inset:0; background:{palette.background};"></div>'

    inner = f"""
      {media}
      {scrim}
      <div style="position:absolute; left:0; right:0; bottom:0; padding: 6% 8%;">
        <div style="font-size:{_px(h, 0.05, scene)}px; font-weight:700; color:#FFFFFF;">{heading}</div>
        {body}
      </div>
    """
    return _wrap(scene, inner), _gsap_for(scene)


def cta_end(scene: Scene, palette: Palette, w: int, h: int) -> tuple[str, str]:
    heading = escape(scene.heading or "")
    accent = scene.text_color_override or palette.accent
    text_color = _text_color(scene, palette)
    sub = (
        f'<div style="font-size:{_px(h, 0.028, scene)}px; color:{text_color}; '
        f'opacity:0.85; margin-top:{int(h*0.015)}px;">{escape(scene.body)}</div>'
        if scene.body
        else ""
    )
    inner = f"""
      <div style="display:flex; flex-direction:column; align-items:center;
                  justify-content:center; width:100%; height:100%; text-align:center;">
        <div style="font-size:{_px(h, 0.07, scene)}px; font-weight:800;
                    color:{accent};">{heading}</div>
        {sub}
      </div>
    """
    bg = _bg_color(scene, palette)
    return _wrap(scene, inner, extra_style=f"background:{bg};"), _gsap_for(scene)


DISPATCH = {
    "title_card": title_card,
    "feature_callout": feature_callout,
    "image_panel": image_panel,
    "cta_end": cta_end,
}


def render_scene(scene: Scene, palette: Palette, w: int, h: int) -> tuple[str, str]:
    fn = DISPATCH.get(scene.blueprint)
    if fn is None:
        raise ValueError(f"no blueprint template for {scene.blueprint!r}")
    return fn(scene, palette, w, h)
