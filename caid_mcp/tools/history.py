"""Undo/snapshot system — save and restore scene states."""

import os
import tempfile
from typing import Optional
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from OCP.BRepTools import BRepTools
import caid

from caid_mcp.core import scene, log


# ---------------------------------------------------------------------------
# Snapshot storage — each snapshot is a dict of name -> BREP string.
# We serialize via BREP to get true deep copies of OCCT shapes.
# Note: single-threaded assumption (MCP stdio transport).
# ---------------------------------------------------------------------------

_snapshots: list[dict] = []
_snapshot_names: list[str] = []
_snapshot_counter: int = 0  # monotonic — never resets, so labels stay unique
MAX_SNAPSHOTS = 20


def _shape_to_brep_str(shape) -> str:
    """Serialize an OCP shape to a BREP string via temp file."""
    fd, tmp_path = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
        BRepTools.Write_s(wrapped, str(tmp))
        return tmp.read_text()
    finally:
        tmp.unlink(missing_ok=True)


def _brep_str_to_shape(brep_str: str):
    """Deserialize a BREP string back to a CadQuery Shape."""
    fd, tmp_path = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        tmp.write_text(brep_str)
        fr = caid.from_brep(tmp)
        if fr.ok:
            return fr.shape
        raise RuntimeError(f"Failed to restore shape from BREP: {fr.diagnostics}")
    finally:
        tmp.unlink(missing_ok=True)


def register(mcp: FastMCP) -> None:
    """Register undo/snapshot tools."""

    @mcp.tool()
    def save_snapshot(label: Optional[str] = None) -> str:
        """Save the current scene state as a snapshot.

        Call this before risky operations (complex booleans, multi-step
        modifications) so you can restore if something goes wrong.

        Snapshots are stored in memory (not on disk). Up to 20 snapshots
        are kept; oldest are dropped when the limit is reached.

        Args:
            label: Optional human-readable label for this snapshot.
                  Default: "snapshot_N" with a monotonic counter.
        """
        global _snapshot_counter
        try:
            if not scene:
                return "FAIL Scene is empty — nothing to snapshot"

            snap = {}
            for name, shape in scene.items():
                try:
                    snap[name] = _shape_to_brep_str(shape)
                except Exception as e:
                    return f"FAIL Could not serialize '{name}': {e}"

            snap_label = label or f"snapshot_{_snapshot_counter}"
            _snapshot_counter += 1

            if len(_snapshots) >= MAX_SNAPSHOTS:
                _snapshots.pop(0)
                _snapshot_names.pop(0)

            _snapshots.append(snap)
            _snapshot_names.append(snap_label)

            idx = len(_snapshots) - 1
            return (
                f"OK Saved snapshot #{idx} '{snap_label}' "
                f"({len(snap)} objects). "
                f"Total snapshots: {len(_snapshots)}"
            )
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def restore_snapshot(index: Optional[int] = None, label: Optional[str] = None) -> str:
        """Restore the scene to a previous snapshot.

        Replaces the entire current scene with the snapshot contents.
        The current state is NOT automatically saved — call save_snapshot
        first if you want to keep it.

        Note: snapshot indices may shift after older snapshots are evicted
        when the 20-snapshot limit is reached. Use list_snapshots to verify.

        Args:
            index: Snapshot index (0-based). If omitted, restores the most recent.
            label: Snapshot label to find. If both index and label given, index wins.
        """
        try:
            if not _snapshots:
                return "FAIL No snapshots saved. Use save_snapshot first."

            if index is not None:
                if index < 0 or index >= len(_snapshots):
                    return f"FAIL Snapshot index {index} out of range (0..{len(_snapshots)-1})"
                snap_idx = index
            elif label is not None:
                try:
                    snap_idx = _snapshot_names.index(label)
                except ValueError:
                    return f"FAIL No snapshot with label '{label}'. Use list_snapshots to see available."
            else:
                snap_idx = len(_snapshots) - 1

            snap = _snapshots[snap_idx]
            snap_label = _snapshot_names[snap_idx]

            scene.clear()
            restored = 0
            failed = []
            for name, brep_str in snap.items():
                try:
                    scene[name] = _brep_str_to_shape(brep_str)
                    restored += 1
                except Exception as e:
                    failed.append(f"'{name}': {e}")

            msg = f"OK Restored snapshot #{snap_idx} '{snap_label}' ({restored} objects)"
            if failed:
                msg += f"\nWARN Failed to restore: {'; '.join(failed)}"
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def list_snapshots() -> str:
        """List all saved snapshots with their index, label, and object counts."""
        if not _snapshots:
            return "No snapshots saved. Use save_snapshot to save the current scene."

        lines = [f"Snapshots ({len(_snapshots)}/{MAX_SNAPSHOTS}):"]
        for i, (snap, label) in enumerate(zip(_snapshots, _snapshot_names)):
            obj_names = list(snap.keys())
            preview = ", ".join(obj_names[:5])
            if len(obj_names) > 5:
                preview += f", ... (+{len(obj_names)-5} more)"
            lines.append(f"  #{i} '{label}' — {len(snap)} objects: [{preview}]")

        lines.append("")
        lines.append("Use restore_snapshot(index=N) to restore.")
        return "\n".join(lines)

    @mcp.tool()
    def undo() -> str:
        """Restore the most recent snapshot (quick undo).

        Pops the latest snapshot off the stack and restores it.
        Call undo() repeatedly to walk backward through the stack.
        """
        try:
            if not _snapshots:
                return "FAIL No snapshots to undo to. Use save_snapshot before operations."

            snap = _snapshots.pop()
            snap_label = _snapshot_names.pop()

            scene.clear()
            restored = 0
            failed = []
            for name, brep_str in snap.items():
                try:
                    scene[name] = _brep_str_to_shape(brep_str)
                    restored += 1
                except Exception as e:
                    failed.append(f"'{name}': {e}")

            remaining = len(_snapshots)
            msg = (
                f"OK Undone to '{snap_label}' ({restored} objects restored). "
                f"{remaining} snapshot{'s' if remaining != 1 else ''} remaining."
            )
            if failed:
                msg += f"\nWARN Failed to restore: {'; '.join(failed)}"
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"
