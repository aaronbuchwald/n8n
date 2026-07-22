"""Node: axial stress sigma = P / A (unit-aware, via forallpeople)."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from demolib.mechanics import axial_stress

main_callable = axial_stress

third_party_import_text = "from demolib.mechanics import axial_stress"
