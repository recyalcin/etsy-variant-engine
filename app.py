# app.py  (FastAPI UI + run_inventory runner)
# Python 3.9 compatible
# - Script'siz çalışır: index.html <form action="/run"> server-side render eder
# - Ayrıca JSON API endpointleri de var: /api/preview, /api/run
# - Dry-run: DB write + Etsy PUT yapmadan plan/log üretir
# - Workshop text içine gömülü JSON override bloğunu parse eder (component_overrides vs)

import os
import sys
import json
import time
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
RUNNER = APP_DIR / "run_inventory.py"
INPUTS_DIR = APP_DIR / "inputs"
INPUTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Etsy Varyant App")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def env_profile() -> str:
    return (os.getenv("DB_PROFILE") or "shiny").strip().lower()


def env_db() -> str:
    return (os.getenv("MYSQL_DB") or "").strip()


def env_write_enabled() -> str:
    return (os.getenv("WRITE_ENABLED") or "true").strip().lower()


def ensure_runner_exists():
    if not RUNNER.exists():
        raise RuntimeError("run_inventory.py not found at: %s" % RUNNER)


def run_cmd(cmd, timeout=300):
    """
    Run subprocess, capture combined output.
    returns (exit_code:int, output_text:str)
    """
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        print("[APP][run_cmd] cwd =", str(APP_DIR), flush=True)
        print("[APP][run_cmd] cmd =", cmd, flush=True)

        p = subprocess.Popen(
            cmd,
            cwd=str(APP_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        out_lines = []
        start = time.time()

        while True:
            line = p.stdout.readline() if p.stdout else ""
            if line:
                out_lines.append(line.rstrip("\n"))

            if p.poll() is not None:
                rest = p.stdout.read() if p.stdout else ""
                if rest:
                    out_lines.extend(rest.splitlines())
                break

            if time.time() - start > timeout:
                p.kill()
                out_lines.append("[APP][ERROR] Timeout reached, process killed.")
                return 124, "\n".join(out_lines)

        return int(p.returncode or 0), "\n".join(out_lines)

    except FileNotFoundError as e:
        return 127, "[APP][ERROR] File not found: %s" % e
    except Exception as e:
        return 1, "[APP][ERROR] %r" % e


def _split_csv(v: str) -> List[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _extract_json_block(text: str) -> Tuple[str, dict]:
    """
    Workshop text içindeki SON dengeli JSON bloğunu parse eder.
    Parse edemezse hata loglar ve override'sız döner.
    """
    txt = (text or "").strip()
    if not txt:
        return "", {}

    end = txt.rfind("}")
    if end == -1:
        return txt, {}

    start_candidate = None
    depth = 0

    for i in range(end, -1, -1):
        ch = txt[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                start_candidate = i
                break

    if start_candidate is None:
        return txt, {}

    prefix = txt[:start_candidate].rstrip()
    candidate = txt[start_candidate : end + 1].strip()

    try:
        overrides = json.loads(candidate)
        if isinstance(overrides, dict):
            print(
                "[APP][_extract_json_block][OK] =",
                json.dumps(overrides, ensure_ascii=False, indent=2),
                flush=True,
            )
            return prefix, overrides

        print("[APP][_extract_json_block][WARN] Parsed JSON is not an object", flush=True)
        return txt, {}

    except Exception as e:
        print("[APP][_extract_json_block][ERROR] JSON parse failed:", repr(e), flush=True)
        print("[APP][_extract_json_block][CANDIDATE] =", candidate, flush=True)
        return txt, {}


def _merge_overrides(payload: dict, overrides: dict) -> dict:
    """
    override dict içindeki bilinen anahtarları payload'a merge eder.
    """
    if not isinstance(overrides, dict) or not overrides:
        print("[APP][_merge_overrides] No overrides found", flush=True)
        return payload

    allowed = {
        "component_overrides",
        "delim_overrides",
        "display_value_overrides",
        "display_value_overrides_by_property",
        "qty_numbers",
        "readiness_state_id",
    }

    for k, v in overrides.items():
        if k in allowed:
            payload[k] = v
            print(f"[APP][_merge_overrides] merged: {k}", flush=True)
        else:
            print(f"[APP][_merge_overrides] skipped unknown key: {k}", flush=True)

    return payload


# ---------------------------
# Normalization helpers
# ---------------------------

def _norm_color_label(raw: str) -> str:
    """
    UI inputlarında GOLD/SILVER/ROSE gibi değerleri Etsy display label'a çevirir.
    """
    s = (raw or "").strip()
    if not s or s == "-":
        return ""

    u = s.upper().strip()
    if u == "GOLD":
        return "Gold"
    if u == "SILVER":
        return "Silver"
    if u in ("ROSE", "ROSE GOLD", "ROSEGOLD"):
        return "Rose"
    return s.strip()


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if not x:
            continue
        k = x.strip()
        if not k:
            continue
        kl = k.lower()
        if kl in seen:
            continue
        seen.add(kl)
        out.append(k)
    return out


def parse_workshop_text_to_payload(workshop_text: str) -> dict:
    """
    Minimal parser for WhatsApp style text.
    """
    txt_raw = (workshop_text or "").strip()
    if not txt_raw:
        raise ValueError("Empty input.")

    txt, overrides = _extract_json_block(txt_raw)

    listing_id = None
    m = re.search(r"/edit/(\d+)", txt)
    if m:
        listing_id = int(m.group(1))

    if listing_id is None:
        m2 = re.search(r"\b(id|listing id)\s*[:=]\s*(\d+)\b", txt, re.IGNORECASE)
        if m2:
            listing_id = int(m2.group(2))

    data: Dict[str, str] = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue

        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower()
            v = v.strip().rstrip(",")
            if k in (
                "type",
                "size",
                "color",
                "length",
                "quantity",
                "space",
                "start",
                "price",
                "listing id",
                "id",
                "pricing_by",
                "pricing by",
            ):
                data[k] = v

        if "pricing_by" not in data and "pricing by" not in data:
            mm = re.match(r'^\s*"?(pricing_by|pricing by)"?\s*[:=]\s*"?(.*?)"?\s*,?\s*$', line, re.IGNORECASE)
            if mm:
                data["pricing_by"] = mm.group(2).strip().rstrip(",")

    if listing_id is None and "id" in data:
        try:
            listing_id = int(re.sub(r"\D", "", data["id"]))
        except Exception:
            pass

    if listing_id is None and "listing id" in data:
        try:
            listing_id = int(re.sub(r"\D", "", data["listing id"]))
        except Exception:
            pass

    if not listing_id:
        raise ValueError("Listing ID not found. Paste Etsy edit URL or add 'listing id: ...'")

    type_name = (data.get("type") or "").strip()
    if not type_name:
        raise ValueError("Type missing.")

    size = (data.get("size") or "-").strip() or "-"
    space = (data.get("space") or "-").strip() or "-"
    start = (data.get("start") or "-").strip() or "-"

    colors_list_raw = _split_csv(data.get("color", "")) if data.get("color") else []
    colors_list = _dedupe_preserve_order(
        [_norm_color_label(c) for c in colors_list_raw if c and c.strip() != "-"]
    )
    if not colors_list:
        colors_list = ["Gold", "Silver", "Rose"]

    lengths = _split_csv(data.get("length", "")) if data.get("length") else []
    quantities = _split_csv(data.get("quantity", "")) if data.get("quantity") else []

    if len(quantities) == 1 and quantities[0] == "-":
        quantities = []
    if len(lengths) == 1 and lengths[0] == "-":
        lengths = []

    quantities = [q for q in quantities if q and q.strip() and q.strip() != "-"]
    lengths = [l for l in lengths if l and l.strip() and l.strip() != "-"]

    price_block: List[str] = []
    in_price = False
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue

        if s.lower().startswith("price"):
            in_price = True
            if ":" in s:
                maybe = s.split(":", 1)[1].strip()
                if maybe and maybe != "-":
                    price_block.append(maybe)
            continue

        if in_price:
            if re.match(
                r"^(type|size|color|length|quantity|space|start|pricing_by|pricing by)\s*:",
                s,
                re.IGNORECASE,
            ):
                break
            price_block.append(s)

    fixed_price: Optional[float] = None
    prices_by_qty: Dict[str, float] = {}
    pricing_labels: Dict[str, float] = {}

    for pb in price_block:
        pb2 = pb.replace(",", ".").strip()
        mfix = re.fullmatch(r"\$?\s*(\d+(\.\d+)?)", pb2)
        if mfix:
            fixed_price = float(mfix.group(1))
            break

    for pb in price_block:
        pb2 = pb.replace(",", ".").strip()

        # Supports:
        #   Gold - $42
        #   Gold: $42
        #   1 disc - on taraf: $39
        #   1 disc - on ve arka: $49
        m3 = re.match(r"(.+?)\s*(?::|-)\s*\$?\s*(\d+(\.\d+)?)\s*$", pb2)
        if not m3:
            continue

        left = m3.group(1).strip()
        val = float(m3.group(2))

        left_u = left.upper().strip()
        if left_u in ("GOLD", "SILVER", "ROSE", "ROSE GOLD", "ROSEGOLD"):
            label = _norm_color_label(left)
            if label:
                pricing_labels[label] = val
        else:
            prices_by_qty[left] = val

    pricing_by = (data.get("pricing_by") or data.get("pricing by") or "").strip().lower().rstrip(",").strip('"').strip("'")
    if pricing_by not in ("", "fixed", "color", "qty"):
        pricing_by = ""

    payload: Dict[str, Any] = {
        "listing_id": listing_id,
        "type": type_name,
        "size": size,
        "space": space,
        "start": start,
        "colors": colors_list,
        "lengths_inch": lengths,
        "quantities": quantities,
        # "quantity": ", ".join(quantities) if quantities else "-",
        "stock": 900,
    }

    if pricing_labels:
        allowed = {c.lower() for c in colors_list}
        payload["pricing_by"] = pricing_by or "color"
        payload["pricing"] = {
            k: float(v) for k, v in pricing_labels.items() if k.lower() in allowed
        }

    elif prices_by_qty:
        payload["pricing_by"] = pricing_by or "qty"

        qty_display_map = (
            overrides.get("display_value_overrides_by_property", {})
            .get("514", {})
            .get("qty", {})
        )

        normalized_pricing = {}
        for k, v in prices_by_qty.items():
            raw_key = str(k).strip()
            display_key = qty_display_map.get(raw_key, raw_key)
            normalized_pricing[display_key] = float(v)

        payload["pricing"] = normalized_pricing

    elif fixed_price is not None:
        payload["pricing_by"] = pricing_by or "fixed"
        payload["pricing"] = float(fixed_price)

    payload = _merge_overrides(payload, overrides)

    print(
        "[APP][PAYLOAD_AFTER_MERGE] =",
        json.dumps(payload, ensure_ascii=False, indent=2),
        flush=True,
    )
    return payload


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "profile": env_profile(),
            "mysql_db": env_db(),
            "write_enabled": env_write_enabled(),
            "form": None,
            "result": None,
        },
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "profile": env_profile(),
        "mysql_db": env_db(),
        "write_enabled": env_write_enabled(),
        "runner_exists": RUNNER.exists(),
        "python_executable": sys.executable,
        "app_dir": str(APP_DIR),
    }


@app.post("/run", response_class=HTMLResponse)
async def run_page(
    request: Request,
    listing_id: int = Form(...),
    workshop_text: str = Form(...),
    dry_run: Optional[str] = Form(None),
):
    ensure_runner_exists()
    is_dry = bool(dry_run)

    wt = (workshop_text or "").strip()
    if wt and ("/edit/" not in wt) and ("listing id" not in wt.lower()) and ("id:" not in wt.lower()):
        wt = "listing id: %s\n%s" % (listing_id, wt)

    try:
        payload = parse_workshop_text_to_payload(wt)
    except Exception as e:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "profile": env_profile(),
                "mysql_db": env_db(),
                "write_enabled": env_write_enabled(),
                "form": {"listing_id": listing_id, "workshop_text": workshop_text, "dry_run": is_dry},
                "result": {"ok": False, "error": str(e), "payload": {}, "logs": ""},
            },
            status_code=400,
        )

    ts = int(time.time())
    input_path = INPUTS_DIR / ("input_%s_%s.json" % (payload["listing_id"], ts))
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [sys.executable, "-u", str(RUNNER), str(input_path)]
    if is_dry:
        cmd.append("--dry-run")

    print("[APP] sys.executable =", sys.executable, flush=True)
    print("[APP] RUNNER =", str(RUNNER), flush=True)
    print("[APP] INPUT =", str(input_path), flush=True)
    print("[APP] INPUT_EXISTS =", input_path.exists(), flush=True)
    print("[APP] CWD =", str(APP_DIR), flush=True)
    print("[APP] CMD =", cmd, flush=True)

    code, out = run_cmd(cmd, timeout=600)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "profile": env_profile(),
            "mysql_db": env_db(),
            "write_enabled": env_write_enabled(),
            "form": {"listing_id": listing_id, "workshop_text": workshop_text, "dry_run": is_dry},
            "result": {
                "ok": code == 0,
                "error": "" if code == 0 else "Runner exit_code=%s" % code,
                "payload": payload,
                "logs": out,
            },
        },
    )


