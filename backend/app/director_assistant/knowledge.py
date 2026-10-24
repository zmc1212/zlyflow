from __future__ import annotations

import io
import math
import re
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

from .repository import AssistantRepository, identifier

_PARSER = ThreadPoolExecutor(max_workers=2, thread_name_prefix="assistant-knowledge")
MAX_UPLOAD = 20 * 1024 * 1024


def tokenize(text: str) -> list[str]:
    terms = re.findall(r"[a-z0-9_]+", text.lower())
    for sequence in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(sequence[i:i + 2] for i in range(max(1, len(sequence) - 1)))
    return terms


def extract_document(filename: str, data: bytes) -> list[tuple[str, str]]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return [("正文", data.decode(encoding))]
            except UnicodeDecodeError:
                continue
        raise ValueError("文本编码无法识别，请转换为 UTF-8")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_UPLOAD:
                    raise ValueError("DOCX 正文过大")
                root = ElementTree.fromstring(archive.read(info))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                return [("正文", "\n".join("".join(p.itertext()) for p in root.findall(".//w:p", ns)))]
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("无法读取 Word 文档") from exc
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("请先解除 PDF 密码保护")
        if len(reader.pages) > 3000:
            raise ValueError("PDF 最多3000页，请分卷导入")
        return [(f"第 {i + 1} 页", page.extract_text() or "") for i, page in enumerate(reader.pages)]
    raise ValueError("支持 TXT、Markdown、DOCX 和文字型 PDF")


def split_sections(pages: list[tuple[str, str]]) -> list[dict]:
    result = []
    for page, text in pages:
        title, buffer = page, ""
        for paragraph in text.replace("\r", "").split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if re.match(r"^(#{1,6}\s|第.{1,18}[回章节卷])", paragraph):
                if buffer:
                    result.append({"section": title, "page": page, "text": buffer})
                    buffer = ""
                title = paragraph.lstrip("# ")[:120]
            while paragraph:
                capacity = 1400 - len(buffer)
                buffer += ("\n" if buffer else "") + paragraph[:capacity]
                paragraph = paragraph[capacity:]
                if len(buffer) >= 1400:
                    result.append({"section": title, "page": page, "text": buffer})
                    buffer = buffer[-120:]
        if buffer.strip():
            result.append({"section": title, "page": page, "text": buffer})
    if not result:
        raise ValueError("未提取到正文；扫描件请先转为文字型 PDF")
    if len(result) > 15000:
        raise ValueError("文档过长，请分卷导入（单份最多15000个片段）")
    return result


