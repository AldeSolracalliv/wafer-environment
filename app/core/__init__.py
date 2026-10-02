"""Core runtime components.

Keep package initialization free of runtime imports. Import Wafer explicitly
from ``app.core.wafer`` so importing a core leaf module does not load the full
application dependency graph. The targeted attribute hook preserves the
historical ``from app.core import Wafer`` public import without eager loading.
"""

__all__ = ["Wafer"]


def __getattr__(name: str):
    if name == "Wafer":
        from .wafer import Wafer

        return Wafer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
