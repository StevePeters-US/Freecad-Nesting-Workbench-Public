import pytest
from unittest.mock import MagicMock
from shapely.geometry import Polygon

from nestingworkbench.Tools.Nesting.algorithms.base_nester import BaseNester


class StubNester(BaseNester):
    """Concrete subclass for testing — always places the part unchanged."""
    def __init__(self, width, height, **kwargs):
        super().__init__(width, height, **kwargs)
        self.force_fail_ids = set()

    def _try_place_part_on_sheet(self, shape, sheet):
        if getattr(shape, 'id', None) in self.force_fail_ids:
            return None
        return shape


def make_shape(polygon, part_id="P1"):
    shape = MagicMock()
    shape.id = part_id
    shape.polygon = polygon
    shape.original_polygon = polygon
    shape.area = polygon.area
    shape.centroid = polygon.centroid
    shape.angle = 0.0
    shape.get_final_placement.return_value = MagicMock()
    shape.placement = None
    return shape


class TestGetCurveP:
    def test_linear_endpoints(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(0.0, "Linear") == pytest.approx(0.0)
        assert n._get_curve_p(1.0, "Linear") == pytest.approx(1.0)

    def test_linear_midpoint(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(0.5, "Linear") == pytest.approx(0.5)

    def test_logarithmic_endpoints(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(0.0, "Logarithmic") == pytest.approx(0.0)
        assert n._get_curve_p(1.0, "Logarithmic") == pytest.approx(1.0)

    def test_quadratic(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(0.5, "Quadratic") == pytest.approx(0.25)

    def test_power_15(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(0.5, "Power 1.5") == pytest.approx(0.5 ** 1.5)

    def test_clamped_below_zero(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(-1.0, "Linear") == pytest.approx(0.0)

    def test_clamped_above_one(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(2.0, "Linear") == pytest.approx(1.0)

    def test_unknown_curve_falls_back_to_linear(self):
        n = StubNester(100, 100)
        assert n._get_curve_p(0.7, "Unknown") == pytest.approx(0.7)


class TestEvaluatePlacement:
    def test_downward_gravity(self):
        n = StubNester(100, 100)
        poly = Polygon([(10, 10), (20, 10), (20, 20), (10, 20)])
        shape = MagicMock()
        shape.centroid = poly.centroid  # centroid at (15, 15)
        score = n._evaluate_placement(shape, (0, -1))
        assert score == pytest.approx(-15.0)

    def test_rightward_gravity(self):
        n = StubNester(100, 100)
        poly = Polygon([(10, 10), (20, 10), (20, 20), (10, 20)])
        shape = MagicMock()
        shape.centroid = poly.centroid
        score = n._evaluate_placement(shape, (1, 0))
        assert score == pytest.approx(15.0)

    def test_none_centroid_returns_negative_inf(self):
        n = StubNester(100, 100)
        shape = MagicMock()
        shape.centroid = None
        assert n._evaluate_placement(shape, (0, -1)) == -float('inf')


class TestNestGreedyLoop:
    def test_single_part_placed_on_new_sheet(self):
        n = StubNester(100, 100)
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        part = make_shape(poly, "A")

        sheets, unplaced = n.nest([part], sort=False)

        assert len(sheets) == 1
        assert len(sheets[0].parts) == 1
        assert len(unplaced) == 0

    def test_unplaceable_part_goes_to_unplaced(self):
        n = StubNester(100, 100)
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        part = make_shape(poly, "A")
        n.force_fail_ids.add("A")

        sheets, unplaced = n.nest([part], sort=False)

        assert len(sheets) == 0
        assert len(unplaced) == 1

    def test_multiple_parts_same_sheet(self):
        n = StubNester(100, 100)
        parts = [make_shape(Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]), f"P{i}") for i in range(3)]

        sheets, unplaced = n.nest(parts, sort=False)

        assert len(sheets) >= 1
        assert len(unplaced) == 0

    def test_cancel_callback_stops_early(self):
        call_count = [0]
        def cancel():
            call_count[0] += 1
            return True

        n = StubNester(100, 100, cancel_callback=cancel)
        parts = [make_shape(Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]), f"P{i}") for i in range(10)]

        sheets, unplaced = n.nest(parts, sort=False)
        assert len(sheets) + len(unplaced) < 10

    def test_sort_places_largest_first(self):
        placed_order = []

        class TrackingNester(BaseNester):
            def _try_place_part_on_sheet(self, shape, sheet):
                placed_order.append(shape.id)
                return shape

        n = TrackingNester(100, 100)
        small = make_shape(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), "small")
        large = make_shape(Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]), "large")

        n.nest([small, large], sort=True)
        assert placed_order[0] == "large"

    def test_progress_callback_called_for_each_part(self):
        calls = []
        n = StubNester(100, 100)
        n.progress_callback = lambda cur, total, msg: calls.append(cur)
        parts = [make_shape(Polygon([(0, 0), (5, 0), (5, 5), (0, 5)]), f"P{i}") for i in range(3)]

        n.nest(parts, sort=False)
        assert calls == [1, 2, 3]
