# Citation Bullshit Detector

[中文版](README_zh-CN.md)

An automated tool for verifying academic paper citations. It parses LaTeX theses, searches cited references on Google Scholar, downloads PDFs, and uses LLMs to assess whether each citation actually supports the claims made in the text.

## Pipeline

```
LaTeX (.tex) + Bibliography (.bib)
        |
        v  [core/parser.py]
  Citation records (key, metadata, context)
        |
        v  [core/downloader.py]
  Google Scholar search (ScrapingDog / SerpAPI)
    |-- PDF available  --> download to data/pdfs/
    |-- No PDF         --> save abstract as fallback
    '-- Not found      --> metadata-only verification
        |
        v  [utils/pdf_extractor.py]
  PDF parsing --> text (FireRed-OCR / MinerU / PyMuPDF)
        |
        v  [core/rag_engine.py]
  TF-IDF retrieval --> relevant passages
        |
        v  [core/llm_analyzer.py]
  LLM verification --> support level + quotes
        |
        v  [main.py]
  Report (Markdown + JSON) --> data/output/
```

## Features

- **LaTeX/BibTeX parsing** -- extracts all `\upcite{}` citations with surrounding context
- **Google Scholar search** -- via ScrapingDog and SerpAPI with automatic key rotation and usage tracking
- **Smart caching** -- search results, abstracts, and PDFs are cached locally to minimize API usage
- **3 PDF parsers** -- FireRed-OCR (VLM-based, default), MinerU, PyMuPDF, switchable via config
- **3 verification modes** -- full-text, abstract-only, metadata-only, automatically selected based on available data
- **Structured report** -- per-citation support level, source quotes, and explanations

## Project Structure

```
cite_bullshit_detect/
├── config/
│   ├── settings.py            # Global config, loads .env
│   └── prompt_templates.py    # LLM prompt templates (3 modes)
├── core/
│   ├── parser.py              # LaTeX/BibTeX parser
│   ├── downloader.py          # Scholar search + PDF download + caching
│   ├── rag_engine.py          # TF-IDF passage retrieval
│   └── llm_analyzer.py        # LLM citation verification
├── utils/
│   ├── logger.py              # Logging
│   ├── text_cleaner.py        # LaTeX command stripping, Chinese sentence splitting
│   └── pdf_extractor.py       # PDF extractors (FireRed-OCR / MinerU / PyMuPDF)
├── data/
│   ├── input/                 # .tex and .bib files
│   ├── pdfs/                  # Downloaded PDFs + caches
│   └── output/                # Generated reports
├── main.py                    # CLI entry point
├── requirements.txt
└── .env.example
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

For FireRed-OCR (default PDF parser), you also need a GPU and the model will be auto-downloaded from HuggingFace on first run.

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI-compatible API key (supports OpenRouter, etc.) |
| `OPENAI_BASE_URL` | API endpoint URL |
| `LLM_MODEL` | Model name (e.g., `gpt-4o-mini`) |
| `SCRAPINGDOG_KEYS` | ScrapingDog API key(s), comma-separated |
| `SERPAPI_KEYS` | SerpAPI key(s), comma-separated |
| `PDF_PARSER` | `firered` (default), `mineru`, or `pymupdf` |

### 3. Prepare input

Place your LaTeX thesis files (`.tex`) and bibliography (`.bib`) in `data/input/`.

### 4. Run

```bash
# Full pipeline
python main.py

# Skip PDF download (use existing PDFs/cache)
python main.py --skip-download

# Use a different PDF parser
python main.py --pdf-parser pymupdf

# Custom output path
python main.py --output my_report.md
```

### 5. View results

- Markdown report: `data/output/report.md`
- JSON results: `data/output/report.json`

## Verification Levels

| Level | Meaning |
|---|---|
| `STRONGLY_SUPPORTS` | Paper clearly supports the thesis claim |
| `SUPPORTS` | Paper is relevant and supportive |
| `WEAKLY_SUPPORTS` | Tangential relevance |
| `UNRELATED` | Paper does not relate to the claim |
| `CONTRADICTS` | Paper contradicts the claim |
| `CANNOT_VERIFY` | Insufficient data to assess |

## Caching

All API results are cached in `data/pdfs/` to avoid redundant requests:

- `scholar_cache.json` -- Google Scholar search results
- `abstracts.json` -- Paper abstracts/snippets
- `*.pdf` -- Downloaded PDF files

Re-running the tool will reuse cached data automatically. Delete these files to force a fresh search.

## License

MIT
