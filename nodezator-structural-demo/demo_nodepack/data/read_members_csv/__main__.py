"""Node: read a CSV with named columns into a list of row dicts."""

import sys
from pathlib import Path

# Make the project's `demolib` importable whether this file is loaded by
# Nodezator (as a node script) or imported directly. parents[3] is the project
# root that contains the demolib package.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from demolib.data import read_members_csv

main_callable = read_members_csv

# Injected into exported graph code so the generated script is self-contained.
third_party_import_text = "from demolib.data import read_members_csv"
