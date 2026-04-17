"""
CAiD MCP Server v0.6.0
=====================
An MCP server that gives AI agents validated 3D modeling
via CAiD (CadQuery wrapper with ForgeResult validation).

Run with:  python server.py
"""

import sys
import logging

from mcp.server.fastmcp import FastMCP

# Verify dependencies
try:
    import OCP
except ImportError:
    print("OCP (cadquery-ocp) is not installed. Install with: pip install cadquery-ocp", file=sys.stderr)
    sys.exit(1)

try:
    import caid
except ImportError:
    print("CAiD is not installed. Install with: pip install caid", file=sys.stderr)
    sys.exit(1)

from caid_mcp.core import log, OUTPUT_DIR

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP("CAiD 3D Modeler")

# ---------------------------------------------------------------------------
# Register tool modules
# ---------------------------------------------------------------------------
from caid_mcp.tools import (
    primitives, modify, transforms, booleans,
    scene, export, advanced, heal, io, assembly, compound, query, view,
    sweep, fasteners, history, parts_warehouse, parts_library, parts_user, curves, split,
    scene_org,
)

primitives.register(mcp)
modify.register(mcp)
transforms.register(mcp)
booleans.register(mcp)
scene.register(mcp)
export.register(mcp)
advanced.register(mcp)
heal.register(mcp)
io.register(mcp)
assembly.register(mcp)
compound.register(mcp)
query.register(mcp)
view.register(mcp)
sweep.register(mcp)
fasteners.register(mcp)
history.register(mcp)
parts_warehouse.register(mcp)
parts_library.register(mcp)
parts_user.register(mcp)
curves.register(mcp)
split.register(mcp)
scene_org.register(mcp)

log.info("CAiD MCP Server v0.6.0 ready — 107 tools — output dir: %s", OUTPUT_DIR)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
