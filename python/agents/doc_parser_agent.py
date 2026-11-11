"""
文档解析 Agent — 多模态文档解析，支持 PDF / 图片 / 表格 / 纯文本

核心能力:
  1. PDF 解析（文字 + 嵌入图片 + 表格）
  2. 图片 OCR + LLM 视觉理解
  3. 表格结构化提取
  4. 文档分块（Chunking）与元数据标注
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings


class DocType(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    TABLE = "table"
    TEXT = "text"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


@dataclass
class DocumentChunk:
    """一个文档块，携带内容 + 元数据"""
    content: str
    doc_id: str
    chunk_index: int
    doc_type: DocType
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}#chunk-{self.chunk_index}"


class DocParserAgent:
    """
    文档解析 Agent

    工作流:
      classify → parse → chunk → enrich_metadata → output
    """

    SUPPORTED_EXTENSIONS: dict[str, DocType] = {
        ".pdf": DocType.PDF,
        ".png": DocType.IMAGE,
        ".jpg": DocType.IMAGE,
        ".jpeg": DocType.IMAGE,
        ".csv": DocType.TABLE,
        ".xlsx": DocType.TABLE,
        ".xls": DocType.TABLE,
        ".txt": DocType.TEXT,
        ".md": DocType.MARKDOWN,
    }

    CHUNK_SIZE = 512
    CHUNK_OVERLAP = 64

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0,
        )

    # ── public API ───────────────────────────────────────────

    async def parse(self, file_path: str) -> list[DocumentChunk]:
        """解析单个文件，返回文档块列表。

        每个 chunk 的 metadata 会带上 parse_mode（text/ocr/vision/failed）
        与 pages，便于接口/前端解释「为什么 embedding 消耗少」。
        """
        doc_type = self._classify(file_path)
        doc_id = self._make_doc_id(file_path)

        raw_texts: list[str] = []
        parse_info: dict = {"mode": "unknown", "pages": 0}
        if doc_type == DocType.PDF:
            raw_texts, parse_info = await self._parse_pdf(file_path)
        elif doc_type == DocType.IMAGE:
            raw_texts, parse_info = await self._parse_image(file_path)
        elif doc_type == DocType.TABLE:
            raw_texts = await self._parse_table(file_path)
        elif doc_type in (DocType.TEXT, DocType.MARKDOWN):
            raw_texts = self._parse_text(file_path)
        else:
            raw_texts = self._parse_text(file_path)

        chunks = self._chunk_texts(raw_texts, doc_id, doc_type, file_path, parse_info)
        return chunks

    async def parse_batch(self, file_paths: list[str]) -> list[DocumentChunk]:
        """批量解析多个文件"""
        all_chunks: list[DocumentChunk] = []
        for fp in file_paths:
            all_chunks.extend(await self.parse(fp))
        return all_chunks

    # ── classification ───────────────────────────────────────

    def _classify(self, file_path: str) -> DocType:
        ext = os.path.splitext(file_path)[1].lower()
        return self.SUPPORTED_EXTENSIONS.get(ext, DocType.UNKNOWN)

    @staticmethod
    def _make_doc_id(file_path: str) -> str:
        return hashlib.sha256(file_path.encode()).hexdigest()[:16]

    # ── PDF parsing ──────────────────────────────────────────

    async def _parse_pdf(self, file_path: str) -> tuple[list[str], dict]:
        """
        PDF 解析:
          1. 优先用 PyPDF2 抽取文字层（绝大多数文本型 PDF 走这里，BGE 消耗正常）；
          2. 若全文无文字（扫描件/图片型 PDF），走 _scanned_pdf_recover：
             OCR 优先、视觉模型兜底，并如实记录 parse_mode 与处理页数。
        """
        texts: list[str] = []
        pages_total = 0
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(file_path)
            pages_total = len(reader.pages)
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    texts.append(page_text.strip())
        except Exception:
            texts.append(f"[PDF 解析失败] {file_path}")

        if texts:
            return texts, {"mode": "text", "pages": pages_total}

        # 扫描件：OCR 优先，视觉模型兜底，记录处理页数
        info = await self._scanned_pdf_recover(file_path)
        return info["texts"], {"mode": info["mode"], "pages": info["pages"]}

    async def _scanned_pdf_recover(self, file_path: str) -> dict:
        """
        扫描件 / 无文字层 PDF 的恢复解析：
          - 渲染每一页为图片，优先用 OCR（pytesseract，本地、免费、产出可嵌入文本）；
          - 单页 OCR 失败时退化为 LLM 视觉描述（昂贵，限制页数避免失控）；
          - 返回 {"texts", "mode", "pages"}，mode ∈ {ocr, vision, failed}。
        """
        MAX_VISION_PAGES = 10  # 视觉模型兜底上限，防止超大扫描件把账单打爆
        try:
            from pdf2image import convert_from_path

            images = convert_from_path(file_path, dpi=150)
        except Exception:
            return {
                "texts": [f"[PDF 渲染失败，请确认已安装 poppler] {file_path}"],
                "mode": "failed",
                "pages": 0,
            }

        images = images[:MAX_VISION_PAGES]
        texts: list[str] = []
        used_vision = False
        for img in images:
            ocr_text = self._ocr(img)
            if ocr_text.strip():
                texts.append(ocr_text.strip())
                continue
            try:
                desc = await self._describe_image_with_llm(img)
                texts.append(desc)
                used_vision = True
            except Exception:
                pass

        texts = [t for t in texts if t.strip()]
        if not texts:
            return {"texts": [f"[扫描件解析失败] {file_path}"], "mode": "failed", "pages": len(images)}
        mode = "vision" if used_vision else "ocr"
        return {"texts": texts, "mode": mode, "pages": len(images)}

    # ── image parsing ────────────────────────────────────────

    async def _parse_image(self, file_path: str) -> tuple[list[str], dict]:
        """图片解析: OCR + LLM 视觉理解。"""
        texts: list[str] = []
        ocr_text = self._ocr(file_path)
        mode = "ocr"
        if ocr_text.strip():
            texts.append(ocr_text)

        from PIL import Image
        img = Image.open(file_path)
        description = await self._describe_image_with_llm(img)
        texts.append(description)
        mode = "ocr+vision" if ocr_text.strip() else "vision"
        return texts, {"mode": mode, "pages": 1}

    @staticmethod
    def _ocr(image: Any) -> str:
        """OCR 图片提取文字。image 可为路径或 PIL.Image。"""
        try:
            import pytesseract
            from PIL import Image
            if isinstance(image, str):
                image = Image.open(image)
            return pytesseract.image_to_string(image, lang="chi_sim+eng")
        except Exception:
            return ""

    async def _describe_image_with_llm(self, image: Any) -> str:
        """调用 LLM 多模态能力描述图片内容"""
        import base64
        import io

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        messages = [
            SystemMessage(content="你是一个专业的文档分析助手，请详细描述图片中的内容，包括文字、表格、图表信息。"),
            HumanMessage(content=[
                {"type": "text", "text": "请描述这张图片的所有内容："},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]),
        ]
        resp = await self.llm.ainvoke(messages)
        return resp.content

    # ── table parsing ────────────────────────────────────────

    async def _parse_table(self, file_path: str) -> list[str]:
        """表格解析: CSV / Excel → 结构化文本"""
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".csv":
                return self._parse_csv(file_path)
            else:
                return self._parse_excel(file_path)
        except Exception:
            return [f"[表格解析失败] {file_path}"]

    @staticmethod
    def _parse_csv(file_path: str) -> list[str]:
        import csv
        texts: list[str] = []
        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows: list[str] = []
            for row in reader:
                rows.append(" | ".join(f"{h}: {row.get(h, '')}" for h in headers))
            for i in range(0, len(rows), 20):
                batch = rows[i : i + 20]
                texts.append(f"表头: {' | '.join(headers)}\n" + "\n".join(batch))
        return texts or ["[空 CSV]"]

    @staticmethod
    def _parse_excel(file_path: str) -> list[str]:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, read_only=True)
            texts: list[str] = []
            for sheet in wb.worksheets:
                rows = list(sheet.iter_rows(values_only=True))
                if not rows:
                    continue
                headers = [str(c) if c else "" for c in rows[0]]
                data_rows: list[str] = []
                for row in rows[1:]:
                    data_rows.append(" | ".join(
                        f"{headers[j]}: {row[j]}" if j < len(headers) else str(row[j])
                        for j in range(len(row))
                    ))
                for i in range(0, len(data_rows), 20):
                    batch = data_rows[i : i + 20]
                    texts.append(f"工作表: {sheet.title}\n表头: {' | '.join(headers)}\n" + "\n".join(batch))
            return texts or ["[空 Excel]"]
        except Exception:
            return [f"[Excel 解析失败] {file_path}"]

    # ── text / markdown ──────────────────────────────────────

    @staticmethod
    def _parse_text(file_path: str) -> list[str]:
        with open(file_path, encoding="utf-8") as f:
            return [f.read()]

    # ── chunking ─────────────────────────────────────────────

    def _chunk_texts(
        self,
        texts: list[str],
        doc_id: str,
        doc_type: DocType,
        source: str,
        parse_info: dict | None = None,
    ) -> list[DocumentChunk]:
        parse_info = parse_info or {}
        chunks: list[DocumentChunk] = []
        idx = 0
        for text in texts:
            start = 0
            while start < len(text):
                end = start + self.CHUNK_SIZE
                content = text[start:end]
                if content.strip():
                    meta = {"source": source, "char_start": start, "char_end": end}
                    if parse_info.get("mode"):
                        meta["parse_mode"] = parse_info["mode"]
                    if parse_info.get("pages"):
                        meta["pages"] = parse_info["pages"]
                    chunks.append(DocumentChunk(
                        content=content.strip(),
                        doc_id=doc_id,
                        chunk_index=idx,
                        doc_type=doc_type,
                        metadata=meta,
                    ))
                    idx += 1
                start = end - self.CHUNK_OVERLAP
        return chunks
