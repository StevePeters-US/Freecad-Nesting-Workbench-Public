import pytest
import numpy as np
from shapely.geometry import Polygon, Point
from unittest.mock import MagicMock
from nestingworkbench.Tools.Nesting.algorithms.minkowski_engine import MinkowskiEngine
from nestingworkbench.Tools.Nesting.algorithms.nfp_gpu_taichi import TAICHI_AVAILABLE, is_available
from nestingworkbench.datatypes.shape import Shape

class MockPart:
    def __init__(self, poly, label="Part"):
        self.original_polygon = poly
        self.source_freecad_object = MagicMock()
        self.source_freecad_object.Label = label
        self.spacing = 0.0
        self.deflection = 0.5
        self.simplification = 0.0
        self.centroid = poly.centroid

class MockSheet:
    def __init__(self):
        self.parts = []
        self.nfp_cache = {}
        from threading import Lock
        self.nfp_cache_lock = Lock()

@pytest.mark.skipif(not TAICHI_AVAILABLE or not is_available(), reason="Taichi GPU not available")
def test_precompute_batch_format_matches_gpu_path():
    """
    NFP-004: Regression test to ensure precompute_nfp_batch produces the same 
    data format ('shells', 'holes') as _calculate_and_cache_nfp_gpu.
    """
    # Setup Engine
    engine = MinkowskiEngine(100, 100, 1.0, use_gpu=True)
    
    # Simple squares
    poly_a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    poly_b = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    
    part_a = MockPart(poly_a, "PartA")
    part_b = MockPart(poly_b, "PartB")
    
    # Mock a placed part p in sheet
    class PlacedPart:
        def __init__(self, shape, angle):
            self.shape = shape
            self.angle = angle
            
    sheet = MockSheet()
    sheet.parts.append(PlacedPart(part_a, 0.0))
    
    # Ensure cache is clear for this test
    with Shape.nfp_cache_lock:
        Shape.nfp_cache = {}
    
    # 1. Run precompute_nfp_batch
    engine.precompute_nfp_batch(part_b, [0.0], sheet)
    
    # 2. Check Shape.nfp_cache
    # Key: (label_A, label_B, angle, spacing, deflection, simplification)
    cache_key = ("PartA", "PartB", 0.0, 0.0, 0.5, 0.0)
    
    with Shape.nfp_cache_lock:
        assert cache_key in Shape.nfp_cache
        nfp_data = Shape.nfp_cache[cache_key]
    
    assert 'shells' in nfp_data, "Pre-cached entry must skip the 'shells' key"
    assert len(nfp_data['shells']) > 0, "Shells list must not be empty for non-empty NFPs"
    assert 'holes' in nfp_data
    assert 'polygon' in nfp_data
    assert not nfp_data['polygon'].is_empty
    
    # 3. Call get_global_nfp_for
    # This should pick up the pre-cached entry and populate entry['shells']
    entry = engine.get_global_nfp_for(part_b, 0.0, sheet)
    
    assert 'shells' in entry
    assert len(entry['shells']) > 0, "Sheet accumulation must have shells from pre-cache"
    assert 'points' in entry
    assert len(entry['points']) > 0, "Candidate points must be generated from pre-cache"
