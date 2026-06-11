#!/usr/bin/env python3
r"""
build_patch.py — turn a small "project profile" into a patch.json that
ribd_patch.py can apply to a prototype .ribd25.

This is the piece that CLOSES THE LOOP: instead of hand-writing the BEMProc
keys in a patch.json, you describe a project in friendly terms (climate zone
number, address, floor area, ...) and this maps them to the exact Proj /
component keys CBECC expects.

Profile shape (all sections optional; only what changes from the template):

    {
      "template_id": "cz13_2100",          # which prototype (for the registry)
      "code_cycle": "2025",
      "project": {
        "name": "Alaniz Residence",        # used for output naming, NOT patched
        "address": "1321 Hadar Rd",
        "city": "Bakersfield",
        "zip": "93307",
        "climate_zone": 13,                 # 1..16  -> exact CBECC string
        "front_orientation_deg": 180,
        "num_bedrooms": 3,
        "conditioned_floor_area_ft2": 2100  # -> area_targets from the template
      },
      "components": [                        # optional raw passthrough
        { "type": "Zone", "name": "...", "props": { "...": ... } }
      ]
    }

The CZ number -> CBECC ClimateZone string map below is the AUTHORITATIVE set
harvested from the shipped CEC prototypes (…\CBECC 2025 Projects\
SingleFamilyPrototypes). Format is "CZ<n>  (City)" with TWO spaces and no
leading zero, e.g. "CZ5  (Santa Maria)", "CZ13  (Fresno)".

Stdlib only.
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Authoritative CA climate-zone -> exact CBECC ClimateZone string.
# Harvested from the CEC SingleFamilyPrototypes (2025_CZ##_*.ribd25).
CZ_STRINGS = {
    1:  "CZ1  (Arcata)",
    2:  "CZ2  (Santa Rosa)",
    3:  "CZ3  (Oakland)",
    4:  "CZ4  (San Jose)",
    5:  "CZ5  (Santa Maria)",
    6:  "CZ6  (Torrance)",
    7:  "CZ7  (San Diego)",
    8:  "CZ8  (Fullerton)",
    9:  "CZ9  (Burbank)",
    10: "CZ10  (Riverside)",
    11: "CZ11  (Red Bluff)",
    12: "CZ12  (Sacramento)",
    13: "CZ13  (Fresno)",
    14: "CZ14  (Palmdale)",
    15: "CZ15  (Palm Springs)",
    16: "CZ16  (Blue Canyon)",
}

# project-field -> Proj BEMProc key (string/number values only)
PROJ_FIELD_MAP = {
    "address":              "Address",
    "city":                 "City",
    "zip":                  "ZipCode",
    "front_orientation_deg": "FrontOrientation",
    "num_bedrooms":         "NumBedrooms",
}


class PatchError(Exception):
    pass


def cz_string(cz):
    """Map a CZ number (or already-formatted string) to the CBECC string."""
    if isinstance(cz, str) and cz.strip().upper().startswith("CZ"):
        return cz  # caller already gave the exact string — trust it
    try:
        n = int(cz)
    except (TypeError, ValueError):
        raise PatchError(f"climate_zone must be 1..16 (got {cz!r})")
    if n not in CZ_STRINGS:
        raise PatchError(f"climate_zone {n} out of range 1..16")
    return CZ_STRINGS[n]


def _coerce_zip(value):
    """CBECC stores ZipCode as a bare integer."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise PatchError(f"zip must be numeric (got {value!r})")


def build_patch(profile, template=None, db_path=None, strict=False):
    """Return a patch dict (the shape ribd_patch.apply_patch consumes).

    template  -- optional registry entry; its "area_targets" list
                 [{type,name,prop}, ...] receives conditioned_floor_area_ft2.
    db_path   -- optional reference.db; if given, climate_zone is cross-checked
                 against the climate_zones table (warn-only).
    strict    -- reserved for library-ref verification (no *_ref fields in the
                 thin override layer yet); kept so callers can pass it through.
    """
    project = profile.get("project", {}) or {}
    proj = {}

    # climate zone -> exact CBECC string
    if project.get("climate_zone") is not None:
        proj["ClimateZone"] = cz_string(project["climate_zone"])

    # simple project-level fields
    for field, key in PROJ_FIELD_MAP.items():
        if project.get(field) is not None:
            value = project[field]
            if field == "zip":
                value = _coerce_zip(value)
            proj[key] = value

    components = []

    # conditioned floor area -> template-declared targets (Zone FloorArea, slab Area, ...)
    area = project.get("conditioned_floor_area_ft2")
    if area is not None and template:
        for tgt in template.get("area_targets", []):
            components.append({
                "type": tgt["type"], "name": tgt["name"],
                "props": {tgt["prop"]: area},
            })

    # raw passthrough components from the profile (template-specific tweaks)
    for comp in profile.get("components", []) or []:
        components.append(comp)

    # optional sanity cross-check against the reference DB (non-fatal)
    if db_path and project.get("climate_zone") is not None and os.path.exists(db_path):
        try:
            n = int(project["climate_zone"])
            con = sqlite3.connect(db_path)
            row = con.execute(
                "SELECT representative_city FROM climate_zones WHERE cz=?", (n,)
            ).fetchone()
            con.close()
            if row and row[0] and row[0].lower() not in proj.get("ClimateZone", "").lower():
                print(f"  note: reference.db lists CZ{n} as '{row[0]}'; CBECC "
                      f"string is '{proj['ClimateZone']}'", file=sys.stderr)
        except sqlite3.Error:
            pass

    patch = {}
    if proj:
        patch["proj"] = proj
    if components:
        patch["components"] = components
    return patch


def _load_registry_entry(registry_path, template_id):
    if not template_id:
        return None
    if not registry_path or not os.path.exists(registry_path):
        raise PatchError(f"registry not found: {registry_path}")
    with open(registry_path, "r", encoding="utf-8") as fh:
        reg = json.load(fh)
    templates = reg.get("templates", reg)  # allow {"templates":[...]} or [...]
    for entry in templates:
        if entry.get("id") == template_id:
            return entry
    raise PatchError(f"template_id '{template_id}' not in registry")


def main():
    ap = argparse.ArgumentParser(description="Build a patch.json from a project profile.")
    ap.add_argument("--profile", required=True, help="profile JSON in")
    ap.add_argument("--out", required=True, help="patch JSON out")
    ap.add_argument("--registry", default=os.path.join(HERE, "templates", "registry.json"))
    ap.add_argument("--template-id", help="override profile.template_id")
    ap.add_argument("--db", default=os.path.join(HERE, "reference.db"))
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    with open(args.profile, "r", encoding="utf-8") as fh:
        profile = json.load(fh)

    template_id = args.template_id or profile.get("template_id")
    try:
        template = _load_registry_entry(args.registry, template_id)
        patch = build_patch(profile, template=template,
                            db_path=args.db, strict=args.strict)
    except PatchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(patch, fh, indent=2)
        fh.write("\n")

    n_proj = len(patch.get("proj", {}))
    n_comp = len(patch.get("components", []))
    print(f"wrote {args.out}: {n_proj} Proj value(s), {n_comp} component patch(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
