import importlib


def test_synthesis_core_is_a_domain_package() -> None:
    module = importlib.import_module("llmwiki.synthesis")

    assert hasattr(module, "__path__")
    assert hasattr(module, "create_synthesis_run")


def test_synthesis_legacy_modules_alias_domain_modules() -> None:
    expected = {
        "llmwiki.synthesis_pages": "llmwiki.synthesis.pages",
        "llmwiki.synthesis_planner": "llmwiki.synthesis.planner",
    }

    for legacy_name, domain_name in expected.items():
        legacy_module = importlib.import_module(legacy_name)
        domain_module = importlib.import_module(domain_name)

        assert legacy_module is domain_module
