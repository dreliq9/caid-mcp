"""Tools for modifying existing geometry — fillet/chamfer via caid, hole/shell via CQ workplane."""

import json
from typing import Optional
import cadquery as cq
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import require_object, store_object, format_result


def _make_edge_selector(shape, indices):
    """Create a CadQuery Selector that matches edges by their index in shape.Edges()."""
    all_edges = shape.Edges()
    target_centers = set()
    for i in indices:
        if i < 0 or i >= len(all_edges):
            raise ValueError(f"Edge index {i} out of range (object has {len(all_edges)} edges)")
        c = all_edges[i].Center()
        target_centers.add((round(c.x, 5), round(c.y, 5), round(c.z, 5)))

    class _IndexSelector(cq.Selector):
        def filter(self, objectList):
            return [o for o in objectList if
                    (round(o.Center().x, 5), round(o.Center().y, 5), round(o.Center().z, 5))
                    in target_centers]

    return _IndexSelector()


def _make_face_selector(shape, face_index):
    """Create a CadQuery Selector that matches a face by its index in shape.Faces()."""
    all_faces = shape.Faces()
    if face_index < 0 or face_index >= len(all_faces):
        raise ValueError(f"Face index {face_index} out of range (object has {len(all_faces)} faces)")
    target = all_faces[face_index]
    tc = target.Center()
    target_center = (round(tc.x, 5), round(tc.y, 5), round(tc.z, 5))

    class _FaceSelector(cq.Selector):
        def filter(self, objectList):
            return [o for o in objectList if
                    (round(o.Center().x, 5), round(o.Center().y, 5), round(o.Center().z, 5))
                    == target_center]

    return _FaceSelector()


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
            face_selector: CadQuery face selector string (e.g. ">Z", "<Y"). Default ">Z" (top face).
            face_index: Face index from list_faces. Overrides face_selector if provided.
        """
        try:
            shape = require_object(name)
            wp = cq.Workplane("XY").add(shape)

            if face_index is not None:
                selector = _make_face_selector(shape, face_index)
            else:
                selector = face_selector or ">Z"

            face_wp = wp.faces(selector).workplane()
            if depth:
                result = face_wp.hole(radius * 2, depth)
            else:
                result = face_wp.hole(radius * 2)

            store_object(name, result)
            target = f"face_index={face_index}" if face_index is not None else f"face='{face_selector or '>Z'}'"
            return f"OK Added hole (r={radius}) to '{name}' on {target}"
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def fillet_edges(name: str, radius: float, edge_selector: Optional[str] = None,
                     edge_indices: Optional[str] = None) -> str:
        """Apply a fillet (round) to edges of an object.

        Args:
            name: Name of existing object to modify.
            radius: Fillet radius (mm). Must be less than half the shortest edge.
            edge_selector: CadQuery edge selector string (e.g. ">Z", "|X").
                          If omitted and no edge_indices, fillets all edges.
            edge_indices: JSON array of edge indices from list_edges (e.g. "[0, 3, 7]").
                         Overrides edge_selector if provided.
        """
        try:
            shape = require_object(name)

            if edge_indices is not None:
                indices = json.loads(edge_indices)
                selector = _make_edge_selector(shape, indices)
                vol_before = shape.Volume()
                result = cq.Workplane("XY").add(shape).edges(selector).fillet(radius)
                result_shape = result.val()
                vol_after = result_shape.Volume()
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
            edge_selector: CadQuery edge selector string (e.g. ">Z", "|X").
                          If omitted and no edge_indices, chamfers all edges.
            edge_indices: JSON array of edge indices from list_edges (e.g. "[0, 3, 7]").
                         Overrides edge_selector if provided.
        """
        try:
            shape = require_object(name)

            if edge_indices is not None:
                indices = json.loads(edge_indices)
                selector = _make_edge_selector(shape, indices)
                vol_before = shape.Volume()
                result = cq.Workplane("XY").add(shape).edges(selector).chamfer(length)
                result_shape = result.val()
                vol_after = result_shape.Volume()
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
            face_to_remove: CadQuery face selector for the opening (e.g. ">Z", "<Z").
            face_index: Face index from list_faces. Overrides face_to_remove if provided.
        """
        try:
            shape = require_object(name)
            wp = cq.Workplane("XY").add(shape)

            if face_index is not None:
                selector = _make_face_selector(shape, face_index)
            else:
                selector = face_to_remove

            result = wp.faces(selector).shell(-thickness)
            store_object(name, result)
            target = f"face_index={face_index}" if face_index is not None else f"opening='{face_to_remove}'"
            return f"OK Shelled '{name}' with wall thickness={thickness}, {target}"
        except Exception as e:
            return f"FAIL Error: {e}"
