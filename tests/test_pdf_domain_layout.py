from __future__ import annotations

import importlib


def test_pdf_domain_modules_are_primary_import_targets():
    modules = {
        "llmwiki.pdf.blocks": "SourceBlock",
        "llmwiki.pdf.quality": "evaluate_pdf_quality",
        "llmwiki.pdf.parser_backends": "PdfParseRequest",
        "llmwiki.pdf.chunks": "SourceChunk",
        "llmwiki.pdf.mineru_runner": "MinerUCommandRequest",
    }

    for module_name, attribute in modules.items():
        module = importlib.import_module(module_name)
        assert hasattr(module, attribute)


def test_legacy_pdf_modules_alias_domain_modules():
    aliases = {
        "llmwiki.pdf_blocks": "llmwiki.pdf.blocks",
        "llmwiki.pdf_quality": "llmwiki.pdf.quality",
        "llmwiki.pdf_parser_backends": "llmwiki.pdf.parser_backends",
        "llmwiki.source_chunks": "llmwiki.pdf.chunks",
        "llmwiki.mineru_runner": "llmwiki.pdf.mineru_runner",
    }

    for legacy_name, domain_name in aliases.items():
        legacy = importlib.import_module(legacy_name)
        domain = importlib.import_module(domain_name)
        assert legacy is domain
