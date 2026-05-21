"""
知識圖譜服務
用 pyvis 建立互動式 HTML 網路圖：
- 論文節點（大小 ∝ 引用數，顏色 = 主要標籤 / 年份 / 引用數）
- 引用邊（藍色有向箭頭）
- 共享概念邊（灰色無向，粗細 ∝ 共享概念數）
- 漂亮的側邊欄 + 右側論文詳情面板
"""

import json
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional

from ..database.sqlite_db import SQLiteDB
from ..models import Paper


# 標籤顏色映射（前 10 個最常見標籤給固定顏色）
_PALETTE = [
    "#6366f1", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
    "#9c755f", "#bab0ac",
]


def _truncate(text: str, n: int = 35) -> str:
    return text[:n] + "…" if len(text) > n else text


def _lerp_color(c1: str, c2: str, t: float) -> str:
    """Linear interpolate between two hex colors (t in [0,1])."""
    def parse(c):
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    r1, g1, b1 = parse(c1)
    r2, g2, b2 = parse(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _color_by_year(year: Optional[int], min_y: int, max_y: int) -> str:
    """Cool blue (old) → warm amber (recent)."""
    if year is None:
        return "#64748b"
    span = max(max_y - min_y, 1)
    t = (year - min_y) / span
    return _lerp_color("#60a5fa", "#f59e0b", t)


def _color_by_citations(count: int, max_c: int) -> str:
    """Light grey (low) → vivid indigo (high)."""
    if max_c <= 0:
        return "#64748b"
    t = min(count / max_c, 1.0)
    return _lerp_color("#94a3b8", "#6366f1", t)


class KnowledgeGraphService:
    """知識圖譜建構服務"""

    def __init__(self, sqlite_db: Optional[SQLiteDB] = None):
        self.db = sqlite_db or SQLiteDB()

    # ── Public API ────────────────────────────────────────────────────────

    def build_citation_graph(
        self,
        max_nodes: int = 200,
        output_path: Optional[str] = None,
    ) -> str:
        """建立引用關係圖：論文節點 + 引用邊"""
        papers = self.db.get_all(limit=max_nodes)
        paper_map = {p.id: p for p in papers}

        tag_color = self._build_tag_color_map(papers)
        net = self._make_network(directed=True)

        for p in papers:
            self._add_paper_node(net, p, tag_color)

        for p in papers:
            refs = self.db.get_references(p.id)
            for ref in refs:
                cited_id = ref.get("cited_paper_id")
                if cited_id and cited_id in paper_map:
                    try:
                        net.add_edge(
                            p.id, cited_id,
                            color="#3a86ff",
                            width=1.5,
                            arrows="to",
                            title="引用",
                        )
                    except Exception:
                        pass

        return self._save_and_return(net, output_path, "citation_graph")

    def build_concept_graph(
        self,
        min_shared: int = 2,
        max_nodes: int = 200,
        output_path: Optional[str] = None,
    ) -> str:
        """建立共享概念圖：論文節點 + 共享概念邊（共享 ≥ min_shared 個概念）"""
        papers = self.db.get_all(limit=max_nodes)
        tag_color = self._build_tag_color_map(papers)
        net = self._make_network(directed=False)

        concept_sets: dict[int, set[int]] = {}
        for p in papers:
            rows = self.db._concept_ids_for_paper(p.id)
            if rows:
                concept_sets[p.id] = set(rows)
            self._add_paper_node(net, p, tag_color)

        paper_ids = list(concept_sets.keys())
        for i in range(len(paper_ids)):
            for j in range(i + 1, len(paper_ids)):
                pid1, pid2 = paper_ids[i], paper_ids[j]
                shared = len(concept_sets[pid1] & concept_sets[pid2])
                if shared >= min_shared:
                    try:
                        net.add_edge(
                            pid1, pid2,
                            color="#adb5bd",
                            width=min(shared, 6),
                            title=f"共享 {shared} 個概念",
                        )
                    except Exception:
                        pass

        return self._save_and_return(net, output_path, "concept_graph")

    def build_combined_graph(
        self,
        min_shared: int = 2,
        max_nodes: int = 200,
        output_path: Optional[str] = None,
    ) -> str:
        """合併圖：引用邊（藍）+ 共享概念邊（灰）"""
        papers = self.db.get_all(limit=max_nodes)
        paper_map = {p.id: p for p in papers}
        tag_color = self._build_tag_color_map(papers)
        net = self._make_network(directed=False)

        concept_sets: dict[int, set[int]] = {}
        for p in papers:
            self._add_paper_node(net, p, tag_color)
            rows = self.db._concept_ids_for_paper(p.id)
            if rows:
                concept_sets[p.id] = set(rows)

        for p in papers:
            for ref in self.db.get_references(p.id):
                cited_id = ref.get("cited_paper_id")
                if cited_id and cited_id in paper_map:
                    try:
                        net.add_edge(
                            p.id, cited_id,
                            color="#3a86ff",
                            width=2,
                            title="引用關係",
                            dashes=False,
                        )
                    except Exception:
                        pass

        paper_ids = list(concept_sets.keys())
        for i in range(len(paper_ids)):
            for j in range(i + 1, len(paper_ids)):
                pid1, pid2 = paper_ids[i], paper_ids[j]
                shared = len(concept_sets[pid1] & concept_sets[pid2])
                if shared >= min_shared:
                    try:
                        net.add_edge(
                            pid1, pid2,
                            color="#adb5bd",
                            width=min(shared, 5),
                            title=f"共享 {shared} 個概念",
                            dashes=True,
                        )
                    except Exception:
                        pass

        return self._save_and_return(net, output_path, "combined_graph")

    def get_graph_stats(self) -> dict:
        """回傳圖譜統計資訊"""
        papers = self.db.get_all(limit=5000)
        total = len(papers)
        with_citations = sum(1 for p in papers if self.db.has_citations(p.id))
        with_concepts = sum(1 for p in papers if self.db.has_concepts(p.id))

        year_dist: dict[int, int] = {}
        for p in papers:
            if p.year:
                year_dist[p.year] = year_dist.get(p.year, 0) + 1

        return {
            "total_papers": total,
            "with_citations": with_citations,
            "with_concepts": with_concepts,
            "year_distribution": dict(sorted(year_dist.items())),
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    def _make_network(self, directed: bool = False):
        from pyvis.network import Network
        net = Network(
            height="720px",
            width="100%",
            directed=directed,
            bgcolor="#1a1a2e",
            font_color="#e0e0e0",
            notebook=False,
        )
        net.set_options(json.dumps({
            "nodes": {
                "borderWidth": 1,
                "borderWidthSelected": 3,
                "font": {"size": 11},
            },
            "edges": {
                "smooth": {"type": "dynamic"},
                "selectionWidth": 3,
            },
            "physics": {
                "barnesHut": {
                    "gravitationalConstant": -8000,
                    "springLength": 120,
                    "springConstant": 0.04,
                },
                "stabilization": {"iterations": 150},
            },
            "interaction": {
                "hover": True,
                "navigationButtons": True,
                "tooltipDelay": 200,
            },
        }))
        return net

    def _build_tag_color_map(self, papers: list[Paper]) -> dict[str, str]:
        """為最常見標籤分配顏色"""
        tag_count: dict[str, int] = {}
        for p in papers:
            for t in (p.tags or []):
                tag_count[t] = tag_count.get(t, 0) + 1

        top_tags = sorted(tag_count, key=lambda t: tag_count[t], reverse=True)[:len(_PALETTE)]
        return {tag: _PALETTE[i] for i, tag in enumerate(top_tags)}

    def _add_paper_node(self, net, paper: Paper, tag_color: dict[str, str]) -> None:
        color = "#8ecae6"
        if paper.tags:
            color = tag_color.get(paper.tags[0], "#8ecae6")

        cite_count = paper.citation_count or 0
        size = max(12, min(40, 12 + cite_count // 5))

        venue_str = f"\n📰 {paper.venue}" if paper.venue else ""
        year_str = f" ({paper.year})" if paper.year else ""
        tags_str = f"\n🏷 {', '.join(paper.tags[:3])}" if paper.tags else ""
        cite_str = f"\n📊 引用 {cite_count} 次" if cite_count else ""

        tooltip = f"<b>{paper.title}</b>{year_str}{venue_str}{tags_str}{cite_str}"

        net.add_node(
            paper.id,
            label=_truncate(paper.title),
            title=tooltip,
            color=color,
            size=size,
        )

    def _save_and_return(self, net, output_path: Optional[str], prefix: str) -> str:
        if output_path:
            path = Path(output_path)
        else:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", prefix=f"smartpaper_{prefix}_", delete=False
            )
            path = Path(tmp.name)
            tmp.close()

        net.save_graph(str(path))
        return str(path)

    def open_in_browser(self, html_path: str) -> None:
        webbrowser.open(f"file:///{Path(html_path).resolve()}")

    # ── Interactive graph (pyvis → browser) ──────────────────────────────

    def build_interactive_graph(
        self,
        graph_type: str = "tag",        # "tag" | "concept" | "citation"
        min_shared: int = 1,
        paper_ids: Optional[list[int]] = None,
        output_path: Optional[str] = None,
        color_by: str = "tag",          # "tag" | "year" | "citations"
        layout: str = "physics",        # "physics" | "hierarchical"
    ) -> str:
        """
        Build a fully interactive pyvis/vis.js graph and return the HTML path.

        Args:
            graph_type:  edge type ("tag" | "concept" | "citation")
            min_shared:  minimum shared tags/concepts to draw an edge
            paper_ids:   which papers to include; None means all
            output_path: optional file path for output HTML
            color_by:    node colour scheme ("tag" | "year" | "citations")
            layout:      graph layout ("physics" | "hierarchical")
        Returns:
            path to the generated HTML file
        """
        from pyvis.network import Network

        if paper_ids is not None:
            all_papers = self.db.get_all(limit=5000)
            papers = [p for p in all_papers if p.id in set(paper_ids)]
        else:
            papers = self.db.get_all(limit=300)

        if not papers:
            return ""

        tag_color = self._build_tag_color_map(papers)
        paper_map = {p.id: p for p in papers}

        # Year / citation ranges for colour schemes
        years = [p.year for p in papers if p.year]
        min_y, max_y = (min(years), max(years)) if years else (2000, 2024)
        cite_counts = [p.citation_count or 0 for p in papers]
        max_c = max(cite_counts) if cite_counts else 1

        directed = (graph_type == "citation")
        net = Network(
            height="100vh",
            width="100%",
            directed=directed,
            bgcolor="#0f172a",
            font_color="#e2e8f0",
            notebook=False,
            select_menu=False,
            filter_menu=False,
        )

        # ── vis.js options ──────────────────────────────────────────────
        physics_opts: dict = {
            "barnesHut": {
                "gravitationalConstant": -12000,
                "centralGravity": 0.3,
                "springLength": 160,
                "springConstant": 0.04,
                "damping": 0.09,
            },
            "stabilization": {"iterations": 200, "updateInterval": 25},
            "enabled": True,
        }
        layout_opts: dict = {}
        if layout == "hierarchical":
            layout_opts = {
                "hierarchical": {
                    "enabled": True,
                    "direction": "UD",
                    "sortMethod": "directed",
                    "levelSeparation": 120,
                    "nodeSpacing": 140,
                }
            }
            physics_opts["enabled"] = False

        net.set_options(json.dumps({
            "nodes": {
                "borderWidth": 2,
                "borderWidthSelected": 4,
                "font": {"size": 13, "face": "Arial"},
                "shadow": {"enabled": True, "size": 8},
            },
            "edges": {
                "smooth": {"type": "continuous"},
                "selectionWidth": 4,
                "shadow": {"enabled": False},
            },
            "interaction": {
                "hover": True,
                "hoverConnectedEdges": True,
                "selectConnectedEdges": True,
                "navigationButtons": True,
                "keyboard": True,
                "tooltipDelay": 100,
                "zoomView": True,
                "dragView": True,
                "dragNodes": True,
            },
            "physics": physics_opts,
            "layout": layout_opts,
        }))

        # ── Nodes ───────────────────────────────────────────────────────
        node_data: dict[int, dict] = {}

        for p in papers:
            # Determine node colour
            if color_by == "year":
                color = _color_by_year(p.year, min_y, max_y)
            elif color_by == "citations":
                color = _color_by_citations(p.citation_count or 0, max_c)
            else:
                color = tag_color.get((p.tags or [""])[0], "#60a5fa") if p.tags else "#60a5fa"

            cite_count = p.citation_count or 0
            size = max(16, min(55, 16 + cite_count // 3))

            # Tooltip HTML (kept for vis.js hover)
            venue_str = f"<br>📰 {p.venue}" if p.venue else ""
            year_str = f" ({p.year})" if p.year else ""
            tags_str = f"<br>🏷 {', '.join((p.tags or [])[:5])}" if p.tags else ""
            cite_str = f"<br>📊 引用 {cite_count} 次" if cite_count else ""
            abstract_preview = f"<br><br><i>{p.abstract[:120]}…</i>" if p.abstract else ""
            tooltip = (
                f"<div style='max-width:300px;font-family:Arial;'>"
                f"<b>{p.title}</b>{year_str}{venue_str}{tags_str}{cite_str}"
                f"{abstract_preview}</div>"
            )

            net.add_node(
                p.id,
                label=_truncate(p.title, 28),
                title=tooltip,
                color={"background": color, "border": "#ffffff30",
                       "highlight": {"background": "#fbbf24", "border": "#f59e0b"},
                       "hover":     {"background": "#a78bfa", "border": "#7c3aed"}},
                size=size,
                font={"color": "#f1f5f9"},
            )

            # Full data for right panel
            node_data[p.id] = {
                "title": p.title,
                "year": p.year,
                "authors": getattr(p, "authors", None) or "",
                "venue": p.venue or "",
                "citation_count": cite_count,
                "tags": p.tags or [],
                "abstract": (p.abstract or "")[:400],
                "doi": getattr(p, "doi", None) or "",
                "color": color,
            }

        # ── Edges ───────────────────────────────────────────────────────
        if graph_type == "tag":
            tag_sets = {p.id: set(p.tags or []) for p in papers}
            pids = list(tag_sets)
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    shared = tag_sets[pids[i]] & tag_sets[pids[j]]
                    if len(shared) >= min_shared:
                        label = ", ".join(sorted(shared)[:2])
                        net.add_edge(
                            pids[i], pids[j],
                            color={"color": "#64748b80", "highlight": "#fbbf24", "hover": "#a78bfa"},
                            width=min(len(shared) * 1.2, 6),
                            title=f"共享標籤：{', '.join(sorted(shared))}",
                            label=label if len(shared) <= 2 else f"{label}…",
                        )
        elif graph_type == "concept":
            concept_sets: dict[int, set[int]] = {}
            for p in papers:
                rows = self.db._concept_ids_for_paper(p.id)
                if rows:
                    concept_sets[p.id] = set(rows)
            pids = list(concept_sets)
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    shared = len(concept_sets[pids[i]] & concept_sets[pids[j]])
                    if shared >= min_shared:
                        net.add_edge(
                            pids[i], pids[j],
                            color={"color": "#64748b80", "highlight": "#fbbf24"},
                            width=min(shared * 1.2, 6),
                            title=f"共享 {shared} 個概念",
                        )
        else:  # citation
            for p in papers:
                for ref in self.db.get_references(p.id):
                    cited_id = ref.get("cited_paper_id")
                    if cited_id and cited_id in paper_map:
                        net.add_edge(
                            p.id, cited_id,
                            color={"color": "#3b82f680", "highlight": "#60a5fa"},
                            width=2,
                            arrows="to",
                            title="引用關係",
                        )

        # ── Save HTML ───────────────────────────────────────────────────
        if output_path:
            html_path = Path(output_path)
        else:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", prefix="smartpaper_graph_", delete=False
            )
            html_path = Path(tmp.name)
            tmp.close()

        net.save_graph(str(html_path))

        graph_title = {
            "tag": "標籤關聯圖", "concept": "概念關聯圖", "citation": "引用關係圖"
        }.get(graph_type, "知識圖譜")

        _inject_interactivity(
            html_path,
            node_data=node_data,
            tag_color_map=tag_color,
            graph_title=graph_title,
            color_by=color_by,
        )

        return str(html_path)


def _inject_interactivity(
    html_path: Path,
    node_data: dict = None,
    tag_color_map: dict = None,
    graph_title: str = "知識圖譜",
    color_by: str = "tag",
) -> None:
    """Patch the pyvis-generated HTML with a full sidebar + right panel UI."""

    node_data = node_data or {}
    tag_color_map = tag_color_map or {}

    # Build legend entries (tag mode only)
    legend_items_js = json.dumps(
        [{"tag": t, "color": c} for t, c in list(tag_color_map.items())[:10]],
        ensure_ascii=False,
    )
    node_data_js = json.dumps(
        {str(k): v for k, v in node_data.items()},
        ensure_ascii=False,
    )
    color_by_js = json.dumps(color_by)
    title_js = json.dumps(graph_title, ensure_ascii=False)

    extra_html = f"""
<style>
/* ── Reset & base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', Arial, sans-serif; overflow: hidden; }}

/* ── Left sidebar ── */
#sp-sidebar {{
  position: fixed; top: 0; left: 0; bottom: 0; width: 260px; z-index: 900;
  background: #0d1526; border-right: 1px solid #1e3a5f;
  display: flex; flex-direction: column; overflow: hidden;
}}
#sp-brand {{
  padding: 18px 16px 12px;
  border-bottom: 1px solid #1e3a5f;
  flex-shrink: 0;
}}
#sp-brand h1 {{
  font-size: 15px; font-weight: 700; color: #6366f1; letter-spacing: 0.3px;
}}
#sp-brand .subtitle {{
  font-size: 11px; color: #64748b; margin-top: 2px;
}}
#sp-search-wrap {{
  padding: 10px 12px; border-bottom: 1px solid #1e3a5f; flex-shrink: 0;
}}
#sp-search {{
  width: 100%; background: #1e293b; border: 1px solid #334155;
  border-radius: 8px; padding: 7px 10px; color: #e2e8f0; font-size: 12px;
  outline: none; transition: border-color .2s;
}}
#sp-search:focus {{ border-color: #6366f1; }}
#sp-search::placeholder {{ color: #475569; }}

#sp-stats {{
  padding: 10px 14px; border-bottom: 1px solid #1e3a5f; flex-shrink: 0;
}}
#sp-stats .stat-row {{
  display: flex; justify-content: space-between; align-items: center;
  font-size: 11px; color: #94a3b8; margin-bottom: 4px;
}}
#sp-stats .stat-val {{ color: #e2e8f0; font-weight: 600; }}

#sp-legend {{
  padding: 10px 14px; flex: 1; overflow-y: auto;
}}
#sp-legend h4 {{
  font-size: 11px; color: #64748b; text-transform: uppercase;
  letter-spacing: 0.8px; margin-bottom: 8px;
}}
.legend-item {{
  display: flex; align-items: center; gap: 7px;
  margin-bottom: 6px; cursor: pointer; border-radius: 4px; padding: 2px 4px;
  transition: background .15s;
}}
.legend-item:hover {{ background: #1e293b; }}
.legend-dot {{
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
}}
.legend-label {{
  font-size: 11px; color: #cbd5e1; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}}

#sp-controls {{
  padding: 10px 12px; border-top: 1px solid #1e3a5f; flex-shrink: 0;
  display: flex; flex-direction: column; gap: 6px;
}}
.ctrl-btn {{
  background: #1e293b; border: 1px solid #334155; border-radius: 7px;
  color: #cbd5e1; font-size: 11px; padding: 7px 10px; cursor: pointer;
  text-align: left; transition: background .15s, border-color .15s;
  display: flex; align-items: center; gap: 6px;
}}
.ctrl-btn:hover {{ background: #253347; border-color: #6366f1; color: #e2e8f0; }}
.ctrl-btn.active {{ background: #312e81; border-color: #6366f1; color: #c7d2fe; }}

/* ── Main canvas offset ── */
#mynetwork, div[id^="mynetwork"] {{
  margin-left: 260px !important;
  width: calc(100% - 260px) !important;
}}

/* ── Right detail panel ── */
#sp-detail {{
  position: fixed; top: 0; right: -360px; bottom: 0; width: 340px; z-index: 950;
  background: #0d1526; border-left: 1px solid #1e3a5f;
  display: flex; flex-direction: column;
  transition: right .3s cubic-bezier(.4,0,.2,1);
  overflow: hidden;
}}
#sp-detail.open {{ right: 0; }}
#sp-detail-header {{
  padding: 14px 16px; border-bottom: 1px solid #1e3a5f; flex-shrink: 0;
  display: flex; align-items: flex-start; gap: 10px;
}}
#sp-detail-color {{ width: 12px; height: 12px; border-radius: 50%; margin-top: 3px; flex-shrink: 0; }}
#sp-detail-title {{
  font-size: 13px; font-weight: 600; color: #f1f5f9; line-height: 1.45; flex: 1;
}}
#sp-detail-close {{
  background: none; border: none; color: #64748b; font-size: 18px; cursor: pointer;
  padding: 0 2px; line-height: 1; flex-shrink: 0;
  transition: color .15s;
}}
#sp-detail-close:hover {{ color: #e2e8f0; }}
#sp-detail-body {{ flex: 1; overflow-y: auto; padding: 14px 16px; }}
.detail-row {{
  display: flex; gap: 8px; align-items: baseline; margin-bottom: 8px; font-size: 12px;
}}
.detail-label {{ color: #64748b; min-width: 52px; flex-shrink: 0; }}
.detail-val {{ color: #cbd5e1; line-height: 1.4; }}
.detail-tags {{ display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }}
.tag-chip {{
  background: #1e3a5f; border-radius: 20px; padding: 2px 9px;
  font-size: 11px; color: #93c5fd;
}}
#sp-detail-abstract {{
  font-size: 11px; color: #94a3b8; line-height: 1.6;
  border-top: 1px solid #1e3a5f; padding-top: 10px; margin-top: 4px;
}}
#sp-detail-doi {{
  margin-top: 12px; font-size: 11px;
}}
#sp-detail-doi a {{ color: #6366f1; text-decoration: none; }}
#sp-detail-doi a:hover {{ text-decoration: underline; }}

/* ── Hint bar ── */
#sp-hint {{
  position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%) translateX(130px);
  background: #1e293b99; border: 1px solid #334155; border-radius: 20px;
  padding: 6px 16px; color: #64748b; font-size: 10px; pointer-events: none;
  white-space: nowrap; z-index: 800;
}}
</style>

<!-- Left sidebar -->
<div id="sp-sidebar">
  <div id="sp-brand">
    <h1>&#128196; SmartPaper</h1>
    <div class="subtitle" id="sp-graph-title">載入中…</div>
  </div>
  <div id="sp-search-wrap">
    <input id="sp-search" type="text" placeholder="&#128269; 搜尋論文標題…" autocomplete="off" />
  </div>
  <div id="sp-stats">
    <div class="stat-row"><span>論文節點</span><span class="stat-val" id="stat-nodes">—</span></div>
    <div class="stat-row"><span>關聯邊數</span><span class="stat-val" id="stat-edges">—</span></div>
    <div class="stat-row"><span>已選取</span><span class="stat-val" id="stat-selected">—</span></div>
  </div>
  <div id="sp-legend">
    <h4 id="sp-legend-title">標籤圖例</h4>
    <div id="sp-legend-items"></div>
  </div>
  <div id="sp-controls">
    <button class="ctrl-btn" id="btn-physics" onclick="togglePhysics()">&#9654; 暫停物理模擬</button>
    <button class="ctrl-btn" onclick="fitView()">&#8982; 重置視野</button>
    <button class="ctrl-btn" onclick="resetHighlight()">&#10226; 清除高亮</button>
  </div>
</div>

<!-- Right detail panel -->
<div id="sp-detail">
  <div id="sp-detail-header">
    <div id="sp-detail-color"></div>
    <div id="sp-detail-title">請點擊節點</div>
    <button id="sp-detail-close" onclick="closeDetail()">&#10005;</button>
  </div>
  <div id="sp-detail-body">
    <div id="sp-detail-meta"></div>
    <div class="detail-tags" id="sp-detail-tags"></div>
    <div id="sp-detail-abstract"></div>
    <div id="sp-detail-doi"></div>
  </div>
</div>

<!-- Hint bar -->
<div id="sp-hint">&#128432; 拖拽移動 &nbsp;&#128269; 滾輪縮放 &nbsp;&#9733; 單擊高亮 &nbsp;&#8635; 雙擊還原 &nbsp;Esc 重置</div>

<script>
(function() {{
  // ── Injected data ────────────────────────────────────────────────────
  var _nodeData = {node_data_js};
  var _legendItems = {legend_items_js};
  var _colorBy = {color_by_js};
  var _graphTitle = {title_js};
  var _physicsRunning = true;

  // ── Init legend + title ──────────────────────────────────────────────
  document.getElementById('sp-graph-title').textContent = _graphTitle;

  var legendEl = document.getElementById('sp-legend-items');
  var legendTitleEl = document.getElementById('sp-legend-title');

  if (_colorBy === 'year') {{
    legendTitleEl.textContent = '顏色 = 年份';
    legendEl.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
      '<div style="width:70px;height:8px;border-radius:4px;background:linear-gradient(to right,#60a5fa,#f59e0b);"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:10px;color:#64748b;">' +
      '<span>較早</span><span>較近</span></div>';
  }} else if (_colorBy === 'citations') {{
    legendTitleEl.textContent = '顏色 = 引用數';
    legendEl.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
      '<div style="width:70px;height:8px;border-radius:4px;background:linear-gradient(to right,#94a3b8,#6366f1);"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:10px;color:#64748b;">' +
      '<span>低</span><span>高</span></div>';
  }} else {{
    legendTitleEl.textContent = '標籤圖例';
    _legendItems.forEach(function(item) {{
      var div = document.createElement('div');
      div.className = 'legend-item';
      div.innerHTML =
        '<div class="legend-dot" style="background:' + item.color + '"></div>' +
        '<span class="legend-label">' + item.tag + '</span>';
      legendEl.appendChild(div);
    }});
  }}

  // ── Poll until vis.js network is ready ──────────────────────────────
  var _check = setInterval(function() {{
    if (typeof network === 'undefined' || typeof nodes === 'undefined') return;
    clearInterval(_check);
    _initGraph();
  }}, 150);

  function _initGraph() {{
    // Stats
    document.getElementById('stat-nodes').textContent = nodes.length;
    document.getElementById('stat-edges').textContent = edges.length;
    document.getElementById('stat-selected').textContent = '無';

    network.on('stabilized', function() {{
      document.getElementById('stat-nodes').textContent = nodes.length;
      document.getElementById('stat-edges').textContent = edges.length;
    }});

    // ── Click: highlight neighbours + open right panel ────────────────
    network.on('click', function(params) {{
      if (params.nodes.length === 0) {{
        resetHighlight();
        return;
      }}
      var nodeId = params.nodes[0];
      highlightNeighbours(nodeId);
      openDetail(nodeId);
      document.getElementById('stat-selected').textContent = nodeId;
    }});

    // ── Double-click: reset ───────────────────────────────────────────
    network.on('doubleClick', function() {{
      resetHighlight();
      closeDetail();
    }});

    network.on('hoverNode', function() {{
      document.getElementById('sp-hint').style.display = 'none';
    }});
  }}

  // ── Highlight logic ──────────────────────────────────────────────────
  function highlightNeighbours(nodeId) {{
    var connEdges = network.getConnectedEdges(nodeId);
    var connNodes = network.getConnectedNodes(nodeId);
    var connEdgeSet = new Set(connEdges);
    var connNodeSet = new Set(connNodes);
    connNodeSet.add(nodeId);

    nodes.update(nodes.getIds().map(function(id) {{
      return {{ id: id, opacity: connNodeSet.has(id) ? 1.0 : 0.15 }};
    }}));
    edges.update(edges.getIds().map(function(id) {{
      return {{ id: id, opacity: connEdgeSet.has(id) ? 1.0 : 0.05 }};
    }}));
  }}

  window.resetHighlight = function() {{
    nodes.update(nodes.getIds().map(function(id) {{ return {{ id: id, opacity: 1.0 }}; }}));
    edges.update(edges.getIds().map(function(id) {{ return {{ id: id, opacity: 1.0 }}; }}));
    document.getElementById('stat-selected').textContent = '無';
  }};

  // ── Detail panel ─────────────────────────────────────────────────────
  function openDetail(nodeId) {{
    var d = _nodeData[String(nodeId)];
    if (!d) return;

    document.getElementById('sp-detail-color').style.background = d.color || '#6366f1';
    document.getElementById('sp-detail-title').textContent = d.title || '';

    var meta = '';
    if (d.year) meta += '<div class="detail-row"><span class="detail-label">年份</span><span class="detail-val">' + d.year + '</span></div>';
    if (d.authors) meta += '<div class="detail-row"><span class="detail-label">作者</span><span class="detail-val">' + String(d.authors).substring(0,80) + '</span></div>';
    if (d.venue) meta += '<div class="detail-row"><span class="detail-label">期刊/會議</span><span class="detail-val">' + d.venue + '</span></div>';
    if (d.citation_count) meta += '<div class="detail-row"><span class="detail-label">引用數</span><span class="detail-val" style="color:#fbbf24;">&#9733; ' + d.citation_count + '</span></div>';
    document.getElementById('sp-detail-meta').innerHTML = meta;

    var tagsEl = document.getElementById('sp-detail-tags');
    tagsEl.innerHTML = '';
    (d.tags || []).forEach(function(t) {{
      var chip = document.createElement('span');
      chip.className = 'tag-chip';
      chip.textContent = t;
      tagsEl.appendChild(chip);
    }});

    var absEl = document.getElementById('sp-detail-abstract');
    absEl.textContent = d.abstract ? d.abstract : '';

    var doiEl = document.getElementById('sp-detail-doi');
    if (d.doi) {{
      doiEl.innerHTML = '<a href="https://doi.org/' + d.doi + '" target="_blank">&#128279; DOI: ' + d.doi + '</a>';
    }} else {{
      doiEl.innerHTML = '';
    }}

    document.getElementById('sp-detail').classList.add('open');
  }}

  window.closeDetail = function() {{
    document.getElementById('sp-detail').classList.remove('open');
  }};

  // ── Search box ───────────────────────────────────────────────────────
  document.getElementById('sp-search').addEventListener('keyup', function() {{
    var kw = this.value.trim().toLowerCase();
    if (!kw) {{
      resetHighlight();
      return;
    }}
    nodes.update(nodes.getIds().map(function(id) {{
      var d = _nodeData[String(id)];
      var match = d && d.title && d.title.toLowerCase().indexOf(kw) >= 0;
      return {{ id: id, opacity: match ? 1.0 : 0.1 }};
    }}));
    edges.update(edges.getIds().map(function(id) {{ return {{ id: id, opacity: 0.05 }}; }}));
  }});

  // ── Control buttons ──────────────────────────────────────────────────
  window.togglePhysics = function() {{
    _physicsRunning = !_physicsRunning;
    if (typeof network !== 'undefined') network.setOptions({{ physics: {{ enabled: _physicsRunning }} }});
    var btn = document.getElementById('btn-physics');
    if (_physicsRunning) {{
      btn.textContent = '⏸ 暫停物理模擬';
      btn.classList.remove('active');
    }} else {{
      btn.textContent = '▶ 繼續物理模擬';
      btn.classList.add('active');
    }}
  }};

  window.fitView = function() {{
    if (typeof network !== 'undefined') network.fit({{ animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }} }});
  }};

  // ── Keyboard shortcut ────────────────────────────────────────────────
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
      resetHighlight();
      closeDetail();
    }}
  }});
}})();
</script>
"""

    html = html_path.read_text(encoding="utf-8")
    html = html.replace("</body>", extra_html + "\n</body>")
    html_path.write_text(html, encoding="utf-8")
