"""Boolean operation tools — subprocess-isolated to survive OCCT segfaults."""

import json
from mcp.server.fastmcp import FastMCP
from caid_mcp.core import (
    require_object, store_object, scene,
    format_result, safe_boolean, shape_volume,
)


def register(mcp: FastMCP) -> None:
    """Register all boolean tools."""

    @mcp.tool()
    def boolean_union(name_a: str, name_b: str, result_name: str) -> str:
        """Combine two objects into one (additive boolean).

        Args:
            name_a: First object name.
            name_b: Second object name.
            result_name: Name for the combined result.
        """
        try:
            a, b = require_object(name_a), require_object(name_b)
            fr = safe_boolean(a, b, "union")
            if isinstance(fr, dict):
                return fr["msg"]
            msg = format_result(fr, f"Union: '{name_a}' + '{name_b}' -> '{result_name}'")
            if fr.shape is not None:
                store_object(result_name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def boolean_cut(name_a: str, name_b: str, result_name: str) -> str:
        """Subtract one object from another.

        Args:
            name_a: Object to cut from (keeps this shape).
            name_b: Object to subtract (the "tool").
            result_name: Name for the result.
        """
        try:
            a, b = require_object(name_a), require_object(name_b)

            # Guard: refuse to cut with degenerate tool geometry
            tool_vol = shape_volume(b)
            if tool_vol < 1e-6:
                return (
                    f"FAIL Tool object '{name_b}' has zero volume (degenerate geometry). "
                    f"Cannot use it for boolean cut — it would corrupt the target. "
                    f"Check that '{name_b}' is a valid solid."
                )

            base_vol = shape_volume(a)
            fr = safe_boolean(a, b, "cut")
            if isinstance(fr, dict):
                return fr["msg"]

            # Guard: if the result volume dropped to near-zero, the cut
            # produced degenerate geometry — don't store it
            if fr.shape is not None:
                result_vol = shape_volume(fr.shape)
                if base_vol > 1e-6 and result_vol < 1e-6:
                    return (
                        f"FAIL Cut produced degenerate geometry (volume went from "
                        f"{base_vol:.1f} to ≈0). The tool may have invalid geometry "
                        f"that corrupted the result. Original '{name_a}' is preserved."
                    )

            msg = format_result(fr, f"Cut: '{name_a}' - '{name_b}' -> '{result_name}'")
            if fr.shape is not None:
                store_object(result_name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def boolean_intersect(name_a: str, name_b: str, result_name: str) -> str:
        """Keep only the overlapping volume of two objects.

        Args:
            name_a: First object name.
            name_b: Second object name.
            result_name: Name for the intersection result.
        """
        try:
            a, b = require_object(name_a), require_object(name_b)
            fr = safe_boolean(a, b, "intersect")
            if isinstance(fr, dict):
                return fr["msg"]
            msg = format_result(fr, f"Intersect: '{name_a}' ^ '{name_b}' -> '{result_name}'")
            if fr.shape is not None:
                store_object(result_name, fr.shape)
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"

    @mcp.tool()
    def combine_objects(names: str, result_name: str) -> str:
        """Combine multiple objects into a single solid via union.

        Args:
            names: JSON array of object names. Example: '["part1", "part2", "part3"]'
            result_name: Name for the combined result.
        """
        try:
            name_list = json.loads(names)
            if len(name_list) < 2:
                return "FAIL Need at least 2 objects to combine"
            result_shape = require_object(name_list[0])
            warnings = []
            failed_count = 0
            for n in name_list[1:]:
                fr = safe_boolean(result_shape, require_object(n), "union")
                if isinstance(fr, dict):
                    return fr["msg"]
                if fr.shape is not None:
                    result_shape = fr.shape
                else:
                    failed_count += 1
                    warnings.append(f"{n}: union produced no shape")
                    continue
                if not fr.valid:
                    warnings.append(f"{n}: {fr.diagnostics.get('reason', '?')}")
            if failed_count == len(name_list) - 1:
                return f"FAIL All {failed_count} union(s) failed — no result produced"
            store_object(result_name, result_shape)
            msg = f"OK Combined {len(name_list)} objects -> '{result_name}'"
            if warnings:
                msg += f" | warnings: {'; '.join(warnings)}"
            return msg
        except Exception as e:
            return f"FAIL Error: {e}"
