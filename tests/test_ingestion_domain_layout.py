import importlib


def test_ingestion_domain_modules_exist() -> None:
    expected = {
        "llmwiki.ingestion.sources": "import_source",
        "llmwiki.ingestion.pipeline": "add_and_process_source",
        "llmwiki.ingestion.ingest": "ingest_source",
        "llmwiki.ingestion.llm_ingest": "create_llm_ingest_proposal",
        "llmwiki.ingestion.apply": "apply_run",
    }

    for module_name, public_name in expected.items():
        module = importlib.import_module(module_name)

        assert hasattr(module, public_name)


def test_ingestion_legacy_modules_alias_domain_modules() -> None:
    expected = {
        "llmwiki.sources": "llmwiki.ingestion.sources",
        "llmwiki.pipeline": "llmwiki.ingestion.pipeline",
        "llmwiki.ingest": "llmwiki.ingestion.ingest",
        "llmwiki.llm_ingest": "llmwiki.ingestion.llm_ingest",
        "llmwiki.apply": "llmwiki.ingestion.apply",
    }

    for legacy_name, domain_name in expected.items():
        legacy_module = importlib.import_module(legacy_name)
        domain_module = importlib.import_module(domain_name)

        assert legacy_module is domain_module
