from unittest.mock import MagicMock
import pytest
from shapely.geometry import Polygon
from nestingworkbench.datatypes.sheet import Sheet

def test_sheet_is_placement_valid_containment():
    sheet = Sheet("test_sheet", 100, 100)
    
    # Valid placement: strictly inside
    shape_inside = MagicMock()
    shape_inside.polygon = Polygon([(10, 10), (20, 10), (20, 20), (10, 20)])
    assert sheet.is_placement_valid(shape_inside) is True
    
    # Invalid placement: partially outside
    shape_partially_outside = MagicMock()
    shape_partially_outside.polygon = Polygon([(90, 90), (110, 90), (110, 110), (90, 110)])
    assert sheet.is_placement_valid(shape_partially_outside) is False
    
    # Invalid placement: completely outside
    shape_completely_outside = MagicMock()
    shape_completely_outside.polygon = Polygon([(110, 110), (120, 110), (120, 120), (110, 120)])
    assert sheet.is_placement_valid(shape_completely_outside) is False

def test_sheet_is_placement_valid_collision():
    sheet = Sheet("test_sheet", 100, 100)
    
    # Add a part to the sheet
    shape1 = MagicMock()
    shape1.polygon = Polygon([(10, 10), (30, 10), (30, 30), (10, 30)])
    shape1.area = 400.0
    placed_part1 = MagicMock()
    placed_part1.shape = shape1
    sheet.add_part(placed_part1)
    
    # Valid placement: no collision
    shape2_valid = MagicMock()
    shape2_valid.polygon = Polygon([(40, 40), (60, 40), (60, 60), (40, 60)])
    assert sheet.is_placement_valid(shape2_valid) is True
    
    # Invalid placement: collision with shape1
    shape2_invalid = MagicMock()
    shape2_invalid.polygon = Polygon([(20, 20), (40, 20), (40, 40), (20, 40)])
    assert sheet.is_placement_valid(shape2_invalid) is False
    
    # Edge case: shared boundary (Shapely's intersects returns True for shared boundary)
    shape2_edge = MagicMock()
    shape2_edge.polygon = Polygon([(30, 10), (50, 10), (50, 30), (30, 30)])
    # In nesting, we usually want to avoid even boundary sharing if spacing is involved, 
    # but here is_placement_valid uses .intersects() which is True for shared boundary.
    assert sheet.is_placement_valid(shape2_edge) is False


