from __future__ import annotations

import sys

from .ingestion import llm_ingest as _module

globals().update(_module.__dict__)
sys.modules[__name__] = _module
