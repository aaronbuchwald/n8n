"""Node: select one row from the list of members."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from demolib.data import select_member

main_callable = select_member

third_party_import_text = "from demolib.data import select_member"
