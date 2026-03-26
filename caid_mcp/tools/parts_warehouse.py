"""Parametric standard parts via cq_warehouse — fasteners, bearings, sprockets, threads."""

from typing import Optional
from mcp.server.fastmcp import FastMCP
from caid_mcp.core import store_object, object_summary, log

# ---------------------------------------------------------------------------
# Class registry — maps friendly category/kind names to cq_warehouse classes
# ---------------------------------------------------------------------------

_FASTENER_MAP: dict[str, type] = {}
_BEARING_MAP: dict[str, type] = {}
_LOADED = False


def _ensure_loaded():
    """Lazy-load cq_warehouse classes on first use."""
    global _LOADED
    if _LOADED:
        return
    try:
        from cq_warehouse.fastener import (
            SocketHeadCapScrew, HexHeadScrew, HexHeadWithFlangeScrew,
            ButtonHeadScrew, ButtonHeadWithCollarScrew,
            CheeseHeadScrew, CounterSunkScrew,
            PanHeadScrew, PanHeadWithCollarScrew,
            RaisedCheeseHeadScrew, RaisedCounterSunkOvalHeadScrew,
            SetScrew,
            HexNut, HexNutWithFlange, UnchamferedHexagonNut,
            SquareNut, DomedCapNut, BradTeeNut, HeatSetNut,
            PlainWasher, ChamferedWasher, CheeseHeadWasher,
        )
        for cls in [
            SocketHeadCapScrew, HexHeadScrew, HexHeadWithFlangeScrew,
            ButtonHeadScrew, ButtonHeadWithCollarScrew,
            CheeseHeadScrew, CounterSunkScrew,
            PanHeadScrew, PanHeadWithCollarScrew,
            RaisedCheeseHeadScrew, RaisedCounterSunkOvalHeadScrew,
            SetScrew,
            HexNut, HexNutWithFlange, UnchamferedHexagonNut,
            SquareNut, DomedCapNut, BradTeeNut, HeatSetNut,
            PlainWasher, ChamferedWasher, CheeseHeadWasher,
        ]:
            _FASTENER_MAP[cls.__name__] = cls

        from cq_warehouse.bearing import (
            SingleRowDeepGrooveBallBearing,
            SingleRowCappedDeepGrooveBallBearing,
            SingleRowAngularContactBallBearing,
            SingleRowCylindricalRollerBearing,
            SingleRowTaperedRollerBearing,
        )
        for cls in [
            SingleRowDeepGrooveBallBearing,
            SingleRowCappedDeepGrooveBallBearing,
            SingleRowAngularContactBallBearing,
            SingleRowCylindricalRollerBearing,
            SingleRowTaperedRollerBearing,
        ]:
            _BEARING_MAP[cls.__name__] = cls

        _LOADED = True
    except ImportError as e:
        log.warning("cq_warehouse not installed: %s", e)


