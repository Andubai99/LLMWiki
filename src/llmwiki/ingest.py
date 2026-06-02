from __future__ import annotations

import sys

from .ingestion import ingest as _module

globals().update(_module.__dict__)
sys.modules[__name__] = _module
