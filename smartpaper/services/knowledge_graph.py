"""
知識圖譜服務
用 pyvis 建立互動式 HTML 網路圖：
- 論文節點（大小 ∝ 引用數，顏色 = 主要標籤）
- 引用邊（藍色有向箭頭）
- 共享概念邊（灰色無向，粗細 ∝ 共享概念數）
"""

import json
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional

from ..database.sqlite_db import SQLiteDB
from ..models import Paper


# 標籤顏色映射（前 8 個最常見標籤給固定顏色）
_PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
    "#9c755f", "#bab0ac",
]


def _truncate(text: str, n: int = 35) -> str:
    return text[:n] + "…" if len(text) > n else text


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
        """
        建立引用關係圖：論文節點 + 引用邊
        Returns: 生成的 HTML 檔案路徑
        """
        papers = self.db.get_all(limit=max_nodes)
        paper_map = {p.id: p for p in papers}

        tag_color = self._build_tag_color_map(papers)
        net = self._make_network(directed=True)

        # 節點
        for p in papers:
            self._add_paper_node(net, p, tag_color)

        # 引用邊：只畫兩端都在圖中的引用
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
        """
        建立共享概念圖：論文節點 + 共享概念邊（共享 ≥ min_shared 個概念）
        Returns: 生成的 HTML 檔案路徑
        """
        papers = self.db.get_all(limit=max_nodes)
        tag_color = self._build_tag_color_map(papers)
        net = self._make_network(directed=False)

        # 先收集所有論文的概念集合
        concept_sets: dict[int, set[int]] = {}
        for p in papers:
            rows = self.db._concept_ids_for_paper(p.id)
            if rows:
                concept_sets[p.id] = set(rows)
            self._add_paper_node(net, p, tag_color)

        # 共享概念邊
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
        """
        合併圖：引用邊（藍）+ 共享概念邊（灰）
        Returns: 生成的 HTML 檔案路徑
        """
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

        # 引用邊
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

        # 共享概念邊
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

        # 年份分布
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
        from pyvis.network import Network  # lazy import
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
        color = "#8ecae6"  # default
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
        paper_ids: Optional[list[int]] = None,  # None = all papers
        output_path: Optional[str] = None,
    ) -> str:
        """
        Build a fully interactive pyvis/vis.js graph and return the HTML path.
        Supports: drag nodes, scroll-to-zoom, click-to-highlight neighbours.

        Args:
            graph_type:  edge type
            min_shared:  minimum shared tags/concepts to draw an edge
            paper_ids:   which papers to include; None means all
        Returns:
            path to the generated HTML file
        """
        from pyvis.network import Network

        # Load papers
        if paper_ids is not None:
            all_papers = self.db.get_all(limit=5000)
            papers = [p for p in all_papers if p.id in set(paper_ids)]
        else:
            papers = self.db.get_all(limit=300)

        if not papers:
            return ""

        tag_color = self._build_tag_color_map(papers)
        paper_map = {p.id: p for p in papers}

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
            "physics": {
                "barnesHut": {
                    "gravitationalConstant": -12000,
                    "centralGravity": 0.3,
                    "springLength": 160,
                    "springConstant": 0.04,
                    "damping": 0.09,
                },
                "stabilization": {"iterations": 200, "updateInterval": 25},
            },
        }))

        # ── Nodes ───────────────────────────────────────────────────────
        for p in papers:
            color = tag_color.get((p.tags or [""])[0], "#60a5fa") if p.tags else "#60a5fa"
            cite_count = p.citation_count or 0
            size = max(16, min(55, 16 + cite_count // 3))

            venue_str = f"<br>📰 {p.venue}" if p.venue else ""
            year_str = f" ({p.year})" if p.year else ""
            tags_str = f"<br>🏷 {', '.join(p.tags[:5])}" if p.tags else ""
            cite_str = f"<br>📊 引用 {cite_count} 次" if cite_count else ""
            abstract_str = ""
            if p.abstract:
                abstract_str = f"<br><br><i>{p.abstract[:150]}…</i>"

            tooltip = (
                f"<div style='max-width:320px;font-family:Arial;'>"
                f"<b>{p.title}</b>{year_str}{venue_str}{tags_str}{cite_str}"
                f"{abstract_str}</div>"
            )

            net.add_node(
                p.id,
                label=_truncate(p.title, 28),
                title=tooltip,
                color={"background": color, "border": "#ffffff40",
                       "highlight": {"background": "#fbbf24", "border": "#f59e0b"},
                       "hover":     {"background": "#a78bfa", "border": "#7c3aed"}},
                size=size,
                font={"color": "#f1f5f9"},
            )

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

        # ── Inject click-highlight JS ───────────────────────────────────
        if output_path:
            html_path = Path(output_path)
        else:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", prefix="smartpaper_graph_", delete=False
            )
            html_path = Path(tmp.name)
            tmp.close()

        net.save_graph(str(html_path))

        # Patch HTML: inject click-to-highlight + info panel
        _inject_interactivity(html_path)

        return str(html_path)


def _inject_interactivity(html_path: Path) -> None:
    """Patch the pyvis-generated HTML to add click-highlight and info panel."""
    extra_js = """
<style>
  #info-panel {
    position: fixed; top: 16px; right: 16px; z-index: 9999;
    background: #1e293bdd; border: 1px solid #475569; border-radius: 12px;
    padding: 16px; max-width: 320px; color: #e2e8f0;
    font-family: Arial, sans-serif; font-size: 13px;
    display: none; backdrop-filter: blur(6px);
    box-shadow: 0 8px 32px #00000088;
  }
  #info-panel h3 { margin: 0 0 8px; font-size: 14px; color: #fbbf24; }
  #info-panel .meta { color: #94a3b8; font-size: 11px; margin-bottom: 6px; }
  #info-panel .abstract { color: #cbd5e1; font-size: 11px; line-height: 1.5; }
  #info-close { float: right; cursor: pointer; color: #94a3b8; font-size: 16px; }
  #hint { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    background: #1e293b99; border: 1px solid #334155; border-radius: 20px;
    padding: 8px 18px; color: #94a3b8; font-size: 11px;
    font-family: Arial, sans-serif; pointer-events: none; }
</style>
<div id="info-panel">
  <span id="info-close" onclick="document.getElementById('info-panel').style.display='none'">✕</span>
  <h3 id="info-title"></h3>
  <div class="meta" id="info-meta"></div>
  <div class="abstract" id="info-abstract"></div>
</div>
<div id="hint">🖱 拖拽移動節點 · 滾輪縮放 · 點擊節點高亮關聯 · 雙擊取消選取</div>
<script>
(function() {
  var _check = setInterval(function() {
    if (typeof network === 'undefined') return;
    clearInterval(_check);

    network.on("click", function(params) {
      if (params.nodes.length === 0) return;
      var nodeId = params.nodes[0];
      var node = nodes.get(nodeId);
      if (!node) return;

      // Highlight neighbours
      var connectedEdges = network.getConnectedEdges(nodeId);
      var connectedNodes = network.getConnectedNodes(nodeId);
      var allNodes = nodes.getIds();
      var allEdges = edges.getIds();

      var nodeUpdates = allNodes.map(function(id) {
        return {
          id: id,
          opacity: (id === nodeId || connectedNodes.indexOf(id) >= 0) ? 1.0 : 0.15
        };
      });
      var edgeUpdates = allEdges.map(function(id) {
        return {
          id: id,
          opacity: connectedEdges.indexOf(id) >= 0 ? 1.0 : 0.05
        };
      });
      nodes.update(nodeUpdates);
      edges.update(edgeUpdates);

      // Show info panel
      var panel = document.getElementById('info-panel');
      var title = node.label || '';
      document.getElementById('info-title').textContent = title;
      var titleTag = node.title || '';
      // Parse meta from title HTML
      var tmp = document.createElement('div');
      tmp.innerHTML = titleTag;
      document.getElementById('info-meta').innerHTML =
        titleTag.replace(/<div[^>]*>|<\/div>/g,'').replace(/<b>.*?<\/b>/,'').split('<br>').slice(0,4).join('<br>');
      document.getElementById('info-abstract').innerHTML = '';
      panel.style.display = 'block';
    });

    network.on("doubleClick", function(params) {
      // Reset all opacity
      var allNodes = nodes.getIds().map(function(id){ return {id:id, opacity:1.0}; });
      var allEdges = edges.getIds().map(function(id){ return {id:id, opacity:1.0}; });
      nodes.update(allNodes);
      edges.update(allEdges);
      document.getElementById('info-panel').style.display = 'none';
    });

    network.on("hoverNode", function(params) {
      document.getElementById('hint').style.display = 'none';
    });
  }, 200);
})();
</script>
"""
    html = html_path.read_text(encoding="utf-8")
    html = html.replace("</body>", extra_js + "\n</body>")
    html_path.write_text(html, encoding="utf-8")
