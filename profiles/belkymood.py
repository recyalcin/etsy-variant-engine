# profiles/belkymood.py
# BelkyMood profile (shiny-like) with explicit SKU order:
#   type - color - qty - length - start - space - size
#
# Notes:
# - belkymood DB color codes are numeric (0/1/2/...) but SKU segment length is still 1.
# - desc2 exists for i_color/i_length/i_qty (you added it) and can be used for Etsy labels / aliases.
# - This profile is "debug & log friendly": it appends structured events into db_actions/log list.

import re
import html

ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def norm_tr(s: str) -> str:
    s = (s or "").strip().lower()
    tr_map = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})
    s = s.translate(tr_map)
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_numeric(s: str) -> str:
    """
    Normalize measurement-ish strings to compare tokens:
    - Unescape HTML
    - Normalize curly quotes to "
    - Remove inches / inch / cm / us tokens
    - Remove "
    """
    x = norm_tr(html.unescape(s or ""))
    x = x.replace("″", '"').replace("”", '"').replace("“", '"')
    x = x.replace('"', "")
    x = x.replace("inches", "").replace("inch", "")
    x = x.replace("cm", "")
    x = x.replace("us", "")
    x = x.strip()
    return x


def _is_plain_number(x: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)?", (x or "").strip()))


class BelkyMoodProfile:
    name = "belkymood"

    # --- SKU format requested by you ---
    sku_order = ["type", "color", "qty", "length", "start", "space", "size"]

    # code lengths (based on your belkymood DB)
    code_len = {
        "type": 2,    # e.g. 10
        "color": 1,   # e.g. 0/1/2
        "qty": 2,     # e.g. 01/02
        "length": 2,  # e.g. 14 / XX
        "start": 2,   # e.g. 00/01/08
        "space": 1,   # e.g. 0/1/2
        "size": 1,    # e.g. 0/4/5/6
    }

    # table schemas (what columns exist). You said desc2 exists for i_color/i_length/i_qty now.
    # i_type has extra columns in your DB; keep them here for documentation/validation if you want.
    tables = {
        "i_type":   {"cols": ["code", "desc", "supplier", "code_spare", "catalog_code"], "code_len": 2},
        "i_color":  {"cols": ["code", "desc", "desc2"], "code_len": 1},
        "i_length": {"cols": ["code", "desc", "desc2"], "code_len": 2},
        "i_qty":    {"cols": ["code", "desc", "desc2"], "code_len": 2},
        "i_size":   {"cols": ["code", "desc"], "code_len": 1},
        "i_start":  {"cols": ["code", "desc"], "code_len": 2},
        "i_space":  {"cols": ["code", "desc"], "code_len": 1},
    }

    # --- small helpers ---

    def log(self, db_actions: list, **event):
        """
        Append a structured event that shows what's happening.
        Keep it machine-readable so you can print as JSON in dry-run.
        """
        if db_actions is None:
            return
        db_actions.append(event)

    # --- SKU encode/decode ---

    def sku_encode(
        self,
        type_code: str,
        color_code: str,
        qty_code: str,
        length_code: str,
        start_code: str,
        space_code: str,
        size_code: str,
    ) -> str:
        # requested order: type-color-qty-length-start-space-size
        return f"{type_code}{color_code}{qty_code}{length_code}{start_code}{space_code}{size_code}"

    def sku_decode(self, sku: str) -> dict:
        s = (sku or "").strip()
        out = {"sku": s}
        i = 0
        for k in self.sku_order:
            ln = self.code_len[k]
            out[k] = s[i : i + ln]
            i += ln
        out["pretty"] = " ".join([f"{k}={out[k]}" for k in self.sku_order])
        return out

    # --- desc2 availability flags (for engines that need it) ---

    def is_qty_has_desc2(self) -> bool:
        return True

    def is_length_has_desc2(self) -> bool:
        return True

    def is_color_has_desc2(self) -> bool:
        return True

    # --- key resolver: length code ---
    # This matches the behavior you fixed earlier:
    # If input contains '"' or "inch" → it should NOT match plain numeric desc/desc2.
    # It should prefer inches-marked labels; otherwise insert with desc2 "{num} inches".
    def resolve_length_code(
        self,
        raw_input: str,
        i_length_rows: list,
        db_actions: list,
    ) -> str:
        raw = (raw_input or "").strip()
        raw = raw.replace("″", '"').replace("”", '"').replace("“", '"')
        raw_l = norm_tr(raw)
        key = normalize_numeric(raw)
        wants_inches = ('"' in raw) or ("inch" in raw_l)

        def indicates_inches(s: str) -> bool:
            sl = norm_tr(s or "")
            return ("inch" in sl) or ('"' in (s or ""))

        # 1) prefer desc2 match
        cand_desc2 = []
        for r in i_length_rows:
            d2 = (r.get("desc2") or "").strip()
            if not d2:
                continue
            if wants_inches and (not indicates_inches(d2)):
                continue
            if normalize_numeric(d2) == key:
                cand_desc2.append(r)

        if cand_desc2:
            r = cand_desc2[0]
            self.log(
                db_actions,
                action="EXISTS",
                table="i_length",
                code=r.get("code"),
                desc=r.get("desc"),
                desc2=r.get("desc2"),
                match="desc2",
                wants_inches=wants_inches,
                raw=raw_input,
            )
            return r.get("code") or ""

        # 2) fallback desc match
        cand_desc = []
        for r in i_length_rows:
            d = (r.get("desc") or "").strip()
            if not d:
                continue
            if wants_inches and (not indicates_inches(d)):
                continue
            if normalize_numeric(d) == key:
                cand_desc.append(r)

        if cand_desc:
            r = cand_desc[0]
            self.log(
                db_actions,
                action="EXISTS",
                table="i_length",
                code=r.get("code"),
                desc=r.get("desc"),
                desc2=r.get("desc2"),
                match="desc",
                wants_inches=wants_inches,
                raw=raw_input,
            )
            return r.get("code") or ""

        # 3) not found → signal to caller to insert
        # (the caller/engine usually does upsert_by_desc + code generation)
        if wants_inches:
            num = normalize_numeric(raw)
            self.log(
                db_actions,
                action="MISSING",
                table="i_length",
                raw=raw_input,
                suggestion_desc=raw,
                suggestion_desc2=f"{num} inches",
                note="wants_inches: insert with desc2 '<num> inches' (do not match plain numbers)",
            )
        else:
            self.log(
                db_actions,
                action="MISSING",
                table="i_length",
                raw=raw_input,
                suggestion_desc=raw,
                suggestion_desc2=raw,
                note="non-inches: insert desc2 same as raw",
            )
        return ""  # caller should insert and return new code
