from __future__ import annotations

import sys

from .vector import index as _module

globals().update(_module.__dict__)
sys.modules[__name__] = _module
