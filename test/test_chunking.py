"""Tests for document chunking strategies."""
from pathlib import Path

from src.document.chunking import (
    chunk_fixed,
    chunk_recursive,
    chunk_text,
    split_sentences,
    text_to_units,
    word_count,
)

ZDU = Path(__file__).resolve().parents[1] / "input" / "ZDU_prereqs.txt"


def test_split_sentences_respects_punctuation():
    parts = split_sentences("First sentence. Second sentence!\nThird line.")
    assert len(parts) == 3


def test_recursive_never_splits_mid_sentence():
    text = "Alpha beta gamma. Delta epsilon zeta. Eta theta iota."
    units = text_to_units(text, max_words=100)
    chunks = chunk_recursive(text, chunk_size=5, overlap=2)
    for chunk in chunks:
        for unit in units:
            if unit in text and word_count(unit) > 1:
                if unit[:10] in chunk:
                    assert unit in chunk or chunk in unit


def test_recursive_short_text_single_chunk():
    text = "One short sentence."
    assert chunk_recursive(text, chunk_size=300, overlap=50) == [text]


def test_fixed_matches_legacy_processor_behavior():
    text = " ".join(f"word{i}" for i in range(500))
    assert chunk_fixed(text, chunk_size=300, overlap=100) == chunk_text(
        text, strategy="fixed", chunk_size=300, overlap=100
    )


def test_recursive_fewer_chunks_than_fixed_on_zdu():
    if not ZDU.is_file():
        return
    text = ZDU.read_text(encoding="utf-8")
    fixed = chunk_fixed(text, chunk_size=300, overlap=100)
    recursive = chunk_recursive(text, chunk_size=300, overlap=50)
    assert len(recursive) < len(fixed)


def test_recursive_overlap_reuses_tail_sentences():
    text = (
        "Sentence one here. Sentence two here. Sentence three here. "
        "Sentence four here. Sentence five here. Sentence six here."
    )
    chunks = chunk_recursive(text, chunk_size=12, overlap=4)
    assert len(chunks) >= 2
    assert chunks[0].split(".")[0] in chunks[1] or chunks[0][-20:] in chunks[1]


def test_oversized_sentence_split_by_max_words():
    long_sentence = " ".join(f"token{i}" for i in range(400))
    units = text_to_units(long_sentence, max_words=300)
    assert len(units) >= 2
    assert all(word_count(unit) <= 300 for unit in units)