class KnowledgeService:
    def __init__(self, repo: AssistantRepository, upload_dir: Path):
        self.repo, self.upload_dir = repo, upload_dir.resolve()
        existing = repo.list("", "knowledge")
        if not any(x["id"] == "builtin-kb-journey" for x in existing):
            kb = repo.insert("", "knowledge", {"name": "西游记设定示例", "description": "工作台编写的创作参考摘要，非原著全文或引文。", "builtin": True}, record_id="builtin-kb-journey")
            doc = repo.insert("", "knowledge_document", {"filename": "西游记人物与世界观示例.md", "knowledge_id": kb["id"], "builtin": True}, parent=kb["id"])
            for chunk in split_sections([("示例摘要", "# 取经与师徒\n《西游记》的取经主线围绕唐僧、孙悟空、猪八戒、沙僧西行展开。孙悟空曾大闹天宫，后护送唐僧取经；猪八戒与沙僧也各有天界往事。师徒在旅途中遭遇妖怪、考验与价值冲突。\n# 三界与人物关系\n故事包含天界、人间与幽冥等空间。天庭、佛门、地方神祇和妖怪形成复杂关系。进行悬疑二创时可围绕身份、动机、隐情和取经途中事件展开；新增阴谋和人物关系属于创作设定，应与原著事实区分。\n# 使用说明\n本库是工作台整理的简短入门示例。具体回目、人物细节和原文引句请导入对应原著资料后查证，不能把本摘要当成原著引文。")]):
                repo.insert("", "knowledge_chunk", {**chunk, "knowledge_id": kb["id"], "filename": doc["filename"]}, parent=doc["id"])

    def catalog(self, owner: str) -> list[dict]:
        output = []
        for kb in self.repo.list(owner, "knowledge", shared=True):
            docs = self.repo.list(owner, "knowledge_document", parent=kb["id"], shared=True)
            output.append({**kb, "documents": [{k: v for k, v in d.items() if k != "source_path"} for d in docs]})
        return output

    def upload(self, owner: str, knowledge_id: str, filename: str, data: bytes) -> dict:
        self.repo.get(owner, knowledge_id, "knowledge")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".docx", ".pdf"} or len(data) > MAX_UPLOAD or not data:
            raise ValueError("请选择20MB以内的 TXT、Markdown、DOCX 或文字型 PDF")
        doc_id = identifier("akd")
        path = self.upload_dir / "director-assistant" / (doc_id + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        doc = self.repo.insert(owner, "knowledge_document", {"knowledge_id": knowledge_id, "filename": Path(filename).name[:255], "source_path": str(path), "error": None}, parent=knowledge_id, record_id=doc_id, status="parsing")
        _PARSER.submit(self.parse, owner, doc_id)
        return {k: v for k, v in doc.items() if k != "source_path"}

    def parse(self, owner: str, doc_id: str) -> None:
        doc = self.repo.get(owner, doc_id, "knowledge_document")
        try:
            path = Path(doc["source_path"]).resolve()
            if not path.is_relative_to(self.upload_dir):
                raise ValueError("资料路径无效")
            chunks = split_sections(extract_document(doc["filename"], path.read_bytes()))
            with self.repo.transaction() as conn:
                doc = self.repo.get(owner, doc_id, "knowledge_document", conn=conn, lock=True)
                conn.execute("DELETE FROM ai_assistant_records WHERE parent_id=? AND kind='knowledge_chunk' AND owner_id=?", (doc_id, owner))
                for chunk in chunks:
                    self.repo.insert(owner, "knowledge_chunk", {**chunk, "knowledge_id": doc["knowledge_id"], "filename": doc["filename"]}, parent=doc_id, conn=conn)
                self.repo.update(owner, doc, {"chunk_count": len(chunks), "error": None}, status="ready", conn=conn)
        except Exception as exc:
            self.repo.update(owner, doc, {"error": str(exc)[:500]}, status="failed")

    def retry(self, owner: str, doc_id: str) -> dict:
        with self.repo.transaction() as conn:
            doc = self.repo.get(owner, doc_id, "knowledge_document", conn=conn, lock=True)
            if doc["status"] != "failed":
                raise ValueError("仅失败的资料可以重试")
            self.repo.update(owner, doc, {"error": None}, status="parsing", conn=conn)
        _PARSER.submit(self.parse, owner, doc_id)
        return {"status": "parsing"}

    def search(self, owner: str, knowledge_ids: list[str], query: str, *, limit=5) -> list[dict]:
        chunks = []
        for kid in knowledge_ids:
            self.repo.get(owner, kid, "knowledge", shared=True)
            for doc in self.repo.list(owner, "knowledge_document", parent=kid, shared=True):
                if doc["status"] == "ready":
                    chunks.extend(self.repo.list(owner, "knowledge_chunk", parent=doc["id"], shared=True, limit=15000))
        if not chunks:
            return []
        query_terms = set(tokenize(query))
        term_counts = [Counter(tokenize(c["section"] + "\n" + c["text"])) for c in chunks]
        df = Counter(term for terms in term_counts for term in query_terms if term in terms)
        lengths = [sum(c.values()) for c in term_counts]
        average = sum(lengths) / len(lengths) or 1
        ranked = []
        for chunk, terms, length in zip(chunks, term_counts, lengths):
            score = 0.0
            for term in query_terms:
                tf = terms[term]
                if tf:
                    score += math.log(1 + (len(chunks) - df[term] + .5) / (df[term] + .5)) * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / average))
            if score > 0:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [{"id": c["id"], "knowledge_id": c["knowledge_id"], "filename": c["filename"], "section": c["section"], "page": c["page"], "text": c["text"]} for _, c in ranked[:limit]]

    def read(self, owner: str, knowledge_ids: list[str], chunk_id: str) -> dict:
        chunk = self.repo.get(owner, chunk_id, "knowledge_chunk", shared=True)
        if chunk["knowledge_id"] not in knowledge_ids:
            raise ValueError("只能读取当前会话选择的知识库")
        self.repo.get(owner, chunk["knowledge_id"], "knowledge", shared=True)
        return {k: chunk[k] for k in ("id", "knowledge_id", "filename", "section", "page", "text")}
