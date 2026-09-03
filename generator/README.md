# Brief-to-Video Generator

Turns a plain-language brief into a `check`-verified MP4 using
[HyperFrames](https://github.com/heygen-com/hyperframes), gpt-5.5 for
planning, and gpt-image-2 for imagery. See
[`PLANNING.md`](PLANNING.md) for the design rationale.

## How it works, in one paragraph

gpt-5.5 never writes HTML. It produces a structured **plan** (scenes,
timing, copy, motion intent) that's validated against a schema. A
deterministic Python builder turns that plan into a HyperFrames
composition using a fixed library of scene blueprints. `npx hyperframes
check --json` gates every composition; if it fails, the system reads the
specific findings, applies rule-based fixes (or a scoped LLM patch as
fallback) to the *plan*, rebuilds, and re-checks — up to 3 attempts —
before rendering the final MP4.

## Requirements

- Node.js >= 22, FFmpeg (same as HyperFrames itself)
- Python >= 3.10
- Network access to `hyperframes`'s Chrome-for-Testing download host and
  to the task's model gateway

## Setup (from a clean clone)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set HYPERFRAMES_API_KEY to your task API key
export $(cat .env | xargs)
```

The first `hyperframes check` run downloads a `chrome-headless-shell`
binary. If your network blocks `storage.googleapis.com`, point
HyperFrames at a local Chrome install instead:

```bash
export HYPERFRAMES_BROWSER_PATH="$(which google-chrome || which chromium)"
```

## Run it

```bash
python cli.py "a 12 second ad for a developer tool, dark theme, purple accent, three feature callouts, ends on a call to action"
```

or from one of the three example briefs:

```bash
python cli.py --brief-file briefs/dev-tool-ad.txt
python cli.py --brief-file briefs/vertical-app-teaser.txt
python cli.py --brief-file briefs/widescreen-conference-recap.txt
```

Output for each run lands in `out/<brief-hash>/`:

- `plan.json` — the structured plan gpt-5.5 produced
- `index.html` — the generated composition
- `assets/` — any gpt-image-2 imagery
- `check-output.json` — the passing `check --json` output
- `render/output.mp4` — the final video
- `failure-report.json` — only written if the pipeline gave up; contains
  the full finding history across every attempt

Re-running the exact same brief text reuses the cached plan
(`.plan-cache/`) instead of calling gpt-5.5 again, satisfying the
"same brief twice = same video" requirement without relying on model-side
determinism alone.

## Tests

Offline, no API key or network needed:

```bash
python -m tests.test_schema_and_repair
```

Covers plan-schema validation (rejects unknown blueprints, missing
required fields, scenes that overrun the runtime, duplicate ids), the
repair rule table (contrast fix picks the higher-contrast option,
overflow fix shrinks font scale, warnings are never acted on, unknown
finding codes are surfaced not silently dropped), and that identical
plans build byte-identical HTML with no `Math.random` anywhere in it.

## Known limitations (see PLANNING.md §5 for the full reasoning)

- No audio/voiceover/music.
- Four scene blueprints only (title card, feature callout, image panel,
  CTA end) — covers the three demo briefs' shapes but isn't a general
  authoring surface.
- Verified in this environment up to `hyperframes lint` (no browser
  available in the sandbox this was built in); `check`/`render` were
  validated against the real CLI's JSON schema and finding-code list by
  inspecting the installed package source, but a full render→check→repair
  cycle needs to be run in an environment with a working headless
  Chrome — do that before recording Video B.
