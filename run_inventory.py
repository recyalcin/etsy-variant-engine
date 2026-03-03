import os
import sys
import argparse
import json
from dotenv import load_dotenv

from engine.config import PROFILES
import engine.config as config
from engine.core import build_and_push
from engine.utils import safe_print

load_dotenv()

# Windows console utf-8 fix
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_json", help="Path to input json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--profile", default=os.environ.get("DB_PROFILE", "shiny"))
    args = ap.parse_args()

    config.DEBUG = bool(args.debug)
    config.WRITE_ENABLED = not bool(args.dry_run)

    prof_name = (args.profile or "shiny").strip().lower().lstrip("-")
    if prof_name not in PROFILES:
        raise RuntimeError("Unknown profile: %s (available: %s)" % (prof_name, ", ".join(PROFILES.keys())))
    profile = PROFILES[prof_name]

    safe_print("[BOOT] Running: %s" % os.path.abspath(__file__))
    safe_print("[BOOT] Python: %s" % sys.version)
    safe_print("[BOOT] dry_run: %s | WRITE_ENABLED: %s" % (args.dry_run, config.WRITE_ENABLED))
    safe_print("[BOOT] profile: %s" % profile.name)

    with open(args.input_json, "r", encoding="utf-8") as f:
        payload = json.load(f)

    build_and_push(profile, payload, dry_run=args.dry_run)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        safe_print("[ERROR] %r" % e)
        raise