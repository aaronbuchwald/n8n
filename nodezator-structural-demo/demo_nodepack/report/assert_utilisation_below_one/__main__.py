"""Node: acceptance check — assert the utilisation ratio f(x) < 1."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from demolib.report import assert_utilisation_below_one

main_callable = assert_utilisation_below_one

third_party_import_text = "from demolib.report import assert_utilisation_below_one"
