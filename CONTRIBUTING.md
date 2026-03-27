# Contributing to CAiD MCP

Thanks for your interest in contributing. This guide covers how to add tools, run tests, and submit changes.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

pip install caid
pip install -e ".[dev]"
```

## Adding a new tool

Each tool category lives in its own module under `caid_mcp/tools/`. To add a tool:

1. **Pick the right module.** If your tool fits an existing category (e.g., a new primitive goes in `primitives.py`), add it there. Only create a new module if it's a genuinely new category.

2. **Follow the registration pattern.** Every module exports a `register(mcp)` function. Define your tool inside it:

```python
# caid_mcp/tools/your_module.py

from mcp.server.fastmcp import FastMCP
from caid_mcp.core import require_object, store_object, format_result

def register(mcp: FastMCP):
    @mcp.tool()
    def your_tool(name: str, param: float) -> str:
        """One-line description of what the tool does."""
        try:
            obj = require_object(name)
            # ... do the thing ...
            store_object(name, result)
            return f"OK your_tool: {name} — details"
        except Exception as e:
            return f"FAIL your_tool: {e}"
```

3. **Register the module in `server.py`:**

```python
from caid_mcp.tools import your_module
your_module.register(mcp)
```

4. **Add tests** in `tests/test_cadquery_mcp.py` (or a new test file for large additions).

5. **Update the tool count** in `server.py`, `README.md`, and `LLM_GUIDE.md` if applicable.

## Tool conventions

- Tools return **strings**, not exceptions. Use `OK`, `WARN`, or `FAIL` prefixes.
- Store results in the scene via `store_object()`. It auto-extracts from ForgeResult.
- Use `require_object()` to fetch scene objects — it raises `ValueError` with a clear message if the object doesn't exist.
- For operations that modify geometry, use CAiD's validated functions when available. Raw OCP calls are fine for queries and transforms.
- Include volume/area in the return string when the operation changes geometry.

## Running tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

All tests should pass before submitting a PR. If you're adding a new tool, add at least one test that covers the happy path and one that covers a common failure mode.

## Code style

- No linter is enforced yet — just match the existing style.
- Keep imports explicit (no `import *`).
- No type annotations are required, but add them if you want.
- Don't add docstrings or comments to code you didn't change.

## Submitting changes

1. Fork the repo and create a feature branch.
2. Make your changes, add tests.
3. Run `pytest tests/ -v` and confirm everything passes.
4. Open a PR with a short description of what you added and why.

## Questions?

Open an issue if something is unclear or you want to discuss an idea before building it.
