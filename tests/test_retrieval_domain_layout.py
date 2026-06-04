import importlib


def test_retrieval_core_is_a_domain_package() -> None:
    module = importlib.import_module("llmwiki.retrieval")

    assert hasattr(module, "__path__")
    assert hasattr(module, "retrieve_context")


def test_retrieval_legacy_modules_alias_domain_modules() -> None:
    expected = {
        "llmwiki.query_analysis": "llmwiki.retrieval.query_analysis",
        "llmwiki.retrievers": "llmwiki.retrieval.retrievers",
        "llmwiki.rerankers": "llmwiki.retrieval.rerankers",
        "llmwiki.evidence_selection": "llmwiki.retrieval.evidence_selection",
        "llmwiki.retrieval_eval": "llmwiki.retrieval.eval",
        "llmwiki.query": "llmwiki.retrieval.query",
        "llmwiki.planned_retrieval": "llmwiki.retrieval.planned",
    }

    for legacy_name, domain_name in expected.items():
        legacy_module = importlib.import_module(legacy_name)
        domain_module = importlib.import_module(domain_name)

        assert legacy_module is domain_module
