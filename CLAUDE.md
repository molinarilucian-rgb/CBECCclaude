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
| `sample_patch.json` | Example patch (CEC example → Bakersfield CZ13) | 2 |
| `generate_ribd.py` | Intake + DB → XML (data-flow **demo only**, not native) | 2 |
| `qa_review.py` | Human-QA gate: list / verify / unverify library rows | 3 |
| `intake_from_csv.py` | CSV pack → `intake.json` (`templates` + `build`) | 4 |
| `intake_csv_example/` | Worked CSV pack (matches `sample_intake.json`) | 4 |
| `verify_cbecc.py` | Locate CBECC install + probe batch/CLI capability | 0 |
| `PHASE0_FINDINGS.md` | What Phase 0 found (CLI, file format, locations) | 0 |
| `run.ps1` | Wrapper: auto-find real Python, forward args to any script | — |
| `reference_files/` | Holds real `.ribd25` patch template (git-ignored) | — |

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

## CBECC install locations (this machine)
- Executable: `C:\Program Files\CBECC 2025` (`CBECC-25.exe`, `CBECC-CLI25.exe`, `CSE\CSE.exe`)
- Program library data: `…\Documents\CBECC 2025 Data`
- Projects (ships 95 `.ribd25` + 112 `.cibd25` examples): `C:\Users\y_sam\OneDrive\Documents\CBECC 2025 Projects`

## Open items (next session)
- Determine the `CBECC-CLI25.exe` primary-function keyword (check repo
  `CBECC-software/cbecc` or a Run Set; candidates: `analyze`, `-prj`, `runset`).
- Open `reference_files/Doe_patched.ribd25` in CBECC; confirm it simulates and
  produces a CF1R.
- Auto-map `intake.json` + `reference.db` → `patch.json` (close the loop).
- Decide template-selection logic (stories × CZ × foundation → which prototype).
