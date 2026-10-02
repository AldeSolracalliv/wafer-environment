from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class WaferConfig:
    version: str = "0.1.0"
    database_path: Path = Path("data/wafer.db")
    log_level: str = "INFO"
    granted_permissions: tuple[str, ...] = ("READ",)

    @classmethod
    def load(cls, path: Path) -> "WaferConfig":
        if not path.exists():
            return cls()
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        wafer = raw.get("wafer", {})
        permissions = raw.get("permissions", {})
        return cls(
            version=str(wafer.get("version", "0.1.0")),
            database_path=Path(wafer.get("database_path", "data/wafer.db")),
            log_level=str(wafer.get("log_level", "INFO")).upper(),
            granted_permissions=tuple(permissions.get("granted", ["READ"])),
        )
