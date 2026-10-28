"""Branching PhysBone roots need their own rest axis, not a child-head axis."""
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "py"))
import sway_hub_placement as placement


def test_root_rest_rotation_is_preserved_when_child_is_not_on_root_tail():
    # Minimal branching-chain example: the selected branch is 27 degrees
    # away from the root's rest axis. The old placement trips the 16.5 deg gate.
    cp = SimpleNamespace(source_chain=("root", "child"),
                         weight_expansion={}, representative_source=())
    gp = SimpleNamespace(chain_plans=(cp,))
    dump = {"root": {"head": (0, 0, 0), "tail": (1, 0, 0)},
            "child": {"head": (math.cos(math.radians(27)), math.sin(math.radians(27)), 0),
                      "tail": (2, 1, 0)}}
    _, head, quat = placement._hub_root_real_segment_transform(
        "hub", gp, placement.Similarity(1, (0, 0, 0), (0, 0, 0)), dump,
        (0, 0, 0), (0, 0, 0, 1), {})
    direction = placement.q_rotate(quat, (1, 0, 0))
    assert head == (0, 0, 0)
    assert direction == pytest.approx((1, 0, 0))
