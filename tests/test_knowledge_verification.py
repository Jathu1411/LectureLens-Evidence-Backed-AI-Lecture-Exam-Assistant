"""
Unit tests for Lecturer Emphasis cue detection and Grounding Verification.
"""

from pipeline.knowledge import detect_lecturer_emphasis
from pipeline.verification import verify_concept_claim


def test_detect_lecturer_emphasis():
    segments = [
        {"index": 1, "start": 10.0, "end": 15.0, "text": "Good morning class, today we begin Module 2."},
        {"index": 2, "start": 16.0, "end": 22.0, "text": "Remember this rule because it will be on the exam."},
        {"index": 3, "start": 23.0, "end": 30.0, "text": "Pay close attention to how the gradient is calculated."},
        {"index": 4, "start": 31.0, "end": 36.0, "text": "Now let us move to the next slide."},
    ]

    signals = detect_lecturer_emphasis(segments, window_index=0)
    assert len(signals) == 2

    # Segment 2 has exam signal
    exam_sig = next(s for s in signals if s["signal_type"] == "EXAM_SIGNAL")
    assert exam_sig["timestamp"] == 16.0
    assert "on the exam" in exam_sig["text"]

    # Segment 3 has importance signal
    imp_sig = next(s for s in signals if s["signal_type"] == "IMPORTANCE_SIGNAL")
    assert imp_sig["timestamp"] == 23.0
    assert "Pay close attention" in imp_sig["text"]


def test_grounding_verification():
    transcript_corpus = "In this lecture we define Batch Normalization as standardizing activation inputs to reduce internal covariate shift."
    slide_corpus = "BATCH NORMALIZATION\n- Normalizes layer activations\n- Accelerates training dynamics"

    # Concept supported by both
    supported_concept = {
        "name": "Batch Normalization",
        "explanation": "Standardizes layer activations to stabilize and accelerate deep neural network training dynamics.",
        "confidence": "HIGH",
    }
    status, evidence, notes = verify_concept_claim(supported_concept, transcript_corpus, slide_corpus)
    assert status == "SUPPORTED"
    assert len(evidence) >= 1

    # Completely hallucinated concept
    hallucinated_concept = {
        "name": "Quantum Chromodynamics",
        "explanation": "The strong interaction between quarks and gluons mediated by color charge gauge fields.",
        "confidence": "LOW",
    }
    status_unsupp, _, _ = verify_concept_claim(hallucinated_concept, transcript_corpus, slide_corpus)
    assert status_unsupp == "UNSUPPORTED"
