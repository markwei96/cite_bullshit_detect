import re
from dataclasses import dataclass, field
from pathlib import Path

import bibtexparser

from utils.logger import get_logger
from utils.text_cleaner import strip_latex_commands, split_sentences_chinese

logger = get_logger(__name__)

# Citation patterns: \upcite{}, \cite{}, \citep{}, \citet{}, etc.
CITE_PATTERNS = [
    re.compile(r'\\upcite\{([^}]+)\}'),
    re.compile(r'\\cite\{([^}]+)\}'),
    re.compile(r'\\citep\{([^}]+)\}'),
    re.compile(r'\\citet\{([^}]+)\}'),
]
INPUT_PATTERN = re.compile(r'\\input\{([^}]+)\}')
INCLUDE_PATTERN = re.compile(r'\\include\{([^}]+)\}')
BIBLIOGRAPHY_PATTERN = re.compile(r'\\bibliography\{([^}]+)\}')
ADDBIBRESOURCE_PATTERN = re.compile(r'\\addbibresource\{([^}]+)\}')


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


# ---------------------------------------------------------------------------
# Auto-discovery: find main tex, bib files, and sub-tex files
# ---------------------------------------------------------------------------

def discover_main_tex(input_dir: Path) -> Path | None:
    """Find the main .tex file in input_dir.

    Strategy:
    1. If main.tex exists, use it.
    2. Otherwise, look for the file containing \\documentclass.
    3. If multiple candidates, return None (caller should ask user).
    """
    # Direct match
    main_tex = input_dir / "main.tex"
    if main_tex.exists():
        return main_tex

    # Scan all .tex files for \documentclass
    tex_files = list(input_dir.rglob("*.tex"))
    if not tex_files:
        return None

    if len(tex_files) == 1:
        return tex_files[0]

    candidates = []
    for tf in tex_files:
        try:
            content = tf.read_text(encoding='utf-8', errors='ignore')
            if re.search(r'\\documentclass', content):
                candidates.append(tf)
        except Exception:
            continue

    if len(candidates) == 1:
        return candidates[0]

    return None  # ambiguous, caller should ask user


def list_tex_files(input_dir: Path) -> list[Path]:
    """List all .tex files in input_dir (non-recursive top-level + one level deep)."""
    files = list(input_dir.rglob("*.tex"))
    return sorted(files)


def find_bib_files(main_tex_path: Path) -> list[Path]:
    """Parse main .tex to find referenced .bib files via \\bibliography{} or \\addbibresource{}."""
    content = main_tex_path.read_text(encoding='utf-8')
    base_dir = main_tex_path.parent
    bib_files = []

    # \bibliography{ref} or \bibliography{ref1,ref2}
    for match in BIBLIOGRAPHY_PATTERN.finditer(content):
        for name in match.group(1).split(','):
            name = name.strip()
            if not name.endswith('.bib'):
                name += '.bib'
            path = base_dir / name
            if path.exists():
                bib_files.append(path)
            else:
                logger.warning(f"Bib file referenced but not found: {path}")

    # \addbibresource{ref.bib}
    for match in ADDBIBRESOURCE_PATTERN.finditer(content):
        name = match.group(1).strip()
        if not name.endswith('.bib'):
            name += '.bib'
        path = base_dir / name
        if path.exists():
            bib_files.append(path)
        else:
            logger.warning(f"Bib file referenced but not found: {path}")

    # Deduplicate
    seen = set()
    unique = []
    for p in bib_files:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)

    # Fallback: if nothing found in main tex, scan for .bib files in the directory
    if not unique:
        logger.info("No \\bibliography or \\addbibresource found in main tex, scanning directory...")
        bib_candidates = list(base_dir.rglob("*.bib"))
        if bib_candidates:
            unique = sorted(bib_candidates)
            logger.info(f"Found bib files by scanning: {[f.name for f in unique]}")

    return unique


def find_sub_tex_files(main_tex_path: Path) -> list[Path]:
    """Parse main .tex to find all \\input{} and \\include{} sub-files."""
    content = main_tex_path.read_text(encoding='utf-8')
    base_dir = main_tex_path.parent
    tex_files = []

    for pattern in [INPUT_PATTERN, INCLUDE_PATTERN]:
        for match in pattern.finditer(content):
            # Skip commented-out lines
            line_start = content.rfind('\n', 0, match.start()) + 1
            line_text = content[line_start:match.start()]
            if '%' in line_text:
                continue

            relative = match.group(1).strip()
            if not relative.endswith('.tex'):
                relative += '.tex'
            full_path = base_dir / relative
            if full_path.exists():
                tex_files.append(full_path)
            else:
                logger.warning(f"Referenced tex file not found: {full_path}")

    return tex_files


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

def _get_paragraph_context(lines: list[str], target_idx: int) -> str:
    """Extract the paragraph containing the target line (text between blank lines)."""
    start = target_idx
    while start > 0 and lines[start - 1].strip():
        start -= 1

    end = target_idx
    while end < len(lines) - 1 and lines[end + 1].strip():
        end += 1

    return ' '.join(line.strip() for line in lines[start:end + 1] if line.strip())


def _find_sentence_with_citation(context_clean: str, cite_key: str) -> str:
    """Find the sentence that originally contained the citation reference."""
    sentences = split_sentences_chinese(context_clean)
    if not sentences:
        return context_clean

    if len(sentences) == 1:
        return sentences[0]

    mid = len(sentences) // 2
    start = max(0, mid - 1)
    end = min(len(sentences), mid + 2)
    return ''.join(sentences[start:end])


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------

def extract_citations_from_tex(tex_path: Path) -> list[CitationOccurrence]:
    """Extract all citation occurrences with surrounding context from a .tex file."""
    content = tex_path.read_text(encoding='utf-8')
    lines = content.split('\n')
    occurrences = []

    for line_idx, line in enumerate(lines):
        # Skip comment lines
        if line.strip().startswith('%'):
            continue

        for pattern in CITE_PATTERNS:
            for match in pattern.finditer(line):
                keys_str = match.group(1)
                keys = [k.strip() for k in keys_str.split(',')]

                context_raw = _get_paragraph_context(lines, line_idx)
                context_clean = strip_latex_commands(context_raw)
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


# ---------------------------------------------------------------------------
# BibTeX parsing
# ---------------------------------------------------------------------------

def parse_bib_file(bib_path: Path) -> dict[str, BibEntry]:
    """Parse a .bib file and return dict keyed by citation key."""
    content = bib_path.read_text(encoding='utf-8')

    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False

    try:
        bib_db = bibtexparser.loads(content, parser=parser)
    except Exception as e:
        logger.warning(f"BibTeX parse error (trying to recover): {e}")
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


def parse_bib_files(bib_paths: list[Path]) -> dict[str, BibEntry]:
    """Parse multiple .bib files and merge results."""
    all_entries = {}
    for bib_path in bib_paths:
        logger.info(f"Parsing bib file: {bib_path.name}")
        entries = parse_bib_file(bib_path)
        all_entries.update(entries)
    return all_entries


def _fix_bib_content(content: str) -> str:
    """Attempt to fix common BibTeX formatting issues."""
    lines = content.split('\n')
    fixed_lines = []
    brace_depth = 0

    for line in lines:
        for char in line:
            if char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1

        if brace_depth < 0:
            logger.warning(f"Skipping line with extra closing brace: {line.strip()}")
            brace_depth = 0
            continue

        fixed_lines.append(line)

    return '\n'.join(fixed_lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_thesis(main_tex: Path, bib_files: list[Path]) -> list[CitationRecord]:
    """Main entry point: parse the thesis and return citation records.

    Args:
        main_tex: Path to the main .tex file.
        bib_files: List of .bib file paths (auto-discovered from main_tex).
    """
    # Parse all bib files
    bib_entries = parse_bib_files(bib_files)
    logger.info(f"Total BibTeX entries: {len(bib_entries)}")

    # Find sub-tex files referenced from main
    sub_tex_files = find_sub_tex_files(main_tex)
    # Always include the main tex itself
    all_tex_files = [main_tex] + sub_tex_files
    logger.info(f"Tex files to scan: {[f.name for f in all_tex_files]}")

    # Collect all citation occurrences grouped by key
    all_occurrences: dict[str, list[CitationOccurrence]] = {}
    for tex_file in all_tex_files:
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
