import pytest
from unittest.mock import MagicMock
from nestingworkbench.Tools.Nesting.algorithms.genetic_utils import tournament_selection

@pytest.fixture
def mock_parts():
    parts = []
    for i in range(5):
        p = MagicMock()
        p.id = f"part_{i}"
        p._angle = 0
        p.set_rotation = MagicMock()
        parts.append(p)
    return parts


def test_tournament_selection():
    # ranked_population: [(fitness, chromosome)]
    # Lower fitness is better
    pop = [
        (10.0, "worse"),
        (1.0, "best"),
        (5.0, "mid")
    ]
    # k=2, should eventually pick the best if sample includes it
    # But let's test k=3 which is the full pop
    winner = tournament_selection(pop, k=3)
    assert winner == "best"


def test_tournament_selection_size_1():
    # T-020: Selection on a population of size 1
    pop = [(1.0, "only_one")]
    winner = tournament_selection(pop, k=3)
    assert winner == "only_one"
