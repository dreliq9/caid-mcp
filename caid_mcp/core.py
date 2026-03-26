"""
Core scene state and shared utilities for the CAiD MCP server.
"""

import json
import os
import sys
import logging
from pathlib import Path
from typing import Any, Optional

import cadquery as cq
from caid.result import ForgeResult
from caid.assembly import Assembly

# ---------------------------------------------------------------------------
# Logging (must go to stderr for stdio-based MCP)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("caid-mcp")

# ---------------------------------------------------------------------------
# Output directory for exported files
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(
    os.environ.get("CAID_OUTPUT_DIR",
    os.environ.get("CADQUERY_OUTPUT_DIR",
    Path.home() / "cadquery-output"))
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Scene state — tracks all named shapes in the workspace
# ---------------------------------------------------------------------------
scene: dict[str, Any] = {}

# Assembly state — tracks named assemblies
assemblies: dict[str, Assembly] = {}


def get_object(name: str) -> Optional[Any]:
    """Get a named shape from the scene, or None."""
    return scene.get(name)


def require_object(name: str) -> Any:
    """Get a named shape, raising ValueError if missing."""
    obj = scene.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found in scene")
    return obj


def store_object(name: str, obj: Any) -> None:
    """Store a shape in the scene. Auto-extracts from ForgeResult or Workplane."""
    if isinstance(obj, ForgeResult):
        obj = obj.unwrap()
    elif isinstance(obj, cq.Workplane):
        obj = obj.val()
    scene[name] = obj


def object_summary(name: str, obj: Any) -> str:
    """Return a one-line summary of a shape."""
    try:
        bb = obj.BoundingBox()
        return f"'{name}': {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm"
    except Exception:
        return f"'{name}': (dimensions unavailable)"


def format_result(fr: ForgeResult, prefix: str) -> str:
    """Format a ForgeResult into a human-readable MCP response string."""
    if fr.ok:
        parts = [f"OK {prefix}"]
        if fr.volume_after is not None:
            parts.append(f"volume={fr.volume_after:.1f}mm3")
        if fr.surface_area is not None:
            parts.append(f"area={fr.surface_area:.1f}mm2")
        return " | ".join(parts)
    elif fr.shape is not None:
        reason = fr.diagnostics.get("reason", "unknown")
        hint = fr.diagnostics.get("hint", "")
        msg = f"WARN {prefix}: {reason}"
        if hint:
            msg += f" (hint: {hint})"
        if fr.volume_after is not None:
            msg += f" | volume={fr.volume_after:.1f}mm3"
        return msg
    else:
        reason = fr.diagnostics.get("reason", "unknown error")
        hint = fr.diagnostics.get("hint", "")
        msg = f"FAIL {prefix}: {reason}"
        if hint:
            msg += f" (hint: {hint})"
        return msg
