import importlib


def test_ask_domain_modules_exist() -> None:
    expected = {
        "llmwiki.ask.answer": "answer_question",
        "llmwiki.ask.planner": "plan_question",
    }

    for module_name, public_name in expected.items():
        module = importlib.import_module(module_name)

        assert hasattr(module, public_name)


def test_ask_legacy_modules_alias_domain_modules() -> None:
    expected = {
        "llmwiki.answer": "llmwiki.ask.answer",
        "llmwiki.planner": "llmwiki.ask.planner",
    }

    for legacy_name, domain_name in expected.items():
        legacy_module = importlib.import_module(legacy_name)
        domain_module = importlib.import_module(domain_name)

        assert legacy_module is domain_module
