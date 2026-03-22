import json
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

from config.settings import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL
from config.prompt_templates import (
    VERIFICATION_PROMPT_FULL,
    VERIFICATION_PROMPT_ABSTRACT,
    VERIFICATION_PROMPT_METADATA,
)
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VerificationResult:
    cite_key: str
    source_file: str
    line_number: int
    support_level: str       # STRONGLY_SUPPORTS, SUPPORTS, etc.
    relevant_quotes: list[str] = field(default_factory=list)
    explanation: str = ""
    thesis_context: str = ""
    verification_mode: str = ""  # "full", "abstract", "metadata"
    error: Optional[str] = None


class LLMAnalyzer:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    def verify_citation(
        self,
        cite_key: str,
        source_file: str,
        line_number: int,
        thesis_context: str,
        bib_entry,
        paper_passages: list[str] = None,
        abstract: str = None,
    ) -> VerificationResult:
        """Verify a citation using the appropriate mode based on available data."""
        # Determine verification mode and select prompt
        if paper_passages and any(p.strip() for p in paper_passages):
            mode = "full"
            prompt = VERIFICATION_PROMPT_FULL.format(
                thesis_context=thesis_context,
                paper_title=bib_entry.title,
                paper_authors=bib_entry.authors,
                paper_year=bib_entry.year,
                paper_venue=bib_entry.journal_or_booktitle,
                paper_passages='\n---\n'.join(paper_passages),
            )
        elif abstract:
            mode = "abstract"
            prompt = VERIFICATION_PROMPT_ABSTRACT.format(
                thesis_context=thesis_context,
                paper_title=bib_entry.title,
                paper_authors=bib_entry.authors,
                paper_year=bib_entry.year,
                paper_venue=bib_entry.journal_or_booktitle,
                abstract=abstract,
            )
        else:
            mode = "metadata"
            prompt = VERIFICATION_PROMPT_METADATA.format(
                thesis_context=thesis_context,
                paper_title=bib_entry.title,
                paper_authors=bib_entry.authors,
                paper_year=bib_entry.year,
                paper_venue=bib_entry.journal_or_booktitle,
            )

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            result_json = json.loads(content)

            return VerificationResult(
                cite_key=cite_key,
                source_file=source_file,
                line_number=line_number,
                support_level=result_json.get("support_level", "CANNOT_VERIFY"),
                relevant_quotes=result_json.get("relevant_quotes", []),
                explanation=result_json.get("explanation", ""),
                thesis_context=thesis_context[:500],
                verification_mode=mode,
            )
        except Exception as e:
            logger.error(f"LLM verification failed for {cite_key}: {e}")
            return VerificationResult(
                cite_key=cite_key,
                source_file=source_file,
                line_number=line_number,
                support_level="CANNOT_VERIFY",
                thesis_context=thesis_context[:500],
                verification_mode=mode,
                error=str(e),
            )
