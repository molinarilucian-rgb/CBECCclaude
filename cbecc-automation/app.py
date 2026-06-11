#!/usr/bin/env python3
r"""
app.py — local web form for the CBECC-Res CF1R automation.

Open http://localhost:8765 in a browser:
  1. pick a prototype Template and (optionally) a saved Project profile,
  2. tweak the handful of project fields,
  3. click "Run Compliance" -> CBECC runs headless (~1 min),
  4. see PASS/FAIL + margins, download the CF1R PDF,
  5. click "I reviewed - sign off" to log the mandatory human QA gate.

Single user, local only: the server binds to 127.0.0.1. Stdlib only
(http.server + sqlite3); no web framework, no pip.

Run:
    python app.py                 # serves on 127.0.0.1:8765
    python app.py --port 9000
"""

import argparse
import datetime as _dt
import html
import json
import os
import re
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import build_patch
import parse_results
import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "templates", "registry.json")
PROFILES_DIR = os.path.join(HERE, "profiles")
RUNS_DIR = os.path.join(HERE, "runs")
DB_PATH = os.path.join(HERE, "reference.db")

# the editable project fields, in display order: (key, label, input type)
FIELDS = [
    ("name",                       "Project name",            "text"),
    ("address",                    "Address",                 "text"),
    ("city",                       "City",                    "text"),
    ("zip",                        "ZIP",                     "text"),
    ("climate_zone",               "Climate zone (1-16)",     "number"),
    ("front_orientation_deg",      "Front orientation (deg)", "number"),
    ("num_bedrooms",               "Bedrooms",                "number"),
    ("conditioned_floor_area_ft2", "Cond. floor area (ft2)",  "number"),
]
NUMERIC = {"climate_zone", "front_orientation_deg", "num_bedrooms",
           "conditioned_floor_area_ft2"}
RUN_ID_RE = re.compile(r"^\d{8}_\d{6}_[A-Za-z0-9._-]+$")


# ----------------------------------------------------------------- data helpers
def load_registry():
    with open(REGISTRY, "r", encoding="utf-8-sig") as fh:  # tolerate BOM
        return json.load(fh).get("templates", [])


def template_by_id(tid):
    for t in load_registry():
        if t.get("id") == tid:
            return t
    return None


def template_exists(t):
    path = t.get("path", "")
    if not os.path.isabs(path):
        path = os.path.join(HERE, path)
    return os.path.exists(path)


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(PROFILES_DIR)
                  if f.endswith(".json"))


def load_profile(name):
    path = os.path.join(PROFILES_DIR, name + ".json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as fh:  # tolerate BOM
        return json.load(fh)


def slug(text, default="project"):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "").strip()).strip("_")
    return s or default


def form_to_profile(form):
    """urldecoded form dict -> profile dict."""
    project = {}
    for key, _, _ in FIELDS:
        val = (form.get(key, [""])[0] or "").strip()
        if val == "":
            continue
        if key in NUMERIC:
            try:
                project[key] = int(val) if val.isdigit() else float(val)
            except ValueError:
                project[key] = val
        else:
            project[key] = val
    return {
        "template_id": (form.get("template_id", [""])[0] or "").strip(),
        "code_cycle": "2025",
        "project": project,
    }


# ----------------------------------------------------------------- QA sign-off
def record_signoff(run_id, reviewer, comments):
    """Log the human-QA sign-off. Prefer reference.db (projects + qa_reviews);
    fall back to a JSON file in the run folder if the DB is absent."""
    meta = _load_run_meta(run_id)
    project = (meta.get("profile", {}).get("project", {}) if meta else {})
    when = _dt.datetime.now().isoformat(timespec="seconds")

    if os.path.exists(DB_PATH):
        con = sqlite3.connect(DB_PATH)
        try:
            cz = project.get("climate_zone")
            cur = con.execute(
                "INSERT INTO projects (name, address, cz, code_cycle_id, status, notes)"
                " VALUES (?,?,?,?, 'qa_approved', ?)",
                (project.get("name") or run_id, project.get("address"),
                 cz if isinstance(cz, int) else None, 3,
                 f"run_id={run_id}"),
            )
            pid = cur.lastrowid
            con.execute(
                "INSERT INTO qa_reviews (project_id, reviewer, decision, comments)"
                " VALUES (?,?, 'approved', ?)",
                (pid, reviewer, comments or f"signed off {when}"),
            )
            con.commit()
        finally:
            con.close()

    # always drop a sign-off marker next to the run for an at-a-glance trail
    rd = os.path.join(RUNS_DIR, run_id)
    if os.path.isdir(rd):
        with open(os.path.join(rd, "signoff.json"), "w", encoding="utf-8") as fh:
            json.dump({"reviewer": reviewer, "comments": comments,
                       "signed_on": when}, fh, indent=2)


