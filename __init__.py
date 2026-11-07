"""rmfit -- agent-operable global R-matrix fitting on top of AZURE2 / pyazr.

See README.md for the layout.  Every module imports pyazr from ``AZURE2_ROOT``.
"""
import os
import sys

AZURE2_ROOT = os.environ.get("AZURE2_ROOT", "/users/rdeboer1/AZURE2")
if AZURE2_ROOT not in sys.path:
    sys.path.insert(0, AZURE2_ROOT)

#: Runtime options every CLI fit of the 13C+alpha archive uses
#: (``--no-long-wavelength --ignore-externals --use-brune``).  pyazr's own
#: defaults differ (``use_long_wavelength=True``), so pass these explicitly.
ARCHIVE_FLAGS = dict(use_long_wavelength=False, ignore_externals=True, use_brune=True)

__version__ = "0.1.0"
