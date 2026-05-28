from __future__ import annotations

from llmwiki.query_analysis import analyze_query, normalize_unicode


def test_analyze_chinese_natural_question_with_catalog_term():
    query = analyze_query("草莓应该怎么保存？", catalog_terms=["草莓"])

    assert query.original == "草莓应该怎么保存？"
    assert query.normalized == "草莓应该怎么保存?"
    assert "草莓" in query.text_terms
    assert "保存" in query.text_terms
    assert "草莓" in query.catalog_terms
    assert "应该" in query.stop_terms
    assert "怎么" in query.stop_terms
    assert {"冷藏", "储存"} & set(query.expanded_terms)


def test_normalize_unicode_folds_full_width_and_compatibility_forms():
    assert normalize_unicode("维生素Ｃ水果") == "维生素C水果"
    query = analyze_query("维生素Ｃ水果")

    assert "维生素C" in query.text_terms
    assert "维生素" in query.text_terms


def test_formula_spans_keep_original_and_normalized_forms():
    water = analyze_query("H₂O 的性质")
    energy = analyze_query("E=mc² 表示什么？")

    assert "H₂O" in water.formula_spans
    assert "H2O" in water.formula_spans
    assert "E=mc²" in energy.formula_spans
    assert "E=mc2" in energy.formula_spans


def test_symbol_and_emoji_spans_are_not_discarded():
    ratio = analyze_query("α/β ratio 怎么解释？")
    apple = analyze_query("🍎 营养")

    assert "α/β" in ratio.symbol_spans
    assert "ratio" in ratio.text_terms
    assert "🍎" in apple.symbol_spans
    assert "营养" in apple.text_terms
