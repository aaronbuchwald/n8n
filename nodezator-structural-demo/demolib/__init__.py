"""demolib — plain Python engineering functions.

These are ordinary, framework-free callables. They know nothing about
Nodezator: they can be imported and called from any script (see
``run_demo.py``) or wrapped as visual nodes (see ``demo_nodepack/``).

That separation is the whole point of the accompanying write-up: the app is
just a skin over these functions. Delete Nodezator and everything here still
runs.
"""

from .data import read_members_csv, select_member, unpack_member
from .mechanics import axial_stress, capacity_margin
from .report import render_stress_check, assert_utilisation_below_one

__all__ = [
    "read_members_csv",
    "select_member",
    "unpack_member",
    "axial_stress",
    "capacity_margin",
    "render_stress_check",
    "assert_utilisation_below_one",
]
