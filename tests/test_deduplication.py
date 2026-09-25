"""
Unit tests for cross-window concept deduplication and synthesis merging.
"""

from pipeline.summarize import deduplicate_cross_window_concepts


def test_deduplicate_cross_window_concepts():
    concepts = [
        # Window 0 instance
        {
            "name": "Gradient Descent",
            "category": "concept",
            "definition": "First-order iterative optimization algorithm.",
            "explanation": "Finds local minimum of a differentiable function.",
            "start_seconds": 120.0,
            "end_seconds": 300.0,
            "slide_id": 2,
            "evidence_references": [{"type": "TRANSCRIPT", "timestamp": 120.0, "evidence_text": "we use gradient descent"}],
            "confidence": "MEDIUM",
        },
        # Window 1 overlapping instance (same concept revisited or overlapping)
        {
            "name": "Gradient Descent",
            "category": "concept",
            "definition": "First-order iterative optimization algorithm.",
            "explanation": "Calculates negative gradient step vector.",
            "start_seconds": 1750.0,
            "end_seconds": 1900.0,
            "slide_id": 2,
            "evidence_references": [{"type": "SLIDE", "timestamp": 1750.0, "slide_index": 2, "evidence_text": "Gradient Descent Algorithm"}],
            "confidence": "MEDIUM",
        },
        # Distinct concept
        {
            "name": "Backpropagation",
            "category": "concept",
            "definition": "Reverse-mode automatic differentiation.",
            "explanation": "Propagates errors backwards through chain rule.",
            "start_seconds": 400.0,
            "end_seconds": 600.0,
            "slide_id": 4,
            "evidence_references": [],
            "confidence": "MEDIUM",
        },
    ]

    deduped = deduplicate_cross_window_concepts(concepts)
    assert len(deduped) == 2

    gd = next(c for c in deduped if c["name"] == "Gradient Descent")
    assert gd["occurrence_count"] == 2
    # Combined evidence citations
    assert len(gd["evidence_references"]) == 2
    # Upgraded confidence
    assert gd["confidence"] == "HIGH"
