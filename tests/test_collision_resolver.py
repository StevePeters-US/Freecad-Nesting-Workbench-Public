import pytest
from nestingworkbench.Tools.ManualNester.collision_resolver import CollisionResolver

class MockVector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z
    
    def copy(self):
        return MockVector(self.x, self.y, self.z)

    def __add__(self, other):
        return MockVector(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        return MockVector(self.x - other.x, self.y - other.y, self.z - other.z)

    def __eq__(self, other):
        return abs(self.x - other.x) < 1e-5 and abs(self.y - other.y) < 1e-5 and abs(self.z - other.z) < 1e-5

    def __repr__(self):
        return f"MockVector({round(self.x, 6)}, {round(self.y, 6)}, {round(self.z, 6)})"

class MockBoundBox:
    def __init__(self, xmin, xmax, ymin, ymax):
        self.XMin = xmin
        self.XMax = xmax
        self.YMin = ymin
        self.YMax = ymax
        self.XLength = xmax - xmin
        self.YLength = ymax - ymin

class MockPlacement:
    def __init__(self, base):
        self.Base = base

    def multiply(self, other):
        """Non-rotated multiply: just add translations."""
        return MockPlacement(self.Base + other.Base)

    def multVec(self, vec):
        """Non-rotated transform: just translate."""
        return vec + self.Base

class MockShape:
    def __init__(self, bbox):
        self.BoundBox = bbox

class MockObj:
    def __init__(self, name, placement, shape):
        self.Name = name
        self.Placement = placement
        self.Shape = shape

@pytest.fixture
def resolver():
    return CollisionResolver()

def test_clamp_to_sheet_inside(resolver):
    sheet_bbox = MockBoundBox(0, 1000, 0, 1000)
    obj_bbox = MockBoundBox(0, 100, 0, 100)
    placement = MockPlacement(MockVector(500, 500, 0))
    obj = MockObj("part", placement, MockShape(obj_bbox))
    
    clamped = resolver.clamp_to_sheet(obj, sheet_bbox)
    assert not clamped
    assert obj.Placement.Base == MockVector(500, 500, 0)

def test_clamp_to_sheet_outside_xmin(resolver):
    sheet_bbox = MockBoundBox(0, 1000, 0, 1000)
    obj_bbox = MockBoundBox(0, 100, 0, 100)
    # obj_min_x = -10 + 0 = -10 (outside)
    placement = MockPlacement(MockVector(-10, 500, 0))
    obj = MockObj("part", placement, MockShape(obj_bbox))
    
    clamped = resolver.clamp_to_sheet(obj, sheet_bbox)
    assert clamped
    # Expected: new_x = -10 + (0 - (-10)) = 0
    assert obj.Placement.Base == MockVector(0, 500, 0)

def test_clamp_to_sheet_outside_xmax(resolver):
    sheet_bbox = MockBoundBox(0, 1000, 0, 1000)
    obj_bbox = MockBoundBox(0, 100, 0, 100)
    # obj_max_x = 950 + 100 = 1050 (outside)
    placement = MockPlacement(MockVector(950, 500, 0))
    obj = MockObj("part", placement, MockShape(obj_bbox))
    
    clamped = resolver.clamp_to_sheet(obj, sheet_bbox)
    assert clamped
    # Expected: new_x = 950 - (1050 - 1000) = 900
    assert obj.Placement.Base == MockVector(900, 500, 0)

def test_separate_overlapping_simple(resolver):
    # part1 at (0,0), size 100x100
    p1 = MockObj("p1", MockPlacement(MockVector(0, 0, 0)), MockShape(MockBoundBox(0, 100, 0, 100)))
    # part2 at (80, 50), size 100x100 -> overlap (80,50) to (100, 150)
    # overlap_x = 100 - 80 = 20
    # overlap_y = 100 - 50 = 50 -> push along X
    p2 = MockObj("p2", MockPlacement(MockVector(80, 50, 0)), MockShape(MockBoundBox(0, 100, 0, 100)))
    
    # We move p2
    resolved = resolver.separate_overlapping(p2, [p1])
    assert resolved
    # p2 was at (80, 50), center (130, 100)
    # p1 center (50, 50)
    # p2.center_x > p1.center_x -> push in +X direction
    # expected p2.x = 80 + 20 + 0.001 = 100.001
    assert p2.Placement.Base == MockVector(100.001, 50, 0)

def test_separate_overlapping_multiple(resolver):
    # p1 at (0,0), size 100x100
    p1 = MockObj("p1", MockPlacement(MockVector(0, 0, 0)), MockShape(MockBoundBox(0, 100, 0, 100)))
    # p2 at (250, 0), size 100x100 -> starts at 250, ends at 350.
    p2 = MockObj("p2", MockPlacement(MockVector(250, 0, 0)), MockShape(MockBoundBox(0, 100, 0, 100)))
    
    # p_moved at (80, 0) -> overlaps p1 (0-100) by 20.
    # Initial pm: 80 to 180.
    # After p1 resolution: pm at (100, 0) -> 100 to 200.
    # pm (100-200) does NOT overlap p2 (250-350).
    p_moved = MockObj("pm", MockPlacement(MockVector(80, 0, 0)), MockShape(MockBoundBox(0, 100, 0, 100)))
    
    resolved = resolver.separate_overlapping(p_moved, [p1, p2])
    assert resolved
    assert p_moved.Placement.Base == MockVector(100.001, 0, 0)

def test_resolve_bi_collision(resolver):
    # p1 at (0,0), size 100x100
    p1 = MockObj("p1", MockPlacement(MockVector(0, 0, 0)), MockShape(MockBoundBox(0, 100, 0, 100)))
    # p2 at (80, 0), size 100x100 -> overlap of 20 in X
    p2 = MockObj("p2", MockPlacement(MockVector(80, 0, 0)), MockShape(MockBoundBox(0, 100, 0, 100)))
    
    # resolve_bi_collision should shift both by 10/2 + epsilon/2 = ~10
    # Wait, shift = ox / 2.0. ox = 20.001. shift = 10.0005
    # dir_x for p1 (center_x=50) vs p2 (center_x=130): 1.0 if 50 > 130 else -1.0 -> -1.0
    # p1 shift: -10.0005
    # p2 shift: -(-10.0005) = 10.0005
    # p1 new x: 0 - 10.0005 = -10.0005
    # p2 new x: 80 + 10.0005 = 90.0005
    
    resolved = resolver.resolve_bi_collision(p1, p2)
    assert resolved
    assert abs(p1.Placement.Base.x - (-10.0005)) < 1e-4
    assert abs(p2.Placement.Base.x - (90.0005)) < 1e-4
