"""LLM Wiki package."""

from __future__ import annotations

import sys as _sys

from .pdf import blocks as _pdf_blocks
from .pdf import chunks as _pdf_chunks
from .pdf import mineru_runner as _pdf_mineru_runner
from .pdf import parser_backends as _pdf_parser_backends
from .pdf import quality as _pdf_quality

_sys.modules.setdefault(f"{__name__}.pdf_blocks", _pdf_blocks)
_sys.modules.setdefault(f"{__name__}.pdf_quality", _pdf_quality)
_sys.modules.setdefault(f"{__name__}.pdf_parser_backends", _pdf_parser_backends)
_sys.modules.setdefault(f"{__name__}.source_chunks", _pdf_chunks)
_sys.modules.setdefault(f"{__name__}.mineru_runner", _pdf_mineru_runner)

pdf_blocks = _pdf_blocks
pdf_quality = _pdf_quality
pdf_parser_backends = _pdf_parser_backends
source_chunks = _pdf_chunks
mineru_runner = _pdf_mineru_runner

__version__ = "0.1.0"
