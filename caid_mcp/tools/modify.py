"""Tools for modifying existing geometry — fillet/chamfer/hole/shell via caid and direct OCP."""

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import require_object, store_object, format_result, shape_volume, _unwrap

from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.TopTools import TopTools_ListOfShape


def _get_edges(shape):
    """Return a list of all TopoDS_Edge from a shape."""
    raw = _unwrap(shape)
    edges = []
    exp = TopExp_Explorer(raw, TopAbs_EDGE)
    while exp.More():
        edges.append(TopoDS.Edge_s(exp.Current()))
        exp.Next()
    return edges


def _get_faces(shape):
    """Return a list of all TopoDS_Face from a shape."""
    raw = _unwrap(shape)
    faces = []
    exp = TopExp_Explorer(raw, TopAbs_FACE)
    while exp.More():
        faces.append(TopoDS.Face_s(exp.Current()))
        exp.Next()
    return faces


def _face_center(face):
    """Return (X, Y, Z) center of mass of a face."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def _select_face_by_selector(shape, selector: str):
    """Pick a face using a simple selector string like '>Z', '<Z', '>X', etc."""
    faces = _get_faces(shape)
    if not faces:
        raise ValueError("Shape has no faces")

    axis_map = {"X": 0, "Y": 1, "Z": 2}
    direction = selector[0]
    axis_char = selector[1:].strip().upper()
    if axis_char not in axis_map:
        raise ValueError(f"Unsupported face selector '{selector}'. Use '>Z', '<Z', '>X', '<X', '>Y', '<Y'.")
    axis_idx = axis_map[axis_char]

    def face_center_component(f):
        c = _face_center(f)
        return c[axis_idx]

    if direction == ">":
        return max(faces, key=face_center_component)
    else:
        return min(faces, key=face_center_component)


def _index_to_selector(shape, face_index: int) -> str:
    """Convert a face index to a best-guess axis selector string for caid.add_hole."""
    faces = _get_faces(shape)
    if face_index < 0 or face_index >= len(faces):
        raise ValueError(f"Face index {face_index} out of range (object has {len(faces)} faces)")
    target = faces[face_index]
    tc = _face_center(target)
    all_centers = [_face_center(f) for f in faces]

    # Find which axis+direction this face is the extreme on
    for axis_idx, axis_char in enumerate("XYZ"):
        vals = [c[axis_idx] for c in all_centers]
        if tc[axis_idx] == max(vals) and vals.count(max(vals)) == 1:
            return f">{axis_char}"
        if tc[axis_idx] == min(vals) and vals.count(min(vals)) == 1:
            return f"<{axis_char}"

    # Fallback: face isn't on a unique extreme. Use >Z as default and warn.
    raise ValueError(
        f"Face index {face_index} is not on a unique axis extreme. "
        "Use face_selector ('>Z', '<X', etc.) instead, or pick a different face."
    )


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
            if face_index is not None:
                sel = _index_to_selector(shape, face_index)
            else:
                sel = face_selector or ">Z"

            fr = caid.add_hole(shape, radius, depth=depth, face_selector=sel)
            msg = format_result(fr, f"Added hole (r={radius}) to '{name}'")
            if fr.shape is not None:
                store_object(name, fr.shape)
            target = f"face_index={face_index}" if face_index is not None else f"face='{sel}'"
            return f"{msg} on {target}"
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
                all_edges = _get_edges(shape)
                selected = []
                for i in indices:
                    if i < 0 or i >= len(all_edges):
                        return f"FAIL Edge index {i} out of range (object has {len(all_edges)} edges)"
                    selected.append(all_edges[i])

                vol_before = shape_volume(shape)
                backend = caid.get_backend()
                result_shape = backend.fillet(shape, radius, selected)
                vol_after = shape_volume(result_shape)
                store_object(name, result_shape)
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
                all_edges = _get_edges(shape)
                selected = []
                for i in indices:
                    if i < 0 or i >= len(all_edges):
                        return f"FAIL Edge index {i} out of range (object has {len(all_edges)} edges)"
                    selected.append(all_edges[i])

                vol_before = shape_volume(shape)
                backend = caid.get_backend()
                result_shape = backend.chamfer(shape, length, selected)
                vol_after = shape_volume(result_shape)
                store_object(name, result_shape)
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
            raw = _unwrap(shape)

            if face_index is not None:
                faces = _get_faces(shape)
                if face_index < 0 or face_index >= len(faces):
                    return f"FAIL Face index {face_index} out of range (object has {len(faces)} faces)"
                face = faces[face_index]
            else:
                face = _select_face_by_selector(shape, face_to_remove)

            faces_to_remove = TopTools_ListOfShape()
            faces_to_remove.Append(face)
            shell_maker = BRepOffsetAPI_MakeThickSolid()
            shell_maker.MakeThickSolidByJoin(raw, faces_to_remove, -thickness, 1e-3)
            shell_maker.Build()
            result = shell_maker.Shape()

            store_object(name, result)
            target = f"face_index={face_index}" if face_index is not None else f"opening='{face_to_remove}'"
            return f"OK Shelled '{name}' with wall thickness={thickness}, {target}"
        except Exception as e:
            return f"FAIL Error: {e}"
