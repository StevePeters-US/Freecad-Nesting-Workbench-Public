import pytest
import numpy as np
from unittest.mock import MagicMock
from shapely.geometry import Polygon

from nestingworkbench.Tools.Nesting.algorithms.nesting_strategy import PlacementOptimizer


def make_engine(bin_width=100, bin_height=100):
    engine = MagicMock()
    engine.bin_width = bin_width
    engine.bin_height = bin_height
    engine.use_gpu = False
    return engine


def make_part(polygon):
    part = MagicMock()
    part.original_polygon = polygon
    part.id = "test_part"
    return part


class TestGetCandidatesForRotation:
    def test_returns_four_corners_when_no_nfp_points(self):
        engine = make_engine(100, 100)
        opt = PlacementOptimizer(engine, rotation_steps=1, search_direction=(0, -1))
        part = make_part(Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]))
        nfp_entry = {'points': np.empty((0, 2), dtype=np.float32)}

        result = opt._get_candidates_for_rotation(0, part, MagicMock(), nfp_entry=nfp_entry)

        assert result.shape == (4, 2)

    def test_includes_nfp_points_inside_bin(self):
        engine = make_engine(100, 100)
        opt = PlacementOptimizer(engine, rotation_steps=1, search_direction=(0, -1))
        part = make_part(Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]))
        nfp_pts = np.array([[50, 50], [150, 150]], dtype=np.float32)  # one in, one out
        nfp_entry = {'points': nfp_pts}

        result = opt._get_candidates_for_rotation(0, part, MagicMock(), nfp_entry=nfp_entry)

        # 4 corners + 1 valid point
        assert len(result) == 5

    def test_excludes_nfp_points_outside_bin(self):
        engine = make_engine(100, 100)
        opt = PlacementOptimizer(engine, rotation_steps=1, search_direction=(0, -1))
        part = make_part(Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]))
        nfp_pts = np.array([[200, 200], [300, 300]], dtype=np.float32)  # both outside
        nfp_entry = {'points': nfp_pts}

        result = opt._get_candidates_for_rotation(0, part, MagicMock(), nfp_entry=nfp_entry)

        assert len(result) == 4  # Only corners

    def test_returns_empty_when_engine_returns_none(self):
        engine = make_engine(100, 100)
        engine.get_global_nfp_for.return_value = None
        opt = PlacementOptimizer(engine, rotation_steps=1, search_direction=(0, -1))
        part = make_part(Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]))

        result = opt._get_candidates_for_rotation(0, part, MagicMock(), nfp_entry=None)

        assert len(result) == 0

    def test_corners_account_for_part_bounds(self):
        """Corners are offset by part bounds so the part fits inside the bin."""
        engine = make_engine(100, 100)
        opt = PlacementOptimizer(engine, rotation_steps=1, search_direction=(0, -1))
        # 20x20 part: bounds go from 0..20 in both axes
        part = make_part(Polygon([(0, 0), (20, 0), (20, 20), (0, 20)]))
        nfp_entry = {'points': np.empty((0, 2), dtype=np.float32)}

        result = opt._get_candidates_for_rotation(0, part, MagicMock(), nfp_entry=nfp_entry)

        # At 0-rotation: min_x=min_y=0, max_x=max_y=20
        # corners should be (0,0), (80,0), (0,80), (80,80)
        xs = sorted(set(result[:, 0]))
        ys = sorted(set(result[:, 1]))
        assert xs == pytest.approx([0, 80])
        assert ys == pytest.approx([0, 80])


class TestPlacementOptimizerInit:
    def test_rotation_steps_minimum_one(self):
        engine = make_engine()
        opt = PlacementOptimizer(engine, rotation_steps=0, search_direction=(1, 0))
        assert opt.rotation_steps == 1

    def test_stores_search_direction(self):
        engine = make_engine()
        opt = PlacementOptimizer(engine, rotation_steps=4, search_direction=(1, 0))
        assert opt.search_direction == (1, 0)

    def test_trial_callback_defaults_none(self):
        engine = make_engine()
        opt = PlacementOptimizer(engine, rotation_steps=1, search_direction=(0, -1))
        assert opt.trial_callback is None
