"""
CAiD MCP — Quickstart Verification Script

Run this after installation to confirm everything works:

    python examples/quickstart.py

Creates a simple bracket (box + hole + fillet), exports STL and STEP,
and prints a summary. If it completes without errors, your install is good.
"""

import caid
from pathlib import Path

OUTPUT_DIR = Path.home() / "cadquery-output"
OUTPUT_DIR.mkdir(exist_ok=True)


def main():
    print("CAiD MCP — Quickstart")
    print("=" * 40)

    # 1. Create a base box
    print("\n1. Creating 40x30x10mm box...")
    box = caid.box(40, 30, 10)
    print(f"   {caid.format_result(box)}")

    # 2. Add a hole through the top face
    print("2. Adding M5 clearance hole (r=2.7mm)...")
    with_hole = caid.add_hole(box, radius=2.7, depth=10)
    print(f"   {caid.format_result(with_hole)}")

    # 3. Fillet the top edges
    print("3. Filleting top edges (r=1.5mm)...")
    filleted = caid.fillet(with_hole, radius=1.5, edge_selector=">Z")
    print(f"   {caid.format_result(filleted)}")

    # 4. Export STL
    stl_path = OUTPUT_DIR / "quickstart_bracket.stl"
    print(f"4. Exporting STL to {stl_path}...")
    stl_result = caid.to_stl(filleted, str(stl_path))
    print(f"   {caid.format_result(stl_result)}")

    # 5. Export STEP
    step_path = OUTPUT_DIR / "quickstart_bracket.step"
    print(f"5. Exporting STEP to {step_path}...")
    step_result = caid.to_step(filleted, str(step_path))
    print(f"   {caid.format_result(step_result)}")

    # 6. Validate
    print("6. Validating final shape...")
    info = caid.check_valid(filleted.shape)
    status = "VALID" if info["is_valid"] else "INVALID"
    print(f"   {status} — {info['n_faces']} faces, {info['n_edges']} edges")

    print("\n" + "=" * 40)
    print("Quickstart complete. If no errors above, your install is working.")
    print(f"Output files in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