def _load_run_meta(run_id):
    rd = os.path.join(RUNS_DIR, run_id)
    out = {}
    for fn in ("profile.json", "signoff.json"):
        p = os.path.join(rd, fn)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                out[fn[:-5]] = json.load(fh)
    return out


def run_pdf_path(run_id):
    rd = os.path.join(RUNS_DIR, run_id, "out")
    if not os.path.isdir(rd):
        return None
    for fn in os.listdir(rd):
        if "CF1RPRF" in fn and fn.lower().endswith(".pdf"):
            return os.path.join(rd, fn)
    return None


# ----------------------------------------------------------------- HTML render
CSS = """
body{font:15px/1.5 system-ui,Segoe UI,Arial;margin:0;background:#f4f6f8;color:#1c2733}
.wrap{max-width:760px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 4px}.sub{color:#5a6b7b;margin:0 0 20px}
.card{background:#fff;border:1px solid #dde3e8;border-radius:10px;padding:20px;margin-bottom:18px}
label{display:block;font-weight:600;margin:12px 0 4px;font-size:13px}
input,select{width:100%;padding:8px 10px;border:1px solid #c4ced6;border-radius:6px;font-size:14px;box-sizing:border-box}
.row{display:flex;gap:14px}.row>div{flex:1}
.btn{display:inline-block;background:#1f6feb;color:#fff;border:0;border-radius:7px;padding:10px 18px;font-size:15px;font-weight:600;cursor:pointer;text-decoration:none}
.btn.sec{background:#5a6b7b}.btn.ghost{background:#fff;color:#1f6feb;border:1px solid #1f6feb}
.bar{display:flex;gap:10px;align-items:center;margin-top:18px;flex-wrap:wrap}
.pass{background:#e7f6ec;border:1px solid #aadcbb;color:#1a7f3c}
.fail{background:#fdecec;border:1px solid #efb4b4;color:#b42318}
.verdict{font-size:22px;font-weight:700;padding:14px 16px;border-radius:8px;margin:0 0 14px}
.warn{background:#fff7e6;border:1px solid #f0d089;color:#8a6100;padding:10px 12px;border-radius:7px;font-size:13px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:14px}td{padding:6px 8px;border-bottom:1px solid #eef1f4}
td:first-child{color:#5a6b7b;width:45%}
.msg{background:#eef4ff;border:1px solid #bcd3ff;padding:10px 12px;border-radius:7px;margin-bottom:14px;font-size:14px}
small{color:#5a6b7b}
"""


