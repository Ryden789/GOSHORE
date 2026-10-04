"""Run from the project root: python -m unittest discover -s scripts -p test_cube_vision.py."""
import copy
import unittest

from app.cube_vision import _clean


def fixture():
    return {"is_net": True, "cells": [
        {"r": r, "c": c, "kind": "image", "bbox": [c / 4, r / 3, (c + 1) / 4, (r + 1) / 3]}
        for r, c in [(0, 1), (1, 0), (1, 1), (1, 2), (1, 3), (2, 1)]
    ]}


class CubeVisionTests(unittest.TestCase):
    def test_preserves_original_bounds_and_unknown_artwork(self):
        data = fixture()
        data["cells"][0]["kind"] = "complex-pattern"
        result = _clean(data)
        self.assertEqual(len(result["cells"]), 6)
        self.assertEqual(result["cells"][0]["kind"], "image")
        self.assertEqual(result["cells"][0]["bbox"], data["cells"][0]["bbox"])

    def test_rejects_missing_or_invalid_bounds(self):
        for bounds in [None, [], [0, 0, 0, 1], [0, 1, 1, 0], [-1, 0, 1, 1],
                       [0, 0, float("nan"), 1], [False, 0, 1, 1], [0, 0, 2, 1]]:
            with self.subTest(bounds=bounds):
                data = fixture()
                data["cells"][0]["bbox"] = bounds
                with self.assertRaises(ValueError):
                    _clean(data)

    def test_rejects_disconnected_duplicate_fractional_cells(self):
        for update in [{"r": 5, "c": 5}, {"r": 1, "c": 0}, {"r": .5}, {"r": True}]:
            data = copy.deepcopy(fixture())
            data["cells"][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                _clean(data)

    def test_non_net(self):
        self.assertFalse(_clean({"is_net": False})["is_net"])


if __name__ == "__main__":
    unittest.main()
