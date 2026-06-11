#!/usr/bin/env python3
r"""
pipeline.py — the single orchestrator that turns a project profile into a CF1R.

    profile (+ template from registry)
        -> build_patch.build_patch      -> patch dict
        -> ribd_patch (apply to template).ribd25
        -> run_compliance.ps1 (CBECC headless)
        -> parse_results.parse_results   -> verdict + margins + CF1R PDF

This is the one entry point used by the web app (app.py) and usable directly
as a CLI. Each run gets its own timestamped folder under runs/.

Usage:
    python pipeline.py --profile profiles\sample_profile_alaniz.json
    python pipeline.py --profile p.json --no-run     # build patched file only
    python pipeline.py --profile p.json --json        # machine-readable result

Stdlib only.
"""

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys

import build_patch
import parse_results
import ribd_patch

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "templates", "registry.json")
RUNS_DIR = os.path.join(HERE, "runs")
RUN_COMPLIANCE = os.path.join(HERE, "run_compliance.ps1")


def _slug(text, default="project"):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "").strip()).strip("_")
    return s or default


def _resolve_template(registry_path, template_id):
    entry = build_patch._load_registry_entry(registry_path, template_id)
    if entry is None:
        raise build_patch.PatchError("profile has no template_id")
    path = entry["path"]
    if not os.path.isabs(path):
        path = os.path.join(HERE, path)
    if not os.path.exists(path):
        raise build_patch.PatchError(
            f"template file missing: {path}\n"
            f"  (copy the prototype for '{template_id}' into reference_files/)")
    return entry, path


def run_pipeline(profile, *, registry_path=REGISTRY, runs_dir=RUNS_DIR,
                 strict=False, reviewer=None, run_cbecc=True, db_path=None):
    """Run profile -> patched .ribd25 -> (optional) CBECC -> verdict.

    Returns a result dict with keys: run_id, run_dir, template_id, patched,
    patch, ran, cbecc_exit, verdict (the parse_results dict, when ran).
    Raises build_patch.PatchError for bad input/missing template.
    """
    if isinstance(profile, str):
        with open(profile, "r", encoding="utf-8") as fh:
            profile = json.load(fh)

    template_id = profile.get("template_id")
    entry, template_path = _resolve_template(registry_path, template_id)

    project = profile.get("project", {}) or {}
    name = _slug(project.get("name") or template_id)
    run_id = _dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + name
    run_dir = os.path.join(runs_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # 1) profile -> patch dict (+ persist for the audit trail)
    patch = build_patch.build_patch(profile, template=entry,
                                    db_path=db_path, strict=strict)
    patch_path = os.path.join(run_dir, "patch.json")
    with open(patch_path, "w", encoding="utf-8") as fh:
        json.dump(patch, fh, indent=2)
    with open(os.path.join(run_dir, "profile.json"), "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)

    # 2) apply patch to the template -> patched .ribd25
    # CBECC writes the CF1R report next to the MODEL INPUT, while intermediates
    # + run.log go to ProcessingPath. Put the patched file inside out/ so the
    # CF1R PDF/XML, the CSE artifacts, and the log all land in one folder.
    out_dir = os.path.join(run_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    with open(template_path, "r", encoding="utf-8", errors="replace") as fh:
        doc = ribd_patch.Ribd(fh.read())
    ribd_patch.apply_patch(doc, patch)
    patched = os.path.join(out_dir, name + ".ribd25")
    with open(patched, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(doc.text())

    result = {
        "run_id": run_id,
        "run_dir": run_dir,
        "template_id": template_id,
        "template_label": entry.get("label"),
        "patched": patched,
        "patch": patch,
        "ran": False,
        "cbecc_exit": None,
        "verdict": None,
    }
    if not run_cbecc:
        return result

    # 3) CBECC headless via run_compliance.ps1 (CF1R + log land in out_dir)
    proc = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", RUN_COMPLIANCE,
         "-ModelInput", patched, "-OutDir", out_dir],
        capture_output=True, text=True,
    )
    result["ran"] = True
    result["cbecc_exit"] = proc.returncode
    with open(os.path.join(run_dir, "pipeline.log"), "w", encoding="utf-8") as fh:
        fh.write(proc.stdout or "")
        fh.write("\n--- stderr ---\n")
        fh.write(proc.stderr or "")

    # 4) parse the verdict out of the CBECC output folder
    result["verdict"] = parse_results.parse_results(out_dir)
    return result


def main():
    ap = argparse.ArgumentParser(description="Profile -> CF1R pipeline.")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--db", default=os.path.join(HERE, "reference.db"))
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--no-run", action="store_true", help="build patched file only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        result = run_pipeline(args.profile, registry_path=args.registry,
                              strict=args.strict, run_cbecc=not args.no_run,
                              db_path=args.db if os.path.exists(args.db) else None)
    except build_patch.PatchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"run_id   : {result['run_id']}")
    print(f"template : {result['template_label']} ({result['template_id']})")
    print(f"patched  : {result['patched']}")
    if not result["ran"]:
        print("(--no-run: skipped CBECC)")
        return 0
    print(f"cbecc    : exit {result['cbecc_exit']}")
    print()
    print(parse_results.pretty(result["verdict"]))
    return 0 if (result["verdict"] and result["verdict"]["complies"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
