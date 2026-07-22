"""Node: explode one member row into individual scalar output sockets.

Demonstrates Nodezator's multiple-named-outputs feature — see the list-of-dicts
return annotation on ``unpack_member`` in ``demolib/data.py``.
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from demolib.data import unpack_member

main_callable = unpack_member

third_party_import_text = "from demolib.data import unpack_member"
