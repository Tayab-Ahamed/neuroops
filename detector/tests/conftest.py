"""
conftest.py for detector tests.

Ensures the detector/ source directory is the FIRST entry on sys.path so that
`from server import active_alerts, app` in test_server.py resolves to
detector/server.py rather than any other server.py that might be on the path.
"""

import os
import sys

# Insert detector source root at position 0 (highest priority)
_detector_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _detector_root not in sys.path:
    sys.path.insert(0, _detector_root)
elif sys.path[0] != _detector_root:
    sys.path.remove(_detector_root)
    sys.path.insert(0, _detector_root)
