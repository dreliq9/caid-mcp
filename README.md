# CAiD MCP Server

<!-- mcp-name: io.github.dreliq9/caid-mcp -->

An MCP server that gives AI agents **validated 3D CAD modeling** via [CAiD](https://github.com/dreliq9/CAiD) and [CadQuery](https://cadquery.readthedocs.io/). No GUI needed — the modeling engine IS the server.

Every geometry operation is validated through CAiD's ForgeResult system, which tracks volume, surface area, and diagnostics. If a boolean silently fails (common with OCCT), the validation layer catches it and tells you why.

```
You: "Make a box with rounded edges and a hole through the top, show me a preview"
Claude → create_box → fillet_edges → add_hole → preview_object → export_stl
Result: SVG preview + ~/cadquery-output/my_part.stl
```

## Available Tools (54 across 13 categories)

Use `discover_tools()` to browse, or `discover_tools(category="query")` for a specific category.

| Category | Count | What it does |
|---|---|---|
| **primitives** | 7 | Box, cylinder, sphere, cone, torus, extruded polygon, revolved profile |
| **modify** | 4 | Holes, fillets, chamfers, shell — with index-based edge/face selection |
| **transforms** | 4 | Translate, rotate, scale, mirror |
| **booleans** | 4 | Union, cut, intersect, multi-combine |
| **query** | 6 | List edges/faces, measure objects/distances, find nearest edges/faces |
| **view** | 2 | Section cuts, exploded assembly views |
| **scene** | 5 | List, info, delete, duplicate, clear |
| **export** | 5 | SVG preview, STL, STEP, batch STL |
| **heal** | 3 | Validity checking, shape repair, face simplification |
| **io** | 3 | BREP export, STEP/BREP import |
| **assembly** | 5 | Create, add parts, move, rotate, merge |
| **compound** | 3 | Belt wires, curve arrays, pulley assemblies |
| **advanced** | 3 | CadQuery scripting, linear patterns, tool discovery |

## Project Structure

```
caid-mcp/
├── server.py                    # Entry point
├── caid_mcp/
│   ├── __init__.py
│   ├── core.py                  # Scene state, shared utilities
│   └── tools/
│       ├── primitives.py        # Shape creation (7 tools)
│       ├── modify.py            # Holes, fillets, chamfers, shell (4 tools)
│       ├── transforms.py        # Translate, rotate, scale, mirror (4 tools)
│       ├── booleans.py          # Union, cut, intersect, combine (4 tools)
│       ├── query.py             # Geometry inspection and measurement (6 tools)
│       ├── view.py              # Section and exploded views (2 tools)
│       ├── scene.py             # Workspace management (5 tools)
│       ├── export.py            # STL, STEP, SVG preview (5 tools)
│       ├── heal.py              # Validation and repair (3 tools)
│       ├── io.py                # BREP/STEP import-export (3 tools)
│       ├── assembly.py          # Multi-part assemblies (5 tools)
│       ├── compound.py          # Belt/pulley systems (3 tools)
│       └── advanced.py          # Scripting, patterns, tool router (3 tools)
├── tests/
│   └── test_cadquery_mcp.py
├── pyproject.toml
├── LLM_GUIDE.md                 # LLM-specific usage guide
├── CHANGELOG.md
└── LICENSE
```

---

## Setup

### Prerequisites

- Python 3.11+
- [CadQuery](https://cadquery.readthedocs.io/) (requires conda or mamba — CadQuery depends on OCCT)
- [CAiD](https://github.com/dreliq9/CAiD) (CadQuery validation wrapper)

### Install

```bash
# 1. Create a conda environment with CadQuery
conda create -n cadforge python=3.11 -y
conda activate cadforge
conda install -c conda-forge cadquery -y

# 2. Install CAiD
pip install caid

# 3. Clone and install this server
git clone https://github.com/dreliq9/caid-mcp.git
cd caid-mcp
pip install -e ".[dev]"
```

### Verify

```bash
conda activate cadforge
python -c "import cadquery; import caid; import mcp; print('All dependencies OK')"
pytest tests/ -v
```

### Connect to Claude Code

```bash
claude mcp add-json caid '{"type":"stdio","command":"conda","args":["run","-n","cadforge","python","/FULL/PATH/TO/caid-mcp/server.py"]}' --scope user
```

Replace `/FULL/PATH/TO/caid-mcp` with the actual absolute path.

Or edit `~/.claude.json` directly:

```json
{
  "mcpServers": {
    "caid": {
      "type": "stdio",
      "command": "conda",
      "args": ["run", "-n", "cadforge", "python", "/FULL/PATH/TO/caid-mcp/server.py"]
    }
  }
}
```

### Claude Desktop

Add the same config to your Claude Desktop config file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### Verify connection

```bash
claude mcp list       # from terminal
/mcp                  # inside Claude Code
```

---

## Key Features

### Geometry Query and Measurement

The query tools let the LLM inspect what it built before modifying it — solving the "blind fillet" problem where the LLM guesses which edge to target.

```
list_edges("box")           → every edge with index, endpoints, length, type
list_faces("box")           → every face with index, area, center, normal
find_edges_near_point(...)  → "what edges are near (10, 5, 2.5)?"
measure_distance(a, b)      → min distance between two objects
```

### Index-Based Edge/Face Selection

Instead of guessing CadQuery selector strings like `">Z"`, the LLM can now:
1. Call `list_edges` to see all edges with their indices
2. Call `fillet_edges(name, radius, edge_indices="[2, 5, 8]")` to target exactly those edges

Same for `add_hole(face_index=3)` and `shell_object(face_index=0)`.

### Section and Exploded Views

```
section_view("part", axis="X", offset=5.0)  → cut and preview cross-section
exploded_view("assembly", scale=2.5)        → push parts outward for inspection
```

### Validated Operations

Every CAiD operation returns a ForgeResult with volume tracking. If a boolean union doesn't increase volume, you get a warning with a hint (shapes may not overlap). Silent OCCT failures are caught automatically.

### CadQuery Scripting Escape Hatch

When built-in tools can't do the job, `run_cadquery_script` gives full access to CadQuery and CAiD:

```python
script = """
obj = cq.Workplane("XY").add(scene["base"])
result = obj.faces(">Z").workplane().pushPoints([(10,10),(-10,-10)]).hole(3)
"""
```

---

## Output Files

All exports go to `~/cadquery-output/` by default. Override with:

```bash
export CAID_OUTPUT_DIR=/your/path
```

Or in the MCP config:
```json
{
  "env": { "CAID_OUTPUT_DIR": "/your/stl/folder" }
}
```

---

## Example Prompts

- *"Create a 50mm cube with 3mm filleted edges, preview it, then export as STL"*
- *"Make a phone stand: rectangular base with an angled slot cut into it"*
- *"Design a mounting bracket: L-shape with two holes, show me front and isometric views"*
- *"List the edges on this part, then fillet just the top edges by index"*
- *"Section view through the middle to check the internal hole dimensions"*

---

## Architecture

```
Claude Code / Claude Desktop / any MCP client
        │
        │  stdio (JSON-RPC)
        ▼
   MCP Server (server.py)
        │
        ├── tools/primitives — create shapes
        ├── tools/modify — holes, fillets, chamfers, shell
        ├── tools/transforms — move, rotate, scale, mirror
        ├── tools/booleans — union, cut, intersect
        ├── tools/query — geometry inspection and measurement
        ├── tools/view — section cuts, exploded views
        ├── tools/scene — workspace management
        ├── tools/export — STL, STEP, SVG preview
        ├── tools/heal — validation, repair, simplification
        ├── tools/io — BREP/STEP import-export
        ├── tools/assembly — multi-part assemblies
        ├── tools/compound — belt/pulley systems
        └── tools/advanced — scripting, patterns, tool router
              │
              ▼
        CAiD → CadQuery → OpenCASCADE kernel
              │
              ▼
        STL / STEP / BREP / SVG files
```

---

## Troubleshooting

**"CadQuery is not installed"** — Activate the conda environment: `conda activate cadforge`

**"CAiD is not installed"** — `pip install caid` in the cadforge environment

**Claude Code doesn't show tools** — `claude mcp list` to check registration. Make sure the path is absolute. Restart Claude Code.

**SVG preview is blank** — Object might have zero volume. Use `list_objects` to check dimensions.

**Fillet/chamfer fails** — Try `heal_object` first, then retry with a smaller radius. Use `list_edges` to verify the shortest edge length.

**Tests failing** — Make sure you're in the cadforge conda env: `conda activate cadforge && pytest tests/ -v`

---

## Acknowledgments

CAiD MCP was co-developed by Adam Steen and [Claude](https://claude.ai) (Anthropic).

## License

MIT — see [LICENSE](LICENSE).
