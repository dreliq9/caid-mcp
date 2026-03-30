"""Import tools for BREP and STEP formats — backed by caid."""

from pathlib import Path
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import store_object, OUTPUT_DIR


def register(mcp: FastMCP) -> None:
    """Register import tools."""

    @mcp.tool()
    def import_step(filename: str, name: str) -> str:
        """Import geometry from a STEP file into the scene.

        Args:
            filename: Path to the STEP file (absolute or relative to output dir).
            name: Name to store the imported object under.
        """
        try:
            path = Path(filename)
            if not path.is_absolute():
                path = OUTPUT_DIR / path
            if not path.exists():
                return f"FAIL File not found: {path}"
            fr = caid.from_step(path)
            if fr.ok:
                store_object(name, fr.shape)
                vol = fr.volume_after or fr.shape.Volume()
                return f"OK Imported STEP -> '{name}' | volume={vol:.1f}mm3"
            return f"FAIL STEP import: {fr.diagnostics.get('reason', 'unknown')}"
        except Exception as e:
            return f"FAIL Error importing STEP: {e}"

    @mcp.tool()
    def import_brep(filename: str, name: str) -> str:
        """Import geometry from a BREP file into the scene.

        Args:
            filename: Path to the BREP file (absolute or relative to output dir).
            name: Name to store the imported object under.
        """
        try:
            path = Path(filename)
            if not path.is_absolute():
                path = OUTPUT_DIR / path
            if not path.exists():
                return f"FAIL File not found: {path}"
            fr = caid.from_brep(path)
            if fr.ok:
                store_object(name, fr.shape)
                vol = fr.volume_after or fr.shape.Volume()
                return f"OK Imported BREP -> '{name}' | volume={vol:.1f}mm3"
            return f"FAIL BREP import: {fr.diagnostics.get('reason', 'unknown')}"
        except Exception as e:
            return f"FAIL Error importing BREP: {e}"
