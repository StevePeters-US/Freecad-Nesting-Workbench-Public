import math

import pytest

from nestingworkbench.Tools.ManualNester.physics_engine import PhysicsEngine


class MockVector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z

    @property
    def Length(self):
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def __eq__(self, other):
        return (abs(self.x - other.x) < 1e-6
                and abs(self.y - other.y) < 1e-6
                and abs(self.z - other.z) < 1e-6)

    def __repr__(self):
        return f"MockVector({self.x}, {self.y}, {self.z})"


def test_compute_falloff():
    pe = PhysicsEngine(radius=200.0, curve_exponent=2.0, strength=1.0)

    # distance = 0 -> 1.0
    assert pe.compute_falloff(0) == 1.0

    # distance = radius -> 0.0
    assert pe.compute_falloff(200.0) == 0.0

    # distance = radius/2 -> 1 - (100/200)^2 = 1 - 0.25 = 0.75
    assert pe.compute_falloff(100.0) == 0.75

    # distance > radius -> 0.0
    assert pe.compute_falloff(250.0) == 0.0


def test_compute_displacements_point_parts():
    """Point-like parts (zero size) — gap distance equals center distance."""
    pe = PhysicsEngine(radius=100.0, curve_exponent=1.0, strength=1.0)

    dragged_center = MockVector(0, 0, 0)
    drag_delta = MockVector(10, 0, 0)

    # (obj, center, width, height) — zero-size parts
    parts_info = [
        ("part1", MockVector(50, 0, 0), 0, 0),   # gap 50 -> falloff 0.5
        ("part2", MockVector(0, 50, 0), 0, 0),   # gap 50 -> falloff 0.5
        ("part3", MockVector(150, 0, 0), 0, 0),  # gap 150 -> falloff 0.0
    ]

    displacements = pe.compute_displacements(
        dragged_center, 0, 0, drag_delta, parts_info
    )

    assert len(displacements) == 3

    # part1: pushed along +X, magnitude = 10 * 0.5 = 5
    assert displacements[0][0] == "part1"
    assert displacements[0][1] == MockVector(5, 0, 0)

    # part2: pushed along +Y, magnitude = 10 * 0.5 = 5
    assert displacements[1][0] == "part2"
    assert displacements[1][1] == MockVector(0, 5, 0)

    # part3: outside radius — no displacement
    assert displacements[2][0] == "part3"
    assert displacements[2][1] == MockVector(0, 0, 0)


def test_compute_displacements_with_dimensions():
    """Parts with real dimensions — gap distance is edge-to-edge, not center-to-center."""
    pe = PhysicsEngine(radius=100.0, curve_exponent=1.0, strength=1.0)

    dragged_center = MockVector(0, 0, 0)
    drag_delta = MockVector(10, 0, 0)

    # Dragged part is 20x20, other part is 20x20, centers are 50 apart on X
    # gap_x = |50| - (20+20)/2 = 50 - 20 = 30
    # gap_y = max(0, 0 - 20) = 0
    # edge_distance = 30 -> falloff = 1 - 30/100 = 0.7
    parts_info = [
        ("part1", MockVector(50, 0, 0), 20, 20),
    ]

    displacements = pe.compute_displacements(
        dragged_center, 20, 20, drag_delta, parts_info
    )

    # push_magnitude = 10 * 0.7 = 7, direction = (1, 0)
    assert displacements[0][0] == "part1"
    assert displacements[0][1] == MockVector(7, 0, 0)


def test_compute_displacements_overlapping():
    """Parts whose bounding boxes overlap have gap distance 0 — full falloff."""
    pe = PhysicsEngine(radius=100.0, curve_exponent=1.0, strength=1.0)

    dragged_center = MockVector(0, 0, 0)
    drag_delta = MockVector(10, 0, 0)

    # Dragged 40x40, other 40x40, center only 20 apart — boxes overlap
    # gap_x = max(0, |20| - (40+40)/2) = max(0, 20 - 40) = 0
    # edge_distance = 0 -> falloff = 1.0
    parts_info = [
        ("part1", MockVector(20, 0, 0), 40, 40),
    ]

    displacements = pe.compute_displacements(
        dragged_center, 40, 40, drag_delta, parts_info
    )

    # push_magnitude = 10 * 1.0 = 10, direction = (1, 0)
    assert displacements[0][0] == "part1"
    assert displacements[0][1] == MockVector(10, 0, 0)


def test_strength():
    pe = PhysicsEngine(radius=100.0, curve_exponent=1.0, strength=2.0)

    dragged_center = MockVector(0, 0, 0)
    drag_delta = MockVector(10, 0, 0)

    # gap = 50, falloff = 0.5, strength = 2.0 -> factor = 1.0
    # push_magnitude = 10 * 1.0 = 10
    parts_info = [
        ("part1", MockVector(50, 0, 0), 0, 0),
    ]

    displacements = pe.compute_displacements(
        dragged_center, 0, 0, drag_delta, parts_info
    )

    assert displacements[0][1] == MockVector(10, 0, 0)


def test_coincident_centers():
    """Parts at the exact same position get zero displacement (no division by zero)."""
    pe = PhysicsEngine(radius=100.0, curve_exponent=1.0, strength=1.0)

    dragged_center = MockVector(0, 0, 0)
    drag_delta = MockVector(10, 0, 0)

    parts_info = [
        ("part1", MockVector(0, 0, 0), 10, 10),
    ]

    displacements = pe.compute_displacements(
        dragged_center, 10, 10, drag_delta, parts_info
    )

    assert displacements[0][1] == MockVector(0, 0, 0)


def test_diagonal_repulsion():
    """Part at 45 degrees is pushed diagonally away."""
    pe = PhysicsEngine(radius=200.0, curve_exponent=1.0, strength=1.0)

    dragged_center = MockVector(0, 0, 0)
    drag_delta = MockVector(10, 0, 0)

    dist = 100.0  # center-to-center along diagonal
    c = dist / math.sqrt(2)
    parts_info = [
        ("part1", MockVector(c, c, 0), 0, 0),
    ]

    displacements = pe.compute_displacements(
        dragged_center, 0, 0, drag_delta, parts_info
    )

    # gap = 100, falloff = 1 - 100/200 = 0.5, push = 10 * 0.5 = 5
    # direction = (c/100, c/100) = (1/sqrt2, 1/sqrt2)
    expected_component = 5.0 / math.sqrt(2)
    result = displacements[0][1]
    assert abs(result.x - expected_component) < 1e-6
    assert abs(result.y - expected_component) < 1e-6
