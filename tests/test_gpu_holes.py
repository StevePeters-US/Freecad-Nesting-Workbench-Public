import pytest
import numpy as np
from shapely.geometry import Polygon, Point
from unittest.mock import MagicMock
from nestingworkbench.Tools.Nesting.algorithms.minkowski_engine import MinkowskiEngine
from nestingworkbench.Tools.Nesting.algorithms.nfp_gpu_taichi import TAICHI_AVAILABLE

@pytest.mark.skipif(not TAICHI_AVAILABLE, reason="Taichi not available")
class MockPart:
    def __init__(self, poly, label="Part"):
        self.original_polygon = poly
        self.source_freecad_object = MagicMock()
        self.source_freecad_object.Label = label
        self.spacing = 0.0
        self.deflection = 0.5
        self.simplification = 0.0
        self.area = poly.area

from unittest.mock import MagicMock

def test_gpu_hole_nesting():
    # Setup Engine
    engine = MinkowskiEngine(100, 100, 1.0, use_gpu=True, search_direction=(0, -1))
    
    # Donut: 10x10 square with 4x4 hole in center (at 3,3 to 7,7)
    donut_poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], 
                         [[(3, 3), (7, 3), (7, 7), (3, 7)]])
    
    # Small Square: 1x1
    small_p = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    
    part_a = MockPart(donut_poly, "Donut")
    part_b = MockPart(small_p, "Small")
    
    # In MinkowskiEngine, _calculate_and_cache_nfp_gpu computes NFP(Placed, ToPlace)
    # If Donut is placed at (0,0), and we want to place Small in the hole.
    # The IFP of Small inside Donut's hole (4x4) is a 3x3 square of valid centroids.
    # Hole is (3,3)-(7,7). Centroid of Small is (0.5, 0.5).
    # Valid centroids for Small are (3.5, 3.5) to (6.5, 6.5).
    
    # We call _calculate_and_cache_nfp_gpu(Donut, 0, Small, 0, "test_cache")
    nfp_data = engine._calculate_and_cache_nfp_gpu(part_a, 0, part_b, 0, "test_cache")
    
    nfp_poly = nfp_data.get("polygon")
    if nfp_poly:
        print(f"\nNFP Area: {nfp_poly.area}")
        print(f"NFP Interiors Count: {len(nfp_poly.interiors)}")
    
    shells = nfp_data["shells"]
    holes = nfp_data["holes"]
    print(f"Num Shell Pieces: {len(shells)}")
    print(f"Num Hole Pieces: {len(holes)}")
    
    # Now check points using compute_batch_pip_with_holes.
    # NFP is centered at (0,0). 
    import nestingworkbench.Tools.Nesting.algorithms.nfp_gpu_taichi as nfp_gpu_taichi
    
    # (0,0) is center of hole -> No collision (0)
    # (4,4) is in solid exterior -> Collision (1)
    # (8,8) is outside NFP entirely -> No collision (0)
    points_np = np.array([[0.0, 0.0], [4.0, 4.0], [8.0, 8.0]], dtype=np.float32)
    
    results = nfp_gpu_taichi.compute_batch_pip_with_holes(points_np, shells, holes)
    print(f"PIP Results: {results}")
    
    assert results[0] == 0  # Center of hole: OK
    assert results[1] == 1  # Solid part: Collision
    assert results[2] == 0  # Outside NFP: OK

def test_two_parts_in_hole_no_overlap():
    if not TAICHI_AVAILABLE:
        pytest.skip("Taichi not available")

    # Setup Engine
    engine = MinkowskiEngine(100, 100, 1.0, use_gpu=True)
    
    # Donut: 20x20 square with 12x12 hole in center (at 4,4 to 16,16)
    donut_poly = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)], 
                         [[(4, 4), (16, 4), (16, 16), (4, 16)]])
    
    # Small Square: 2x2
    small_poly = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    
    # Setup Placed Part A (Donut)
    part_a = MockPart(donut_poly, "Donut")
    
    # Setup Placed Part C (Small) - will be placed inside Donut's hole
    part_c = MockPart(small_poly, "Small_C")
    
    class MockPlacedPart:
        def __init__(self, shape, angle, centroid):
            self.shape = shape
            self.angle = angle
            self.shape.centroid = centroid

    # Place A at (0,0) -> hole is (4,4)-(16,16)
    placed_a = MockPlacedPart(part_a, 0.0, Point(10, 10))
    # Place C at (6,6) -> inside hole
    placed_c = MockPlacedPart(part_c, 0.0, Point(6, 6))
    
    from nestingworkbench.datatypes.sheet import Sheet
    sheet = Sheet("test_sheet", 100, 100)
    sheet.add_part(placed_a)
    sheet.add_part(placed_c)
    
    # Part D (Small Square) to be placed
    part_d = MockPart(small_poly, "Small_D")
    
    # 1. Compute global NFP for angle 0
    nfp_entry = engine.get_global_nfp_for(part_d, 0.0, sheet)
    
    assert nfp_entry is not None
    assert 'per_part_nfps' in nfp_entry
    assert len(nfp_entry['per_part_nfps']) == 2
    
    # 2. Score candidates using GPU logic
    # Candidate 1: (6, 6) -> overlaps C (collision with C's shells)
    # Candidate 2: (12, 12) -> inside hole, clear of C
    # Build nfp_entry for angle=0 — required by new score_candidates_gpu API
    nfp_entry = engine.get_global_nfp_for(part_d, 0.0, sheet)
    assert nfp_entry is not None

    points = [Point(6, 6), Point(12, 12)]
    candidates = [(0.0, points, nfp_entry)]

    # dir=(0,-1) -> metric = pt.x*(0) + pt.y*(1) = pt.y; smaller Y is better.
    # 6 < 12, so (6,6) would be preferred — but it overlaps C, so (12,12) is picked.

    result = engine.score_candidates_gpu(part_d, candidates)
    
    assert result['x'] == 12.0
    assert result['y'] == 12.0
