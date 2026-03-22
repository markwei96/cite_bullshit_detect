import re


def strip_latex_commands(text: str) -> str:
    """Remove LaTeX commands while preserving readable text."""
    # Remove \upcite{...} references
    text = re.sub(r'\\upcite\{[^}]*\}', '', text)
    # Remove \cite{...} and variants
    text = re.sub(r'\\(?:cite|citep|citet|ref|eqref|label)\{[^}]*\}', '', text)
    # Remove formatting commands, keeping content: \textbf{content} -> content
    text = re.sub(r'\\(?:textbf|textit|emph|text|underline)\{([^}]*)\}', r'\1', text)
    # Remove section/chapter headers
    text = re.sub(r'\\(?:chapter|section|subsection|subsubsection)\*?\{[^}]*\}', '', text)
    # Remove environments like \begin{...} and \end{...}
    text = re.sub(r'\\(?:begin|end)\{[^}]*\}', '', text)
    # Remove inline math $...$ with placeholder
    text = re.sub(r'\$[^$]*\$', '[formula]', text)
    # Remove remaining simple commands
    text = re.sub(r'\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})*', '', text)
    # Remove LaTeX comments
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def split_sentences_chinese(text: str) -> list[str]:
    """Split Chinese/English mixed text into sentences."""
    # Split on Chinese punctuation (。；？！) and English period followed by space
    parts = re.split(r'(?<=[。；？！])|(?<=\.)\s+', text)
    return [s.strip() for s in parts if s.strip()]
