import os
from pathlib import Path

import degen_sim

ROOT_DIR = str(Path(degen_sim.__file__).parent.resolve())
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(ROOT_DIR)), "data")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(ROOT_DIR)), "reports")
