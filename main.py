"""
Citation Bullshit Detector - Main Pipeline

Usage:
    python main.py                          # Full pipeline
    python main.py --skip-download          # Skip PDF download, use existing PDFs
    python main.py --pdf-parser pymupdf     # Use PyMuPDF instead of MinerU
    python main.py --output report.md       # Custom output path
"""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from config.settings import MAIN_TEX, BIB_FILE, PDF_DIR, OUTPUT_DIR, PDF_PARSER
from core.parser import parse_thesis
from core.downloader import download_all
from core.rag_engine import find_relevant_passages
from core.llm_analyzer import LLMAnalyzer, VerificationResult
from utils.pdf_extractor import get_extractor, extract_text_chunked
from utils.logger import get_logger

logger = get_logger("main")


def main():
    parser = argparse.ArgumentParser(description="Citation verification tool")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip PDF download, use existing PDFs only")
    parser.add_argument("--output", default=None,
                        help="Output report path (default: data/output/report.md)")
    parser.add_argument("--pdf-parser", default=PDF_PARSER, choices=["firered", "mineru", "pymupdf"],
                        help="PDF parser to use (default: firered)")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else OUTPUT_DIR / "report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Parse LaTeX and BibTeX
    logger.info("=" * 50)
    logger.info("Step 1: Parsing LaTeX and BibTeX files...")
    records = parse_thesis(MAIN_TEX, BIB_FILE)
    logger.info(f"Found {len(records)} unique cited references with "
                f"{sum(len(r.occurrences) for r in records)} total citation occurrences")

    # Step 2: Download PDFs
    download_results = {}
    abstract_cache: dict[str, str] = {}
    if not args.skip_download:
        logger.info("=" * 50)
        logger.info("Step 2: Downloading PDFs via Google Scholar...")
        download_results = download_all(records, PDF_DIR)
    else:
        logger.info("=" * 50)
        logger.info("Step 2: Skipping download (--skip-download)")
        # Load saved abstracts from previous runs
        abstract_file = PDF_DIR / "abstracts.json"
        if abstract_file.exists():
            abstract_cache = json.loads(abstract_file.read_text(encoding="utf-8"))
            logger.info(f"Loaded {len(abstract_cache)} cached abstracts")

    # Step 3: Extract text from PDFs
    logger.info("=" * 50)
    logger.info("Step 3: Extracting text from PDFs...")
    extractor = get_extractor(args.pdf_parser)
    paper_texts: dict[str, str] = {}
    paper_chunks_map: dict[str, list[str]] = {}

    for record in records:
        key = record.bib_entry.key
        pdf_path = PDF_DIR / f"{key}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            try:
                text = extractor.extract_text(pdf_path)
                paper_texts[key] = text
                paper_chunks_map[key] = extract_text_chunked(text)
                logger.info(f"  Extracted: {key} ({len(text)} chars)")
            except Exception as e:
                logger.warning(f"  Failed to extract {key}: {e}")

    logger.info(f"Successfully extracted text from {len(paper_texts)}/{len(records)} papers")

    # Step 4: Verify each citation with LLM
    logger.info("=" * 50)
    logger.info("Step 4: Verifying citations with LLM...")
    analyzer = LLMAnalyzer()
    all_results: list[VerificationResult] = []

    for record in records:
        key = record.bib_entry.key
        paper_text = paper_texts.get(key, "")
        paper_chunks = paper_chunks_map.get(key, [])

        # Get abstract from download results or cache
        dr = download_results.get(key)
        abstract = dr.abstract if dr else abstract_cache.get(key)

        # Deduplicate: verify each unique context only once per key
        seen_contexts = set()
        for occ in record.occurrences:
            context_key = occ.context_clean[:200]
            if context_key in seen_contexts:
                continue
            seen_contexts.add(context_key)

            # Find relevant passages from the paper
            relevant = find_relevant_passages(paper_text, paper_chunks, occ.context_clean)

            result = analyzer.verify_citation(
                cite_key=key,
                source_file=occ.source_file,
                line_number=occ.line_number,
                thesis_context=occ.context_clean,
                bib_entry=record.bib_entry,
                paper_passages=relevant,
                abstract=abstract,
            )
            all_results.append(result)

            icon = {"STRONGLY_SUPPORTS": "++", "SUPPORTS": "+", "WEAKLY_SUPPORTS": "~",
                    "UNRELATED": "!", "CONTRADICTS": "X", "CANNOT_VERIFY": "?"}
            logger.info(f"  [{icon.get(result.support_level, '?')}] {key} "
                        f"({occ.source_file}:{occ.line_number}) [{result.verification_mode}]")

    # Step 5: Generate report
    logger.info("=" * 50)
    logger.info("Step 5: Generating report...")
    report = generate_report(all_results, download_results)
    output_path.write_text(report, encoding='utf-8')

    # Also save JSON results
    json_path = output_path.with_suffix('.json')
    json_results = [asdict(r) for r in all_results]
    json_path.write_text(json.dumps(json_results, ensure_ascii=False, indent=2), encoding='utf-8')

    logger.info(f"Report saved to {output_path}")
    logger.info(f"JSON results saved to {json_path}")

    # Print summary
    print_summary(all_results)


