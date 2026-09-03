# Brief-to-Video Generator — Planning & System Design

## 1. What I understood the problem to be

The deliverable is not "call an LLM, get HTML, render it." It's a system that
can **certify its own output** against an objective, external gate
(`hyperframes check`) and **repair itself** when it fails — without a human
in the loop, deterministically, and with a bounded number of attempts before
it refuses to ship.

Three things are being graded that a naive pipeline would miss:

- **A real plan artifact.** The structured plan from gpt-5.5 has to be
  something a human can read and audit, not a prompt buried in a chain.
- **A verification loop with teeth.** It's not enough to run `check` once —
  the system has to read the *specific* issues, act on them, re-run the
  gate, and know when to give up.
- **Honest failure.** A generator that ships a broken video because it ran
  out of patience is explicitly called out as worse than one that refuses.
  That means the exit code / final report has to distinguish "succeeded,"
  "succeeded after N repairs," and "failed after cap — here is exactly why."

## 2. System design

### Components

```
brief (string)
   │
   ▼
[1] Planner            gpt-5.5 → structured plan (JSON) + plan.md (human-readable)
   │
   ▼
[2] Composition Builder  plan → HyperFrames HTML, using fixed scene blueprints
   │                     (no freeform LLM-authored HTML — see §3)
   ▼
[3] Asset Generator     gpt-image-2 → PNG assets for scenes that need imagery
   │                     composited into <img> tags referenced by the HTML
   ▼
[4] Render              `npx hyperframes render` → MP4
   │
   ▼
[5] Verify              `npx hyperframes check . --json` → {ok, issues[]}
   │
   ├─ ok: true  ──────────────────────────────► done, package outputs
   │
   └─ ok: false
        │
        ▼
   [6] Repair            classify each issue → rule-based fix if known type,
        │                 else targeted LLM patch of just the affected element
        │                 (not the whole file)
        │
        └─► back to [4], up to REPAIR_CAP attempts (default 3)
              │
              └─ cap hit ──► fail loudly: write failure-report.json with the
                              full issue history across attempts, non-zero exit
```

### Data that moves between stages, and where it can break

