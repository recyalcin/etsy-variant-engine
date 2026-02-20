# app.py  (FastAPI UI + run_inventory runner)
# Python 3.9 compatible
# - Script'siz çalışır: index.html <form action="/run"> server-side render eder
# - Ayrıca JSON API endpointleri de var: /api/preview, /api/run
# - Dry-run: DB write + Etsy PUT yapmadan plan/log üretir
# - Metin silinmez: form değerleri template'e geri basılır

import os
import json
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional

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
        p = subprocess.Popen(
            cmd,
            cwd=str(APP_DIR),
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


def parse_workshop_text_to_payload(workshop_text: str) -> dict:
    """
    Minimal parser for WhatsApp style text.
    Finds listing_id from:
      - Etsy edit URL (/edit/<id>)
      - "listing id: <id>" or "id: <id>"

    Parses:
      Type, Size, Color, Length, Quantity, Space, Start, Price block
    Price:
      - "Price: $82" => fixed price
      - "Gold - $82" => color_prices
      - "1 taki - $58" => prices (by qty string)
    """
    import re

    txt = (workshop_text or "").strip()
    if not txt:
        raise ValueError("Empty input.")

    listing_id = None
    m = re.search(r"/edit/(\d+)", txt)
    if m:
        listing_id = int(m.group(1))

    if listing_id is None:
        m2 = re.search(r"\b(id|listing id)\s*[:=]\s*(\d+)\b", txt, re.IGNORECASE)
        if m2:
            listing_id = int(m2.group(2))

    data = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower()
            v = v.strip()
            if k in ("type", "size", "color", "length", "quantity", "space", "start", "price", "listing id", "id"):
                data[k] = v

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

    def split_csv(v: str):
        return [x.strip() for x in (v or "").split(",") if x.strip()]

    type_name = (data.get("type") or "").strip()
    if not type_name:
        raise ValueError("Type missing.")

    size = (data.get("size") or "-").strip() or "-"
    space = (data.get("space") or "-").strip() or "-"
    start = (data.get("start") or "-").strip() or "-"

    # Colors -> default mapping for GOLD/SILVER/ROSE
    colors_list = split_csv(data.get("color", "")) if data.get("color") else []
    colors_map = {}
    for c in colors_list:
        cl = c.strip().upper()
        if cl == "GOLD":
            colors_map["G"] = "Gold"
        elif cl == "SILVER":
            colors_map["S"] = "Silver"
        elif cl in ("ROSE", "ROSE GOLD"):
            colors_map["R"] = "Rose"
        elif cl == "-":
            continue
        else:
            code = (cl[:1] or "X")
            colors_map[code] = c.strip()

    if not colors_map:
        colors_map = {"G": "Gold", "S": "Silver", "R": "Rose"}

    lengths = split_csv(data.get("length", "")) if data.get("length") else []
    quantities = split_csv(data.get("quantity", "")) if data.get("quantity") else []
    if len(quantities) == 1 and quantities[0] == "-":
        quantities = []
    if len(lengths) == 1 and lengths[0] == "-":
        lengths = []

    # ---- price block ----
    price_block = []
    in_price = False
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith("price"):
            in_price = True
            if ":" in s:
                maybe = s.split(":", 1)[1].strip()
                if maybe:
                    price_block.append(maybe)
            continue
        if in_price:
            # stop when another "Key:" starts (Type:, Size:, etc.)
            if re.match(r"^(type|size|color|length|quantity|space|start)\s*:", s, re.IGNORECASE):
                break
            price_block.append(s)

    fixed_price = None
    prices_by_qty = {}
    color_prices = {}

    for pb in price_block:
        pb2 = pb.replace(",", ".").strip()
        mfix = re.fullmatch(r"\$?\s*(\d+(\.\d+)?)", pb2)
        if mfix:
            fixed_price = float(mfix.group(1))
            break

    for pb in price_block:
        pb2 = pb.replace(",", ".")
        m3 = re.match(r"(.+?)\s*-\s*\$?\s*(\d+(\.\d+)?)", pb2)
        if not m3:
            continue
        left = m3.group(1).strip()
        val = float(m3.group(2))
        left_u = left.upper()
        if left_u in ("GOLD", "SILVER", "ROSE", "ROSE GOLD"):
            if left_u == "GOLD":
                color_prices["G"] = val
                color_prices["Gold"] = val
            elif left_u == "SILVER":
                color_prices["S"] = val
                color_prices["Silver"] = val
            else:
                color_prices["R"] = val
                color_prices["Rose"] = val
        else:
            prices_by_qty[left] = val

    payload = {
        "listing_id": listing_id,
        "type": type_name,
        "size": size,
        "space": space,
        "start": start,
        "colors": colors_map,
        "lengths_inch": lengths,
        "quantities": quantities,
        "stock": 900,
    }
    if fixed_price is not None:
        payload["price"] = fixed_price
    if prices_by_qty:
        payload["prices"] = prices_by_qty
    if color_prices:
        payload["color_prices"] = color_prices

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
    }


# --------- Script'siz server-side akış (index.html form action="/run") ---------
@app.post("/run", response_class=HTMLResponse)
async def run_page(
    request: Request,
    listing_id: int = Form(...),
    workshop_text: str = Form(...),
    dry_run: Optional[str] = Form(None),
):
    ensure_runner_exists()
    is_dry = bool(dry_run)

    # Parser listing_id'yi metinden de bulabilsin diye: metinde yoksa ekle
    wt = (workshop_text or "").strip()
    if wt and ("/edit/" not in wt) and ("listing id" not in wt.lower()) and ("id:" not in wt.lower()):
        wt = "listing id: %s\n%s" % (listing_id, wt)

    # payload üret
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

    cmd = [shutil.which("python") or "python", "-u", str(RUNNER), str(input_path)]
    if is_dry:
        cmd.append("--dry-run")

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


# --------- JSON API (istersen ileride JS ile kullanırsın) ---------
@app.post("/api/preview")
async def api_preview(workshop_text: str = Form(...), debug: Optional[bool] = Form(False)):
    ensure_runner_exists()
    try:
        payload = parse_workshop_text_to_payload(workshop_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    ts = int(time.time())
    input_path = INPUTS_DIR / "input_%s_%s.json" % (payload["listing_id"], ts)
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [shutil.which("python") or "python", "-u", str(RUNNER), str(input_path), "--dry-run"]
    if debug:
        cmd.append("--debug")

    code, out = run_cmd(cmd, timeout=300)
    return JSONResponse(
        {
            "ok": code == 0,
            "exit_code": code,
            "input_path": str(input_path),
            "payload": payload,
            "stdout": out,
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
    

    cmd = [shutil.which("python") or "python", "-u", str(RUNNER), str(input_path)]
    if debug:
        cmd.append("--debug")

    code, out = run_cmd(cmd, timeout=600)
    return JSONResponse(
        {
            "ok": code == 0,
            "exit_code": code,
            "input_path": str(input_path),
            "payload": payload,
            "stdout": out,
        }
    )
