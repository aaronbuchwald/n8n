"""Node: render the stress-check equations as LaTeX (handcalcs + forallpeople)."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from demolib.report import render_stress_check

main_callable = render_stress_check

third_party_import_text = "from demolib.report import render_stress_check"
