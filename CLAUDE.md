# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

**This repo's active focus is `cbecc-automation/`.** Other top-level items
(`lead_tracker.html`, `alpaca.js`, `perplexity.js`, `orb-bot/`, `tictactoe.html`,
`Campaign Scripts/`) are unrelated and out of scope — do not modify them unless
explicitly asked. All guidance below refers to `cbecc-automation/`.

## Git workflow

**Commit and push to GitHub continuously as work progresses — do not wait until the end of a session.**

After completing any meaningful unit of work, immediately run:

```
git add <changed files>
git commit -m "short, imperative description of what changed"
git push
```

Rules:
- Commit after **every** logical change: feature added, bug fixed, file created, config updated.
- Push immediately after every commit — never let commits sit unpushed.
- Never batch unrelated changes into one commit.
- Use imperative present-tense messages: `"Add patch validator"`, `"Fix code-cycle check"`, not `"Added"` or `"Fixed stuff"`.
- Never end a session without a clean, fully pushed state — no uncommitted edits, no unpushed commits.

## What this project is

A phased system to cut residential **Title 24 (CF1R)** report production from
several hours to **under ~30 minutes** for repeat-type projects, without
compromising accuracy or code compliance. CBECC-Res first (`.ribd25` →
CF1R-PRF), architected so CBECC-Com (`.cibd25` → NRCC) can be added later.

