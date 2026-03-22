import os
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)


class PDFExtractor(ABC):
    """Abstract base class for PDF text extraction."""

    @abstractmethod
    def extract_text(self, pdf_path: Path) -> str:
        """Extract text from a PDF file, return as string."""
        ...


class FireRedOCRExtractor(PDFExtractor):
    """PDF text extraction using FireRed-OCR (VLM-based OCR -> Markdown).

    Converts PDF pages to images, then uses FireRed-OCR model to recognize
    text and output Markdown. Requires GPU.
    """

    def __init__(self, model_dir: str = None):
        from config.settings import FIRERED_MODEL_DIR, FIRERED_OCR_DIR
        self.model_dir = model_dir or FIRERED_MODEL_DIR
        self.firered_dir = FIRERED_OCR_DIR
        self._model = None
        self._processor = None

    def _load_model(self):
        """Lazy-load the model and processor."""
        if self._model is not None:
            return

        try:
            from transformers import Qwen3VLForConditionalGeneration, AutoProcessor
        except ImportError:
            logger.error("transformers not installed. Install with: pip install transformers qwen-vl-utils")
            raise

        logger.info(f"Loading FireRed-OCR model from {self.model_dir}...")
        self._processor = AutoProcessor.from_pretrained(self.model_dir)
        self._model = Qwen3VLForConditionalGeneration.from_pretrained(
            self.model_dir,
            torch_dtype="auto",
            device_map="auto",
        )
        logger.info("FireRed-OCR model loaded.")

    def _pdf_to_images(self, pdf_path: Path, output_dir: str) -> list[str]:
        """Convert PDF pages to PNG images using PyMuPDF."""
        try:
            import fitz
        except ImportError:
            logger.error("PyMuPDF required for PDF-to-image conversion. Install with: pip install PyMuPDF")
            raise

        doc = fitz.open(str(pdf_path))
        image_paths = []
        for page_idx, page in enumerate(doc):
            # Render at 300 DPI for good OCR quality
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_path = os.path.join(output_dir, f"page_{page_idx:04d}.png")
            pix.save(img_path)
            image_paths.append(img_path)
        doc.close()
        return image_paths

    def _generate_conv(self, image_path: str) -> list[dict]:
        """Generate conversation prompt for the model."""
        # Add FireRed-OCR directory to path so we can import conv_for_infer
        firered_dir_str = str(self.firered_dir)
        if firered_dir_str not in sys.path:
            sys.path.insert(0, firered_dir_str)

        try:
            from conv_for_infer import generate_conv
            return generate_conv(image_path)
        except ImportError:
            # Fallback: inline the prompt if the file is not available
            PROMPT = (
                "You are an AI assistant specialized in converting PDF images to Markdown format. "
                "Accurately recognize all text content. Convert to Markdown. "
                "Convert math formulas to LaTeX. Convert tables to HTML. Ignore figures."
            )
            return [{
                "role": "user",
                "content": [
                    {"type": "image", "image": image_path},
                    {"type": "text", "text": PROMPT},
                ],
            }]

    def _ocr_image(self, image_path: str) -> str:
        """Run OCR on a single image and return Markdown text."""
        self._load_model()

        messages = self._generate_conv(image_path)

        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self._model.device)

        outputs = self._model.generate(**inputs, max_new_tokens=4096)
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, outputs)
        ]
        text = self._processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]

        return text

    def extract_text(self, pdf_path: Path) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Step 1: Convert PDF to images
            logger.info(f"Converting PDF to images: {pdf_path.name}")
            image_paths = self._pdf_to_images(pdf_path, tmp_dir)
            logger.info(f"  {len(image_paths)} pages")

            # Step 2: OCR each page
            page_texts = []
            for i, img_path in enumerate(image_paths):
                logger.info(f"  OCR page {i + 1}/{len(image_paths)}...")
                text = self._ocr_image(img_path)
                page_texts.append(text)

            return '\n\n---\n\n'.join(page_texts)


class MinerUExtractor(PDFExtractor):
    """PDF text extraction using MinerU (outputs Markdown)."""

    def extract_text(self, pdf_path: Path) -> str:
        try:
            from mineru.cli.common import read_fn, prepare_env
            from mineru.data.data_reader_writer import FileBasedDataWriter
            from mineru.backend.pipeline.pipeline_analyze import doc_analyze
            from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json
            from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make
            from mineru.utils.enum_class import MakeMode
        except ImportError:
            logger.error("MinerU not installed. Install with: pip install mineru")
            raise

        pdf_bytes = read_fn(str(pdf_path))
        file_name = pdf_path.stem

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = tmp_dir

            # Run pipeline analysis
            infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = \
                doc_analyze([pdf_bytes], ["en"], parse_method="auto", formula_enable=False, table_enable=False)

            # Convert to middle JSON
            local_image_dir, local_md_dir = prepare_env(output_dir, file_name, "auto")
            image_writer = FileBasedDataWriter(local_image_dir)
            middle_json = result_to_middle_json(
                infer_results[0], all_image_lists[0], all_pdf_docs[0],
                image_writer, lang_list[0], ocr_enabled_list[0], False
            )

            # Generate markdown text
            pdf_info = middle_json["pdf_info"]
            image_dir = os.path.basename(local_image_dir)
            md_content = union_make(pdf_info, MakeMode.MM_MD, image_dir)

            return md_content


class PyMuPDFExtractor(PDFExtractor):
    """PDF text extraction using PyMuPDF (fitz)."""

    def extract_text(self, pdf_path: Path) -> str:
        try:
            import fitz
        except ImportError:
            logger.error("PyMuPDF not installed. Install with: pip install PyMuPDF")
            raise

        doc = fitz.open(str(pdf_path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()

        full_text = '\n'.join(text_parts)
        full_text = full_text.replace('\x00', '')
        return full_text


def get_extractor(parser_name: str = "firered") -> PDFExtractor:
    """Factory function to get the configured PDF extractor."""
    if parser_name == "firered":
        return FireRedOCRExtractor()
    elif parser_name == "mineru":
        return MinerUExtractor()
    elif parser_name == "pymupdf":
        return PyMuPDFExtractor()
    else:
        logger.warning(f"Unknown parser '{parser_name}', falling back to firered")
        return FireRedOCRExtractor()


def extract_text_chunked(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
    """Split extracted text into overlapping chunks for RAG."""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks
