"""
論文匯出服務
支援 BibTeX 和 RIS 格式，供 Zotero、Mendeley 等文獻管理軟體匯入
"""

import re
from pathlib import Path
from typing import Optional

from ..models import Paper


def _make_bibtex_key(paper: Paper) -> str:
    """生成 BibTeX citation key：FirstAuthorYear 格式，或 title 首單字"""
    if paper.year:
        # 取標題第一個有意義的英文單字
        words = re.findall(r'[A-Za-z]{3,}', paper.title)
        word = words[0].lower() if words else "paper"
        return f"{word}{paper.year}"
    else:
        words = re.findall(r'[A-Za-z]{3,}', paper.title)
        return words[0].lower() if words else f"paper{paper.id or 0}"


class PaperExporter:
    """論文格式匯出服務"""

    # ── BibTeX ───────────────────────────────────────────────────────────

    def to_bibtex(self, papers: list[Paper]) -> str:
        """將論文清單轉成 BibTeX 格式字串"""
        entries = []
        used_keys: dict[str, int] = {}

        for paper in papers:
            base_key = _make_bibtex_key(paper)
            # 確保 key 唯一
            count = used_keys.get(base_key, 0)
            key = base_key if count == 0 else f"{base_key}{chr(ord('a') + count - 1)}"
            used_keys[base_key] = count + 1

            entry_type = "article" if paper.venue else "misc"
            lines = [f"@{entry_type}{{{key},"]
            lines.append(f"  title     = {{{paper.title}}},")
            if paper.venue:
                lines.append(f"  journal   = {{{paper.venue}}},")
            if paper.year:
                lines.append(f"  year      = {{{paper.year}}},")
            if paper.doi:
                lines.append(f"  doi       = {{{paper.doi}}},")
            if paper.abstract:
                abstract_clean = paper.abstract.replace('{', '').replace('}', '')[:500]
                lines.append(f"  abstract  = {{{abstract_clean}}},")
            if paper.tags:
                lines.append(f"  keywords  = {{{', '.join(paper.tags)}}},")
            lines.append("}")
            entries.append("\n".join(lines))

        return "\n\n".join(entries)

    def save_bibtex(self, papers: list[Paper], output_path: str | Path) -> None:
        """儲存 BibTeX 檔案"""
        Path(output_path).write_text(self.to_bibtex(papers), encoding="utf-8")

    # ── RIS ──────────────────────────────────────────────────────────────

    def to_ris(self, papers: list[Paper]) -> str:
        """將論文清單轉成 RIS 格式字串"""
        entries = []
        for paper in papers:
            lines = ["TY  - JOUR" if paper.venue else "TY  - GEN"]
            lines.append(f"TI  - {paper.title}")
            if paper.venue:
                lines.append(f"JO  - {paper.venue}")
            if paper.year:
                lines.append(f"PY  - {paper.year}")
            if paper.doi:
                lines.append(f"DO  - {paper.doi}")
            if paper.abstract:
                lines.append(f"AB  - {paper.abstract[:800]}")
            for tag in (paper.tags or []):
                lines.append(f"KW  - {tag}")
            lines.append("ER  -")
            entries.append("\n".join(lines))

        return "\n\n".join(entries)

    def save_ris(self, papers: list[Paper], output_path: str | Path) -> None:
        """儲存 RIS 檔案"""
        Path(output_path).write_text(self.to_ris(papers), encoding="utf-8")