def page(title, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><div class='wrap'>{body}</div></body></html>")


def render_form(selected_id=None, profile=None, message=None):
    templates = load_registry()
    profile = profile or {}
    proj = profile.get("project", {})
    sel_tid = selected_id or profile.get("template_id") or (
        templates[0]["id"] if templates else "")

    # template options
    opts = []
    for t in templates:
        miss = "" if template_exists(t) else "  [FILE MISSING]"
        sel = " selected" if t["id"] == sel_tid else ""
        opts.append(f"<option value='{html.escape(t['id'])}'{sel}>"
                    f"{html.escape(t.get('label', t['id']))}{miss}</option>")
    # profile options
    popts = ["<option value=''>- none -</option>"]
    for p in list_profiles():
        popts.append(f"<option value='{html.escape(p)}'>{html.escape(p)}</option>")

    # warn if the chosen template's file is missing
    sel_t = template_by_id(sel_tid)
    warn = ""
    if sel_t and not template_exists(sel_t):
        warn = (f"<div class='warn'>Template file not found: "
                f"<code>{html.escape(sel_t.get('path',''))}</code>. Copy the "
                f"prototype into <code>reference_files/</code> before running.</div>")

    # editable fields
    rows = []
    for key, lbl, typ in FIELDS:
        val = proj.get(key, "")
        rows.append(
            f"<label>{html.escape(lbl)}</label>"
            f"<input name='{key}' type='{typ}' value='{html.escape(str(val))}'>")

    msg = f"<div class='msg'>{html.escape(message)}</div>" if message else ""

    body = f"""
    <h1>CBECC-Res CF1R automation</h1>
    <p class='sub'>Pick a template + profile, adjust the few project fields, run.</p>
    {msg}
    <form method='get' action='/' class='card'>
      <label>Load a saved profile</label>
      <div class='row'>
        <div><select name='profile' onchange='this.form.submit()'>{''.join(popts)}</select></div>
        <div style='flex:0 0 auto'><button class='btn ghost' type='submit'>Load</button></div>
      </div>
      <small>Loading a profile pre-fills the fields below. You can still edit them.</small>
    </form>
    <form method='post' action='/run' class='card'>
      <label>Template (prototype)</label>
      <select name='template_id'>{''.join(opts)}</select>
      {warn}
      {''.join(rows)}
      <label><input type='checkbox' name='strict' style='width:auto'> Strict (block unverified library data)</label>
      <div class='bar'>
        <button class='btn' type='submit'>Run Compliance</button>
        <span><small>CBECC runs headless; expect ~1 minute.</small></span>
      </div>
    </form>
    <form method='post' action='/profile/save' class='card'>
      <label>Save current fields as a profile</label>
      <div class='row'>
        <div><input name='profile_name' placeholder='e.g. alaniz_adu' value=''></div>
        <div style='flex:0 0 auto'><button class='btn sec' type='submit'>Save profile</button></div>
      </div>
      <small>Saved profiles live in <code>profiles/</code> for reuse on repeat jobs.</small>
      {''.join(f"<input type='hidden' name='{k}' value='{html.escape(str(proj.get(k,'')))}'>" for k,_,_ in FIELDS)}
      <input type='hidden' name='template_id' value='{html.escape(sel_tid)}'>
    </form>
    """
    return page("CBECC CF1R automation", body)


def render_result(result):
    v = result.get("verdict") or {}
    complies = v.get("complies")
    cls = "pass" if complies else "fail"
    label = ("PASS - Complies" if complies else
             "FAIL - Does Not Comply" if complies is False else
             "UNKNOWN - no verdict found")
    m = v.get("margins", {})
    mrow = ""
    if m:
        order = [("total", "Total"), ("efficiency", "Efficiency"),
                 ("source_energy", "Source energy"), ("peak_cooling", "Peak cooling")]
        mrow = "".join(f"<tr><td>Margin - {lbl}</td><td>{m[k]}</td></tr>"
                       for k, lbl in order if k in m)

    run_id = result.get("run_id", "")
    has_pdf = bool(run_pdf_path(run_id))
    dl = (f"<a class='btn' href='/download/{html.escape(run_id)}'>Download CF1R PDF</a>"
          if has_pdf else "<span><small>No CF1R PDF was produced.</small></span>")

    pv = v.get("pv_note")
    pv_row = f"<tr><td>PV note</td><td>{html.escape(pv)}</td></tr>" if pv else ""
    errs = v.get("errors") or []
    err_row = ""
    if errs:
        err_row = ("<tr><td>Errors</td><td>" +
                   "<br>".join(html.escape(e) for e in errs) + "</td></tr>")

    body = f"""
    <h1>Compliance result</h1>
    <p class='sub'>{html.escape(result.get('template_label') or '')} &middot; run {html.escape(run_id)}</p>
    <div class='card'>
      <div class='verdict {cls}'>{label}</div>
      <table>
        <tr><td>CBECC exit code</td><td>{result.get('cbecc_exit')}</td></tr>
        {mrow}{pv_row}{err_row}
        <tr><td>Result source</td><td>{html.escape(v.get('source') or 'none')}</td></tr>
      </table>
      <div class='bar'>{dl}<a class='btn ghost' href='/'>New run</a></div>
    </div>
    <form method='post' action='/signoff' class='card'>
      <h1 style='font-size:16px'>Human QA sign-off</h1>
      <p class='sub'>Required before a CF1R is treated as final. Logged to the QA audit trail.</p>
      <label>Reviewer</label>
      <input name='reviewer' placeholder='e.g. L. Molinari' required>
      <label>Comments (optional)</label>
      <input name='comments' placeholder='reviewed inputs against plans'>
      <input type='hidden' name='run_id' value='{html.escape(run_id)}'>
      <div class='bar'><button class='btn' type='submit'>I reviewed - sign off</button></div>
    </form>
    """
    return page("Compliance result", body)


# ----------------------------------------------------------------- HTTP handler
class Handler(BaseHTTPRequestHandler):
    server_version = "CBECCAuto/1.0"

    def _send(self, body, code=200, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, val in (extra or {}).items():
            self.send_header(k, val)
        self.end_headers()
        self.wfile.write(data)

    def _read_form(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8") if n else ""
        return parse_qs(raw, keep_blank_values=True)

    def log_message(self, *a):  # quieter console
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            q = parse_qs(u.query)
            pname = (q.get("profile", [""])[0] or "").strip()
            profile = load_profile(pname) if pname else None
            self._send(render_form(profile=profile))
        elif u.path.startswith("/download/"):
            run_id = u.path[len("/download/"):]
            if not RUN_ID_RE.match(run_id):
                self._send(page("Error", "<h1>Bad run id</h1>"), 400); return
            pdf = run_pdf_path(run_id)
            if not pdf:
                self._send(page("Error", "<h1>PDF not found</h1>"), 404); return
            with open(pdf, "rb") as fh:
                data = fh.read()
            fn = os.path.basename(pdf)
            self._send(data, ctype="application/pdf",
                       extra={"Content-Disposition": f'inline; filename="{fn}"'})
        else:
            self._send(page("Not found", "<h1>404</h1>"), 404)

    def do_POST(self):
        u = urlparse(self.path)
        form = self._read_form()
        if u.path == "/run":
            self._handle_run(form)
        elif u.path == "/profile/save":
            self._handle_save(form)
        elif u.path == "/signoff":
            self._handle_signoff(form)
        else:
            self._send(page("Not found", "<h1>404</h1>"), 404)

    def _handle_run(self, form):
        profile = form_to_profile(form)
        strict = bool(form.get("strict"))
        if not profile["template_id"]:
            self._send(render_form(message="Choose a template first."), 400); return
        try:
            result = pipeline.run_pipeline(
                profile, registry_path=REGISTRY, strict=strict,
                db_path=DB_PATH if os.path.exists(DB_PATH) else None)
        except build_patch.PatchError as e:
            self._send(render_form(selected_id=profile["template_id"],
                                   profile=profile,
                                   message=f"Could not run: {e}"), 400)
            return
        self._send(render_result(result))

    def _handle_save(self, form):
        profile = form_to_profile(form)
        name = slug((form.get("profile_name", [""])[0] or "").strip()
                    or profile["project"].get("name") or "profile")
        os.makedirs(PROFILES_DIR, exist_ok=True)
        with open(os.path.join(PROFILES_DIR, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(profile, fh, indent=2)
            fh.write("\n")
        self._send("", code=303, extra={"Location": f"/?profile={name}"})

    def _handle_signoff(self, form):
        run_id = (form.get("run_id", [""])[0] or "").strip()
        reviewer = (form.get("reviewer", [""])[0] or "").strip()
        comments = (form.get("comments", [""])[0] or "").strip()
        if not RUN_ID_RE.match(run_id) or not reviewer:
            self._send(page("Error", "<h1>Missing reviewer or bad run id</h1>"), 400)
            return
        record_signoff(run_id, reviewer, comments)
        body = (f"<h1>Signed off</h1><div class='card'>"
                f"<p>Run <code>{html.escape(run_id)}</code> reviewed by "
                f"<b>{html.escape(reviewer)}</b> and logged to the QA audit trail.</p>"
                f"<div class='bar'><a class='btn' href='/'>New run</a>"
                f"<a class='btn ghost' href='/download/{html.escape(run_id)}'>Download CF1R PDF</a></div></div>")
        self._send(page("Signed off", body))


def main():
    ap = argparse.ArgumentParser(description="CBECC CF1R local web app.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"CBECC CF1R automation running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
