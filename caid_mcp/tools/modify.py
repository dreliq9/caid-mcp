"""Tools for modifying existing geometry — fillet, chamfer, hole, shell via build123d + caid."""

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import require_object, store_object, format_result


def _select_edges_by_index(shape, indices):
    """Return a list of edge objects selected by index from shape.edges()."""
    all_edges = shape.edges()
    selected = []
    for i in indices:
        if i < 0 or i >= len(all_edges):
            raise ValueError(f"Edge index {i} out of range (object has {len(all_edges)} edges)")
        selected.append(all_edges[i])
    return selected


def _select_face_by_index(shape, face_index):
    """Return a single face object selected by index from shape.faces()."""
    all_faces = shape.faces()
    if face_index < 0 or face_index >= len(all_faces):
        raise ValueError(f"Face index {face_index} out of range (object has {len(all_faces)} faces)")
    return all_faces[face_index]


# Legacy name kept for backward compatibility (imported by fasteners.py).
# Returns face_index as a string selector of format "#N" that caid.add_hole
# doesn't understand, so callers should be migrated. For now, we return the
# face center coordinates so callers can match manually.
def _make_face_selector(shape, face_index):
    """Return the face at face_index from shape.faces().

    Kept for backward compatibility with fasteners.py imports.
    Returns the face object directly instead of a CadQuery Selector.
    """
    return _select_face_by_index(shape, face_index)


