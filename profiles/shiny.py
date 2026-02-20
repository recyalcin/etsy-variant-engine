# profiles/shiny.py
import re

ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def norm_tr(s: str) -> str:
    s = (s or "").strip().lower()
    tr_map = str.maketrans({"ı":"i","İ":"i","ş":"s","ğ":"g","ü":"u","ö":"o","ç":"c"})
    s = s.translate(tr_map)
    s = re.sub(r"\s+", " ", s)
    return s

def normalize_numeric(s: str) -> str:
    x = norm_tr(s)
    x = x.replace('"', '')
    x = x.replace("inches", "").replace("inch", "")
    x = x.replace("us", "")
    x = x.strip()
    return x

class ShinyProfile:
    name = "shiny"

    # code lengths
    code_len = {
        "type": 2,
        "color": 1,
        "qty": 2,
        "length": 2,
        "size": 1,
        "start": 2,
        "space": 1,
    }

    sku_order = ["type", "color", "qty", "length", "start", "space", "size"]

    # table schemas
    tables = {
        "i_type":   {"cols": ["code", "desc", "supplier", "desc2", "catalog_code"], "code_len": 2},
        "i_color":  {"cols": ["code", "desc", "desc2"], "code_len": 1},
        "i_length": {"cols": ["code", "desc", "desc2"], "code_len": 2},
        "i_qty":    {"cols": ["code", "desc", "desc2"], "code_len": 2},
        "i_size":   {"cols": ["code", "desc", "desc2"], "code_len": 1},
        "i_start":  {"cols": ["code", "desc", "desc2"], "code_len": 2},
        "i_space":  {"cols": ["code", "desc", "desc2"], "code_len": 1},
    }

    def sku_encode(self, type_code, length_code, color_code, qty_code, size_code, start_code, space_code) -> str:
        # shiny order: type + color + qty + length + start + space + size
        return f"{type_code}{color_code}{qty_code}{length_code}{start_code}{space_code}{size_code}"

    def sku_decode(self, sku: str):
        s = (sku or "").strip()
        out = {}
        i = 0
        for k in self.sku_order:
            ln = self.code_len[k]
            out[k] = s[i:i+ln]
            i += ln
        out["pretty"] = " ".join([f"{k}={out[k]}" for k in self.sku_order])
        return out

    def is_qty_has_desc2(self) -> bool:
        return True

    def is_length_has_desc2(self) -> bool:
        return True

    def resolve_length_code(self, raw_input: str, i_length_rows, template_has_us: bool, db_actions: list):
        raw = (raw_input or "").strip()
        key = normalize_numeric(raw)
        wants_inches = ('"' in raw) or ("inch" in norm_tr(raw))

        # 1) prefer desc2 match
        cand = []
        for r in i_length_rows:
            d2 = (r.get("desc2") or "").strip()
            if d2 and d2 != "-" and normalize_numeric(d2) == key:
                cand.append(r)

        if cand:
            # if input is plain number (like ring size) prefer plain desc2 over "X inches"
            if not wants_inches:
                for r in cand:
                    d2 = (r.get("desc2") or "").strip()
                    if re.fullmatch(r"\d+(\.\d+)?", d2):
                        db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"desc2_plain"})
                        return r["code"]
            # if input wants inches, prefer inches
            if wants_inches:
                for r in cand:
                    d2 = norm_tr(r.get("desc2") or "")
                    if "inch" in d2:
                        db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"desc2_inches"})
                        return r["code"]

            r = cand[0]
            db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"desc2_any"})
            return r["code"]

        # 2) fallback desc match
        for r in i_length_rows:
            d = (r.get("desc") or "").strip()
            if d and d != "-" and normalize_numeric(d) == key:
                db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"desc"})
                return r["code"]

        return ""
