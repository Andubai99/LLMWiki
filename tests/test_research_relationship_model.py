from __future__ import annotations

import pytest

from llmwiki.research.relationships import (
    RESEARCH_GRAPH_SCHEMA_VERSION,
    RESEARCH_RELATIONSHIP_BUNDLE_SCHEMA_VERSION,
    RESEARCH_RELATIONSHIP_EDGE_SCHEMA_VERSION,
    RESEARCH_RELATIONSHIP_RUN_SCHEMA_VERSION,
    RESEARCH_RELATIONSHIP_WARNING_SCHEMA_VERSION,
    RESEARCH_SYNTHESIS_SCHEMA_VERSION,
    ResearchRelationshipFilterError,
    relationship_warning,
    validate_limit_offset,
)


def test_research_relationship_schema_constants() -> None:
    assert RESEARCH_RELATIONSHIP_RUN_SCHEMA_VERSION == "research_relationship_run.v5.0"
    assert RESEARCH_RELATIONSHIP_BUNDLE_SCHEMA_VERSION == "research_relationship_bundle.v5.0"
    assert RESEARCH_RELATIONSHIP_EDGE_SCHEMA_VERSION == "research_relationship_edge.v5.0"
    assert RESEARCH_GRAPH_SCHEMA_VERSION == "research_graph.v5.0"
    assert RESEARCH_SYNTHESIS_SCHEMA_VERSION == "research_synthesis.v5.0"
    assert RESEARCH_RELATIONSHIP_WARNING_SCHEMA_VERSION == "research_relationship_warning.v5.0"


def test_research_relationship_limit_offset_validation() -> None:
    limit, offset, warnings = validate_limit_offset(None, None)
    assert (limit, offset) == (200, 0)
    assert warnings == []

    limit, offset, warnings = validate_limit_offset(1200, 3)
    assert (limit, offset) == (1000, 3)
    assert warnings[0]["code"] == "limit_clamped"

    with pytest.raises(ResearchRelationshipFilterError):
        validate_limit_offset(0, 0)
    with pytest.raises(ResearchRelationshipFilterError):
        validate_limit_offset(1, -1)


def test_research_relationship_warning_shape() -> None:
    warning = relationship_warning("not_comparable", "Dataset splits differ.", severity="warning")

    assert warning == {
        "schema_version": "research_relationship_warning.v5.0",
        "code": "not_comparable",
        "message": "Dataset splits differ.",
        "severity": "warning",
    }
