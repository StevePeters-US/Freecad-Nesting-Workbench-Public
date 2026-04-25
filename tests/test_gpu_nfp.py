import pytest
import numpy as np
from shapely.geometry import Polygon, MultiPoint
from nestingworkbench.Tools.Nesting.algorithms.nfp_gpu_taichi import (
    TAICHI_AVAILABLE, compute_nfp_pairs, compute_nfp_batch
)

@pytest.mark.skipif(not TAICHI_AVAILABLE, reason="Taichi not available")
def test_gpu_convex_hull_correctness():
    # Define two unit squares
    # poly_a: [0,0], [1,0], [1,1], [0,1]
    # poly_b: [0,0], [1,0], [1,1], [0,1] (reflected B is same shape but different coords? 
    # Wait, NFP(A,B) = A + (-B). 
    # Let's just test compute_nfp_pairs with simple squares.
    
    poly_a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    poly_b = Polygon([(0, 0), (-1, 0), (-1, -1), (0, -1)]) # This is -B for a unit square
    
    pairs = [(poly_a, poly_b, 0.0)]
    
    results = compute_nfp_pairs(pairs)
    
    assert len(results) == 1
    hull = results[0]
    assert hull is not None
    
    # Square A + Square B (both 1x1) should be a 2x2 square if they are aligned correctly.
    # In this case A is (0,0)-(1,1) and -B is (-1,-1)-(0,0).
    # Vertices of A + (-B):
    # (0,0)+(-1,-1) = (-1,-1)
    # (1,1)+(0,0) = (1,1)
    # The bounds should be (-1, -1, 1, 1) -> width 2, height 2. area 4.
    
    assert pytest.approx(hull.area) == 4.0
    assert hull.bounds == (-1.0, -1.0, 1.0, 1.0)

@pytest.mark.skipif(not TAICHI_AVAILABLE, reason="Taichi not available")
def test_gpu_nfp_batch_correctness():
    poly_a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    poly_b_reflected = Polygon([(0, 0), (-1, 0), (-1, -1), (0, -1)])
    
    poly_a_list = [poly_a]
    poly_b_list = [poly_b_reflected]
    rotations_deg = [0.0, 90.0]
    
    results_per_rot = compute_nfp_batch(poly_a_list, poly_b_list, rotations_deg)
    
    assert len(results_per_rot) == 2
    for rot_results in results_per_rot:
        assert len(rot_results) == 1
        hull = rot_results[0]
        assert pytest.approx(hull.area) == 4.0

@pytest.mark.skipif(not TAICHI_AVAILABLE, reason="Taichi not available")
def test_gpu_convex_hull_empty_input():
    # Test with valid but very small polygons to ensure no crashes.
    poly_small_a = Polygon([(0,0), (0.001, 0), (0, 0.001)])
    poly_small_b = Polygon([(0,0), (0.001, 0), (0, 0.001)])
    
    pairs = [(poly_small_a, poly_small_b, 0.0)]
    results = compute_nfp_pairs(pairs)
    assert results[0] is not None
    assert results[0].area > 0

