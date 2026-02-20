# profiles/__init__.py
import os

def load_profile():
    name = (os.getenv("DB_PROFILE") or "shiny").strip().lower()
    if name == "silveristic":
        from .silveristic import SilveristicProfile
        return SilveristicProfile()
    from .shiny import ShinyProfile
    return ShinyProfile()
