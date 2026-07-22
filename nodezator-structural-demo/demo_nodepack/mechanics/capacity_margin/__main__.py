"""Node: ramp load until yield — the imperative (while-loop) math node."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from demolib.mechanics import capacity_margin

main_callable = capacity_margin

third_party_import_text = "from demolib.mechanics import capacity_margin"
