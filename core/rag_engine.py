import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from utils.logger import get_logger

logger = get_logger(__name__)

# Threshold for character count below which we skip RAG and use full text
FULL_TEXT_THRESHOLD = 8000


class SimpleRetriever:
    """Simple TF-IDF based retriever for finding relevant chunks."""

    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=5000)
        self.chunks: list[str] = []
        self.chunk_vectors = None

    def index(self, chunks: list[str]):
        """Index a set of text chunks."""
        self.chunks = [c for c in chunks if c.strip()]
        if not self.chunks:
            self.chunk_vectors = None
            return
        try:
            self.chunk_vectors = self.vectorizer.fit_transform(self.chunks)
        except ValueError:
            # All chunks are empty or contain only stop words
            self.chunk_vectors = None

    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        """Find the top-k most relevant chunks for the query."""
        if self.chunk_vectors is None or not self.chunks:
            return []
        try:
            query_vec = self.vectorizer.transform([query])
            similarities = cosine_similarity(query_vec, self.chunk_vectors)[0]
            top_indices = np.argsort(similarities)[::-1][:top_k]
            return [self.chunks[i] for i in top_indices if similarities[i] > 0.0]
        except Exception as e:
            logger.warning(f"Retrieval failed: {e}")
            return []


def find_relevant_passages(paper_text: str, paper_chunks: list[str],
                           thesis_context: str, top_k: int = 3) -> list[str]:
    """Given paper text/chunks and thesis context, find relevant passages.

    If the paper is short enough, returns the full text instead of using RAG.
    """
    if not paper_chunks and not paper_text:
        return []

    # For short papers, use the full text directly
    if paper_text and len(paper_text) < FULL_TEXT_THRESHOLD:
        return [paper_text]

    # Use RAG for longer papers
    if not paper_chunks:
        return [paper_text[:FULL_TEXT_THRESHOLD]] if paper_text else []

    retriever = SimpleRetriever()
    retriever.index(paper_chunks)
    return retriever.retrieve(thesis_context, top_k=top_k)