def register(mcp: FastMCP) -> None:
    """Register all modification tools."""

    @mcp.tool()
    def add_hole(name: str, radius: float, depth: Optional[float] = None,
                 face_selector: Optional[str] = None, face_index: Optional[int] = None) -> str:
        """Add a hole through a face of an existing object.

        Args:
            name: Name of existing object to modify.
            radius: Radius of the hole (mm).
            depth: Depth of hole (mm). If omitted, goes all the way through.
            face_selector: Face selector string (e.g. ">Z", "<Y"). Default ">Z" (top face).
            face_index: Face index from list_faces. Overrides face_selector if provided.
        """
        try:
            shape = require_object(name)

            # Determine face selector string for caid.add_hole
            if face_index is not None:
                # Build a selector string by finding which axis-extreme the face is at
                face = _select_face_by_index(shape, face_index)
                fc = face.center()
                # Find the best matching standard selector by checking all 6 options
                all_faces = shape.faces()
                best_sel = _face_to_selector(fc, all_faces)
                sel_str = best_sel
            else:
                sel_str = face_selector or ">Z"

            fr = caid.add_hole(shape, radius, depth, sel_str)
            msg = format_result(fr, f"Added hole (r={radius}) to '{name}'")
            if fr.shape is not None:
                store_object(name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def fillet_edges(name: str, radius: float, edge_selector: Optional[str] = None,
                     edge_indices: Optional[str] = None) -> str:
        """Apply a fillet (round) to edges of an object.

        Args:
            name: Name of existing object to modify.
            radius: Fillet radius (mm). Must be less than half the shortest edge.
            edge_selector: Edge selector string (e.g. ">Z", "|X").
                          If omitted and no edge_indices, fillets all edges.
            edge_indices: JSON array of edge indices from list_edges (e.g. "[0, 3, 7]").
                         Overrides edge_selector if provided.
        """
        try:
            shape = require_object(name)

            if edge_indices is not None:
                indices = json.loads(edge_indices)
                selected = _select_edges_by_index(shape, indices)
                vol_before = shape.volume
                result = shape.fillet(radius, selected)
                vol_after = result.volume
                store_object(name, result)
                return (f"OK Filleted '{name}' edges {indices} with radius={radius} "
                        f"| volume={vol_after:.1f}mm3 (was {vol_before:.1f}mm3)")
            else:
                fr = caid.fillet(shape, radius, edge_selector)
                msg = format_result(fr, f"Filleted '{name}' with radius={radius}")
                if fr.shape is not None:
                    store_object(name, fr.shape)
                return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def chamfer_edges(name: str, length: float, edge_selector: Optional[str] = None,
                      edge_indices: Optional[str] = None) -> str:
        """Apply a chamfer (bevel) to edges of an object.

        Args:
            name: Name of existing object to modify.
            length: Chamfer length (mm).
            edge_selector: Edge selector string (e.g. ">Z", "|X").
                          If omitted and no edge_indices, chamfers all edges.
            edge_indices: JSON array of edge indices from list_edges (e.g. "[0, 3, 7]").
                         Overrides edge_selector if provided.
        """
        try:
            shape = require_object(name)

            if edge_indices is not None:
                indices = json.loads(edge_indices)
                selected = _select_edges_by_index(shape, indices)
                vol_before = shape.volume
                result = shape.chamfer(length, None, selected)
                vol_after = result.volume
                store_object(name, result)
                return (f"OK Chamfered '{name}' edges {indices} with length={length} "
                        f"| volume={vol_after:.1f}mm3 (was {vol_before:.1f}mm3)")
            else:
                fr = caid.chamfer(shape, length, edge_selector)
                msg = format_result(fr, f"Chamfered '{name}' with length={length}")
                if fr.shape is not None:
                    store_object(name, fr.shape)
                return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def shell_object(name: str, thickness: float, face_to_remove: str = ">Z",
                     face_index: Optional[int] = None) -> str:
        """Hollow out a solid object, leaving walls of specified thickness.

        Args:
            name: Name of existing object to modify.
            thickness: Wall thickness (mm).
            face_to_remove: Face selector for the opening (e.g. ">Z", "<Z").
            face_index: Face index from list_faces. Overrides face_to_remove if provided.
        """
        try:
            shape = require_object(name)

            if face_index is not None:
                face = _select_face_by_index(shape, face_index)
            else:
                # Use selector string to find the face
                faces = shape.faces()
                face = _select_face_by_selector(faces, face_to_remove)

            vol_before = shape.volume
            result = shape.shell(thickness, faces=[face])
            vol_after = result.volume
            store_object(name, result)
            target = f"face_index={face_index}" if face_index is not None else f"opening='{face_to_remove}'"
            return (f"OK Shelled '{name}' with wall thickness={thickness}, {target} "
                    f"| volume={vol_after:.1f}mm3 (was {vol_before:.1f}mm3)")
        except Exception as e:
            return f"FAIL Error: {e}"


def _face_to_selector(face_center, all_faces) -> str:
    """Given a face center, find the best standard selector string (>Z, <Z, etc.)."""
    from build123d import Vector

    axis_map = {"X": Vector(1, 0, 0), "Y": Vector(0, 1, 0), "Z": Vector(0, 0, 1)}
    best_sel = ">Z"
    best_diff = float("inf")

    for axis_name, axis_vec in axis_map.items():
        for op, func in [(">", max), ("<", min)]:
            extreme_face_center = func(
                (f.center() for f in all_faces),
                key=lambda c: c.X * axis_vec.X + c.Y * axis_vec.Y + c.Z * axis_vec.Z,
            )
            dx = face_center.X - extreme_face_center.X
            dy = face_center.Y - extreme_face_center.Y
            dz = face_center.Z - extreme_face_center.Z
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if dist < best_diff:
                best_diff = dist
                best_sel = f"{op}{axis_name}"

    return best_sel


def _select_face_by_selector(faces, selector: str):
    """Select a face using selector strings (>Z, <Z, >X, etc.)."""
    from build123d import Vector

    if not faces:
        raise ValueError("Shape has no faces")

    sel = selector.strip()
    if len(sel) < 2:
        return faces[0]

    axis_map = {"X": Vector(1, 0, 0), "Y": Vector(0, 1, 0), "Z": Vector(0, 0, 1)}
    op = sel[0]
    axis_key = sel[1:].upper()
    axis_vec = axis_map.get(axis_key)
    if axis_vec is None:
        return faces[0]

    def _center_val(f):
        c = f.center()
        return c.X * axis_vec.X + c.Y * axis_vec.Y + c.Z * axis_vec.Z

    if op == ">":
        return max(faces, key=_center_val)
    elif op == "<":
        return min(faces, key=_center_val)
    return faces[0]
