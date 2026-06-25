"""Text chunking strategies for entity extraction."""
from __future__ import annotations

import re
from typing import Literal, List

ChunkStrategy = Literal["fixed", "recursive"]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n")


def word_count(text: str) -> int:
    return len(text.split())


def split_paragraphs(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def split_sentences(paragraph: str) -> List[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(paragraph) if part.strip()]
    return parts or ([paragraph.strip()] if paragraph.strip() else [])


def split_oversized_unit(unit: str, max_words: int) -> List[str]:
    words = unit.split()
    if len(words) <= max_words:
        return [unit]
    return [" ".join(words[index : index + max_words]) for index in range(0, len(words), max_words)]


def text_to_units(text: str, max_words: int) -> List[str]:
    """Split text into sentence-level units, never exceeding max_words per unit."""
    units: List[str] = []
    for paragraph in split_paragraphs(text):
        for sentence in split_sentences(paragraph):
            units.extend(split_oversized_unit(sentence, max_words))
    return units


def chunk_fixed(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Fixed-size word window with word-based overlap (legacy strategy)."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - overlap
    return chunks


def _overlap_start(units: List[str], end_index: int, overlap_words: int) -> int:
    """Return unit index where the next chunk should start to preserve overlap."""
    if end_index <= 0 or overlap_words <= 0:
        return end_index

    overlap_units = 0
    words_in_overlap = 0
    for index in range(end_index - 1, -1, -1):
        words_in_overlap += word_count(units[index])
        overlap_units += 1
        if words_in_overlap >= overlap_words:
            break
    return max(end_index - overlap_units, 0)


def chunk_recursive(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Pack paragraphs and sentences up to chunk_size; overlap at sentence boundaries."""
    units = text_to_units(text, chunk_size)
    if not units:
        return []
    if sum(word_count(unit) for unit in units) <= chunk_size:
        return [" ".join(units)]

    chunks: List[str] = []
    start = 0
    while start < len(units):
        chunk_units: List[str] = []
        chunk_words = 0
        index = start
        while index < len(units):
            unit_words = word_count(units[index])
            if chunk_units and chunk_words + unit_words > chunk_size:
                break
            chunk_units.append(units[index])
            chunk_words += unit_words
            index += 1

        if not chunk_units:
            chunk_units = [units[start]]
            index = start + 1

        chunks.append(" ".join(chunk_units))
        if index >= len(units):
            break

        next_start = _overlap_start(units, index, overlap)
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return chunks


def chunk_word_start_indices(
    text: str,
    *,
    strategy: ChunkStrategy = "recursive",
    chunk_size: int = 300,
    overlap: int = 50,
) -> list[int]:
    """Return word-index start position for each chunk (for boundary analysis)."""
    words = text.split()
    if not words:
        return []

    if strategy == "fixed":
        starts = [0]
        start = 0
        while start + chunk_size < len(words):
            start = start + chunk_size - overlap
            starts.append(start)
        return starts

    units = text_to_units(text, chunk_size)
    if not units:
        return [0]

    unit_word_counts = [word_count(unit) for unit in units]
    starts = [0]
    unit_start = 0
    while unit_start < len(units):
        chunk_units = 0
        chunk_words = 0
        index = unit_start
        while index < len(units):
            next_words = unit_word_counts[index]
            if chunk_units and chunk_words + next_words > chunk_size:
                break
            chunk_words += next_words
            chunk_units += 1
            index += 1
        if index >= len(units):
            break
        next_unit_start = _overlap_start(units, index, overlap)
        if next_unit_start <= unit_start:
            next_unit_start = unit_start + 1
        unit_start = next_unit_start
        word_offset = sum(unit_word_counts[:unit_start])
        if word_offset not in starts:
            starts.append(word_offset)
    return starts


def chunk_text(
    text: str,
    *,
    strategy: ChunkStrategy = "recursive",
    chunk_size: int = 300,
    overlap: int = 50,
) -> List[str]:
    if strategy == "fixed":
        return chunk_fixed(text, chunk_size, overlap)
    return chunk_recursive(text, chunk_size, overlap)
