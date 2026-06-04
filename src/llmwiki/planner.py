from __future__ import annotations

import sys

from .ask import planner as _module

globals().update(_module.__dict__)
sys.modules[__name__] = _module
