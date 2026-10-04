import platform
import sys

from app.security.permissions import Permission
from app.tools.registry import Tool


SYSTEM_INFO_TOOL = "system.info"


def system_info(_: dict) -> dict[str, str]:
    return {
        "operating_system": platform.system(),
        "python_version": platform.python_version(),
        "architecture": platform.machine() or platform.architecture()[0],
    }


def create_system_info_tool() -> Tool:
    return Tool(
        name=SYSTEM_INFO_TOOL,
        description="Return basic, non-sensitive operating system and Python information.",
        parameter_schema={"type": "object", "properties": {}, "additionalProperties": False},
        required_permission=Permission.READ,
        implementation=system_info,
    )