| Stage | Input | Output | Failure mode | Handling |
|---|---|---|---|---|
| Planner | brief text | `plan.json` (schema-validated) | gpt-5.5 returns prose instead of JSON, or a plan that's internally inconsistent (scene durations don't sum to total, text too long for stated duration) | Strict JSON-schema validation (pydantic). On failure, re-prompt once with the validator's error message appended verbatim. Cap at 2 attempts, then abort with a clear "planner could not produce a valid plan" error — this is the *model returning something unusable* case named in the brief. |
| Builder | `plan.json` | `index.html` + sub-compositions | Plan references a scene type the builder has no blueprint for | Builder validates plan against the **enum of blueprints it actually supports** before building anything. This check happens at planning time too — the planner's system prompt is given the exact blueprint list and constrained to it, so this should be rare, but the builder re-checks because prompts are not contracts. |
| Asset Generator | image briefs from plan | PNG files | gpt-image-2 times out, errors, or returns unusable bytes | Retry with backoff (2 attempts, 180s client timeout per the brief's guidance). On final failure, fall back to a deterministic solid-panel background (brand color, no image) rather than blocking the whole render — documented as a degraded-but-shippable state, logged in the final report. |
| Render | HTML + assets | MP4 | `hyperframes render` throws (missing FFmpeg, bad path, JS runtime error in composition) | Run `hyperframes lint` *before* `render` as a cheap static pre-check — catches structural mistakes (missing `data-duration`, malformed `class="clip"`) without spending a render cycle. |
| Verify | rendered composition | `{ok, issues[]}` | `check` itself errors out (not the same as `ok:false`) | Treated as an infrastructure failure, not a repairable issue — logged separately, does not consume a repair attempt. |
| Repair | issues[] | patched HTML | Issue type not in the known rule set | Falls through to LLM patch mode, scoped to only the offending element's outerHTML plus the issue text — smaller surface area than "rewrite everything," which both keeps repairs cheap and keeps failures legible when they don't converge. |

### Determinism

- Any pseudo-randomness needed for layout variation (e.g. staggered
  entrance delays across feature callouts) is seeded from a hash of the
  brief text via a small seeded PRNG (`mulberry32`), never `Math.random()`
  directly in generated compositions — this mirrors the constraint the
  framework itself enforces for its own examples.
- gpt-5.5 is called with `temperature: 0` for the planning step specifically
  because "the same brief run twice must produce the same video" is a hard
  constraint, and plan-level nondeterminism is the likeliest source of
  drift. (Model-level determinism isn't fully guaranteed by any provider,
  so the plan is cached by a hash of the brief — the *second* run of an
  identical brief reuses the cached plan rather than re-calling the model
  at all. This is belt-and-suspenders, and I say so rather than claiming
  perfect determinism I can't back up.)

## 3. Choices made, and what I rejected

**Rejected: letting gpt-5.5 author the HyperFrames HTML/GSAP directly.**
This is the obvious approach and I expect most submissions will try it. I'm
not, because it directly undermines the thing being graded hardest — the
repair loop. If the LLM free-writes the whole composition, a `check` failure
means asking the same unreliable process to patch code it may not
"remember" the structure of, with no guarantee the fix doesn't break
something else. Repairs would be a second full generation, not a targeted
fix, and two generations of the same unreliable process is not more
reliable than one.

Instead, gpt-5.5's output is constrained to a plan (scene list, timing,
copy, motion intent, image briefs) validated against a small fixed set of
scene blueprints I author and control. This trades creative range (the
video can only look like compositions of five or six known scene types)
for a system where verification failures are patchable by adjusting known
parameters — font size, color, duration, layout offset — rather than
regenerating unknown code. Given the grading weight on the verify/repair
loop (25 pts) vs. raw creative range (not scored directly), this is the
right trade for 48 hours.

**Rejected: async/parallel scene rendering.** HyperFrames renders a
composition as a whole; there's no per-scene render step to parallelize
without added complexity for no scored benefit. Sequential pipeline, kept
simple.

**Rejected: a queueing/retry framework (e.g. Celery, BullMQ).** This is a
single-shot CLI tool, not a service. A plain bounded `for` loop with a
cap is the correct amount of infrastructure; anything more is scope
gold-plating that doesn't move any of the five graded criteria.

**Orchestration language: Python**, shelling out to the `hyperframes` CLI
via `subprocess`, using the `openai` SDK pointed at the provided gateway for
both chat and image endpoints. I considered a pure Node pipeline (since
HyperFrames is npm-native) but the orchestration logic — plan validation,
repair classification, retry bookkeeping — is not framework-specific, and
subprocess calls to `npx hyperframes ...` are equally clean from either
language. Python lets me move faster given it's my stronger stack, and the
only thing that must be Node is HyperFrames itself, which runs as an
external process either way.

## 4. Handling the model returning something wrong

Three distinct "wrong" cases, handled differently on purpose:

1. **Planner returns unusable JSON** (malformed, missing fields, violates
   schema) → validate immediately, re-prompt once with the exact validator
   error, cap at 2 tries total, then abort before any code is generated.
   Cheapest possible failure — nothing downstream has run yet.
2. **Planner returns a *valid but bad* plan** (e.g. total scene duration
   doesn't match the requested video length, or references an image brief
   with no scene to place it in) → caught by a semantic validation pass
   separate from schema validation (schema-valid JSON can still be a bad
   plan). Same re-prompt-once-then-abort policy.
3. **Composition fails the `check` gate** → this is the expected, designed-
   for case, handled by the repair loop in §2, capped at `REPAIR_CAP`
   (default 3) full render→check cycles. On cap-out, the system does not
   return a video — it returns a `failure-report.json` with the brief, the
   full plan, and the issues from every attempt, and exits non-zero. A
   human can hand that report back in as a bug report.

## 5. What I will not have time to build, and why the cut is correct

- **No audio, voiceover, or music.** Nothing in the requirements asks for
  it, and HyperFrames' audio track model (mixing, ducking, sync) is a
  meaningful chunk of additional surface area to get right and verify.
  Cutting it keeps the repair loop's scope to what's actually graded
  (visual/motion/contrast checks), not audio QA that isn't part of the
  gate.
- **No web UI.** The task describes a system that takes a brief and
  produces a video — a CLI satisfies that contract exactly, and the two
  demo videos (walkthrough + live test) don't need a UI to be compelling.
  A UI is pure surface area with zero grading return.
- **No cloud/Lambda rendering.** Local rendering is sufficient for three
  briefs in 48 hours; distributed rendering solves a scaling problem I
  don't have.
- **No arbitrary scene-type extensibility beyond the blueprint set built
  for the three demo briefs.** I'm building enough blueprints to cover a
  vertical/short brief, a widescreen/ad-style brief, and a text-heavy
  brief — not a general-purpose template authoring system. Building a
  "blueprint plugin architecture" would be solving a problem I don't have
  evidence I need, at the cost of hours I don't have to spare.
- **No caching/reuse of generated images across unrelated runs.** Only the
  identical-brief-twice case is cached (needed for the determinism
  requirement). General asset caching is a nice-to-have that doesn't
  affect grading and risks stale-asset bugs I won't have time to test
  properly.

Each of these is cut because it spends hours on something outside the five
graded criteria, at the expense of the thing that's worth the most points:
a repair loop that's actually robust across three genuinely different
briefs.
