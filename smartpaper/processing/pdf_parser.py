"""
PDF 解析模組
Section 為主框架 + Paragraph 為切割單位 + 表格抽取
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


# ── 已知 section 名稱（英文，小寫）
KNOWN_SECTIONS_EN = {
    "abstract", "introduction", "background", "motivation",
    "related work", "related works", "literature review", "prior work",
    "preliminary", "preliminaries", "problem formulation", "problem statement",
    "methodology", "method", "methods", "approach", "proposed method", "proposed approach",
    "model", "framework", "architecture", "system design", "system overview",
    "experiment", "experiments", "experimental setup", "experimental results",
    "experimental evaluation", "evaluation", "evaluation setup",
    "results", "result", "analysis", "discussion", "ablation", "ablation study",
    "conclusion", "conclusions", "future work", "future directions",
    "acknowledgment", "acknowledgements", "acknowledgments",
    "references", "bibliography", "appendix",
}

# ── 已知 section 名稱（中文）
KNOWN_SECTIONS_ZH = {
    "摘要", "前言", "引言", "緒論", "研究背景", "研究動機", "研究目的",
    "文獻回顧", "文獻探討", "相關研究", "理論基礎", "背景",
    "研究方法", "方法論", "研究設計", "研究架構", "系統架構", "模型",
    "實驗", "實驗設計", "實驗結果", "評估", "分析", "討論",
    "結論", "結語", "研究結論", "未來展望", "未來研究",
    "致謝", "致謝辭", "參考文獻", "附錄",
}

KNOWN_SECTIONS = KNOWN_SECTIONS_EN | KNOWN_SECTIONS_ZH

# 跳過這些 section（對 QA 無用）
SKIP_SECTIONS_EN = {
    "references", "bibliography",
    "acknowledgment", "acknowledgements", "acknowledgments",
    "appendix",
}
SKIP_SECTIONS_ZH = {"參考文獻", "致謝", "致謝辭", "附錄"}
SKIP_SECTIONS = SKIP_SECTIONS_EN | SKIP_SECTIONS_ZH

# 段落合併閾值
MIN_CHUNK_CHARS = 150   # 太短的段落往後合併
MAX_CHUNK_CHARS = 1200  # 太長的段落在句子邊界切割
OVERLAP_CHARS = 80      # 跨段落重疊（保留 context 連貫性）


# ── Section 語意分類與重要性權重 ────────────────────────────────────────

SECTION_CANONICAL: dict[str, str] = {
    # abstract
    "abstract": "abstract", "摘要": "abstract",
    # introduction
    "introduction": "introduction", "前言": "introduction",
    "引言": "introduction", "緒論": "introduction",
    "研究背景": "introduction", "研究動機": "introduction",
    "background": "introduction", "motivation": "introduction",
    # related work
    "related work": "related_work", "related works": "related_work",
    "literature review": "related_work", "prior work": "related_work",
    "文獻回顧": "related_work", "文獻探討": "related_work", "相關研究": "related_work",
    # methodology
    "methodology": "methodology", "method": "methodology", "methods": "methodology",
    "approach": "methodology", "proposed method": "methodology",
    "proposed approach": "methodology", "framework": "methodology",
    "model": "methodology", "system design": "methodology",
    "研究方法": "methodology", "方法論": "methodology",
    "研究設計": "methodology", "系統架構": "methodology", "架構": "methodology",
    # results / experiments
    "results": "results", "result": "results",
    "experiments": "results", "experiment": "results",
    "experimental results": "results", "evaluation": "results",
    "experimental evaluation": "results", "experimental setup": "results",
    "實驗": "results", "實驗結果": "results", "評估": "results",
    # discussion
    "discussion": "discussion", "analysis": "discussion",
    "ablation": "discussion", "ablation study": "discussion",
    "討論": "discussion", "分析": "discussion",
    # conclusion
    "conclusion": "conclusion", "conclusions": "conclusion",
    "future work": "conclusion", "future directions": "conclusion",
    "結論": "conclusion", "結語": "conclusion",
    "未來展望": "conclusion", "未來研究": "conclusion",
}

SECTION_IMPORTANCE: dict[str, float] = {
    "abstract":     1.5,   # 全文精華，最優先
    "methodology":  1.4,   # 核心方法
    "results":      1.3,   # 實驗數據
    "conclusion":   1.2,   # 總結
    "introduction": 1.1,   # 背景動機
    "discussion":   1.1,   # 分析解讀
    "related_work": 0.85,  # 相關工作（避免壓過主論文方法）
    "other":        1.0,
}


def _classify_section(section_name: str) -> tuple[str, float]:
    """把 section 原始名稱 → (section_type, importance_weight)"""
    import re as _re
    s = section_name.lower().strip()
    # 去掉數字/羅馬數字前綴（如 "3. results" → "results"，"IV. conclusion" → "conclusion"）
    s_clean = _re.sub(r'^[\d\.]+\s+', '', s)
    s_clean = _re.sub(r'^[ivxlcdm]+\.\s+', '', s_clean, flags=_re.I)

    for candidate in [s, s_clean]:
        # 完全比對
        if candidate in SECTION_CANONICAL:
            st = SECTION_CANONICAL[candidate]
            return st, SECTION_IMPORTANCE.get(st, 1.0)
        # 前綴比對
        for key, canonical in SECTION_CANONICAL.items():
            if candidate.startswith(key):
                return canonical, SECTION_IMPORTANCE.get(canonical, 1.0)

    return "other", SECTION_IMPORTANCE["other"]


@dataclass
class ParsedChunk:
    section: str
    text: str
    chunk_index: int
    page_num: int
    is_table: bool = False
    section_type: str = "other"      # canonical type（abstract/methodology/results…）
    importance_weight: float = 1.0   # RAG 檢索加權


@dataclass
class ParseResult:
    chunks: list[ParsedChunk] = field(default_factory=list)
    total_pages: int = 0
    sections_found: list[str] = field(default_factory=list)
    table_count: int = 0
    error: Optional[str] = None


# ── Section header 偵測 ─────────────────────────────────────────────────

# ── 正規表達式
# 英文數字前綴："1.", "2.1", "3.2.1"
_RE_NUMBERED = re.compile(r'^\d+(\.\d+)*\.?\s+(.+)$')
# 羅馬數字："I.", "II.", "III."
_RE_ROMAN = re.compile(r'^(I{1,3}|IV|V?I{0,3}|IX|X)\.\s+(.+)$', re.IGNORECASE)
# 全大寫英文
_RE_ALL_CAPS = re.compile(r'^[A-Z][A-Z\s\-&:]{3,}$')
# 中文數字前綴："一、", "二、", "（一）", "第一節", "壹、"
_RE_ZH_NUMBERED = re.compile(
    r'^[（(]?[一二三四五六七八九十百壹貳參肆伍陸柒捌玖拾]+[）)、。]?\s*(.+)$'
)
# 「第N節/章」
_RE_ZH_CHAPTER = re.compile(r'^第[一二三四五六七八九十\d]+[章節]\s*(.*)$')
# 中文阿拉伯混合："1. 摘要"
_RE_ZH_ARABIC = re.compile(r'^\d+[\.、]\s*([一-鿿].+)$')


def _is_section_header(line: str) -> tuple[bool, str]:
    """
    判斷一行是否為 section header（支援中英文）。
    回傳 (is_header, section_name)。
    """
    line = line.strip()
    if not line or len(line) > 80:
        return False, ""

    # ── 英文：數字前綴
    m = _RE_NUMBERED.match(line)
    if m:
        name = m.group(2).strip().lower()
        if any(name.startswith(s) or s.startswith(name.split()[0])
               for s in KNOWN_SECTIONS_EN):
            return True, name

    # ── 英文：羅馬數字前綴
    m = _RE_ROMAN.match(line)
    if m:
        name = m.group(2).strip().lower()
        if name in KNOWN_SECTIONS_EN or any(name.startswith(s)
                                             for s in KNOWN_SECTIONS_EN):
            return True, name

    # ── 英文：全大寫
    if _RE_ALL_CAPS.match(line):
        name = line.strip().lower()
        if name in KNOWN_SECTIONS_EN or any(name.startswith(s)
                                             for s in KNOWN_SECTIONS_EN):
            return True, name

    # ── 英文：首字大寫完全匹配
    lower = line.strip().lower().rstrip(".")
    if lower in KNOWN_SECTIONS_EN:
        return True, lower

    # ── 中文：直接比對已知 section 名稱
    stripped = line.strip().rstrip("。：:")
    if stripped in KNOWN_SECTIONS_ZH:
        return True, stripped

    # ── 中文：阿拉伯數字前綴（"1. 摘要"）
    m = _RE_ZH_ARABIC.match(line)
    if m:
        name = m.group(1).strip().rstrip("。：:")
        if name in KNOWN_SECTIONS_ZH or any(name.startswith(s)
                                              for s in KNOWN_SECTIONS_ZH):
            return True, name

    # ── 中文：中文數字前綴（"一、研究方法"）
    m = _RE_ZH_NUMBERED.match(line)
    if m:
        name = m.group(1).strip().rstrip("。：:")
        if name in KNOWN_SECTIONS_ZH or any(name.startswith(s)
                                              for s in KNOWN_SECTIONS_ZH):
            return True, name

    # ── 中文：「第N章/節」
    m = _RE_ZH_CHAPTER.match(line)
    if m:
        rest = m.group(1).strip().rstrip("。：:")
        # 有標題內容且符合已知 section
        if rest and (rest in KNOWN_SECTIONS_ZH or any(rest.startswith(s)
                                                        for s in KNOWN_SECTIONS_ZH)):
            return True, rest
        # 沒有額外名稱（如「第一章」），直接用章節作為 section
        if not rest:
            return True, line.strip()

    return False, ""


# ── 文字清理 ────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """清理 pdfplumber 抽出的原始文字"""
    # 處理斷行連字號：algo-\nrithm → algorithm
    text = re.sub(r'-\n', '', text)
    # 段落內換行 → 空格
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    # 多個空格 → 單一空格
    text = re.sub(r' {2,}', ' ', text)
    # 刪除行首/行尾多餘空格
    lines = [l.strip() for l in text.split('\n')]
    return '\n'.join(lines)


# ── 段落切割與 chunk 合併 ───────────────────────────────────────────────

def _split_into_paragraphs(text: str) -> list[str]:
    """以空行分割段落，過濾空段落"""
    paras = re.split(r'\n\s*\n', text)
    return [p.strip() for p in paras if p.strip()]


def _split_long_paragraph(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """在句子邊界切割過長段落（支援中英文）"""
    if len(text) <= max_chars:
        return [text]
    # 中英文句子邊界：. ! ? 。！？
    sentences = re.split(r'(?<=[.!?。！？])\s*', text)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= max_chars:
            current = (current + " " + sent).strip() if current else sent
        else:
            if current:
                chunks.append(current)
            current = sent
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


def _merge_short_paragraphs(paras: list[str]) -> list[str]:
    """合併太短的段落"""
    merged, buf = [], ""
    for p in paras:
        if not buf:
            buf = p
        elif len(buf) < MIN_CHUNK_CHARS:
            buf = buf + "\n" + p
        else:
            merged.append(buf)
            buf = p
    if buf:
        merged.append(buf)
    return merged


def _build_chunks_from_section(
    section_name: str,
    section_text: str,
    start_chunk_index: int,
    page_num: int,
) -> list[ParsedChunk]:
    """將 section 文字轉成 ParsedChunk 列表"""
    paras = _split_into_paragraphs(section_text)
    paras = _merge_short_paragraphs(paras)
    section_type, importance_weight = _classify_section(section_name)

    chunks = []
    idx = start_chunk_index
    for para in paras:
        sub_chunks = _split_long_paragraph(para)
        for sub in sub_chunks:
            if len(sub.strip()) < 50:
                continue
            chunks.append(ParsedChunk(
                section=section_name,
                text=sub.strip(),
                chunk_index=idx,
                page_num=page_num,
                is_table=False,
                section_type=section_type,
                importance_weight=importance_weight,
            ))
            idx += 1
    return chunks


# ── 表格格式化 ──────────────────────────────────────────────────────────

def _format_table(table: list[list]) -> Optional[str]:
    """將 pdfplumber 抽出的表格格式化為可讀文字"""
    if not table:
        return None
    rows = []
    for row in table:
        cells = [str(cell or "").strip().replace("\n", " ") for cell in row]
        rows.append(" | ".join(cells))
    if not rows:
        return None
    # 加上分隔線（第一行視為標題）
    if len(rows) > 1:
        sep = " | ".join(["---"] * len(table[0]))
        rows.insert(1, sep)
    return "\n".join(rows)


# ── 主要解析函數 ────────────────────────────────────────────────────────

_MIN_PAGE_CHARS = 30  # 少於此字元才嘗試下一個策略


def _extract_page_text(page) -> str:
    """從 pdfplumber 頁面提取文字，找到足夠文字即停止（快速路徑優先）"""

    # 策略 1：最常見，成功率高，優先嘗試（早停）
    try:
        t = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
        if len(t.strip()) >= _MIN_PAGE_CHARS:
            return t
    except Exception:
        pass

    # 策略 2：寬鬆 tolerance（掃描品質差的 PDF）
    try:
        t = page.extract_text(x_tolerance=6, y_tolerance=6) or ""
        if len(t.strip()) >= _MIN_PAGE_CHARS:
            return t
    except Exception:
        pass

    # 策略 3：layout 模式（多欄版面，較慢，只在前兩策略失敗時嘗試）
    try:
        t = page.extract_text(layout=True) or ""
        if len(t.strip()) >= _MIN_PAGE_CHARS:
            return t
    except Exception:
        pass

    # 策略 4：words 重組（最後手段，較慢）
    try:
        words = page.extract_words(x_tolerance=3, y_tolerance=3,
                                   keep_blank_chars=False)
        if words:
            words_sorted = sorted(words, key=lambda w: (round(w["top"] / 5) * 5, w["x0"]))
            lines_map: dict[int, list[str]] = {}
            for w in words_sorted:
                key = round(w["top"] / 5) * 5
                lines_map.setdefault(key, []).append(w["text"])
            t = "\n".join(" ".join(ws) for ws in lines_map.values())
            if t.strip():
                return t
    except Exception:
        pass

    return ""


def parse_pdf(file_path: str | Path) -> ParseResult:
    """
    解析 PDF 檔案，回傳 ParseResult（chunks + 統計資訊）。

    提取策略（依序嘗試直到成功）：
    1. pdfplumber — 多 tolerance + layout + words 模式
    2. pypdf      — 備用
    3. PyMuPDF    — 針對複雜版面 / 特殊字型（需 pip install pymupdf）
    4. 若全部失敗 → 回傳清楚的錯誤訊息
    """
    if not PDFPLUMBER_AVAILABLE:
        return ParseResult(error="pdfplumber 未安裝，請執行 pip install pdfplumber")

    file_path = Path(file_path)
    if not file_path.exists():
        return ParseResult(error=f"找不到檔案：{file_path}")

    result = ParseResult()
    chunk_index = 0
    total_raw_chars = 0

    sections: list[tuple[str, str, int]] = []
    current_section = "preamble"
    current_page = 1
    current_lines: list[str] = []

    # ── 策略 1：pdfplumber ─────────────────────────────────────────────
    try:
        with pdfplumber.open(file_path) as pdf:
            result.total_pages = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables() or []

                raw_text = _extract_page_text(page)
                total_raw_chars += len(raw_text)
                raw_text = _clean_text(raw_text)

                for line in raw_text.split('\n'):
                    is_hdr, section_name = _is_section_header(line)
                    if is_hdr:
                        if current_lines:
                            sections.append((current_section,
                                             "\n".join(current_lines), current_page))
                        current_section = section_name
                        current_page = page_num
                        current_lines = []
                    else:
                        current_lines.append(line)

                for table in tables:
                    formatted = _format_table(table)
                    if not formatted or len(formatted) < 30:
                        continue
                    if _should_skip(current_section):
                        continue
                    sections.append((f"{current_section} [Table]", formatted, page_num))
                    result.table_count += 1

            if current_lines:
                sections.append((current_section, "\n".join(current_lines), current_page))

    except Exception as e:
        return ParseResult(error=f"PDF 開啟失敗：{e}")

    # ── 策略 2：pypdf fallback ──────────────────────────────────────────
    if total_raw_chars < 50:
        try:
            import pypdf
            fallback_lines: list[str] = []
            with pypdf.PdfReader(str(file_path)) as reader:
                if not result.total_pages:
                    result.total_pages = len(reader.pages)
                for pg in reader.pages:
                    t = pg.extract_text() or ""
                    total_raw_chars += len(t)
                    if t.strip():
                        fallback_lines.extend(t.split('\n'))
            if fallback_lines:
                sections = [("preamble", "\n".join(fallback_lines), 1)]
        except Exception:
            pass

    # ── 策略 3：PyMuPDF fallback（最強，對複雜版面 / 特殊字型最好）──
    if total_raw_chars < 50:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(file_path))
            if not result.total_pages:
                result.total_pages = len(doc)
            all_text_parts = []
            for pg in doc:
                # "blocks" 模式對多欄版面好很多
                blocks = pg.get_text("blocks")
                for b in sorted(blocks, key=lambda b: (b[1], b[0])):
                    t = b[4].strip()
                    if t:
                        all_text_parts.append(t)
                        total_raw_chars += len(t)
            if all_text_parts:
                sections = [("preamble", "\n\n".join(all_text_parts), 1)]
            doc.close()
        except ImportError:
            pass  # PyMuPDF 未安裝，不報錯
        except Exception:
            pass

    if total_raw_chars < 50:
        tips = (
            "PDF 無法提取文字（共 0 字元）。常見原因：\n"
            "① 掃描版 PDF（純圖片）→ 請先用 Adobe Acrobat 或 tesseract OCR 處理\n"
            "② PDF 有密碼保護 → 請先解除保護\n"
            "③ 特殊字型嵌入問題 → 嘗試安裝 PyMuPDF：pip install pymupdf\n"
            "   然後重新上傳，會自動使用 PyMuPDF 解析"
        )
        return ParseResult(error=tips)

    # ── 轉換為 chunks
    sections_seen: set[str] = set()
    for section_name, text, page_num in sections:
        base_section = section_name.replace(" [Table]", "")

        if _should_skip(base_section):
            continue

        is_table = "[Table]" in section_name

        if is_table:
            if len(text.strip()) >= 30:
                s_type, s_weight = _classify_section(base_section)
                result.chunks.append(ParsedChunk(
                    section=base_section,
                    text=f"[表格]\n{text.strip()}",
                    chunk_index=chunk_index,
                    page_num=page_num,
                    is_table=True,
                    section_type=s_type,
                    importance_weight=s_weight * 1.1,  # 表格額外加成
                ))
                chunk_index += 1
        else:
            new_chunks = _build_chunks_from_section(
                section_name=section_name,
                section_text=text,
                start_chunk_index=chunk_index,
                page_num=page_num,
            )
            result.chunks.extend(new_chunks)
            chunk_index += len(new_chunks)

        if base_section not in sections_seen:
            sections_seen.add(base_section)
            result.sections_found.append(base_section)

    return result


def _should_skip(section_name: str) -> bool:
    """判斷此 section 是否應跳過（支援中英文）"""
    s = section_name.strip()
    lower = s.lower()
    # 英文比對
    if any(lower == sk or lower.startswith(sk) for sk in SKIP_SECTIONS_EN):
        return True
    # 中文比對
    if any(s == sk or s.startswith(sk) for sk in SKIP_SECTIONS_ZH):
        return True
    return False
