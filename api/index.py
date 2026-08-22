import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# opentrons.config creates its settings dir at import time; only /tmp is
# writable in Vercel's serverless filesystem, unlike a normal home directory.
os.environ.setdefault("OT_API_CONFIG_DIR", "/tmp/opentrons")

from app import app  # noqa: E402
