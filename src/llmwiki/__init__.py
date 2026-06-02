"""LLM Wiki package."""

from __future__ import annotations

import sys as _sys

from .ask import answer as _ask_answer
from .ask import planner as _ask_planner
from .ingestion import apply as _ingestion_apply
from .ingestion import ingest as _ingestion_ingest
from .ingestion import llm_ingest as _ingestion_llm_ingest
from .ingestion import pipeline as _ingestion_pipeline
from .ingestion import sources as _ingestion_sources
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
from .vector import embeddings as _vector_embeddings
from .vector import index as _vector_index

_sys.modules.setdefault(f"{__name__}.pdf_blocks", _pdf_blocks)
_sys.modules.setdefault(f"{__name__}.pdf_quality", _pdf_quality)
_sys.modules.setdefault(f"{__name__}.pdf_parser_backends", _pdf_parser_backends)
_sys.modules.setdefault(f"{__name__}.source_chunks", _pdf_chunks)
_sys.modules.setdefault(f"{__name__}.mineru_runner", _pdf_mineru_runner)
_sys.modules.setdefault(f"{__name__}.sources", _ingestion_sources)
_sys.modules.setdefault(f"{__name__}.pipeline", _ingestion_pipeline)
_sys.modules.setdefault(f"{__name__}.ingest", _ingestion_ingest)
_sys.modules.setdefault(f"{__name__}.llm_ingest", _ingestion_llm_ingest)
_sys.modules.setdefault(f"{__name__}.apply", _ingestion_apply)
_sys.modules.setdefault(f"{__name__}.answer", _ask_answer)
_sys.modules.setdefault(f"{__name__}.planner", _ask_planner)
_sys.modules.setdefault(f"{__name__}.query_analysis", _retrieval_query_analysis)
_sys.modules.setdefault(f"{__name__}.retrievers", _retrieval_retrievers)
_sys.modules.setdefault(f"{__name__}.rerankers", _retrieval_rerankers)
_sys.modules.setdefault(f"{__name__}.evidence_selection", _retrieval_evidence_selection)
_sys.modules.setdefault(f"{__name__}.retrieval_eval", _retrieval_eval)
_sys.modules.setdefault(f"{__name__}.query", _retrieval_query)
_sys.modules.setdefault(f"{__name__}.planned_retrieval", _retrieval_planned)
_sys.modules.setdefault(f"{__name__}.synthesis_pages", _synthesis_pages)
_sys.modules.setdefault(f"{__name__}.synthesis_planner", _synthesis_planner)
_sys.modules.setdefault(f"{__name__}.embeddings", _vector_embeddings)
_sys.modules.setdefault(f"{__name__}.vector_index", _vector_index)

pdf_blocks = _pdf_blocks
pdf_quality = _pdf_quality
pdf_parser_backends = _pdf_parser_backends
source_chunks = _pdf_chunks
mineru_runner = _pdf_mineru_runner
sources = _ingestion_sources
pipeline = _ingestion_pipeline
ingest = _ingestion_ingest
llm_ingest = _ingestion_llm_ingest
apply = _ingestion_apply
answer = _ask_answer
planner = _ask_planner
query_analysis = _retrieval_query_analysis
retrievers = _retrieval_retrievers
rerankers = _retrieval_rerankers
evidence_selection = _retrieval_evidence_selection
retrieval_eval = _retrieval_eval
query = _retrieval_query
planned_retrieval = _retrieval_planned
synthesis_pages = _synthesis_pages
synthesis_planner = _synthesis_planner
embeddings = _vector_embeddings
vector_index = _vector_index

__version__ = "0.1.0"
