# Template library

`registry.json` catalogs the prototype `.ribd25` files the automation can
patch. Each entry:

```json
{
  "id": "cec_cz13_2100",                 // referenced by a profile's template_id
  "label": "CEC prototype - CZ13 ...",   // shown in the web form dropdown
  "path": "reference_files/2025_CZ13_2100ft2_Prop.ribd25",  // relative to cbecc-automation/
  "code_cycle": "2025",
  "tags": { "climate_zone": 13, "stories": 1, "foundation": "slab", "size_ft2": 2100 },
  "area_targets": [                       // components that receive conditioned_floor_area_ft2
    { "type": "Zone",      "name": "<zone name>", "prop": "FloorArea" },
    { "type": "SlabFloor", "name": "<slab name>", "prop": "Area" }
  ]
}
```

Template files themselves are **git-ignored** (`reference_files/*.ribd*`) because
they can carry client data. The registry (this folder) is tracked.

## Bulk: regenerate from the shipped CEC prototypes

`build_registry.py` copies every `2025_CZ##_####ft2_Prop.ribd25` into
`reference_files/` and rebuilds this `registry.json` (reading each file's real
`ClimateZone` string + story count), preserving hand-curated entries:

```powershell
.\run.ps1 build_registry.py            # auto-detects the CBECC Projects folder
.\run.ps1 build_registry.py --dry-run  # preview without copying/writing
```

Generated entries have empty `area_targets` (project-level patching only). Fill
them by hand per template to allow floor-area override (see below).

## Adding a single prototype manually

The CBECC install ships **complete, compliant** CEC prototypes for every climate
zone at 2100 and 2700 ft2 — the best starting library:

```
…\CBECC 2025 Projects\SingleFamilyPrototypes\2025_CZ##_####ft2_Prop.ribd25
```

1. Copy the `*_Prop.ribd25` you want into `reference_files/`.
2. Add (or confirm) a `registry.json` entry pointing at it.
3. Fill `area_targets`: open the file, find the conditioned-zone block
   (`Zone   "<name>"` with `Type = "Conditioned"`) and any slab/floor blocks
   whose area should track the project's floor area, and list their exact
   component names + the area property (`FloorArea` for zones, `Area` for slabs).
   Leave `area_targets` empty to patch project-level fields only.
4. Run a smoke test: `\.run.ps1 pipeline.py --profile <a profile using this id>`.

## Climate-zone strings

`build_patch.py` maps a CZ **number** (1-16) to the exact CBECC `ClimateZone`
string (e.g. `13` -> `"CZ13  (Fresno)"`). The strings are the CEC weather-station
labels, not the jobsite city — a Bakersfield project is still `CZ13  (Fresno)`.
Use the number in profiles and let `build_patch` produce the string.
