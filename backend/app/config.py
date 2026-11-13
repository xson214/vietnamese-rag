import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('DATA_DIR', './data/runtime')))
    embedding_backend: str = field(default_factory=lambda: os.getenv('EMBEDDING_BACKEND', 'sentence_transformers'))
    embedding_model: str = field(default_factory=lambda: os.getenv('EMBEDDING_MODEL', 'intfloat/multilingual-e5-small'))
    embedding_revision: str = field(default_factory=lambda: os.getenv('EMBEDDING_REVISION', '614241f622f53c4eeff9890bdc4f31cfecc418b3'))
    reranker_backend: str = field(default_factory=lambda: os.getenv('RERANKER_BACKEND', 'lexical'))
    reranker_model: str = field(default_factory=lambda: os.getenv('RERANKER_MODEL', 'BAAI/bge-reranker-v2-m3'))
    reranker_revision: str = field(default_factory=lambda: os.getenv('RERANKER_REVISION', 'main'))
    qdrant_url: str | None = field(default_factory=lambda: os.getenv('QDRANT_URL') or None)
    generation_backend: str = field(default_factory=lambda: os.getenv('GENERATION_BACKEND', 'extractive'))
    llm_base_url: str = field(default_factory=lambda: os.getenv('LLM_BASE_URL', ''))
    llm_api_key: str = field(default_factory=lambda: os.getenv('LLM_API_KEY', ''), repr=False)
    llm_model: str = field(default_factory=lambda: os.getenv('LLM_MODEL', ''))
    llm_timeout: float = field(default_factory=lambda: float(os.getenv('LLM_TIMEOUT', '60')))
    context_char_budget: int = 12000
    chunking_strategy: str = field(default_factory=lambda: os.getenv('CHUNKING_STRATEGY', 'recursive'))
    chunk_size: int = field(default_factory=lambda: int(os.getenv('CHUNK_SIZE', '120')))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv('CHUNK_OVERLAP', '20')))
    libreoffice_path: str = field(default_factory=lambda: os.getenv('LIBREOFFICE_PATH', 'soffice'))
    ocr_enabled: bool = field(default_factory=lambda: os.getenv('OCR_ENABLED', 'true').lower() in {'1', 'true', 'yes'})
    ocr_languages: str = field(default_factory=lambda: os.getenv('OCR_LANGUAGES', 'vie+eng'))
    tesseract_path: str = field(default_factory=lambda: os.getenv('TESSERACT_PATH', 'tesseract'))
    ocr_data_dir: str | None = field(default_factory=lambda: os.getenv('OCR_DATA_DIR') or None)
    ocr_timeout: int = field(default_factory=lambda: int(os.getenv('OCR_TIMEOUT', '60')))
    ocr_min_confidence: float = field(default_factory=lambda: float(os.getenv('OCR_MIN_CONFIDENCE', '60')))
    max_image_pixels: int = field(default_factory=lambda: int(os.getenv('MAX_IMAGE_PIXELS', '24000000')))
    ocr_max_pages: int = field(default_factory=lambda: int(os.getenv('OCR_MAX_PAGES', '20')))
    max_file_bytes: int = 20 * 1024 * 1024
    max_pages: int = 300

    def __post_init__(self):
        self.data_dir = Path(self.data_dir).resolve()
        if self.ocr_data_dir is None:
            self.ocr_data_dir = str(self.data_dir / 'tessdata')
        if self.ocr_timeout <= 0 or not 0 <= self.ocr_min_confidence <= 100 or self.ocr_max_pages < 1 or self.max_image_pixels < 1:
            raise ValueError('OCR limits must be positive; OCR_MIN_CONFIDENCE must be in [0,100]')
        if self.embedding_backend not in {'hash', 'sentence_transformers'}:
            raise ValueError('Unsupported EMBEDDING_BACKEND')
        if self.reranker_backend not in {'lexical', 'cross_encoder'}:
            raise ValueError('Unsupported RERANKER_BACKEND')
        if self.generation_backend not in {'extractive', 'api'}:
            raise ValueError('Unsupported GENERATION_BACKEND')
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError('Require 0 <= CHUNK_OVERLAP < CHUNK_SIZE')
