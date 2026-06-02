"""LLM Wiki package."""

from __future__ import annotations

import sys as _sys

from .pdf import blocks as _pdf_blocks
from .pdf import chunks as _pdf_chunks
from .pdf import mineru_runner as _pdf_mineru_runner
from .pdf import parser_backends as _pdf_parser_backends
from .pdf import quality as _pdf_quality
from .retrieval import evidence_selection as _retrieval_evidence_selection
from .retrieval import eval as _retrieval_eval
from .retrieval import planned as _retrieval_planned
from .retrieval import query as _retrieval_query
from .retrieval import query_analysis as _retrieval_query_analysis
from .retrieval import rerankers as _retrieval_rerankers
from .retrieval import retrievers as _retrieval_retrievers
from .synthesis import pages as _synthesis_pages
from .synthesis import planner as _synthesis_planner

_sys.modules.setdefault(f"{__name__}.pdf_blocks", _pdf_blocks)
_sys.modules.setdefault(f"{__name__}.pdf_quality", _pdf_quality)
_sys.modules.setdefault(f"{__name__}.pdf_parser_backends", _pdf_parser_backends)
_sys.modules.setdefault(f"{__name__}.source_chunks", _pdf_chunks)
_sys.modules.setdefault(f"{__name__}.mineru_runner", _pdf_mineru_runner)
_sys.modules.setdefault(f"{__name__}.query_analysis", _retrieval_query_analysis)
_sys.modules.setdefault(f"{__name__}.retrievers", _retrieval_retrievers)
_sys.modules.setdefault(f"{__name__}.rerankers", _retrieval_rerankers)
_sys.modules.setdefault(f"{__name__}.evidence_selection", _retrieval_evidence_selection)
_sys.modules.setdefault(f"{__name__}.retrieval_eval", _retrieval_eval)
_sys.modules.setdefault(f"{__name__}.query", _retrieval_query)
_sys.modules.setdefault(f"{__name__}.planned_retrieval", _retrieval_planned)
_sys.modules.setdefault(f"{__name__}.synthesis_pages", _synthesis_pages)
_sys.modules.setdefault(f"{__name__}.synthesis_planner", _synthesis_planner)

pdf_blocks = _pdf_blocks
pdf_quality = _pdf_quality
pdf_parser_backends = _pdf_parser_backends
source_chunks = _pdf_chunks
mineru_runner = _pdf_mineru_runner
query_analysis = _retrieval_query_analysis
retrievers = _retrieval_retrievers
rerankers = _retrieval_rerankers
evidence_selection = _retrieval_evidence_selection
retrieval_eval = _retrieval_eval
query = _retrieval_query
planned_retrieval = _retrieval_planned
synthesis_pages = _synthesis_pages
synthesis_planner = _synthesis_planner

__version__ = "0.1.0"
