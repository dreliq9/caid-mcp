"""Shared Pydantic models for structured tool outputs.

FastMCP serializes these as both `structuredContent` (typed JSON) and as
`content` text via __str__. Clients that understand structured output get
typed access; legacy clients still see a clean human-readable line.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Point3(BaseModel):
    x: float
    y: float
    z: float

    def __str__(self) -> str:
        return f"({self.x:.2f}, {self.y:.2f}, {self.z:.2f})"


class BoundingBox(BaseModel):
    xmin: float; ymin: float; zmin: float
    xmax: float; ymax: float; zmax: float
    xlen: float; ylen: float; zlen: float

    def __str__(self) -> str:
        return f"{self.xlen:.2f}x{self.ylen:.2f}x{self.zlen:.2f}mm"


class ShapeResult(BaseModel):
    """Result from any shape-creating tool (primitives, sweep, fasteners, ...)."""

    ok: bool = Field(description="True if shape was created and stored")
    name: str = Field(description="Scene-local name of the created object")
    kind: str = Field(description="Primitive kind: box, cylinder, sphere, ...")
    volume_mm3: Optional[float] = Field(default=None, description="Volume in mm^3 (None on failure)")
    bbox: Optional[BoundingBox] = Field(default=None, description="Axis-aligned bounding box")
    reason: Optional[str] = Field(default=None, description="Failure reason when ok=False")
    hint: Optional[str] = Field(default=None, description="Suggested fix when ok=False")

    def __str__(self) -> str:
        if not self.ok:
            tail = f" (hint: {self.hint})" if self.hint else ""
            return f"FAIL {self.kind} '{self.name}': {self.reason}{tail}"
        v = f" | volume={self.volume_mm3:.1f}mm3" if self.volume_mm3 is not None else ""
        bb = f" | bbox={self.bbox}" if self.bbox is not None else ""
        return f"OK Created {self.kind} '{self.name}'{v}{bb}"


class EdgeInfo(BaseModel):
    index: int
    length_mm: float
    start: list[float]
    end: list[float]
    midpoint: list[float]
    type: str = Field(description="LINE, CIRCLE, ELLIPSE, BSPLINE, OTHER")
    distance_to_point: Optional[float] = Field(
        default=None,
        description="Distance from a query point to the edge midpoint (only set by find_edges_near_point)",
    )


class FaceInfo(BaseModel):
    index: int
    area_mm2: float
    center: list[float]
    normal: Optional[list[float]] = None
    type: str = Field(description="PLANE, CYLINDER, CONE, SPHERE, TORUS, BSPLINE, OTHER")
    bounds: dict
    num_edges: int
    distance_to_point: Optional[float] = Field(
        default=None,
        description="Distance from a query point to the face center (only set by find_faces_near_point)",
    )


class EdgeListResult(BaseModel):
    object: str
    count: int
    edges: list[EdgeInfo]

    def __str__(self) -> str:
        return f"'{self.object}' has {self.count} edge(s)"


class FaceListResult(BaseModel):
    object: str
    count: int
    faces: list[FaceInfo]

    def __str__(self) -> str:
        return f"'{self.object}' has {self.count} face(s)"


class DistanceResult(BaseModel):
    object_a: str
    object_b: str
    min_distance_mm: float

    def __str__(self) -> str:
        return f"min distance '{self.object_a}'-'{self.object_b}' = {self.min_distance_mm:.4f} mm"


class InspectResult(BaseModel):
    name: str
    volume_mm3: float
    surface_area_mm2: float
    center_of_mass: Point3
    bounding_box: BoundingBox
    num_faces: int
    num_edges: int
    num_vertices: int
    face_types: dict[str, int] = Field(description="Count by face type (PLANE, CYLINDER, ...)")

    def __str__(self) -> str:
        types = ", ".join(
            f"{n} {t.lower()}" for t, n in
            sorted(self.face_types.items(), key=lambda x: -x[1])
        )
        return (
            f"'{self.name}' is a solid {self.bounding_box}. "
            f"It has {self.num_faces} faces ({types}), {self.num_edges} edges, "
            f"{self.num_vertices} vertices. "
            f"Volume: {self.volume_mm3:.2f} mm^3. Area: {self.surface_area_mm2:.2f} mm^2. "
            f"CoM: {self.center_of_mass}."
        )


class MassResult(BaseModel):
    name: str
    material: str = Field(description="Material name, or 'custom' if density was given directly")
    density_g_per_cm3: float
    volume_mm3: float
    volume_cm3: float
    surface_area_mm2: float
    mass_grams: float
    mass_kg: float
    weight_newtons: float
    center_of_mass: Point3
    bounding_box: BoundingBox

    def __str__(self) -> str:
        return (
            f"'{self.name}' in {self.material} (rho={self.density_g_per_cm3} g/cm^3): "
            f"mass={self.mass_grams:.2f} g ({self.mass_kg:.3f} kg), "
            f"weight={self.weight_newtons:.2f} N, volume={self.volume_cm3:.3f} cm^3"
        )


class NearestEdgesResult(BaseModel):
    object: str
    query_point: list[float]
    nearest_edges: list[EdgeInfo]

    def __str__(self) -> str:
        if not self.nearest_edges:
            return f"No edges found near {self.query_point}"
        e = self.nearest_edges[0]
        return (
            f"Nearest edge to {self.query_point} on '{self.object}': "
            f"index={e.index}, type={e.type}, dist={e.distance_to_point:.3f} mm"
        )


class NearestFacesResult(BaseModel):
    object: str
    query_point: list[float]
    nearest_faces: list[FaceInfo]

    def __str__(self) -> str:
        if not self.nearest_faces:
            return f"No faces found near {self.query_point}"
        f = self.nearest_faces[0]
        return (
            f"Nearest face to {self.query_point} on '{self.object}': "
            f"index={f.index}, type={f.type}, dist={f.distance_to_point:.3f} mm"
        )
