"""
學術格式解析器
支援：BibTeX (.bib)、RIS (.ris)、EndNote XML (.xml)

均回傳 list[dict]，每個 dict 欄位與 XLSXIngestion 相容：
  title, abstract, doi, authors, venue, year, tags
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path


# ── BibTeX ────────────────────────────────────────────────────────────

def parse_bibtex(path: str | Path) -> list[dict]:
    """解析 .bib 檔，回傳論文清單。不依賴第三方套件。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    papers = []

    # 找出每個 entry：@TYPE{key, ... }
    entry_pattern = re.compile(
        r'@\w+\s*\{[^,]+,\s*(.*?)\n\}',
        re.DOTALL | re.IGNORECASE,
    )
    field_pattern = re.compile(
        r'(\w+)\s*=\s*[\{"](.*?)[\}"](?:\s*,|\s*$)',
        re.DOTALL,
    )

    for entry_m in entry_pattern.finditer(text):
        body = entry_m.group(1)
        fields: dict[str, str] = {}
        for fm in field_pattern.finditer(body):
            key = fm.group(1).lower().strip()
            val = fm.group(2).strip()
            # 移除 BibTeX 內部大括號
            val = re.sub(r'\{|\}', '', val).strip()
            fields[key] = val

        title = fields.get("title", "").strip()
        if not title:
            continue

        paper: dict = {"title": title}

        if "abstract" in fields:
            paper["abstract"] = fields["abstract"]
        if "doi" in fields:
            paper["doi"] = fields["doi"]
        if "year" in fields:
            try:
                paper["year"] = int(fields["year"][:4])
            except (ValueError, TypeError):
                pass
        if "journal" in fields:
            paper["venue"] = fields["journal"]
        elif "booktitle" in fields:
            paper["venue"] = fields["booktitle"]

        # 作者：BibTeX 用 " and " 分隔
        if "author" in fields:
            raw_authors = fields["author"]
            parts = [a.strip() for a in raw_authors.split(" and ") if a.strip()]
            paper["authors"] = parts

        # 關鍵字
        kw_raw = fields.get("keywords", "") or fields.get("keyword", "")
        if kw_raw:
            paper["tags"] = [k.strip() for k in re.split(r"[;,]", kw_raw) if k.strip()]

        papers.append(paper)

    return papers


# ── RIS ──────────────────────────────────────────────────────────────

_RIS_FIELD_MAP = {
    "TI": "title",
    "T1": "title",
    "AB": "abstract",
    "DO": "doi",
    "PY": "year",
    "Y1": "year",
    "JO": "venue",
    "JF": "venue",
    "T2": "venue",
    "BT": "venue",
}


def parse_ris(path: str | Path) -> list[dict]:
    """解析 .ris 檔，回傳論文清單。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    papers = []
    current: dict = {}
    authors: list[str] = []
    tags: list[str] = []

    def _flush():
        nonlocal current, authors, tags
        if current.get("title"):
            if authors:
                current["authors"] = authors
            if tags:
                current["tags"] = tags
            papers.append(current)
        current = {}
        authors = []
        tags = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # RIS format: "TY  - value"
        m = re.match(r'^([A-Z0-9]{2})\s+-\s*(.*)', line)
        if not m:
            continue

        tag, value = m.group(1), m.group(2).strip()

        if tag == "ER":
            _flush()
            continue
        if tag == "TY":
            continue   # entry type, skip

        if tag in ("AU", "A1", "A2"):
            if value:
                authors.append(value)
        elif tag in ("KW", "DE"):
            if value:
                tags.append(value)
        elif tag == "PY" or tag == "Y1":
            try:
                current["year"] = int(value[:4])
            except (ValueError, TypeError):
                pass
        elif tag in _RIS_FIELD_MAP:
            field = _RIS_FIELD_MAP[tag]
            if field not in current:   # 先到先得，T1/TI 都對應 title
                current[field] = value

    _flush()   # 最後一筆如果沒有 ER 標記
    return papers


# ── EndNote XML ──────────────────────────────────────────────────────

def parse_endnote_xml(path: str | Path) -> list[dict]:
    """解析 EndNote XML (.xml) 匯出格式，回傳論文清單。"""
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as e:
        raise ValueError(f"XML 解析失敗：{e}") from e

    root = tree.getroot()
    papers = []

    # 支援 <records>/<record> 或 <xml><records><record>
    records = root.findall(".//record")

    for rec in records:
        def _text(xpath):
            el = rec.find(xpath)
            return el.text.strip() if el is not None and el.text else ""

        def _texts(xpath):
            return [el.text.strip() for el in rec.findall(xpath) if el.text]

        title = (
            _text(".//titles/title/style")
            or _text(".//titles/title")
            or _text(".//title/style")
            or _text(".//title")
        )
        if not title:
            continue

        paper: dict = {"title": title}

        abstract = _text(".//abstract/style") or _text(".//abstract")
        if abstract:
            paper["abstract"] = abstract

        doi = _text(".//electronic-resource-num/style") or _text(".//electronic-resource-num")
        if doi:
            paper["doi"] = doi.strip()

        year_raw = _text(".//dates/year/style") or _text(".//dates/year")
        if year_raw:
            try:
                paper["year"] = int(year_raw[:4])
            except (ValueError, TypeError):
                pass

        venue = (
            _text(".//periodical/full-title/style")
            or _text(".//periodical/full-title")
            or _text(".//full-title")
        )
        if venue:
            paper["venue"] = venue

        # 作者
        author_els = rec.findall(".//contributors/authors/author")
        if not author_els:
            author_els = rec.findall(".//author")
        authors = []
        for el in author_els:
            name = (el.find("style").text if el.find("style") is not None
                    else el.text) or ""
            if name.strip():
                authors.append(name.strip())
        if authors:
            paper["authors"] = authors

        # 關鍵字
        kw_els = rec.findall(".//keywords/keyword")
        kws = []
        for el in kw_els:
            val = (el.find("style").text if el.find("style") is not None
                   else el.text) or ""
            if val.strip():
                kws.append(val.strip())
        if kws:
            paper["tags"] = kws

        papers.append(paper)

    return papers


# ── 統一入口 ──────────────────────────────────────────────────────────

def parse_reference_file(path: str | Path) -> list[dict]:
    """根據副檔名自動選擇解析器，回傳論文清單。"""
    suffix = Path(path).suffix.lower()
    if suffix == ".bib":
        return parse_bibtex(path)
    elif suffix == ".ris":
        return parse_ris(path)
    elif suffix == ".xml":
        return parse_endnote_xml(path)
    else:
        raise ValueError(f"不支援的格式：{suffix}（支援 .bib / .ris / .xml）")
