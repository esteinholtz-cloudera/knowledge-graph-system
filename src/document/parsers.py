"""Document parsers for various file formats."""
import os
from typing import Optional
from pathlib import Path


class TextParser:
    """Parser for plain text files."""
    
    @staticmethod
    def parse(file_path: str) -> str:
        """Extract text from a text file."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()


class MarkdownParser:
    """Parser for Markdown files."""
    
    @staticmethod
    def parse(file_path: str) -> str:
        """Extract text from a Markdown file."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()


class PDFParser:
    """Parser for PDF files."""
    
    @staticmethod
    def parse(file_path: str) -> str:
        """Extract text from a PDF file."""
        try:
            import PyPDF2
        except ImportError:
            try:
                import pdfplumber
            except ImportError:
                raise ImportError(
                    "PDF parsing requires either PyPDF2 or pdfplumber. "
                    "Install with: pip install PyPDF2 or pip install pdfplumber"
                )
        
        # Try pdfplumber first (better text extraction)
        try:
            import pdfplumber
            text = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text.append(page_text)
            return '\n\n'.join(text)
        except ImportError:
            pass
        
        # Fallback to PyPDF2
        try:
            import PyPDF2
            text = []
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text.append(page_text)
            return '\n\n'.join(text)
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}")


class WordParser:
    """Parser for Microsoft Word documents."""
    
    @staticmethod
    def parse(file_path: str) -> str:
        """Extract text from a Word document."""
        try:
            from docx import Document
        except ImportError:
            raise ImportError(
                "Word document parsing requires python-docx. "
                "Install with: pip install python-docx"
            )
        
        doc = Document(file_path)
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        return '\n\n'.join(paragraphs)


def get_parser(file_path: str):
    """Get the appropriate parser for a file based on its extension."""
    ext = Path(file_path).suffix.lower()
    
    parsers = {
        '.txt': TextParser,
        '.md': MarkdownParser,
        '.markdown': MarkdownParser,
        '.pdf': PDFParser,
        '.docx': WordParser,
        '.doc': WordParser,
    }
    
    parser_class = parsers.get(ext)
    if parser_class is None:
        raise ValueError(f"Unsupported file format: {ext}. Supported formats: {', '.join(parsers.keys())}")
    
    return parser_class()