def register(mcp: FastMCP) -> None:
    """Register parametric parts tools."""

    @mcp.tool()
    def list_warehouse_parts() -> str:
        """List all available parametric part kinds from cq_warehouse.

        Returns categories (Screws, Nuts, Washers, Bearings) and the
        specific part kinds in each, along with their fastener_type options.
        """
        _ensure_loaded()
        if not _FASTENER_MAP and not _BEARING_MAP:
            return "FAIL cq_warehouse is not installed. Install with: pip install git+https://github.com/gumyr/cq_warehouse.git"

        lines = ["=== Parametric Parts (cq_warehouse) ===", ""]

        # Group fasteners by category
        screws, nuts, washers = [], [], []
        for name, cls in sorted(_FASTENER_MAP.items()):
            try:
                types = sorted(cls.types())
            except Exception:
                types = []
            entry = f"  {name}: types={types}"
            if "Screw" in name or "Set" in name:
                screws.append(entry)
            elif "Nut" in name:
                nuts.append(entry)
            elif "Washer" in name:
                washers.append(entry)

        if screws:
            lines.append("SCREWS:")
            lines.extend(screws)
            lines.append("")
        if nuts:
            lines.append("NUTS:")
            lines.extend(nuts)
            lines.append("")
        if washers:
            lines.append("WASHERS:")
            lines.extend(washers)
            lines.append("")

        if _BEARING_MAP:
            lines.append("BEARINGS:")
            for name, cls in sorted(_BEARING_MAP.items()):
                try:
                    types = sorted(cls.types())
                except Exception:
                    types = []
                lines.append(f"  {name}: types={types}")
            lines.append("")

        lines.append("Use list_warehouse_sizes to see available sizes for a specific part.")
        return "\n".join(lines)

    @mcp.tool()
    def list_warehouse_sizes(kind: str, fastener_type: str) -> str:
        """List available sizes for a specific part kind and type.

        Args:
            kind: Part class name, e.g. "SocketHeadCapScrew", "HexNut", "SingleRowDeepGrooveBallBearing".
            fastener_type: The standard/type, e.g. "iso4762", "iso4032", "SKT".
        """
        _ensure_loaded()
        cls = _FASTENER_MAP.get(kind) or _BEARING_MAP.get(kind)
        if cls is None:
            available = sorted(list(_FASTENER_MAP.keys()) + list(_BEARING_MAP.keys()))
            return f"FAIL Unknown kind '{kind}'. Available: {available}"
        try:
            sizes = cls.sizes(fastener_type)
            return f"OK {kind} ({fastener_type}) — {len(sizes)} sizes:\n{sizes}"
        except Exception as e:
            return f"FAIL Error listing sizes: {e}"

    @mcp.tool()
    def create_warehouse_fastener(
        name: str,
        kind: str,
        fastener_type: str,
        size: str,
        length: Optional[float] = None,
        simple: bool = True,
    ) -> str:
        """Create a parametric fastener (screw, nut, or washer) and add to scene.

        Args:
            name: Name to store the part under in the scene.
            kind: Part class name, e.g. "SocketHeadCapScrew", "HexNut", "PlainWasher".
            fastener_type: The standard, e.g. "iso4762", "iso4032", "iso7089".
            size: Size string, e.g. "M3-0.5", "M8-1.25".
            length: Screw length in mm (required for screws, ignored for nuts/washers).
            simple: If True, generate simplified geometry (faster). Default True.
        """
        _ensure_loaded()
        cls = _FASTENER_MAP.get(kind)
        if cls is None:
            return f"FAIL Unknown fastener kind '{kind}'. Use list_warehouse_parts to see options."

        try:
            kwargs = {
                "size": size,
                "fastener_type": fastener_type,
                "simple": simple,
            }
            # Screws need length, nuts/washers don't
            if length is not None:
                kwargs["length"] = length

            part = cls(**kwargs)
            store_object(name, part)
            summary = object_summary(name, part)
            return f"OK Created {kind} ({fastener_type} {size}) -> {summary}"
        except Exception as e:
            return f"FAIL Error creating {kind}: {e}"

    @mcp.tool()
    def create_warehouse_bearing(
        name: str,
        kind: str,
        bearing_type: str,
        size: str,
    ) -> str:
        """Create a parametric bearing and add to scene.

        Args:
            name: Name to store the bearing under in the scene.
            kind: Bearing class name, e.g. "SingleRowDeepGrooveBallBearing".
            bearing_type: The type, e.g. "SKT".
            size: Size string, e.g. "M8-22-7" (bore-OD-width in mm).
        """
        _ensure_loaded()
        cls = _BEARING_MAP.get(kind)
        if cls is None:
            return f"FAIL Unknown bearing kind '{kind}'. Use list_warehouse_parts to see options."

        try:
            part = cls(size=size, bearing_type=bearing_type)
            store_object(name, part)
            summary = object_summary(name, part)
            return f"OK Created {kind} ({bearing_type} {size}) -> {summary}"
        except Exception as e:
            return f"FAIL Error creating {kind}: {e}"