@app.post("/api/preview")
async def api_preview(workshop_text: str = Form(...), debug: Optional[bool] = Form(False)):
    ensure_runner_exists()
    try:
        payload = parse_workshop_text_to_payload(workshop_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    ts = int(time.time())
    input_path = INPUTS_DIR / ("input_%s_%s.json" % (payload["listing_id"], ts))
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [sys.executable, "-u", str(RUNNER), str(input_path), "--dry-run"]
    if debug:
        cmd.append("--debug")

    print("[APP][preview] CMD =", cmd, flush=True)
    code, out = run_cmd(cmd, timeout=300)

    return JSONResponse(
        {
            "ok": code == 0,
            "exit_code": code,
            "input_path": str(input_path),
            "payload": payload,
            "stdout": out,
            "python_executable": sys.executable,
        }
    )


@app.post("/api/run")
async def api_run(workshop_text: str = Form(...), debug: Optional[bool] = Form(False)):
    ensure_runner_exists()
    try:
        payload = parse_workshop_text_to_payload(workshop_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    ts = int(time.time())
    input_path = INPUTS_DIR / ("input_%s_%s.json" % (payload["listing_id"], ts))
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [sys.executable, "-u", str(RUNNER), str(input_path)]
    if debug:
        cmd.append("--debug")

    print("[APP][run] CMD =", cmd, flush=True)
    code, out = run_cmd(cmd, timeout=600)

    return JSONResponse(
        {
            "ok": code == 0,
            "exit_code": code,
            "input_path": str(input_path),
            "payload": payload,
            "stdout": out,
            "python_executable": sys.executable,
        }
    )