# Brief2Motion — Planning & System Design

## 1. Problem Understanding

The goal of Brief2Motion is to build an automated motion-graphics video generator using HyperFrames.

A user provides a short plain-language brief such as:

> "A 12 second ad for a developer tool, dark theme, purple accent, three feature callouts, ends on a call to action."

The system should transform that brief into a rendered MP4 without requiring a human to manually edit the composition.

The important part of the problem is not simply generating HTML. The system must reason about the brief, create an explicit production plan, generate a HyperFrames composition from that plan, generate any required imagery, verify the generated composition using HyperFrames' validation gate, repair problems when possible, and only report success when the final artifact has been successfully produced and verified.

The intended pipeline is:

```text
Plain-language brief
        ↓
GPT-5.5 planning
        ↓
Structured plan artifact
        ↓
Composition generation
        ↓
GPT-image-2 assets
        ↓
HyperFrames HTML/CSS/GSAP composition
        ↓
HyperFrames check gate
        ↓
Repair if required
        ↓
HyperFrames render
        ↓
MP4
```

The design deliberately separates planning from composition generation. This makes the model's decisions inspectable and gives the system a stable intermediate representation that can be validated before code is generated.

---

# 2. Goals

### Primary goals

1. Accept a plain-language video brief.
2. Convert the brief into a structured production plan using GPT-5.5.
3. Persist the plan as a real artifact rather than keeping it hidden inside a prompt.
4. Generate a HyperFrames composition from the plan.
5. Generate required visual assets using gpt-image-2.
6. Run the HyperFrames verification gate on every generated composition.
7. Interpret validation failures and attempt bounded repairs.
8. Refuse to report success when verification or rendering fails.
9. Make repeated runs deterministic.
10. Support different durations, scene counts, text density and aspect ratios.

### Secondary goals

* Keep the architecture small enough to understand and debug quickly.
* Make failures observable through persisted artifacts and reports.
* Keep model-generated content constrained by a schema rather than allowing arbitrary model output to directly control the renderer.

---

# 3. System Design

The implementation is organized into the following components.

```text
cli.py
  │
  ▼
pipeline.py
  │
  ├── planner.py
  │      └── GPT-5.5
  │
  ├── schema.py
  │
  ├── seed.py
  │
  ├── assets.py
  │      └── gpt-image-2
  │
  ├── builder.py
  │      └── HyperFrames composition
  │
  ├── checker.py
  │      └── HyperFrames check/render
  │
  └── repair.py
         └── GPT-assisted repair
```

## Components

### `cli.py`

The command-line entry point.

It accepts either a direct brief or a brief file:

```bash
python cli.py "A 12 second ad..."
```

or:

```bash
python cli.py --brief-file briefs/dev-tool-ad.txt
```

It also exposes configuration such as:

* output directory
* plan cache directory
* repair attempt cap
* model name

The CLI is intentionally thin. Business logic is kept inside the `src` package.

---

## `planner.py`

Responsible for turning natural language into a structured video plan.

GPT-5.5 is used for planning rather than directly generating the final HTML.

The planner determines information such as:

* duration
* aspect ratio
* scene count
* scene timing
* scene purpose
* text content
* visual direction
* motion intent
* asset requirements
* transition intent
* CTA information

The resulting plan is stored as:

```text
plan.json
```

This makes the model's reasoning output a concrete artifact that can be inspected independently of the generated composition.

---

## `schema.py`

Defines the expected structure of the generated plan.

The schema acts as a boundary between the language model and the deterministic parts of the system.

Instead of allowing arbitrary model output to directly become HTML, the pipeline first validates and normalizes the plan.

This reduces the chance that an unusable model response reaches the composition generator.

---

## `builder.py`

Converts the structured plan into a HyperFrames composition.

The builder is responsible for:

* HTML structure
* CSS styling
* scene layout
* text placement
* animation definitions
* GSAP timelines
* image placement
* composition metadata
* timing

The builder should remain deterministic for a given plan.

The important architectural choice is:

```text
Model → Plan → Builder
```

rather than:

```text
Model → arbitrary HTML
```

This makes the system easier to validate and repair.

---

## `assets.py`

Handles visual asset generation.

When a plan requires generated imagery, the system calls gpt-image-2 through the provided OpenAI-compatible gateway.

The image response is returned as base64 data.

The pipeline decodes the response and writes the image bytes to the project asset directory.

Generated assets are then referenced by the HyperFrames composition.

The system also has a degraded path for cases where an image request cannot be completed, allowing a composition to fall back to a deterministic non-image visual treatment where appropriate.

---

## `checker.py`

This is one of the most important components.

The assignment explicitly requires:

```bash
npx hyperframes check . --json
```

to be executed against every generated composition.

The checker invokes the HyperFrames gate and parses its JSON result.

The HyperFrames gate covers multiple categories including:

* lint
* runtime validation
* layout inspection
* motion checks
* contrast/accessibility checks

The pipeline treats the returned `ok` value as authoritative.

