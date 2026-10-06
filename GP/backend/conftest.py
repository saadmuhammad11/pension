import os
import sys
import tempfile

# Make the `gpf` package importable when running pytest from anywhere.
sys.path.insert(0, os.path.dirname(__file__))

# Route API persistence to a throwaway dir so tests never touch backend/data -- nor the shared
# portal database, which is where cases go by default (GPF_DB).
_TMP = tempfile.mkdtemp(prefix="gpf-test-")
os.environ.setdefault("GPF_DATA_DIR", _TMP)
os.environ.setdefault("GPF_DB", os.path.join(_TMP, "portal.sqlite3"))
