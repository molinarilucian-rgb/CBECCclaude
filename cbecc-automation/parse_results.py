#!/usr/bin/env python3
r"""
parse_results.py — read a CBECC headless run's output into a clean verdict.

Given a run/output directory (the "<model>_run" folder run_compliance.ps1
writes), this finds the CF1R-PRF result XML and extracts:

  - complies      : bool   (overall pass/fail)
  - result_text   : str    ("Complies" / "Does Not Comply")
  - margins       : dict   (LSC efficiency / total / source-energy / peak-cooling)
  - pv_note       : str    (Standard Design PV capacity note, if present)
  - errors        : list   (any ERROR lines scraped from run.log)
  - cf1r_pdf      : str    (path to the CF1R PDF, if produced)

The CF1R XML uses a default namespace, so we match elements by LOCAL name
(tag after the '}') to stay namespace-agnostic. Falls back to run.log's
"Analysis result:" line when the XML is missing.

Stdlib only.

Usage:
    python parse_results.py <run_dir>
    python parse_results.py <run_dir> --json
"""

import argparse
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET

# local-name -> our key, for the compliance-margin block
MARGIN_TAGS = {
    "Lsc02_LSC_MarginEfficiency":   "efficiency",
    "Lsc03_LSC_MarginTotal":        "total",
    "Lsc04_LSC_MarginSourceEnergy": "source_energy",
    "Lsc05_LSC_MarginPeakCooling":  "peak_cooling",
}


def _local(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_text(root, local_name):
    for el in root.iter():
        if _local(el.tag) == local_name:
            return (el.text or "").strip()
    return None


def _find_cf1r_xml(run_dir):
    hits = glob.glob(os.path.join(run_dir, "*CF1RPRF01E.xml"))
    # prefer the plain result XML over -BEES.xml or AnalysisResults.xml
    hits = [h for h in hits if "BEES" not in os.path.basename(h)]
    return hits[0] if hits else None


def _find_cf1r_pdf(run_dir):
    hits = glob.glob(os.path.join(run_dir, "*CF1RPRF*.pdf"))
    return hits[0] if hits else None


def _scrape_log(run_dir):
    """Return (result_line, [error lines]) from run.log if present."""
    log = os.path.join(run_dir, "run.log")
    result_line, errors = None, []
    if not os.path.exists(log):
        return result_line, errors
    with open(log, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if "Analysis result:" in s and result_line is None:
                result_line = s
            # the PEM/SignXML line is benign — don't report it as an error
            if s.startswith("ERROR:") and "SignXML" not in s and "PEM_read_bio" not in s:
                errors.append(s)
    return result_line, errors


def parse_results(run_dir):
    result = {
        "run_dir": run_dir,
        "complies": None,
        "result_text": None,
        "margins": {},
        "pv_note": None,
        "errors": [],
        "cf1r_pdf": None,
        "cf1r_xml": None,
        "source": None,
    }

    log_result, log_errors = _scrape_log(run_dir)
    result["errors"] = log_errors
    result["cf1r_pdf"] = _find_cf1r_pdf(run_dir)

    xml_path = _find_cf1r_xml(run_dir)
    if xml_path:
        result["cf1r_xml"] = xml_path
        try:
            root = ET.parse(xml_path).getroot()
            c01 = _find_text(root, "C01_ResidentialPerformanceComplianceResult")
            lsc = _find_text(root, "LscResults_ComplianceResultLSC")
            if c01 is not None:
                result["complies"] = (c01.strip().lower() == "true")
            if lsc:
                result["result_text"] = lsc
                if result["complies"] is None:
                    result["complies"] = ("not" not in lsc.lower())
            for tag, key in MARGIN_TAGS.items():
                v = _find_text(root, tag)
                if v not in (None, ""):
                    try:
                        result["margins"][key] = float(v)
                    except ValueError:
                        result["margins"][key] = v
            pv = _find_text(root, "LscResultNotes_LSC_ComplianceNotes")
            if pv:
                result["pv_note"] = pv
            result["source"] = "cf1r_xml"
        except ET.ParseError as e:
            result["errors"].append(f"XML parse error: {e}")

    # fall back to the log verdict if the XML didn't yield one
    if result["complies"] is None and log_result:
        result["result_text"] = log_result
        result["complies"] = ("FAIL" not in log_result.upper())
        result["source"] = "run.log"

    return result


def pretty(result):
    lines = []
    if result["complies"] is True:
        verdict = "PASS - Complies"
    elif result["complies"] is False:
        verdict = "FAIL - Does Not Comply"
    else:
        verdict = "UNKNOWN (no verdict found)"
    lines.append(f"Verdict : {verdict}")
    if result.get("result_text"):
        lines.append(f"Result  : {result['result_text']}")
    m = result.get("margins", {})
    if m:
        parts = []
        if "total" in m:         parts.append(f"total {m['total']}")
        if "efficiency" in m:    parts.append(f"efficiency {m['efficiency']}")
        if "source_energy" in m: parts.append(f"source {m['source_energy']}")
        if "peak_cooling" in m:  parts.append(f"peak-cooling {m['peak_cooling']}")
        lines.append("Margins : " + ", ".join(parts))
    if result.get("pv_note"):
        lines.append(f"PV note : {result['pv_note']}")
    if result.get("cf1r_pdf"):
        lines.append(f"CF1R PDF: {result['cf1r_pdf']}")
    if result.get("errors"):
        lines.append("Errors  :")
        lines.extend(f"  - {e}" for e in result["errors"])
    lines.append(f"(source: {result.get('source') or 'none'})")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Parse a CBECC run dir into a verdict.")
    ap.add_argument("run_dir")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()

    if not os.path.isdir(args.run_dir):
        print(f"ERROR: not a directory: {args.run_dir}", file=sys.stderr)
        return 2

    result = parse_results(args.run_dir)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(pretty(result))
    # exit 0 on pass, 1 on fail/unknown — handy for scripting
    return 0 if result["complies"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