A composition is not considered verified unless:

```json
{
  "ok": true
}
```

is returned.

---

# 4. Verification and Repair Loop

The core reliability mechanism is the bounded verification/repair loop.

The intended control flow is:

```text
Generate composition
        ↓
Run HyperFrames check
        ↓
       PASS?
      /     \
    yes      no
    ↓        ↓
 render    inspect issues
             ↓
          repair
             ↓
       regenerate/check
             ↓
       attempt limit?
```

The system never silently ignores validation failures.

For every attempt, the result is recorded.

If the check fails:

1. Parse the returned JSON.
2. Extract the issues.
3. Pass the relevant issue information to the repair logic.
4. Modify/regenerate the composition.
5. Run the HyperFrames check again.
6. Stop after the configured repair cap.

The default repair cap is three attempts.

If all attempts fail, the pipeline reports failure rather than returning an unverified video.

This is important because an automated generator should fail closed rather than claim success on an invalid composition.

---

# 5. Handling Bad Model Output

A model will sometimes return an unusable response.

The system therefore assumes failure is possible at every model boundary.

## Planning failures

Possible problems include:

* invalid JSON
* missing fields
* incorrect duration
* impossible scene timing
* unsupported aspect ratio
* empty scene list
* excessive text
* malformed structure

The schema validation layer catches structural problems before composition generation.

The planner can also reject unusable responses rather than passing them downstream.

---

## Image-generation failures

Possible problems include:

* API errors
* timeout
* malformed response
* missing image data
* unusable generated asset

The asset layer handles the response explicitly.

Where appropriate, the composition can use a deterministic fallback visual rather than allowing a missing asset to produce a broken HTML reference.

---

## Composition failures

Even when the plan is valid, generated composition code can fail HyperFrames validation.

Examples include:

* elements outside the frame
* runtime JavaScript errors
* poor contrast
* layout collisions
* problematic motion
* unsupported or missing assets

These are handled through the HyperFrames check/repair loop.

---

# 6. Determinism

The requirement states that running the same brief twice should produce the same video.

The system therefore avoids uncontrolled randomness.

A stable hash of the brief is used as the basis for output/cache identity.

Planning results are cached using this identity.

Random-looking composition decisions should use a deterministic seed rather than an uncontrolled random generator.

This provides reproducibility for:

```text
same brief
    ↓
same plan
    ↓
same composition decisions
    ↓
same asset decisions where deterministic caching applies
```

Determinism is particularly important for debugging because a failure should be reproducible.

---

# 7. Aspect Ratio Handling

The system does not assume a single video format.

The briefs used during development were intentionally different:

### Brief 1

12-second developer-tool advertisement.

Characteristics:

* dark theme
* purple accent
* three feature callouts
* CTA ending

### Brief 2

9-second vertical meditation-app teaser.

Characteristics:

* vertical format
* calm/minimal visual direction
* warm tones
* sunrise hero image
* very little text
* app-name ending

### Brief 3

20-second widescreen technology-conference recap.

Characteristics:

* widescreen format
* energetic visual direction
* red/black palette
* opening title
* five talk callouts
* closing image panel
* registration CTA

The purpose of these briefs is to test whether the pipeline can respond to different structure rather than simply swapping words inside the same template.

---

# 8. Failure Modes

The major failure boundaries identified during design are:

| Failure                 | Detection           | Response                       |
| ----------------------- | ------------------- | ------------------------------ |
| Missing API key         | CLI startup         | Fail immediately               |
| Invalid plan            | Schema validation   | Reject/regenerate              |
| Image API failure       | Asset layer         | Retry/fallback where possible  |
| Invalid composition     | HyperFrames check   | Repair                         |
| Runtime browser failure | HyperFrames check   | Fail/repair                    |
| Layout issue            | HyperFrames check   | Repair                         |
| Contrast issue          | HyperFrames check   | Repair                         |
| Render failure          | Render wrapper      | Fail with report               |
| Missing MP4             | Artifact validation | Fail rather than claim success |
| Repair cap reached      | Pipeline            | Fail loudly                    |

---

# 9. Choices and Rejected Alternatives

## Choice: Explicit structured planning

I chose to make the plan a first-class artifact.

### Why

The assignment specifically evaluates how the system thinks before generating code.

A persisted plan also makes debugging easier because I can compare:

```text
brief → plan → composition
```

instead of trying to understand a large generated HTML file directly.

### Rejected alternative

Having GPT-5.5 directly generate the final HTML from the brief.

This is faster to prototype but makes the system harder to reason about and repair.

---

## Choice: Deterministic builder

The composition builder is deterministic given the plan.

### Why

This separates creative planning from mechanical rendering and makes failures reproducible.

### Rejected alternative

Allowing the model to rewrite arbitrary HTML until it "looks right."

That creates an uncontrolled loop and makes it difficult to determine why a change happened.

---

## Choice: HyperFrames as the verification authority

