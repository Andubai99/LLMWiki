from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


STOP_TERMS = (
    "应该",
    "怎么",
    "如何",
    "为什么",
    "吗",
    "呢",
    "可以",
    "是否",
    "哪个",
    "哪种",
    "什么",
)

EXPANSIONS: dict[str, tuple[str, ...]] = {
    "保存": ("冷藏", "储存", "存放", "久放", "尽快食用", "保持干燥"),
    "储存": ("保存", "冷藏", "存放", "久放"),
    "营养": ("维生素", "膳食纤维", "矿物质", "热量"),
    "怎么吃": ("食用", "搭配", "做法", "适合"),
    "适合": ("建议", "不建议", "人群", "注意"),
    "补充": ("富含", "含有", "摄入"),
    "比较": ("哪种", "更", "优势", "差异"),
    "血糖": ("糖分", "含糖量", "不建议", "控制血糖"),
    "糖分": ("含糖量", "血糖", "不建议"),
    "能量": ("热量", "糖分", "注意"),
}


@dataclass(frozen=True)
class RetrievalQuery:
    original: str
    normalized: str
    text_terms: list[str]
    expanded_terms: list[str]
    catalog_terms: list[str]
    ngrams: list[str]
    exact_spans: list[str]
    symbol_spans: list[str]
    formula_spans: list[str]
    stop_terms: list[str]

    def all_terms(self) -> list[str]:
        return unique(
            [
                *self.text_terms,
                *self.expanded_terms,
                *self.catalog_terms,
                *self.ngrams,
                *self.exact_spans,
                *self.symbol_spans,
                *self.formula_spans,
            ]
        )

    def diagnostics(self) -> dict[str, list[str]]:
        return {
            "text_terms": self.text_terms,
            "expanded_terms": self.expanded_terms,
            "catalog_terms": self.catalog_terms,
            "ngrams": self.ngrams,
            "exact_spans": self.exact_spans,
            "symbol_spans": self.symbol_spans,
            "formula_spans": self.formula_spans,
            "stop_terms": self.stop_terms,
        }


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def analyze_query(question: str, catalog_terms: list[str] | tuple[str, ...] = ()) -> RetrievalQuery:
    original = question
    normalized = normalize_unicode(question).strip()
    stop_terms = [term for term in STOP_TERMS if term in normalized]
    catalog_matches = match_catalog_terms(normalized, catalog_terms)
    formula_spans = extract_formula_spans(original, normalized)
    symbol_spans = extract_symbol_spans(original)
    text_terms = extract_text_terms(normalized, catalog_matches)
    expanded_terms = expand_terms(text_terms)
    ngrams = cjk_ngrams(remove_stop_terms(normalized), min_n=2, max_n=4)
    exact_spans = unique([*catalog_matches, *formula_spans, *symbol_spans])
    return RetrievalQuery(
        original=original,
        normalized=normalized,
        text_terms=unique(text_terms),
        expanded_terms=unique(expanded_terms),
        catalog_terms=unique(catalog_matches),
        ngrams=unique(ngrams),
        exact_spans=exact_spans,
        symbol_spans=unique(symbol_spans),
        formula_spans=unique(formula_spans),
        stop_terms=unique(stop_terms),
    )


def match_catalog_terms(normalized: str, catalog_terms: list[str] | tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    normalized_query = normalized.casefold()
    for term in sorted({term for term in catalog_terms if str(term).strip()}, key=len, reverse=True):
        normalized_term = normalize_unicode(str(term)).strip()
        if normalized_term.casefold() in normalized_query:
            matches.append(normalized_term)
    return unique(matches)


def extract_text_terms(normalized: str, catalog_matches: list[str]) -> list[str]:
    terms: list[str] = [*catalog_matches]
    compact = remove_stop_terms(normalized)
    terms.extend(re.findall(r"[A-Za-z0-9_]{2,}", normalized))
    terms.extend(re.findall(r"[\u3400-\u9fff]+[A-Za-z0-9]+", normalized))
    terms.extend(domain_terms(normalized))
    for key in EXPANSIONS:
        if key in normalized:
            terms.append(key)
    for run in re.findall(r"[\u3400-\u9fff]{2,}", compact):
        if len(run) <= 4:
            terms.append(run)
    return [term for term in unique(terms) if term and term not in STOP_TERMS]


def domain_terms(text: str) -> list[str]:
    terms: list[str] = []
    if re.search(r"维生素\s*C", text, flags=re.IGNORECASE):
        terms.extend(["维生素C", "维生素"])
    return terms


def expand_terms(text_terms: list[str]) -> list[str]:
    expanded: list[str] = []
    for term in text_terms:
        expanded.extend(EXPANSIONS.get(term, ()))
    return unique(expanded)


def remove_stop_terms(text: str) -> str:
    result = text
    for term in STOP_TERMS:
        result = result.replace(term, "")
    return result


def cjk_ngrams(text: str, min_n: int, max_n: int) -> list[str]:
    grams: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        for size in range(min_n, max_n + 1):
            if len(run) < size:
                continue
            grams.extend(run[index : index + size] for index in range(0, len(run) - size + 1))
    return unique(grams)


def extract_formula_spans(original: str, normalized: str) -> list[str]:
    spans: list[str] = []
    pattern = r"(?i)\b[A-Z][A-Z0-9₀-₉⁰-⁹¹²³]*\b(?:\s*[=+\-*/^]\s*[A-Z0-9₀-₉⁰-⁹¹²³]+)+|\b[A-Z][A-Z0-9₀-₉⁰-⁹¹²³]*[₀-₉⁰-⁹¹²³0-9][A-Z0-9₀-₉⁰-⁹¹²³]*\b"
    for text in (original, normalized):
        spans.extend(match.group(0).replace(" ", "") for match in re.finditer(pattern, text))
    return unique(spans)


def extract_symbol_spans(original: str) -> list[str]:
    spans: list[str] = []
    spans.extend(re.findall(r"[\u0370-\u03ff]+(?:/[ \t]*[\u0370-\u03ff]+)+", original))
    spans.extend(char for char in original if is_symbol_char(char))
    return unique(span.replace(" ", "") for span in spans)


def is_symbol_char(char: str) -> bool:
    category = unicodedata.category(char)
    if category in {"So", "Sm", "Sc", "Sk"}:
        return not char.isspace()
    return False


def unique(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
