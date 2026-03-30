"""Split, trim, and intersection tools — divide solids and extract intersection curves."""

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP

from OCP.gp import gp_Pnt, gp_Dir, gp_Pln
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BOPAlgo import BOPAlgo_Splitter
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp

from caid_mcp.core import (
    require_object, store_object,
    shape_volume, shape_bounding_box, _unwrap,
)


def _extract_solids(compound_shape):
    """Extract individual solids from a compound/shape."""
    solids = []
    exp = TopExp_Explorer(compound_shape, TopAbs_SOLID)
    while exp.More():
        solids.append(TopoDS.Solid_s(exp.Current()))
        exp.Next()
    return solids


def _solid_center(solid):
    """Get center of mass of a solid."""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, props)
    c = props.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def _make_cutting_face(axis, offset):
    """Create a large planar face for splitting along X/Y/Z."""
    axis_upper = axis.upper()
    normals = {"X": gp_Dir(1, 0, 0), "Y": gp_Dir(0, 1, 0), "Z": gp_Dir(0, 0, 1)}
    origins = {
        "X": gp_Pnt(offset, 0, 0),
        "Y": gp_Pnt(0, offset, 0),
        "Z": gp_Pnt(0, 0, offset),
    }
    if axis_upper not in normals:
        return None, f"FAIL Invalid axis '{axis}'. Use X, Y, or Z."

    pln = gp_Pln(origins[axis_upper], normals[axis_upper])
    # Large enough to cut through any reasonable geometry
    face = BRepBuilderAPI_MakeFace(pln, -5000, 5000, -5000, 5000).Face()
    return face, None


