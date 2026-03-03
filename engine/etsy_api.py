import time
import requests
from typing import Dict, Any

from .utils import require_env
from .config import ETSY_API

ETSY_TOKEN_CACHE = {"access_token": None, "expires_at": 0.0}

def refresh_access_token(debug: bool = False) -> str:
    api_key = require_env("ETSY_API_KEY")
    refresh_tok = require_env("ETSY_REFRESH_TOKEN")
    client_id = api_key.split(":", 1)[0] if ":" in api_key else api_key

    url = "https://api.etsy.com/v3/public/oauth/token"
    data = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_tok}

    r = requests.post(url, data=data, timeout=30)
    if r.status_code != 200:
        raise RuntimeError("Token refresh failed: %s" % r.text)

    token_data = r.json()
    access_token = token_data["access_token"]
    expires_in = int(token_data.get("expires_in", 3600))

    ETSY_TOKEN_CACHE["access_token"] = access_token
    ETSY_TOKEN_CACHE["expires_at"] = time.time() + expires_in - 60
    return access_token

def get_access_token() -> str:
    now = time.time()
    if (ETSY_TOKEN_CACHE["access_token"] is None) or (now >= ETSY_TOKEN_CACHE["expires_at"]):
        return refresh_access_token()
    return ETSY_TOKEN_CACHE["access_token"]

def etsy_headers() -> Dict[str, str]:
    key = require_env("ETSY_API_KEY")
    secret = require_env("ETSY_API_SECRET") if "ETSY_API_SECRET" in __import__("os").environ else ""
    x_api_key = f"{key}:{secret}" if (secret and ":" not in key) else key
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "x-api-key": x_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def etsy_request(method: str, url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 60)
    r = requests.request(method, url, headers=etsy_headers(), timeout=timeout, **kwargs)
    if r.status_code == 401:
        refresh_access_token()
        r = requests.request(method, url, headers=etsy_headers(), timeout=timeout, **kwargs)
    return r

def get_inventory(listing_id: int) -> Dict[str, Any]:
    url = f"{ETSY_API}/v3/application/listings/{listing_id}/inventory"
    r = etsy_request("GET", url, timeout=45)
    r.raise_for_status()
    return r.json()

def put_inventory_overwrite(listing_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{ETSY_API}/v3/application/listings/{listing_id}/inventory"
    r = etsy_request("PUT", url, json=payload, timeout=140)
    if not r.ok:
        raise RuntimeError(f"[ETSY][PUT][ERROR] status={r.status_code} body={r.text[:4000]}")
    return r.json()