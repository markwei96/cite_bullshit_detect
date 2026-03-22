VERIFICATION_PROMPT_FULL = """You are an academic citation verification assistant.

A Chinese thesis makes the following claim and cites a reference to support it. You have access to relevant passages from the cited paper.

## Thesis context (in Chinese):
{thesis_context}

## Cited paper metadata:
- Title: {paper_title}
- Authors: {paper_authors}
- Year: {paper_year}
- Venue: {paper_venue}

## Relevant passages from the cited paper:
{paper_passages}

## Your task:
1. Does the cited paper's content support the claim made in the thesis? Rate the support level.
2. Quote the specific passage(s) from the cited paper that are most relevant to the thesis claim.
3. Provide a brief explanation of your assessment.

Respond in JSON format:
{{
  "support_level": "STRONGLY_SUPPORTS | SUPPORTS | WEAKLY_SUPPORTS | UNRELATED | CONTRADICTS | CANNOT_VERIFY",
  "relevant_quotes": ["quote1", "quote2"],
  "explanation": "Brief explanation in Chinese"
}}
"""

VERIFICATION_PROMPT_ABSTRACT = """You are an academic citation verification assistant.

A Chinese thesis makes the following claim and cites a reference. Only the abstract is available.

## Thesis context (in Chinese):
{thesis_context}

## Cited paper metadata:
- Title: {paper_title}
- Authors: {paper_authors}
- Year: {paper_year}
- Venue: {paper_venue}

## Abstract of the cited paper:
{abstract}

## Your task:
Based on the abstract and paper metadata, assess whether this citation is likely valid.
1. Rate the support level (note: with only an abstract, use CANNOT_VERIFY if uncertain).
2. Quote relevant parts of the abstract if applicable.
3. Provide a brief explanation.

Respond in JSON format:
{{
  "support_level": "STRONGLY_SUPPORTS | SUPPORTS | WEAKLY_SUPPORTS | UNRELATED | CONTRADICTS | CANNOT_VERIFY",
  "relevant_quotes": ["quote1"],
  "explanation": "Brief explanation in Chinese"
}}
"""

VERIFICATION_PROMPT_METADATA = """You are an academic citation verification assistant.

A Chinese thesis makes the following claim and cites a reference. No full text or abstract is available.

## Thesis context (in Chinese):
{thesis_context}

## Cited paper metadata:
- Title: {paper_title}
- Authors: {paper_authors}
- Year: {paper_year}
- Venue: {paper_venue}

## Your task:
Based on the paper's title and metadata, and your knowledge of this paper (if you know it):
1. Assess whether the citation topic is plausible given the thesis claim.
2. Provide any relevant information you know about this paper.

Respond in JSON format:
{{
  "support_level": "SUPPORTS | WEAKLY_SUPPORTS | UNRELATED | CANNOT_VERIFY",
  "relevant_quotes": [],
  "explanation": "Brief explanation in Chinese"
}}
"""
