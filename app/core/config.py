from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class WaferConfig:
    version: str = "0.1.0"
    database_path: Path = Path("data/wafer.db")
    log_level: str = "INFO"
    granted_permissions: tuple[str, ...] = ("READ",)
    host_enabled_agents: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "WaferConfig":
        if not path.exists():
            return cls()
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        wafer = raw.get("wafer", {})
        permissions = raw.get("permissions", {})
        host = raw.get("host", {})
        if not isinstance(host, dict):
            raise ValueError("[host] must be a TOML table")
        enabled_agents = host.get("enabled_agents", [])
        if not isinstance(enabled_agents, list) or any(
            not isinstance(agent_id, str) or not agent_id.strip()
            for agent_id in enabled_agents
        ):
            raise ValueError("[host].enabled_agents must be an array of non-empty agent IDs")
        if len(enabled_agents) != len(set(enabled_agents)):
            raise ValueError("[host].enabled_agents cannot contain duplicate agent IDs")
        return cls(
            version=str(wafer.get("version", "0.1.0")),
            database_path=Path(wafer.get("database_path", "data/wafer.db")),
            log_level=str(wafer.get("log_level", "INFO")).upper(),
            granted_permissions=tuple(permissions.get("granted", ["READ"])),
            host_enabled_agents=tuple(enabled_agents),
        )
