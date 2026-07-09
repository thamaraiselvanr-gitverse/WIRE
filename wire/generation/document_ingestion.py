import base64
import io
import os
import re
import uuid
import zipfile
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class DocumentIngestionPipeline:
    """Ingests user-uploaded base64 documents and extracts their text.

    Supported: PDF, DOCX, and plain-text families (TXT/MD/CSV/HTML/JSON). The
    original file is stored under ``<target_dir>/user_uploads/`` and, when
    possible, the text is extracted so it can feed content-aware substitution
    (e.g. a resume PDF supplying an About section). Text families and DOCX use
    only the standard library; PDF text extraction uses ``pypdf`` if installed,
    otherwise the file is stored without extracted text.
    """

    DEFAULT_MAX_BYTES = 25 * 1024 * 1024  # 25MB

    TEXT_EXTS = {"txt", "md", "csv", "html", "htm", "json", "rtf", "log"}
    MAX_EXTRACTED_CHARS = 200_000  # guard against pathological documents

    @staticmethod
    def decode_and_verify(
        b64_string: str, max_size_bytes: int = DEFAULT_MAX_BYTES
    ) -> bytes:
        if "," in b64_string and b64_string.strip().startswith("data:"):
            b64_string = b64_string.split(",", 1)[1]
        try:
            data = base64.b64decode(b64_string)
        except Exception as e:
            raise ValueError(f"Base64 decoding failed: {e}")
        if len(data) > max_size_bytes:
            raise ValueError(
                f"Document size ({len(data)} bytes) exceeds the limit of "
                f"{max_size_bytes} bytes."
            )
        if not data:
            raise ValueError("Empty document.")
        return data

    @classmethod
    def process(
        cls,
        b64_string: str,
        target_dir: str,
        original_filename: str = "",
        max_size_bytes: int = DEFAULT_MAX_BYTES,
    ) -> Dict[str, Any]:
        data = cls.decode_and_verify(b64_string, max_size_bytes)
        ext = cls._detect_ext(data, original_filename)
        if ext is None:
            raise ValueError(
                "Unsupported document format (expected PDF, DOCX, or text)."
            )

        text = cls._extract_text(data, ext)
        structure = cls._structure(text)

        uploads_dir = os.path.join(target_dir, "user_uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        base = uuid.uuid4().hex
        stored_path = os.path.join(uploads_dir, f"{base}.{ext}")
        with open(stored_path, "wb") as f:
            f.write(data)

        # Persist extracted text as a sidecar for auditing/reuse.
        if text:
            with open(f"{stored_path}.txt", "w", encoding="utf-8") as tf:
                tf.write(text)

        run_dir = os.path.dirname(target_dir)
        relative_reference = os.path.relpath(stored_path, run_dir).replace("\\", "/")

        logger.info(
            "document_ingested",
            ext=ext,
            size=len(data),
            extracted_chars=len(text or ""),
            title=structure.get("title"),
            headings=len(structure.get("headings", [])),
            path=relative_reference,
        )
        return {
            "stored_path": relative_reference,
            "extracted_text": text,
            "char_count": len(text or ""),
            "content_type": cls._content_type(ext),
            "ext": ext,
            "structure": structure,
        }

    # ── structured understanding ──
    @classmethod
    def _structure(cls, text: str) -> Dict[str, Any]:
        """Derive queryable fields from flat text so content-aware substitution
        can pull the right piece into the right slot instead of the whole blob.

        - ``title``: the first substantial line.
        - ``headings``: short heading-like lines (markdown ``#``, ALL CAPS, or
          Title Case with no trailing punctuation).
        - ``summary``: the first paragraph (block up to a blank line).
        - ``emails`` / ``urls``: extracted contact/link references.
        - ``word_count`` / ``line_count``.
        """
        if not text or not text.strip():
            return {
                "title": None,
                "headings": [],
                "summary": None,
                "emails": [],
                "urls": [],
                "word_count": 0,
                "line_count": 0,
            }

        lines = [ln.strip() for ln in text.splitlines()]
        non_empty = [ln for ln in lines if ln]

        title = None
        for ln in non_empty:
            if 2 <= len(ln) <= 120:
                title = ln.lstrip("# ").strip()
                break

        headings = []
        for ln in non_empty:
            stripped = ln.lstrip("# ").strip()
            if not (2 <= len(stripped) <= 80):
                continue
            is_md = ln.startswith("#")
            is_caps = stripped.isupper() and any(c.isalpha() for c in stripped)
            is_titlecase = (
                stripped[-1] not in ".!?,:;"
                and stripped == stripped.title()
                and len(stripped.split()) <= 8
            )
            if is_md or is_caps or is_titlecase:
                headings.append(stripped)
            if len(headings) >= 20:
                break

        # First paragraph = first run of non-empty lines.
        summary_lines: list[str] = []
        started = False
        for ln in lines:
            if ln:
                summary_lines.append(ln)
                started = True
            elif started:
                break
        summary = " ".join(summary_lines)[:500] or None

        emails = sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)))
        urls = sorted(set(re.findall(r"https?://[^\s<>\"')]+", text)))

        return {
            "title": title,
            "headings": headings,
            "summary": summary,
            "emails": emails[:20],
            "urls": urls[:40],
            "word_count": len(text.split()),
            "line_count": len(non_empty),
        }

    # ── format detection ──
    @classmethod
    def _detect_ext(cls, data: bytes, filename: str) -> Optional[str]:
        if data[:4] == b"%PDF":
            return "pdf"
        if data[:4] == b"PK\x03\x04":
            # zip container — treat as docx if it carries a Word document part.
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    if "word/document.xml" in z.namelist():
                        return "docx"
            except zipfile.BadZipFile:
                return None
            return None
        # Fall back to the declared extension for text families.
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in cls.TEXT_EXTS:
            return ext
        # Last resort: if it decodes as UTF-8 text, treat as .txt.
        try:
            data.decode("utf-8")
            return "txt"
        except UnicodeDecodeError:
            return None

    # ── text extraction ──
    @classmethod
    def _extract_text(cls, data: bytes, ext: str) -> str:
        if ext == "pdf":
            return cls._extract_pdf(data)
        if ext == "docx":
            return cls._extract_docx(data)
        # text families
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        if ext in ("html", "htm"):
            text = re.sub(r"<[^>]+>", " ", text)
        return cls._clip(text)

    @classmethod
    def _extract_pdf(cls, data: bytes) -> str:
        try:
            import pypdf  # optional dependency
        except Exception:
            logger.info("pypdf_unavailable_pdf_stored_without_text")
            return ""
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            parts = [(page.extract_text() or "") for page in reader.pages]
            return cls._clip("\n".join(parts).strip())
        except Exception as e:
            logger.warning("pdf_text_extraction_failed", error=str(e))
            return ""

    @classmethod
    def _extract_docx(cls, data: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            # Paragraph breaks, then strip tags.
            xml = re.sub(r"</w:p>", "\n", xml)
            text = re.sub(r"<[^>]+>", "", xml)
            return cls._clip(text.strip())
        except Exception as e:
            logger.warning("docx_text_extraction_failed", error=str(e))
            return ""

    @classmethod
    def _clip(cls, text: str) -> str:
        if len(text) > cls.MAX_EXTRACTED_CHARS:
            return text[: cls.MAX_EXTRACTED_CHARS]
        return text

    @staticmethod
    def _content_type(ext: str) -> str:
        return {
            "pdf": "application/pdf",
            "docx": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            "html": "text/html",
            "htm": "text/html",
            "csv": "text/csv",
            "json": "application/json",
            "md": "text/markdown",
        }.get(ext, "text/plain")
