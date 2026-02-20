# profiles/silveristic.py
import re

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

def length_inch_to_code(raw: str) -> str:
    # 14" -> in14, 5" -> in50, 5.5" -> in55, 9.5" -> in95
    x = (raw or "").strip().lower()
    x = x.replace("inches", "").replace("inch", "").replace('"', '').strip()
    if not re.fullmatch(r"\d+(\.\d+)?", x):
        return ""
    v = float(x)
    if abs(v - int(v)) < 1e-9:
        n = int(v)
        if n >= 10:
            return "in%02d" % n
        return "in%02d" % (n * 10)
    if abs(v * 10 - round(v * 10)) < 1e-9:
        return "in%02d" % int(round(v * 10))
    return ""

def ring_us_to_code(raw: str) -> str:
    # 3.5 -> U035, 10.5 -> U105
    x = (raw or "").strip().lower().replace("us", "").strip()
    if not re.fullmatch(r"\d+(\.\d+)?", x):
        return ""
    v = float(x)
    code_num = int(round(v * 10))
    return "U%03d" % code_num

def inch_desc2_from_raw(raw: str) -> str:
    x = (raw or "").strip().lower().replace("inches", "").replace("inch", "").replace('"', "").strip()
    # keep as original numeric
    return f"{x} inches"

class SilveristicProfile:
    name = "silveristic"

    code_len = {
        "type": 4,
        "length": 4,
        "color": 1,
        "qty": 3,
        "size": 4,
        "start": 3,
        "space": 2,
    }

    sku_order = ["type", "length", "color", "qty", "size", "start", "space"]

    tables = {
        "i_type":   {"cols": ["code", "desc", "supplier", "catalog_code"], "code_len": 4},
        "i_color":  {"cols": ["code", "desc"], "code_len": 1},
        "i_length": {"cols": ["code", "desc", "desc2"], "code_len": 4},  # desc2 eklendi
        "i_qty":    {"cols": ["code", "desc"], "code_len": 3},           # desc2 yok
        "i_size":   {"cols": ["code", "desc"], "code_len": 4},
        "i_start":  {"cols": ["code", "desc"], "code_len": 3},
        "i_space":  {"cols": ["code", "desc"], "code_len": 2},
    }

    def sku_encode(self, type_code, length_code, color_code, qty_code, size_code, start_code, space_code) -> str:
        return f"{type_code}{length_code}{color_code}{qty_code}{size_code}{start_code}{space_code}"

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
        return False

    def is_length_has_desc2(self) -> bool:
        return True

    def length_insert_desc2(self, raw_length: str, template_has_us: bool) -> str:
        raw = (raw_length or "").strip()
        # if it is inch-ish
        if ('"' in raw) or ("inch" in raw.lower()):
            return inch_desc2_from_raw(raw)
        # if template is US and numeric -> keep numeric
        if template_has_us and re.fullmatch(r"\d+(\.\d+)?", normalize_numeric(raw)):
            return normalize_numeric(raw)
        # default same as desc
        return raw

    def resolve_length_code(self, raw_input: str, i_length_rows, template_has_us: bool, db_actions: list):
        raw = (raw_input or "").strip()
        raw_l = raw.lower()
        key = normalize_numeric(raw)

        # 1) inch intent => try inXX
        if ('"' in raw) or ("inch" in raw_l):
            code_guess = length_inch_to_code(raw)
            if code_guess:
                for r in i_length_rows:
                    if (r.get("code") or "").strip() == code_guess:
                        db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"code_guess_in"})
                        return r["code"]

        # 2) ring size intent => try Uxxx
        if template_has_us:
            code_guess = ring_us_to_code(raw)
            if code_guess:
                for r in i_length_rows:
                    if (r.get("code") or "").strip() == code_guess:
                        db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"code_guess_us"})
                        return r["code"]

        # 3) desc2 normalize match
        for r in i_length_rows:
            d2 = (r.get("desc2") or "").strip()
            if d2 and d2 != "-" and normalize_numeric(d2) == key:
                db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"desc2"})
                return r["code"]

        # 4) desc normalize match
        for r in i_length_rows:
            d = (r.get("desc") or "").strip()
            if d and d != "-" and normalize_numeric(d) == key:
                db_actions.append({"action":"EXISTS","table":"i_length","code":r["code"],"desc":r.get("desc"),"desc2":r.get("desc2"),"match":"desc"})
                return r["code"]

        return ""