I use the provided HyperFrames gate rather than implementing a separate custom validator.

### Why

The assignment explicitly defines the gate as the required quality boundary.

It also combines multiple validation categories in one interface.

### Rejected alternative

Only checking that an MP4 file exists.

A file existing does not prove that the composition is valid.

---

## Choice: Bounded repair

Repairs have a hard attempt limit.

### Why

An unconstrained agent loop can spend unlimited time repeatedly modifying a composition without converging.

A cap gives predictable failure behavior.

### Rejected alternative

Retry indefinitely until the check passes.

This violates the requirement to fail loudly when the system cannot repair itself and can hide systematic problems.

---

# 10. What I Would Not Have Time to Build

Given the available development window, I prioritized the core architecture and verification mechanism over secondary features.

The following were intentionally not prioritized:

### Advanced visual templates

A large library of highly polished templates could improve visual variety, but it would not demonstrate the central engineering requirement of automatic planning, verification and repair.

### Audio generation

Voiceover, music generation and audio mixing were not necessary to prove the core brief-to-video pipeline.

### Web UI

A browser-based front end would improve usability, but the CLI already demonstrates the required automation path and leaves more time for the core pipeline.

### Cloud rendering

Local HyperFrames rendering was sufficient for the assignment. Cloud deployment would add operational complexity without improving the core demonstration.

### Large-scale asset caching

A more sophisticated content-addressed asset cache could reduce repeated image-generation costs, but it was not essential to demonstrate the architecture.

The principle was:

> Build the smallest system that demonstrates the important engineering property rather than spending the available time on peripheral polish.

---

# 11. Current Implementation Status

The core pipeline was implemented and tested against the first brief.

The following stages were successfully demonstrated:

```text
Brief ingestion                    ✓
GPT-5.5 planning                   ✓
Structured plan artifact           ✓
gpt-image-2 asset generation       ✓
HyperFrames composition            ✓
HyperFrames check                  ✓
HyperFrames check: "ok": true     ✓
Browser frame capture              ✓
360 / 360 frames captured         ✓
Encoding/assembly                  ✓
Artifact validation                ✓
Final Python MP4 handoff           ✗
Brief 2                             Not completed
Brief 3                             Not completed
```

The successful HyperFrames verification result is important:

```json
{
  "ok": true
}
```

The render log also reached:

```text
framesCompleted: 360
```

followed by:

```text
artifact validated
```

---

# 12. Remaining Render-Wrapper Issue

The remaining issue is not the HyperFrames composition validation itself.

The first brief successfully passed the HyperFrames check and the HyperFrames render pipeline progressed through frame capture, encoding, assembly and artifact validation.

The failure occurs in the Python wrapper after HyperFrames finishes.

The CLI currently reports:

```text
FAILED after 1 attempt(s):
hyperframes render exited non-zero or produced no file
```

The available render trace shows that HyperFrames captured all 360 frames and reached artifact validation, so the evidence indicates that the underlying rendering process completed its main work.

The likely issue is an output-path mismatch between the path supplied by the Python wrapper and the path HyperFrames uses relative to its project working directory.

The generated output directory shows nested output paths, indicating that a relative output path is being interpreted from the HyperFrames project directory rather than from the original CLI working directory.

Conceptually, the problem is:

```text
Python expected:

out/brief1/<hash>/render/video.mp4

but HyperFrames was invoked from:

out/brief1/<hash>/

with a relative output path that caused an additional:

out/brief1/<hash>/

to be introduced.
```

As a result, HyperFrames can complete the render while the Python wrapper fails to locate the expected MP4 and reports the overall operation as unsuccessful.

This is deliberately treated as a failure rather than being hidden.

The correct fix would be to make the render output path unambiguous, preferably by resolving the output path to an absolute path before invoking HyperFrames, or by using a project-relative output path and then checking that exact location.

---

# 13. Briefs 2 and 3

Briefs 2 and 3 were defined and included in the repository, but they were not completed within the available development window.

This is intentional rather than a claim of completion.

The first priority was to establish that the fundamental architecture worked against a real HyperFrames browser/rendering environment.

Brief 1 reached the verification and actual rendering stages, exposing the remaining wrapper-level issue.

Completing the other two briefs before resolving the first end-to-end path would have increased the number of unverified failure points.

Therefore, the decision was to stop rather than produce three superficially generated outputs without reliable verification.

---

# 14. Final Engineering Position

The main engineering objective was to demonstrate a system that does not blindly trust generated video compositions.

The architecture therefore treats:

```text
generation ≠ success
```

Instead:

```text
generation
    ↓
verification
    ↓
repair if necessary
    ↓
verification again
    ↓
render
    ↓
artifact confirmation
    ↓
success
```

This makes the system fail closed.

The current implementation demonstrates the majority of this pipeline, including a successful HyperFrames verification and a complete underlying capture/encoding pass for Brief 1.

The remaining work is primarily finishing the render-wrapper artifact handoff and then running the same pipeline against Briefs 2 and 3.
