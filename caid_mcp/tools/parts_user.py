"""User part library — scan, search, and import custom CAiD/CadQuery scripts.

Walks a directory of .py part scripts, extracts metadata from docstring
frontmatter, generates PNG thumbnails, and stores a JSON index for fast
keyword search. Parts can be imported into the scene with parameter overrides.

Docstring frontmatter format (at the top of each .py file):
    '''
    Name: Hex Standoff
    Description: M3 hex standoff with female threads
    Tags: fastener, standoff, M3, spacer
    Author: Adam
    '''

The script must assign the final shape to a variable called `result`.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
import caid

from caid_mcp.core import (
    require_object, store_object, OUTPUT_DIR, log, _unwrap,
    shape_volume, shape_area, shape_bounding_box,
)
from caid.result import ForgeResult


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def _extract_metadata(script_path: Path) -> dict:
    """Extract frontmatter metadata from a Python file's docstring."""
    text = script_path.read_text(encoding="utf-8", errors="replace")

    # Find the module docstring (first triple-quoted string)
    docstring = None
    for delim in ('"""', "'''"):
        idx = text.find(delim)
        if idx != -1:
            end = text.find(delim, idx + 3)
            if end != -1:
                docstring = text[idx + 3:end].strip()
                break

    meta = {
        "name": script_path.stem.replace("_", " ").title(),
        "description": "",
        "tags": [],
        "author": "",
        "file": str(script_path),
        "mtime": script_path.stat().st_mtime,
    }

    if not docstring:
        return meta

    for line in docstring.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "name":
                meta["name"] = value
            elif key == "description":
                meta["description"] = value
            elif key == "tags":
                meta["tags"] = [t.strip().lower() for t in value.split(",") if t.strip()]
            elif key == "author":
                meta["author"] = value

    return meta


def _extract_params(script_path: Path) -> list[dict]:
    """Extract # PARAM markers from a script.

    Format: variable = value  # PARAM description [min:max]
    """
    params = []
    text = script_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "# PARAM" not in line:
            continue
        # Split on # PARAM
        code_part, _, desc = line.partition("# PARAM")
        code_part = code_part.strip()
        desc = desc.strip()
        if "=" not in code_part:
            continue
        var_name, _, default_val = code_part.partition("=")
        var_name = var_name.strip()
        default_val = default_val.strip()
        params.append({
            "name": var_name,
            "default": default_val,
            "description": desc,
        })
    return params


# ---------------------------------------------------------------------------
# Subprocess execution for scanning and importing
# ---------------------------------------------------------------------------

def _run_part_script(
    script_path: Path,
    result_brep_path: Path,
    param_overrides: Optional[dict] = None,
    timeout: int = 60,
) -> dict:
    """Execute a part script in a subprocess and export the result as BREP."""
    script_text = script_path.read_text(encoding="utf-8")

    # Apply parameter overrides
    if param_overrides:
        for var_name, value in param_overrides.items():
            # Replace the line that assigns this variable
            import re
            pattern = rf"^(\s*){re.escape(var_name)}\s*=\s*.+?(#.*)?$"
            replacement = rf"\g<1>{var_name} = {repr(value) if isinstance(value, str) else value}"
            script_text = re.sub(pattern, replacement, script_text, count=1, flags=re.MULTILINE)

    wrapper = (
        "from caid.vector import Vector\n"
        "import caid\n"
        "from pathlib import Path\n"
        f"OUTPUT_DIR = Path({repr(str(OUTPUT_DIR))})\n"
        "\n"
        f"{script_text}\n"
        "\n"
        'if "result" in dir() or "result" in globals():\n'
        '    from caid.result import ForgeResult as _FR\n'
        '    _obj = result\n'
        '    if isinstance(_obj, _FR):\n'
        '        _obj = _obj.unwrap()\n'
        '    from OCP.BRepTools import BRepTools\n'
        '    _wrapped = _obj.wrapped if hasattr(_obj, "wrapped") else _obj\n'
        f'    BRepTools.Write_s(_wrapped, {repr(str(result_brep_path))})\n'
        '    print("__RESULT_EXPORTED__")\n'
        'else:\n'
        '    print("__NO_RESULT__")\n'
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", wrapper],
            capture_output=True, text=True,
            timeout=timeout,
            cwd=str(script_path.parent),
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "exported": "__RESULT_EXPORTED__" in proc.stdout,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "stdout": "", "stderr": f"Timed out after {timeout}s",
            "returncode": -1, "exported": False,
        }


