"""Browse and import parts from the FreeCAD Parts Library (GitHub) on demand.

Downloads individual STEP files via GitHub's raw content URL —
no need to clone the full ~6 GB repo.
"""

import urllib.request
import urllib.error
import urllib.parse
import json
from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP
import caid
from caid_mcp.core import store_object, object_summary, OUTPUT_DIR, log

_REPO = "FreeCAD/FreeCAD-library"
_API_BASE = f"https://api.github.com/repos/{_REPO}/contents"
_RAW_BASE = f"https://raw.githubusercontent.com/{_REPO}/master"

# Cache directory for downloaded STEP files
_CACHE_DIR = OUTPUT_DIR / "freecad-library-cache"


def _github_api_get(url: str) -> list[dict]:
    """Fetch a GitHub API URL and return parsed JSON."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _is_step_file(name: str) -> bool:
    low = name.lower()
    return low.endswith(".step") or low.endswith(".stp")


def register(mcp: FastMCP) -> None:
    """Register FreeCAD Parts Library tools."""

    @mcp.tool()
    def freecad_library_browse(path: str = "") -> str:
        """Browse the FreeCAD Parts Library directory structure.

        Shows folders and STEP files at the given path. Start with "" (root)
        to see top-level categories, then drill into subcategories.

        Args:
            path: Directory path within the library (e.g. "Mechanical Parts/Fasteners").
                  Use "" or "/" for root.
        """
        path = path.strip("/")
        url = f"{_API_BASE}/{path}" if path else _API_BASE
        try:
            items = _github_api_get(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return f"FAIL Path not found: '{path}'. Use '' to start at root."
            return f"FAIL GitHub API error: {e.code} {e.reason}"
        except Exception as e:
            return f"FAIL Error fetching library: {e}"

        dirs = []
        step_files = []
        other_count = 0

        for item in items:
            if item["type"] == "dir":
                dirs.append(item["name"])
            elif _is_step_file(item["name"]):
                size_kb = item.get("size", 0) / 1024
                step_files.append(f"  {item['name']} ({size_kb:.0f} KB)")
            else:
                other_count += 1

        lines = [f"=== FreeCAD Parts Library: /{path or '(root)'} ===", ""]

        if dirs:
            lines.append(f"FOLDERS ({len(dirs)}):")
            for d in sorted(dirs):
                lines.append(f"  {d}/")
            lines.append("")

        if step_files:
            lines.append(f"STEP FILES ({len(step_files)}):")
            lines.extend(sorted(step_files))
            lines.append("")

        if other_count:
            lines.append(f"({other_count} other files not shown)")

        if not dirs and not step_files:
            lines.append("(empty or no STEP files at this path)")

        return "\n".join(lines)

    @mcp.tool()
    def freecad_library_search(query: str, path: str = "") -> str:
        """Search for STEP files in the FreeCAD Parts Library by name.

        Uses GitHub's code search to find matching files. Searches file names
        and paths, not file contents.

        Args:
            query: Search term (e.g. "M8 bolt", "bearing 608", "capacitor").
            path: Optional subdirectory to restrict search (e.g. "Mechanical Parts").
        """
        # GitHub search API for filenames in the repo
        q = f"{query} repo:{_REPO}"
        if path:
            q += f" path:{path}"
        # Only match STEP files
        q += " extension:step OR extension:stp"

        url = f"https://api.github.com/search/code?q={urllib.parse.quote(q)}&per_page=20"
        try:
            url = f"https://api.github.com/search/code?q={urllib.parse.quote(q)}&per_page=20"
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            return f"FAIL Search error: {e}"

        items = data.get("items", [])
        total = data.get("total_count", 0)

        if not items:
            return f"No STEP files found for '{query}'. Try broader terms or browse with freecad_library_browse."

        lines = [f"=== Search results for '{query}' ({total} total, showing {len(items)}) ===", ""]
        for item in items:
            lines.append(f"  {item['path']}")
        lines.append("")
        lines.append("Use freecad_library_import with the file path to import a part.")
        return "\n".join(lines)

    @mcp.tool()
    def freecad_library_import(file_path: str, name: str) -> str:
        """Download a STEP file from the FreeCAD Parts Library and import into the scene.

        Args:
            file_path: Path within the library (e.g. "Mechanical Parts/Fasteners/Bolts/M8x30.step").
            name: Name to store the imported object under in the scene.
        """
        file_path = file_path.strip("/")
        if not _is_step_file(file_path):
            return f"FAIL Not a STEP file: {file_path}"

        # Check cache first
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = file_path.replace("/", "__")
        cached = _CACHE_DIR / safe_name
        if not cached.exists():
            # Download from GitHub raw
            url = f"{_RAW_BASE}/{urllib.parse.quote(file_path)}"
            try:
                url = f"{_RAW_BASE}/{urllib.parse.quote(file_path)}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                cached.write_bytes(data)
                size_kb = len(data) / 1024
                log.info("Downloaded %s (%.0f KB)", file_path, size_kb)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return f"FAIL File not found in library: '{file_path}'. Check the path with freecad_library_browse."
                return f"FAIL Download error: {e.code} {e.reason}"
            except Exception as e:
                return f"FAIL Download error: {e}"
        else:
            log.info("Using cached %s", file_path)

        # Import via caid
        try:
            fr = caid.from_step(cached)
            if fr.ok:
                store_object(name, fr.shape)
                summary = object_summary(name, fr.shape)
                return f"OK Imported '{file_path}' -> {summary}"
            return f"FAIL STEP import error: {fr.diagnostics.get('reason', 'unknown')}"
        except Exception as e:
            return f"FAIL Error importing STEP: {e}"
