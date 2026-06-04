import importlib


def test_vector_domain_modules_exist() -> None:
    expected = {
        "llmwiki.vector.embeddings": "create_embedding_provider",
        "llmwiki.vector.index": "load_vector_index",
    }

    for module_name, public_name in expected.items():
        module = importlib.import_module(module_name)

        assert hasattr(module, public_name)


def test_vector_legacy_modules_alias_domain_modules() -> None:
    expected = {
        "llmwiki.embeddings": "llmwiki.vector.embeddings",
        "llmwiki.vector_index": "llmwiki.vector.index",
    }

    for legacy_name, domain_name in expected.items():
        legacy_module = importlib.import_module(legacy_name)
        domain_module = importlib.import_module(domain_name)

        assert legacy_module is domain_module