# ---------------------------------------------------------------------------
# Thumbnail generation
# ---------------------------------------------------------------------------

def _generate_thumbnail(brep_path: Path, thumb_path: Path) -> bool:
    """Generate a PNG thumbnail from a BREP file. Returns True on success."""
    try:
        import tempfile
        import trimesh
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import numpy as np
        from matplotlib.colors import to_rgb

        fr = caid.from_brep(brep_path)
        if not fr.ok or fr.shape is None:
            return False

        raw = _unwrap(fr.shape)
        tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
        tmp.close()
        try:
            stl_fr = caid.to_stl(raw, tmp.name, tolerance=0.2)
            if not stl_fr.valid:
                return False
            mesh = trimesh.load(tmp.name)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

        fig = plt.figure(figsize=(3, 3))
        ax = fig.add_subplot(111, projection="3d")

        verts = mesh.vertices
        polygons = verts[mesh.faces]
        normals = mesh.face_normals
        light_dir = np.array([1.0, -1.0, 1.5])
        light_dir = light_dir / np.linalg.norm(light_dir)
        intensity = np.clip(normals @ light_dir, 0.15, 1.0)
        base_rgb = np.array(to_rgb("#4a90d9"))
        face_colors = np.outer(intensity, base_rgb)
        face_colors = np.clip(face_colors, 0, 1)
        face_colors = np.column_stack([face_colors, np.ones(len(face_colors))])
        collection = Poly3DCollection(polygons, linewidth=0.1, edgecolor="#333333")
        collection.set_facecolor(face_colors)
        ax.add_collection3d(collection)

        center = verts.mean(axis=0)
        max_range = verts.ptp(axis=0).max() / 2 * 1.15
        for setter, c in zip([ax.set_xlim, ax.set_ylim, ax.set_zlim], center):
            setter(c - max_range, c + max_range)
        ax.view_init(elev=25, azim=135)
        ax.set_axis_off()

        fig.savefig(str(thumb_path), dpi=100, bbox_inches="tight",
                    facecolor="white", pad_inches=0.05)
        plt.close(fig)
        return True
    except Exception as e:
        log.warning("Thumbnail generation failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

_INDEX_FILENAME = ".caid_parts_index.json"


def _load_index(library_dir: Path) -> dict:
    """Load or create the part library index."""
    idx_path = library_dir / _INDEX_FILENAME
    if idx_path.exists():
        try:
            return json.loads(idx_path.read_text())
        except Exception:
            pass
    return {"version": 1, "parts": {}}


def _save_index(library_dir: Path, index: dict) -> None:
    """Save the part library index."""
    idx_path = library_dir / _INDEX_FILENAME
    idx_path.write_text(json.dumps(index, indent=2))


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp: FastMCP) -> None:
    """Register user part library tools."""

    @mcp.tool()
    def scan_part_library(directory: str) -> str:
        """Scan a directory of .py CAiD/CadQuery scripts and build a searchable
        index with metadata and thumbnails.

        Each script should have a docstring with frontmatter:
            '''
            Name: Part Name
            Description: What this part does
            Tags: tag1, tag2, tag3
            Author: Your Name
            '''

        And should assign the final shape to a variable called `result`.
        Scripts with # PARAM markers will have their parameters extracted.

        Args:
            directory: Path to the directory containing .py part scripts.
        """
        try:
            lib_dir = Path(directory).expanduser().resolve()
            if not lib_dir.is_dir():
                return f"FAIL Directory not found: {lib_dir}"

            scripts = sorted(lib_dir.glob("*.py"))
            scripts = [s for s in scripts if not s.name.startswith("_")]

            if not scripts:
                return f"No .py scripts found in {lib_dir}"

            index = _load_index(lib_dir)
            thumb_dir = lib_dir / ".thumbnails"
            thumb_dir.mkdir(exist_ok=True)

            scanned = 0
            skipped = 0
            failed = 0
            results = []

            for script in scripts:
                # Check if already indexed and up to date
                existing = index["parts"].get(script.name)
                if existing and existing.get("mtime", 0) >= script.stat().st_mtime:
                    skipped += 1
                    results.append(f"  SKIP {script.name} (unchanged)")
                    continue

                # Extract metadata
                meta = _extract_metadata(script)
                meta["params"] = _extract_params(script)

                # Execute script to generate BREP for thumbnail
                brep_path = thumb_dir / f"{script.stem}.brep"
                thumb_path = thumb_dir / f"{script.stem}.png"

                run = _run_part_script(script, brep_path, timeout=30)

                if run["ok"] and run["exported"] and brep_path.exists():
                    # Generate thumbnail
                    thumb_ok = _generate_thumbnail(brep_path, thumb_path)
                    meta["has_thumbnail"] = thumb_ok
                    if thumb_ok:
                        meta["thumbnail"] = str(thumb_path)
                    brep_path.unlink(missing_ok=True)
                    scanned += 1
                    results.append(f"  OK {script.name}: {meta['name']}")
                else:
                    meta["has_thumbnail"] = False
                    stderr_short = run["stderr"][:200] if run["stderr"] else ""
                    if run["returncode"] in (139, -11):
                        meta["error"] = "segfault"
                        results.append(f"  WARN {script.name}: segfault during scan (indexed without thumbnail)")
                    elif not run["exported"]:
                        meta["error"] = "no result variable"
                        results.append(f"  WARN {script.name}: no 'result' variable (indexed without thumbnail)")
                    else:
                        meta["error"] = stderr_short
                        results.append(f"  FAIL {script.name}: {stderr_short}")
                        failed += 1
                        continue

                    scanned += 1
                    brep_path.unlink(missing_ok=True)

                index["parts"][script.name] = meta

            _save_index(lib_dir, index)
            total = len(index["parts"])

            return (
                f"OK Scanned {lib_dir}: {scanned} new/updated, {skipped} unchanged, {failed} failed.\n"
                f"Index contains {total} parts.\n"
                + "\n".join(results)
            )
        except Exception as e:
            return f"FAIL Error scanning library: {e}"

    @mcp.tool()
    def search_parts(query: str, directory: str) -> str:
        """Search the part library index by keyword.

        Searches across part name, description, tags, and author fields.
        Returns results ranked by relevance (number of field matches).

        Args:
            query: Search keywords (space-separated, all must match at least one field).
            directory: Path to the library directory (must be scanned first).
        """
        try:
            lib_dir = Path(directory).expanduser().resolve()
            index = _load_index(lib_dir)

            if not index["parts"]:
                return f"FAIL No parts indexed in {lib_dir}. Run scan_part_library first."

            keywords = [k.lower() for k in query.split() if k.strip()]
            if not keywords:
                return "FAIL Provide at least one search keyword."

            scored = []
            for filename, meta in index["parts"].items():
                # Build searchable text per field
                name_text = meta.get("name", "").lower()
                desc_text = meta.get("description", "").lower()
                tags_text = " ".join(meta.get("tags", [])).lower()
                author_text = meta.get("author", "").lower()
                all_text = f"{name_text} {desc_text} {tags_text} {author_text}"

                # All keywords must appear somewhere
                if not all(kw in all_text for kw in keywords):
                    continue

                # Score: name match = 3, tag match = 2, desc match = 1, author = 1
                score = 0
                for kw in keywords:
                    if kw in name_text:
                        score += 3
                    if kw in tags_text:
                        score += 2
                    if kw in desc_text:
                        score += 1
                    if kw in author_text:
                        score += 1

                scored.append((score, filename, meta))

            scored.sort(key=lambda x: -x[0])

            if not scored:
                return f"No parts matching '{query}' in {lib_dir}."

            results = []
            for score, filename, meta in scored[:10]:
                entry = {
                    "name": meta.get("name", filename),
                    "file": filename,
                    "description": meta.get("description", ""),
                    "tags": meta.get("tags", []),
                    "author": meta.get("author", ""),
                    "has_thumbnail": meta.get("has_thumbnail", False),
                }
                if meta.get("params"):
                    entry["parameters"] = [
                        {"name": p["name"], "default": p["default"], "description": p["description"]}
                        for p in meta["params"]
                    ]
                if meta.get("thumbnail"):
                    entry["thumbnail"] = meta["thumbnail"]
                results.append(entry)

            return json.dumps({
                "query": query,
                "matches": len(scored),
                "showing": len(results),
                "results": results,
            }, indent=2)
        except Exception as e:
            return f"FAIL Error searching: {e}"

    @mcp.tool()
    def find_parts(query: str, user_library: Optional[str] = None) -> str:
        """Search for parts across all three part library systems at once.

        Searches the FreeCAD Parts Library (GitHub STEP files), cq_warehouse
        parametric parts (fasteners, bearings), and your custom user part
        library (if a directory is provided).

        Returns combined results grouped by source.

        Args:
            query: Search keywords (e.g. "M8 bolt", "bearing", "washer").
            user_library: Optional path to a scanned user part library directory.
        """
        keywords = [k.lower() for k in query.split() if k.strip()]
        if not keywords:
            return "FAIL Provide at least one search keyword."

        sections = []

        # --- 1. FreeCAD Parts Library (GitHub search) ---
        try:
            import urllib.request
            import urllib.error
            import urllib.parse

            _REPO = "FreeCAD/FreeCAD-library"
            q = f"{query} repo:{_REPO} extension:step OR extension:stp"
            url = f"https://api.github.com/search/code?q={urllib.parse.quote(q)}&per_page=10"
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            items = data.get("items", [])
            total = data.get("total_count", 0)
            if items:
                lines = [f"FREECAD LIBRARY ({total} total, showing {len(items)}):"]
                for item in items:
                    lines.append(f"  {item['path']}")
                lines.append("  -> Use freecad_library_import to import a file.")
                sections.append("\n".join(lines))
            else:
                sections.append("FREECAD LIBRARY: no matches.")
        except Exception as e:
            sections.append(f"FREECAD LIBRARY: search unavailable ({e})")

        # --- 2. cq_warehouse parametric parts ---
        try:
            from caid_mcp.tools.parts_warehouse import _ensure_loaded, _FASTENER_MAP, _BEARING_MAP
            _ensure_loaded()

            warehouse_hits = []
            all_classes = list(_FASTENER_MAP.items()) + list(_BEARING_MAP.items())
            for class_name, cls in all_classes:
                # Match keywords against the class name (e.g. "HexNut" matches "hex", "nut")
                name_lower = class_name.lower()
                if all(kw in name_lower for kw in keywords):
                    try:
                        types = sorted(cls.types())
                    except Exception:
                        types = []
                    warehouse_hits.append(f"  {class_name}: types={types}")

            if warehouse_hits:
                lines = [f"CQ_WAREHOUSE ({len(warehouse_hits)} matches):"]
                lines.extend(warehouse_hits[:15])
                lines.append("  -> Use create_warehouse_fastener or create_warehouse_bearing to create.")
                sections.append("\n".join(lines))
            else:
                sections.append("CQ_WAREHOUSE: no matches.")
        except ImportError:
            sections.append("CQ_WAREHOUSE: not available (cq_warehouse not installed).")
        except Exception as e:
            sections.append(f"CQ_WAREHOUSE: search error ({e})")

        # --- 3. User part library ---
        if user_library:
            try:
                lib_dir = Path(user_library).expanduser().resolve()
                index = _load_index(lib_dir)

                if not index["parts"]:
                    sections.append(f"USER LIBRARY ({lib_dir.name}): no parts indexed. Run scan_part_library first.")
                else:
                    scored = []
                    for filename, meta in index["parts"].items():
                        name_text = meta.get("name", "").lower()
                        desc_text = meta.get("description", "").lower()
                        tags_text = " ".join(meta.get("tags", [])).lower()
                        all_text = f"{name_text} {desc_text} {tags_text}"

                        if not all(kw in all_text for kw in keywords):
                            continue

                        score = 0
                        for kw in keywords:
                            if kw in name_text:
                                score += 3
                            if kw in tags_text:
                                score += 2
                            if kw in desc_text:
                                score += 1
                        scored.append((score, filename, meta))

                    scored.sort(key=lambda x: -x[0])

                    if scored:
                        lines = [f"USER LIBRARY ({len(scored)} matches):"]
                        for _score, filename, meta in scored[:10]:
                            name = meta.get("name", filename)
                            tags = ", ".join(meta.get("tags", []))
                            lines.append(f"  {name} [{filename}]" + (f"  tags: {tags}" if tags else ""))
                        lines.append("  -> Use import_part with the script path to import.")
                        sections.append("\n".join(lines))
                    else:
                        sections.append(f"USER LIBRARY ({lib_dir.name}): no matches.")
            except Exception as e:
                sections.append(f"USER LIBRARY: search error ({e})")
        else:
            sections.append("USER LIBRARY: skipped (no user_library path provided).")

        header = f"=== find_parts: '{query}' ==="
        return header + "\n\n" + "\n\n".join(sections)

    @mcp.tool()
    def import_part(
        script_path: str,
        name: str,
        parameters: Optional[str] = None,
    ) -> str:
        """Execute a part script and import the result into the scene.

        The script must assign the final shape to a variable called `result`.
        Parameters marked with # PARAM can be overridden.

        Args:
            script_path: Path to the .py part script.
            name: Name to store the imported part under in the scene.
            parameters: Optional JSON object of parameter overrides,
                       e.g. '{"length": 20, "diameter": 5}'.
        """
        try:
            sp = Path(script_path).expanduser().resolve()
            if not sp.exists():
                return f"FAIL Script not found: {sp}"

            param_overrides = None
            if parameters:
                param_overrides = json.loads(parameters)

            brep_path = OUTPUT_DIR / f"_import_{name}.brep"
            run = _run_part_script(sp, brep_path, param_overrides=param_overrides, timeout=60)

            if run["returncode"] in (139, -11):
                brep_path.unlink(missing_ok=True)
                return "FAIL Script segfaulted (OCCT crash). Try simplifying the part."

            if not run["ok"]:
                brep_path.unlink(missing_ok=True)
                stderr = run["stderr"][:500] if run["stderr"] else "unknown error"
                return f"FAIL Script error:\n{stderr}"

            if not run["exported"] or not brep_path.exists():
                brep_path.unlink(missing_ok=True)
                return (
                    "FAIL Script ran but no 'result' variable was found. "
                    "The script must assign the final shape to a variable called 'result'."
                )

            fr = caid.from_brep(brep_path)
            brep_path.unlink(missing_ok=True)

            if not fr.ok or fr.shape is None:
                return f"FAIL BREP reimport failed: {fr.diagnostics}"

            store_object(name, fr.shape)
            bb = shape_bounding_box(fr.shape)
            vol = shape_volume(fr.shape)
            dims = f"{bb['xlen']:.1f} x {bb['ylen']:.1f} x {bb['zlen']:.1f} mm"

            msg = f"OK Imported '{sp.name}' as '{name}' ({dims}, volume={vol:.1f} mm\u00b3)"
            if param_overrides:
                msg += f"\n  Parameters: {json.dumps(param_overrides)}"
            return msg
        except json.JSONDecodeError:
            return "FAIL parameters must be valid JSON, e.g. '{\"length\": 20}'"
        except Exception as e:
            return f"FAIL Error importing part: {e}"