- **Platform:** Windows (CBECC's native OS). **Volume:** ~20 reports/month.
- **Code cycle:** **2025** is in effect (as of 2026-01-01).

### Three hard rules the design obeys
1. **No GUI automation.** Modify the project input file directly and invoke the
   CBECC engine in batch. No screen-clicking.
2. **Code-cycle tagging everywhere.** Every reference-DB row carries a
   `code_cycle_id`; the tooling refuses to mix cycles.
3. **Human-QA gate is mandatory.** No straight-through automation into a
   permit-bound CF1R. A person signs off (`--strict` blocks unverified data).

## Critical design fact (Phase 0)

A real `.ribd25` is **BEMProc indented text, NOT XML.** See
[`cbecc-automation/PHASE0_FINDINGS.md`](cbecc-automation/PHASE0_FINDINGS.md).

- The native path is **template-and-patch**: pick the closest CBECC-valid
  example `.ribd25` and overwrite only project-specific values
  (`ribd_patch.py`, verified against a real file).
- `generate_ribd.py` emits XML and is a **data-flow demo only** — it does NOT
  produce a file CBECC opens. Don't treat it as the native serializer.
- Headless execution is feasible via `CBECC-CLI25.exe` (exact primary-function
  keyword still an open item) or native Batch Run Set CSVs.

### `.ribd25` text format (when editing/patching)
- Component header at **column 0**: `Type   "Name"`.
- Properties indented 3 spaces: `   Key = value` (strings quoted, numbers bare).
- Arrays: `   Key = ( a, b, c )`; indexed: `   Key[1] = v`.
- Each component closes with a line that is exactly `   ..`.
- Components are a **flat, ordered list**; containment is by document order +
  name references, not by nesting.

## Architecture

```
INTAKE (spreadsheet/CSV → intake.json; or Phase 5 PDF → proposed intake.json)
   │
   ▼
REFERENCE DB (SQLite, enter-once-reuse, every row code-cycle tagged + verified)
   │              ◄── HUMAN QA GATE (reviewer confirms; status → qa_approved)
   ▼
TEMPLATE + PATCH (ribd_patch.py: patch closest example .ribd25 BEMProc text)
   │
   ▼
CBECC BATCH RUN (CBECC-CLI25.exe / native Run Set CSV → CSE simulation)
   │
   ▼
OUTPUT: CF1R-PRF (PDF) + pass/fail + margin
```

The reference DB is the center of value: data entered once, QA'd once, reused
across every report — most of the time savings come from here, independent of AI.

## Key files (`cbecc-automation/`)

| File | Purpose | Phase |
|---|---|---|
| `schema.sql` | Reference DB schema (SQLite), code-cycle tagged, QA audit columns | 1 |
| `init_db.py` | Create + seed `reference.db` | 1 |
| `intake_schema.json` | Intake form contract (JSON Schema 2020-12) | 2 |
| `sample_intake.json` | Worked example intake | 2 |
| `ribd_patch.py` | **Native path:** patch a real `.ribd25` BEMProc template | 2 |
| `sample_patch.json` | Example patch (CEC example → CZ13) | 2 |
| `build_patch.py` | **Closes the loop:** project profile → `patch.json` (CZ#→exact CBECC string, forces CF1R PDF/XML output) | 2 |
| `parse_results.py` | CBECC output → verdict (PASS/FAIL + LSC margins + CF1R PDF), namespace-agnostic XML w/ `run.log` fallback | 2 |
| `pipeline.py` | **Orchestrator:** profile → build_patch → ribd_patch → run_compliance → parse_results (one `runs/<id>/` per run) | 2 |
| `app.py` | **Local web app** (127.0.0.1:8765): form → run → verdict + CF1R download + QA sign-off | 2 |
| `start_app.ps1` | Double-click launcher for `app.py` (finds Python, opens browser) | — |
| `templates/registry.json` | Catalog of prototype `.ribd25` files (archetype tags + `area_targets`) | 2 |
| `templates/README.md` | How to add a prototype + the CZ#→string note | 2 |
| `profiles/` | Saved per-project override profiles (enter-once-reuse) | 2 |
| `generate_ribd.py` | Intake + DB → XML (data-flow **demo only**, not native) | 2 |
| `qa_review.py` | Human-QA gate: list / verify / unverify library rows | 3 |
| `intake_from_csv.py` | CSV pack → `intake.json` (`templates` + `build`) | 4 |
| `intake_csv_example/` | Worked CSV pack (matches `sample_intake.json`) | 4 |
| `verify_cbecc.py` | Locate CBECC install + probe batch/CLI capability | 0 |
| `run_compliance.ps1` | Headless CBECC `-Compliance` run → CF1R PDF/XML + verdict | 0 |
| `PHASE0_FINDINGS.md` | What Phase 0 found (CLI, file format, locations) | 0 |
| `run.ps1` | Wrapper: auto-find real Python, forward args to any script | — |
| `reference_files/` | Holds real `.ribd25` templates incl. CEC prototypes (git-ignored) | — |

## Running the project

Python 3.12 is installed. The scripts use **only the standard library** — no
`pip install` needed. `python` on PATH may be the Windows Store stub, so prefer
the `run.ps1` wrapper (auto-finds the real Python and forwards args). All
commands run from inside `cbecc-automation/`.

```powershell
.\run.ps1 init_db.py                                  # create + seed reference.db
.\run.ps1 qa_review.py list                           # see unverified library rows
.\run.ps1 qa_review.py verify-all --by "L. Molinari"  # human sign-off
.\run.ps1 generate_ribd.py --intake sample_intake.json --out Doe.ribd --strict

# Spreadsheet path: fill CSV pack, convert, generate
.\run.ps1 intake_from_csv.py templates ./my_project_csv
.\run.ps1 intake_from_csv.py build ./intake_csv_example --out intake.json

# Phase 0: locate CBECC + probe batch mode
.\run.ps1 verify_cbecc.py --probe
```

(If scripts are blocked: `powershell -ExecutionPolicy Bypass -File .\run.ps1 ...`)

## Run it daily (the closed loop)

The end-to-end loop is wired and verified: **profile → CF1R PDF + PASS/FAIL**.

```powershell
# Daily, GUI-free: double-click start_app.ps1 (or run it), browser opens to
# http://localhost:8765 — pick a template + profile, edit a few fields, Run,
# see the verdict, download the CF1R PDF, and sign off (logs to qa_reviews).
.\start_app.ps1

# Same loop headless / scriptable:
.\run.ps1 pipeline.py --profile profiles\sample_profile_cz13.json
.\run.ps1 pipeline.py --profile p.json --no-run   # build patched .ribd25 only
```

- Templates: prefer the shipped CEC prototypes (complete + compliant) in
  `…\CBECC 2025 Projects\SingleFamilyPrototypes\2025_CZ##_####ft2_Prop.ribd25`;
  copy into `reference_files/` and register in `templates/registry.json`.
- **CZ gotcha:** CBECC's CZ13 string is `"CZ13  (Fresno)"` (weather station),
  not Bakersfield. `build_patch.py` holds the authoritative CZ#→string map.
- Each run lands in `runs/<timestamp>_<name>/` (git-ignored): `patch.json`,
  `profile.json`, the patched `.ribd25`, and `out/` with the CF1R + CSE artifacts.

## CBECC install locations (this machine)
- Executable: `C:\Program Files\CBECC 2025` (`CBECC-25.exe`, `CBECC-CLI25.exe`, `CSE\CSE.exe`)
- Program library data: `…\Documents\CBECC 2025 Data`
- Projects (ships 95 `.ribd25` + 112 `.cibd25` examples): `C:\Users\y_sam\OneDrive\Documents\CBECC 2025 Projects`

## Status / open items

**Closed:** CLI keyword (`-Compliance`, see `run_compliance.ps1`); loop closed
(`build_patch.py` → `pipeline.py`); end-to-end verified on the CEC CZ13
prototype (CBECC exit 0, PASS, CF1R PDF produced, sign-off logged); daily access
shipped as a local web app (`app.py`).

**Open (next session):**
- Build the template library: copy more CEC prototypes (2700 ft2, 2-story, ADU,
  other CZs) into `reference_files/` and register them with `area_targets`.
- Template auto-suggest: pick a prototype from project tags (stories × CZ ×
  foundation × size) instead of manual selection.
- Richer overrides: drive HVAC/window/PV deltas from `reference.db` library rows
  through `build_patch` (currently project-level fields + raw component
  passthrough); wire `--strict` verified-row enforcement to those refs.
- Background-run UX: `/run` blocks ~1 min synchronously; consider a progress page.
- Confirm Alaniz file's climate zone (file says CZ16; Bakersfield is CZ13).