def generate_report(results: list[VerificationResult], download_results: dict) -> str:
    """Generate a Markdown report."""
    lines = ["# 引用验证报告 (Citation Verification Report)\n"]

    # Summary statistics
    total = len(results)
    supports = sum(1 for r in results if "SUPPORT" in r.support_level)
    unrelated = sum(1 for r in results if r.support_level == "UNRELATED")
    contradicts = sum(1 for r in results if r.support_level == "CONTRADICTS")
    cannot_verify = sum(1 for r in results if r.support_level == "CANNOT_VERIFY")

    lines.append("## 总览\n")
    lines.append(f"- 验证总数: {total}")
    lines.append(f"- 支撑引用: {supports}")
    lines.append(f"- 不相关: {unrelated}")
    lines.append(f"- 矛盾: {contradicts}")
    lines.append(f"- 无法验证: {cannot_verify}\n")

    # Download statistics
    if download_results:
        dl_stats = {}
        for dr in download_results.values():
            dl_stats[dr.source] = dl_stats.get(dr.source, 0) + 1
        lines.append("### 文献获取情况")
        for source, count in sorted(dl_stats.items()):
            label = {"pdf_downloaded": "PDF已下载", "abstract_only": "仅摘要",
                     "cached": "已缓存", "not_found": "未找到"}.get(source, source)
            lines.append(f"- {label}: {count}")
        lines.append("")

    lines.append("## 详细结果\n")

    for r in results:
        status_label = {
            "STRONGLY_SUPPORTS": "[强支撑]",
            "SUPPORTS": "[支撑]",
            "WEAKLY_SUPPORTS": "[弱支撑]",
            "UNRELATED": "[不相关]",
            "CONTRADICTS": "[矛盾]",
            "CANNOT_VERIFY": "[无法验证]",
        }.get(r.support_level, "[未知]")

        lines.append(f"### {status_label} `{r.cite_key}`\n")
        lines.append(f"- **位置**: {r.source_file}:{r.line_number}")
        lines.append(f"- **验证模式**: {r.verification_mode}")
        lines.append(f"- **支撑等级**: {r.support_level}\n")

        lines.append(f"**正文上下文:**\n")
        lines.append(f"> {r.thesis_context[:400]}{'...' if len(r.thesis_context) > 400 else ''}\n")

        if r.relevant_quotes:
            lines.append("**引用文献中的支撑原文:**\n")
            for q in r.relevant_quotes:
                lines.append(f"> {q}\n")

        if r.explanation:
            lines.append(f"**解释:** {r.explanation}\n")

        if r.error:
            lines.append(f"**错误:** {r.error}\n")

        lines.append("---\n")

    return '\n'.join(lines)


def print_summary(results: list[VerificationResult]):
    """Print a concise summary to stdout."""
    print("\n" + "=" * 50)
    print("CITATION VERIFICATION SUMMARY")
    print("=" * 50)

    stats = {}
    for r in results:
        stats[r.support_level] = stats.get(r.support_level, 0) + 1

    for level in ["STRONGLY_SUPPORTS", "SUPPORTS", "WEAKLY_SUPPORTS",
                   "UNRELATED", "CONTRADICTS", "CANNOT_VERIFY"]:
        count = stats.get(level, 0)
        if count > 0:
            print(f"  {level}: {count}")

    # Highlight problematic citations
    problems = [r for r in results if r.support_level in ("UNRELATED", "CONTRADICTS")]
    if problems:
        print(f"\nPotentially problematic citations ({len(problems)}):")
        for r in problems:
            print(f"  - {r.cite_key} ({r.source_file}:{r.line_number}): {r.support_level}")

    print("=" * 50)


if __name__ == "__main__":
    main()
