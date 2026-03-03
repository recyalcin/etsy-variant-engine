import re
from dataclasses import dataclass
from typing import Dict, List

ETSY_API = "https://api.etsy.com"
ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DELIMS = [" / ", " - ", " | ", "/", "-"]

NUM_PREFIX = re.compile(r"^\s*(\d+)\s+(.*\S)\s*$")

DEBUG = False
WRITE_ENABLED = False

@dataclass
class Profile:
    name: str
    type_len: int
    length_len: int
    color_len: int
    qty_len: int
    size_len: int
    start_len: int
    space_len: int
    sku_order: List[str]

    def sku_lengths(self) -> Dict[str, int]:
        return {
            "type": self.type_len,
            "length": self.length_len,
            "color": self.color_len,
            "qty": self.qty_len,
            "size": self.size_len,
            "start": self.start_len,
            "space": self.space_len,
        }

PROFILES: Dict[str, Profile] = {
    "shiny": Profile(
        name="shiny",
        type_len=2, length_len=2, color_len=1, qty_len=2, size_len=1, start_len=2, space_len=1,
        sku_order=["type", "color", "qty", "length", "start", "space", "size"],
    ),
    "silveristic": Profile(
        name="silveristic",
        type_len=4, length_len=4, color_len=1, qty_len=3, size_len=4, start_len=3, space_len=2,
        sku_order=["type", "length", "color", "qty", "size", "start", "space"],
    ),
    "belkymood": Profile(
        name="belkymood",
        type_len=2, length_len=2, color_len=1, qty_len=2, size_len=1, start_len=2, space_len=1,
        sku_order=["type", "color", "qty", "length", "start", "space", "size"],
    ),
}