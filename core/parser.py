import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import bibtexparser

from utils.logger import get_logger
from utils.text_cleaner import strip_latex_commands, split_sentences_chinese

logger = get_logger(__name__)

UPCITE_PATTERN = re.compile(r'\\upcite\{([^}]+)\}')
INPUT_PATTERN = re.compile(r'\\input\{([^}]+)\}')


@dataclass
class CitationOccurrence:
    """One instance of a citation being used in the thesis."""
    cite_key: str
    source_file: str
    line_number: int
    context_raw: str        # Raw LaTeX text around the citation
    context_clean: str      # Cleaned text (LaTeX stripped)
    sentence_with_cite: str # The specific sentence containing the cite


@dataclass
class BibEntry:
    """Parsed BibTeX entry."""
    key: str
    entry_type: str
    title: str
    authors: str
    year: str
    journal_or_booktitle: str
    raw_entry: dict


@dataclass
class CitationRecord:
    """Complete record linking a citation key to its metadata and all usages."""
    bib_entry: BibEntry
    occurrences: list[CitationOccurrence] = field(default_factory=list)


def find_tex_files(main_tex_path: Path) -> list[Path]:
    """Parse main.tex, find all \\input{} directives, return list of .tex paths."""
    content = main_tex_path.read_text(encoding='utf-8')
    input_dir = main_tex_path.parent
    tex_files = []
    for match in INPUT_PATTERN.finditer(content):
        relative = match.group(1)
        if not relative.endswith('.tex'):
            relative += '.tex'
        full_path = input_dir / relative
        if full_path.exists():
            tex_files.append(full_path)
        else:
            logger.warning(f"Referenced tex file not found: {full_path}")
    return tex_files


def _get_paragraph_context(lines: list[str], target_idx: int) -> str:
    """Extract the paragraph containing the target line (text between blank lines)."""
    # Find paragraph start (go backwards to find blank line)
    start = target_idx
    while start > 0 and lines[start - 1].strip():
        start -= 1

    # Find paragraph end (go forwards to find blank line)
    end = target_idx
    while end < len(lines) - 1 and lines[end + 1].strip():
        end += 1

    return ' '.join(line.strip() for line in lines[start:end + 1] if line.strip())


def _find_sentence_with_citation(context_clean: str, cite_key: str) -> str:
    """Find the sentence that originally contained the citation reference."""
    sentences = split_sentences_chinese(context_clean)
    if not sentences:
        return context_clean

    # After cleaning, the \upcite{} is removed, so we return the full cleaned context
    # as the "sentence" since Chinese paragraphs are often one long sentence
    # For better granularity, return the first 300 chars
    if len(sentences) == 1:
        return sentences[0]

    # Return up to 3 sentences around the middle of the context
    mid = len(sentences) // 2
    start = max(0, mid - 1)
    end = min(len(sentences), mid + 2)
    return ''.join(sentences[start:end])


def extract_citations_from_tex(tex_path: Path) -> list[CitationOccurrence]:
    """Extract all citation occurrences with surrounding context from a .tex file."""
    content = tex_path.read_text(encoding='utf-8')
    lines = content.split('\n')
    occurrences = []

    for line_idx, line in enumerate(lines):
        # Skip comment lines
        if line.strip().startswith('%'):
            continue

        for match in UPCITE_PATTERN.finditer(line):
            keys_str = match.group(1)
            keys = [k.strip() for k in keys_str.split(',')]

            # Extract paragraph context
            context_raw = _get_paragraph_context(lines, line_idx)
            context_clean = strip_latex_commands(context_raw)

            # Find the relevant sentence
            sentence = _find_sentence_with_citation(context_clean, keys_str)

            for key in keys:
                occurrences.append(CitationOccurrence(
                    cite_key=key,
                    source_file=tex_path.name,
                    line_number=line_idx + 1,
                    context_raw=context_raw,
                    context_clean=context_clean,
                    sentence_with_cite=sentence
                ))

    return occurrences


def parse_bib_file(bib_path: Path) -> dict[str, BibEntry]:
    """Parse ref.bib and return dict keyed by citation key."""
    content = bib_path.read_text(encoding='utf-8')

    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False

    try:
        bib_db = bibtexparser.loads(content, parser=parser)
    except Exception as e:
        logger.warning(f"BibTeX parse error (trying to recover): {e}")
        # Try to fix common issues like extra braces
        content_fixed = _fix_bib_content(content)
        bib_db = bibtexparser.loads(content_fixed, parser=parser)

    entries = {}
    for entry in bib_db.entries:
        key = entry.get('ID', '')
        entries[key] = BibEntry(
            key=key,
            entry_type=entry.get('ENTRYTYPE', ''),
            title=entry.get('title', ''),
            authors=entry.get('author', ''),
            year=entry.get('year', ''),
            journal_or_booktitle=entry.get('journal', entry.get('booktitle', '')),
            raw_entry=entry
        )

    return entries


def _fix_bib_content(content: str) -> str:
    """Attempt to fix common BibTeX formatting issues."""
    lines = content.split('\n')
    fixed_lines = []
    brace_depth = 0

    for line in lines:
        # Track brace depth
        for char in line:
            if char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1

        # Skip lines that would make brace depth negative (extra closing braces)
        if brace_depth < 0:
            logger.warning(f"Skipping line with extra closing brace: {line.strip()}")
            brace_depth = 0
            continue

        fixed_lines.append(line)

    return '\n'.join(fixed_lines)


def parse_thesis(main_tex: Path, bib_file: Path) -> list[CitationRecord]:
    """Main entry point: parse the full thesis and return citation records."""
    logger.info(f"Parsing BibTeX file: {bib_file}")
    bib_entries = parse_bib_file(bib_file)
    logger.info(f"Found {len(bib_entries)} BibTeX entries")

    logger.info(f"Finding .tex files from: {main_tex}")
    tex_files = find_tex_files(main_tex)
    logger.info(f"Found {len(tex_files)} .tex files")

    # Collect all citation occurrences grouped by key
    all_occurrences: dict[str, list[CitationOccurrence]] = {}
    for tex_file in tex_files:
        occs = extract_citations_from_tex(tex_file)
        for occ in occs:
            all_occurrences.setdefault(occ.cite_key, []).append(occ)
        if occs:
            logger.info(f"  {tex_file.name}: {len(occs)} citation occurrences")

    # Build citation records
    records = []
    missing_keys = []
    for key, occs in all_occurrences.items():
        bib = bib_entries.get(key)
        if bib is None:
            missing_keys.append(key)
            continue
        records.append(CitationRecord(bib_entry=bib, occurrences=occs))

    if missing_keys:
        logger.warning(f"Citation keys not found in bib file: {missing_keys}")

    total_occs = sum(len(r.occurrences) for r in records)
    logger.info(f"Total: {len(records)} unique references, {total_occs} citation occurrences")

    return records
