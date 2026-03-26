"""
Core scene state and shared utilities for the CAiD MCP server.
"""

import json
import os
import subprocess
import sys
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

from build123d import Vector, Solid, Compound
import caid
from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Shape
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
    """Store a shape in the scene. Auto-extracts from ForgeResult."""
    if isinstance(obj, ForgeResult):
        obj = obj.unwrap()
    scene[name] = obj


def object_summary(name: str, obj: Any) -> str:
    """Return a one-line summary of a shape."""
    try:
        bb = obj.bounding_box()
        return f"'{name}': {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm"
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


# ---------------------------------------------------------------------------
# Subprocess-isolated boolean operations (survives OCCT segfaults)
# ---------------------------------------------------------------------------

def _shape_to_brep_file(shape, path: Path) -> None:
    """Write an OCP shape to a BREP file."""
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    BRepTools.Write_s(wrapped, str(path))


def _brep_file_to_shape(path: Path):
    """Read a BREP file back into a build123d shape."""
    fr = caid.from_brep(path)
    if fr.ok:
        return fr.shape
    raise RuntimeError(f"Failed to reimport BREP: {fr.diagnostics}")


def safe_boolean(shape_a, shape_b, operation: str, timeout: int = 60):
    """Run a boolean operation in a subprocess to survive OCCT segfaults.

    Args:
        shape_a: First operand (build123d Shape).
        shape_b: Second operand (build123d Shape).
        operation: One of "union", "cut", "intersect".
        timeout: Max seconds before killing the subprocess.

    Returns:
        ForgeResult with the boolean result.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="caid_bool_"))
    brep_a = tmp_dir / "a.brep"
    brep_b = tmp_dir / "b.brep"
    brep_out = tmp_dir / "result.brep"
    diag_file = tmp_dir / "diagnostics.json"

    try:
        _shape_to_brep_file(shape_a, brep_a)
        _shape_to_brep_file(shape_b, brep_b)
    except Exception as e:
        _cleanup_dir(tmp_dir)
        return {"ok": False, "shape": None, "msg": f"FAIL exporting operands: {e}", "diagnostics": {}}

    script = (
        "import caid, json\n"
        "from pathlib import Path\n"
        f"fr = caid.boolean_{operation}(\n"
        f"    caid.from_brep(Path('{brep_a}')).shape,\n"
        f"    caid.from_brep(Path('{brep_b}')).shape,\n"
        ")\n"
        "diag = dict(fr.diagnostics) if fr.diagnostics else {}\n"
        "diag['ok'] = fr.ok\n"
        "diag['valid'] = fr.valid\n"
        "if fr.volume_after is not None:\n"
        "    diag['volume_after'] = fr.volume_after\n"
        "if fr.surface_area is not None:\n"
        "    diag['surface_area'] = fr.surface_area\n"
        f"Path('{diag_file}').write_text(json.dumps(diag))\n"
        "if fr.shape is not None:\n"
        "    from OCP.BRepTools import BRepTools\n"
        f"    BRepTools.Write_s(fr.shape.wrapped, '{brep_out}')\n"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _cleanup_dir(tmp_dir)
        return {
            "ok": False, "shape": None,
            "msg": f"FAIL Boolean {operation} timed out after {timeout}s",
            "diagnostics": {},
        }

    # Segfault
    if proc.returncode in (139, -11, -6, 134):
        log.warning(f"Boolean {operation} segfaulted — server is safe")
        _cleanup_dir(tmp_dir)
        return {
            "ok": False, "shape": None,
            "msg": (
                f"FAIL Boolean {operation} crashed (OCCT segfault). "
                "The MCP server is still running. Try simplifying the geometry "
                "or using a different boolean approach."
            ),
            "diagnostics": {"reason": "OCCT segfault", "hint": "simplify geometry"},
        }

    # Other errors
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        _cleanup_dir(tmp_dir)
        return {
            "ok": False, "shape": None,
            "msg": f"FAIL Boolean {operation} error:\n{stderr}",
            "diagnostics": {},
        }

    # Read diagnostics
    diagnostics = {}
    if diag_file.exists():
        try:
            diagnostics = json.loads(diag_file.read_text())
        except Exception:
            pass

    # Read result shape
    result_shape = None
    if brep_out.exists():
        try:
            result_shape = _brep_file_to_shape(brep_out)
        except Exception as e:
            _cleanup_dir(tmp_dir)
            return {
                "ok": False, "shape": None,
                "msg": f"FAIL Boolean {operation} ran but result reimport failed: {e}",
                "diagnostics": diagnostics,
            }

    _cleanup_dir(tmp_dir)

    was_ok = diagnostics.get("ok", False)
    was_valid = diagnostics.get("valid", False)

    # Build a ForgeResult so callers can use format_result()
    fr = ForgeResult(
        shape=result_shape,
        valid=was_valid,
        volume_after=diagnostics.get("volume_after"),
        surface_area=diagnostics.get("surface_area"),
        diagnostics={k: v for k, v in diagnostics.items()
                     if k not in ("ok", "valid", "volume_after", "surface_area")},
    )
    return fr


def _cleanup_dir(d: Path) -> None:
    """Remove a temp directory and its contents."""
    try:
        for f in d.iterdir():
            f.unlink(missing_ok=True)
        d.rmdir()
    except Exception:
        pass