def register(mcp: FastMCP) -> None:
    """Register split, trim, and intersection tools."""

    @mcp.tool()
    def split_with_plane(
        name: str,
        axis: str = "Z",
        offset: float = 0.0,
        name_pos: Optional[str] = None,
        name_neg: Optional[str] = None,
    ) -> str:
        """Split a solid into two pieces along a plane. Both halves are kept.

        Unlike section_view (which discards one half for visualization), this
        tool stores both resulting solids in the scene for further operations.

        Common uses: splitting a body for multi-part manufacturing, creating
        mating surfaces, dividing a model for separate material assignment.

        Args:
            name: Object to split.
            axis: Cutting plane normal — "X", "Y", or "Z" (default "Z").
            offset: Position along the axis for the cut (mm). Default 0.
            name_pos: Name for the positive-side half (default: {name}_pos).
            name_neg: Name for the negative-side half (default: {name}_neg).
        """
        try:
            shape = require_object(name)
            raw = _unwrap(shape)

            face, err = _make_cutting_face(axis, offset)
            if err:
                return err

            splitter = BOPAlgo_Splitter()
            splitter.AddArgument(raw)
            splitter.AddTool(face)
            splitter.Perform()

            if splitter.HasErrors():
                return "FAIL Split operation failed — geometry may be too complex"

            solids = _extract_solids(splitter.Shape())
            if len(solids) < 2:
                return f"FAIL Split produced {len(solids)} piece(s) — plane may not intersect the object. Check axis and offset."

            # Sort solids by their center position along the cut axis
            axis_idx = {"X": 0, "Y": 1, "Z": 2}[axis.upper()]
            solids_with_center = [(s, _solid_center(s)) for s in solids]
            solids_with_center.sort(key=lambda sc: sc[1][axis_idx])

            rname_neg = name_neg or f"{name}_neg"
            rname_pos = name_pos or f"{name}_pos"

            # Negative side = lower along axis, positive = higher
            store_object(rname_neg, solids_with_center[0][0])
            store_object(rname_pos, solids_with_center[-1][0])

            vol_orig = shape_volume(raw)
            vol_neg = shape_volume(solids_with_center[0][0])
            vol_pos = shape_volume(solids_with_center[-1][0])

            lines = [
                f"OK Split '{name}' along {axis}={offset}mm into {len(solids)} pieces",
                f"  '{rname_neg}' (- side): volume={vol_neg:.1f}mm3",
                f"  '{rname_pos}' (+ side): volume={vol_pos:.1f}mm3",
            ]

            # If more than 2 pieces, store extras too
            if len(solids) > 2:
                for i, (s, c) in enumerate(solids_with_center[1:-1], start=1):
                    extra_name = f"{name}_mid{i}"
                    store_object(extra_name, s)
                    vol = shape_volume(s)
                    lines.append(f"  '{extra_name}': volume={vol:.1f}mm3")

            lines.append(f"Original volume: {vol_orig:.1f}mm3")
            return "\n".join(lines)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def split_with_object(
        name: str, tool_name: str,
        keep: str = "all",
    ) -> str:
        """Split a solid using another solid as the cutting tool.

        The tool shape divides the target into pieces wherever they overlap.
        All resulting pieces are stored in the scene.

        Unlike boolean_cut (which discards the intersection), this keeps
        every fragment — useful for analyzing how two bodies interact or
        for separating a complex shape into regions.

        Args:
            name: Object to split (the target).
            tool_name: Object to split with (the tool/cutter).
            keep: What to keep — "all" (default), "inside" (only the
                  intersection region), or "outside" (everything except
                  the intersection).
        """
        try:
            shape = require_object(name)
            tool = require_object(tool_name)
            raw = _unwrap(shape)
            raw_tool = _unwrap(tool)

            splitter = BOPAlgo_Splitter()
            splitter.AddArgument(raw)
            splitter.AddTool(raw_tool)
            splitter.Perform()

            if splitter.HasErrors():
                return "FAIL Split operation failed — geometry may be incompatible"

            solids = _extract_solids(splitter.Shape())
            if not solids:
                return "FAIL Split produced no solids"

            vol_orig = shape_volume(raw)

            # Classify solids: "inside" = overlaps with tool, "outside" = doesn't
            # We use a simple heuristic: check if center of mass is inside the tool bbox
            tool_bb = shape_bounding_box(raw_tool)

            results = []
            for i, solid in enumerate(solids):
                cx, cy, cz = _solid_center(solid)
                vol = shape_volume(solid)
                inside = (
                    tool_bb["xmin"] <= cx <= tool_bb["xmax"] and
                    tool_bb["ymin"] <= cy <= tool_bb["ymax"] and
                    tool_bb["zmin"] <= cz <= tool_bb["zmax"]
                )
                results.append({
                    "solid": solid,
                    "volume": vol,
                    "center": (cx, cy, cz),
                    "inside": inside,
                    "index": i,
                })

            # Filter based on keep parameter
            if keep == "inside":
                filtered = [r for r in results if r["inside"]]
            elif keep == "outside":
                filtered = [r for r in results if not r["inside"]]
            else:
                filtered = results

            if not filtered:
                return f"FAIL No solids match keep='{keep}'"

            lines = [f"OK Split '{name}' with '{tool_name}' -> {len(filtered)} piece(s)"]
            for r in filtered:
                piece_name = f"{name}_piece{r['index']}"
                store_object(piece_name, r["solid"])
                region = "inside" if r["inside"] else "outside"
                lines.append(
                    f"  '{piece_name}': volume={r['volume']:.1f}mm3 ({region})"
                )
            lines.append(f"Original volume: {vol_orig:.1f}mm3")
            return "\n".join(lines)
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def intersect_curves(
        name_a: str, name_b: str,
        result_name: Optional[str] = None,
    ) -> str:
        """Extract the intersection curves/edges where two shapes meet.

        Computes the geometric intersection between two solids and returns
        the resulting edges as a wire. Useful for finding trim lines,
        engraving paths along body intersections, or analyzing fit between
        mating parts.

        Args:
            name_a: First object name.
            name_b: Second object name.
            result_name: Name for the intersection wire (default: {name_a}_x_{name_b}).
        """
        try:
            shape_a = require_object(name_a)
            shape_b = require_object(name_b)
            raw_a = _unwrap(shape_a)
            raw_b = _unwrap(shape_b)

            section = BRepAlgoAPI_Section(raw_a, raw_b)
            section.Build()

            if not section.IsDone():
                return "FAIL Section operation failed"

            result = section.Shape()

            # Count resulting edges
            edges = []
            exp = TopExp_Explorer(result, TopAbs_EDGE)
            total_length = 0.0
            while exp.More():
                edge = TopoDS.Edge_s(exp.Current())
                edges.append(edge)
                curve = BRepAdaptor_Curve(edge)
                total_length += GCPnts_AbscissaPoint.Length_s(curve)
                exp.Next()

            if not edges:
                return f"FAIL No intersection found between '{name_a}' and '{name_b}' — objects may not overlap"

            rname = result_name or f"{name_a}_x_{name_b}"
            store_object(rname, result)

            return (
                f"OK Intersection of '{name_a}' and '{name_b}' -> '{rname}' | "
                f"{len(edges)} edge(s), total length={total_length:.2f}mm"
            )
        except Exception as e:
            return f"FAIL Error: {e}"
