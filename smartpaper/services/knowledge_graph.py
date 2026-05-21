"""
知識圖譜服務 v3 — 全面升級版
新增：
- 度中心性節點大小（連接數越多越大）
- 邊粗細/透明度依權重動態調整
- 縮放自適應標籤（zoom-based dynamic labels）
- Hover 節點放大 + 豐富 Tooltip
- 點擊焦點模式（高亮鄰居 + 降暗其他）
- 右側面板顯示完整 Metadata
- 圖例點擊 → 閃爍高亮該標籤所有節點
- 孤立節點過濾開關
- 強化物理引擎（avoidOverlap + 更強排斥力）
"""

import hashlib
import json
import pickle
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional

from ..database.sqlite_db import SQLiteDB
from ..models import Paper

_PROJECT_ROOT    = Path(__file__).resolve().parents[2]
_GRAPH_CACHE_DIR = _PROJECT_ROOT / "data" / "graph_cache"
_ADJ_CACHE_FILE  = _PROJECT_ROOT / "data" / "adj_cache.pkl"


_PALETTE = [
    "#6366f1", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
    "#9c755f", "#bab0ac",
]


def _truncate(text: str, n: int = 15) -> str:
    return text[:n] + "…" if len(text) > n else text


def _lerp_color(c1: str, c2: str, t: float) -> str:
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
    if year is None:
        return "#64748b"
    span = max(max_y - min_y, 1)
    t = (year - min_y) / span
    return _lerp_color("#60a5fa", "#f59e0b", t)


def _color_by_citations(count: int, max_c: int) -> str:
    if max_c <= 0:
        return "#64748b"
    t = min(count / max_c, 1.0)
    return _lerp_color("#94a3b8", "#6366f1", t)


class KnowledgeGraphService:
    def __init__(self, sqlite_db: Optional[SQLiteDB] = None):
        self.db = sqlite_db or SQLiteDB()
        # Adjacency cache: {(graph_type, min_shared): {paper_id: set(neighbor_ids)}}
        self._adj_cache: dict[tuple, dict[int, set[int]]] = {}
        self._adj_papers_sig: str = ""  # hash of paper ids for invalidation

    # ── 鄰接表預計算（N-hop 加速）────────────────────────────────────────

    def _papers_sig(self, papers: list) -> str:
        return hashlib.md5(
            ",".join(str(p.id) for p in papers).encode()
        ).hexdigest()[:12]

    def _get_adjacency(
        self,
        graph_type: str,
        min_shared: int,
        papers: list,
    ) -> dict[int, set[int]]:
        """回傳鄰接表，若 papers 集合未變則直接回傳快取。"""
        sig = self._papers_sig(papers)
        cache_key = (graph_type, min_shared)

        if sig != self._adj_papers_sig:
            self._adj_cache.clear()
            self._adj_papers_sig = sig

        if cache_key in self._adj_cache:
            return self._adj_cache[cache_key]

        adj: dict[int, set[int]] = {p.id: set() for p in papers}

        if graph_type in ("tag", "concept"):
            tag_sets = {p.id: set(p.tags or []) for p in papers}
            pids = list(tag_sets)
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    if len(tag_sets[pids[i]] & tag_sets[pids[j]]) >= min_shared:
                        adj[pids[i]].add(pids[j])
                        adj[pids[j]].add(pids[i])

        elif graph_type == "citation":
            for p in papers:
                refs = getattr(p, "references", None) or []
                for ref_id in refs:
                    if ref_id in adj:
                        adj[p.id].add(ref_id)
                        adj[ref_id].add(p.id)

        self._adj_cache[cache_key] = adj
        return adj

    def invalidate_graph_cache(self) -> None:
        """論文資料變動後清除圖譜 HTML 快取與鄰接表快取。"""
        self._adj_cache.clear()
        self._adj_papers_sig = ""
        try:
            if _GRAPH_CACHE_DIR.exists():
                for f in _GRAPH_CACHE_DIR.glob("*.html"):
                    f.unlink(missing_ok=True)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────

    def build_citation_graph(self, max_nodes: int = 200, output_path: Optional[str] = None) -> str:
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
                        net.add_edge(p.id, cited_id, color="#3a86ff", width=1.5, arrows="to", title="引用")
                    except Exception:
                        pass
        return self._save_and_return(net, output_path, "citation_graph")

    def build_concept_graph(self, min_shared: int = 2, max_nodes: int = 200, output_path: Optional[str] = None) -> str:
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
                        net.add_edge(pid1, pid2, color="#adb5bd", width=min(shared, 6), title=f"共享 {shared} 個概念")
                    except Exception:
                        pass
        return self._save_and_return(net, output_path, "concept_graph")

    def build_combined_graph(self, min_shared: int = 2, max_nodes: int = 200, output_path: Optional[str] = None) -> str:
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
                        net.add_edge(p.id, cited_id, color="#3a86ff", width=2, title="引用關係", dashes=False)
                    except Exception:
                        pass
        paper_ids = list(concept_sets.keys())
        for i in range(len(paper_ids)):
            for j in range(i + 1, len(paper_ids)):
                pid1, pid2 = paper_ids[i], paper_ids[j]
                shared = len(concept_sets[pid1] & concept_sets[pid2])
                if shared >= min_shared:
                    try:
                        net.add_edge(pid1, pid2, color="#adb5bd", width=min(shared, 5), title=f"共享 {shared} 個概念", dashes=True)
                    except Exception:
                        pass
        return self._save_and_return(net, output_path, "combined_graph")

    def get_graph_stats(self) -> dict:
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
        net = Network(height="720px", width="100%", directed=directed,
                      bgcolor="#1a1a2e", font_color="#e0e0e0", notebook=False)
        net.set_options(json.dumps({
            "nodes": {"borderWidth": 1, "borderWidthSelected": 3, "font": {"size": 11}},
            "edges": {"smooth": {"type": "dynamic"}, "selectionWidth": 3},
            "physics": {
                "barnesHut": {
                    "gravitationalConstant": -8000,
                    "springLength": 120,
                    "springConstant": 0.04,
                },
                "stabilization": {"iterations": 150},
            },
            "interaction": {"hover": True, "navigationButtons": True, "tooltipDelay": 200},
        }))
        return net

    def _build_tag_color_map(self, papers: list[Paper]) -> dict[str, str]:
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
        net.add_node(paper.id, label=_truncate(paper.title), title=tooltip, color=color, size=size)

    def _save_and_return(self, net, output_path: Optional[str], prefix: str) -> str:
        if output_path:
            path = Path(output_path)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".html", prefix=f"smartpaper_{prefix}_", delete=False)
            path = Path(tmp.name)
            tmp.close()
        net.save_graph(str(path))
        return str(path)

    def open_in_browser(self, html_path: str) -> None:
        webbrowser.open(f"file:///{Path(html_path).resolve()}")

    # ── Interactive graph ─────────────────────────────────────────────────

    def build_interactive_graph(
        self,
        graph_type: str = "tag",
        min_shared: int = 1,
        paper_ids: Optional[list[int]] = None,
        output_path: Optional[str] = None,
        color_by: str = "tag",
        layout: str = "physics",
    ) -> str:
        from pyvis.network import Network

        if paper_ids is not None:
            all_papers = self.db.get_all(limit=5000)
            papers = [p for p in all_papers if p.id in set(paper_ids)]
        else:
            papers = self.db.get_all(limit=300)

        if not papers:
            return ""

        # ── HTML 快取（hash of inputs）────────────────────────────────────
        if output_path is None:
            _ids = sorted(p.id for p in papers)
            _key = f"{graph_type}_{min_shared}_{color_by}_{layout}_{'_'.join(map(str, _ids))}"
            _hash = hashlib.md5(_key.encode()).hexdigest()[:16]
            _cached = _GRAPH_CACHE_DIR / f"{_hash}.html"
            if _cached.exists():
                return str(_cached)
        else:
            _cached = None

        tag_color = self._build_tag_color_map(papers)
        paper_map = {p.id: p for p in papers}

        years = [p.year for p in papers if p.year]
        min_y, max_y = (min(years), max(years)) if years else (2000, 2024)
        cite_counts = [p.citation_count or 0 for p in papers]
        max_c = max(cite_counts) if cite_counts else 1

        # ── Step 1: Build edge list first (needed for degree centrality) ──
        edges_to_add: list[dict] = []

        if graph_type == "tag":
            tag_sets = {p.id: set(p.tags or []) for p in papers}
            pids = list(tag_sets)
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    shared = tag_sets[pids[i]] & tag_sets[pids[j]]
                    if len(shared) >= min_shared:
                        lbl = ", ".join(sorted(shared)[:2])
                        edges_to_add.append({
                            "src": pids[i], "dst": pids[j],
                            "weight": len(shared),
                            "label": lbl if len(shared) <= 2 else f"{lbl}…",
                            "title": f"共享標籤：{', '.join(sorted(shared))}",
                        })
        elif graph_type == "concept":
            concept_sets: dict[int, set[int]] = {}
            for p in papers:
                rows = self.db._concept_ids_for_paper(p.id)
                if rows:
                    concept_sets[p.id] = set(rows)
            cpids = list(concept_sets)
            for i in range(len(cpids)):
                for j in range(i + 1, len(cpids)):
                    shared = len(concept_sets[cpids[i]] & concept_sets[cpids[j]])
                    if shared >= min_shared:
                        edges_to_add.append({
                            "src": cpids[i], "dst": cpids[j],
                            "weight": shared, "label": "",
                            "title": f"共享 {shared} 個概念",
                        })
        else:  # citation
            for p in papers:
                for ref in self.db.get_references(p.id):
                    cited_id = ref.get("cited_paper_id")
                    if cited_id and cited_id in paper_map:
                        edges_to_add.append({
                            "src": p.id, "dst": cited_id,
                            "weight": 2, "label": "", "title": "引用關係",
                        })

        # ── Step 2: Degree centrality ──────────────────────────────────────
        degree: dict[int, int] = {p.id: 0 for p in papers}
        for e in edges_to_add:
            degree[e["src"]] = degree.get(e["src"], 0) + 1
            degree[e["dst"]] = degree.get(e["dst"], 0) + 1

        max_degree = max(degree.values()) if any(v > 0 for v in degree.values()) else 1

        # Tag → node id mapping (for legend click highlight)
        tag_nodes: dict[str, list[int]] = {}
        for p in papers:
            for t in (p.tags or []):
                tag_nodes.setdefault(t, []).append(p.id)

        # Isolated nodes (degree == 0)
        isolated_node_ids = [pid for pid, deg in degree.items() if deg == 0]

        # ── Step 3: Network setup ──────────────────────────────────────────
        directed = (graph_type == "citation")
        net = Network(
            height="100vh", width="100%",
            directed=directed, bgcolor="#0f172a",
            font_color="#e2e8f0", notebook=False,
            select_menu=False, filter_menu=False,
        )

        physics_opts: dict = {
            "barnesHut": {
                "gravitationalConstant": -22000,  # strong repulsion → nodes spread out
                "centralGravity": 0.06,            # weak center pull
                "springLength": 220,               # longer springs → more spacing
                "springConstant": 0.025,
                "damping": 0.12,
                "avoidOverlap": 0.9,               # critical: prevent node overlap
            },
            "stabilization": {"iterations": 300, "updateInterval": 10, "fit": True},
            "enabled": True,
        }
        layout_opts: dict = {}
        if layout == "hierarchical":
            layout_opts = {
                "hierarchical": {
                    "enabled": True,
                    "direction": "UD",
                    "sortMethod": "directed",
                    "levelSeparation": 150,
                    "nodeSpacing": 170,
                }
            }
            physics_opts["enabled"] = False

        net.set_options(json.dumps({
            "nodes": {
                "borderWidth": 2,
                "borderWidthSelected": 4,
                "font": {
                    "size": 11, "face": "Arial",
                    "strokeWidth": 3, "strokeColor": "#0a0f1e",
                },
                "shadow": {"enabled": True, "size": 10, "color": "rgba(0,0,0,0.5)"},
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
                "tooltipDelay": 120,
                "zoomView": True,
                "dragView": True,
                "dragNodes": True,
            },
            "physics": physics_opts,
            "layout": layout_opts,
        }))

        # ── Step 4: Add nodes (degree-based sizing) ────────────────────────
        node_data: dict[int, dict] = {}

        for p in papers:
            if color_by == "year":
                color = _color_by_year(p.year, min_y, max_y)
            elif color_by == "citations":
                color = _color_by_citations(p.citation_count or 0, max_c)
            else:
                color = tag_color.get((p.tags or [""])[0], "#60a5fa") if p.tags else "#60a5fa"

            # Degree-based size (primary) + citation count boost (secondary)
            deg = degree[p.id]
            deg_ratio = deg / max_degree
            base_size = 13 + int(deg_ratio * 38)   # 13 (isolated) → 51 (hub)
            cite_count = p.citation_count or 0
            cite_boost = min(cite_count, 300) // 30  # 0–10 bonus
            size = max(12, min(55, base_size + cite_boost))

            year_str = f" ({p.year})" if p.year else ""
            venue_str = f"<br>📰 {p.venue}" if p.venue else ""
            tags_str = f"<br>🏷 {', '.join((p.tags or [])[:5])}" if p.tags else ""
            cite_str = f"<br>📊 引用 {cite_count} 次" if cite_count else ""
            deg_str = f"<br>🔗 度中心性：{deg} 條邊"
            abstract_preview = f"<br><br><i>{p.abstract[:120]}…</i>" if p.abstract else ""
            tooltip = (
                f"<div style='max-width:300px;font-family:Arial;padding:4px;'>"
                f"<b style='font-size:13px;'>{p.title}</b>{year_str}"
                f"{venue_str}{tags_str}{cite_str}{deg_str}{abstract_preview}</div>"
            )

            net.add_node(
                p.id,
                label=_truncate(p.title, 15),
                title=tooltip,
                color={
                    "background": color,
                    "border": "#ffffff30",
                    "highlight": {"background": "#fbbf24", "border": "#f59e0b"},
                    "hover":     {"background": "#a78bfa", "border": "#7c3aed"},
                },
                size=size,
                font={"color": "#f1f5f9", "size": 11},
            )

            node_data[p.id] = {
                "title": p.title,
                "year": p.year,
                "authors": getattr(p, "authors", None) or "",
                "venue": p.venue or "",
                "citation_count": cite_count,
                "tags": p.tags or [],
                "abstract": (p.abstract or "")[:500],
                "doi": getattr(p, "doi", None) or "",
                "color": color,
                "degree": deg,
                "size": size,
            }

        # ── Step 5: Add edges (weight-proportional thickness + opacity) ────
        for e in edges_to_add:
            w = e["weight"]
            # Edge opacity scales with weight: 0.20 → 0.80
            opacity = min(0.20 + w * 0.12, 0.80)
            # Edge width scales with weight: 1 → 7
            edge_w = min(1 + (w - 1) * 1.5, 7)

            if graph_type == "citation":
                base_color = f"rgba(59,130,246,{opacity:.2f})"
                h_color = "#60a5fa"
            else:
                base_color = f"rgba(100,116,139,{opacity:.2f})"
                h_color = "#fbbf24"

            kwargs: dict = {
                "color": {"color": base_color, "highlight": h_color, "hover": "#a78bfa"},
                "width": edge_w,
                "title": e["title"],
            }
            if e.get("label"):
                kwargs["label"] = e["label"]
            if graph_type == "citation":
                kwargs["arrows"] = "to"

            try:
                net.add_edge(e["src"], e["dst"], **kwargs)
            except Exception:
                pass

        # ── Step 6: Save & inject interactivity ───────────────────────────
        if output_path:
            html_path = Path(output_path)
        elif _cached is not None:
            # 存入快取目錄
            _GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            html_path = _cached
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
            tag_nodes=tag_nodes,
            isolated_node_ids=isolated_node_ids,
        )

        return str(html_path)

    def build_neighborhood_graph(
        self,
        center_paper_id: int,
        hops: int = 2,
        graph_type: str = "tag",
        min_shared: int = 1,
        color_by: str = "tag",
        output_path: Optional[str] = None,
    ) -> str:
        """只渲染中心論文的 N 跳鄰居（使用預計算鄰接表，防止 300+ 節點卡死）。"""
        papers = self.db.get_all(limit=5000)
        paper_map = {p.id: p for p in papers}

        if center_paper_id not in paper_map:
            return self.build_interactive_graph(
                graph_type=graph_type,
                min_shared=min_shared,
                color_by=color_by,
                output_path=output_path,
            )

        # 使用預計算鄰接表（第一次 O(n²)，之後 O(1) 查快取）
        adj = self._get_adjacency(graph_type, min_shared, papers)

        # BFS from center up to `hops` hops
        visited: set[int] = {center_paper_id}
        frontier: set[int] = {center_paper_id}
        for _ in range(hops):
            next_frontier: set[int] = set()
            for pid in frontier:
                for neighbor in adj.get(pid, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier

        return self.build_interactive_graph(
            graph_type=graph_type,
            min_shared=min_shared,
            paper_ids=list(visited),
            color_by=color_by,
            output_path=output_path,
        )


# ── HTML injection ──────────────────────────────────────────────────────────


def _inject_interactivity(
    html_path: Path,
    node_data: dict = None,
    tag_color_map: dict = None,
    graph_title: str = "知識圖譜",
    color_by: str = "tag",
    tag_nodes: dict = None,
    isolated_node_ids: list = None,
) -> None:
    """Patch the pyvis-generated HTML with full interactive UI v3."""

    node_data = node_data or {}
    tag_color_map = tag_color_map or {}
    tag_nodes = tag_nodes or {}
    isolated_node_ids = isolated_node_ids or []

    legend_items_js = json.dumps(
        [{"tag": t, "color": c} for t, c in list(tag_color_map.items())[:12]],
        ensure_ascii=False,
    )
    node_data_js = json.dumps(
        {str(k): v for k, v in node_data.items()},
        ensure_ascii=False,
    )
    tag_nodes_js = json.dumps(
        {k: [str(i) for i in v] for k, v in tag_nodes.items()},
        ensure_ascii=False,
    )
    isolated_nodes_js = json.dumps([str(i) for i in isolated_node_ids])
    color_by_js = json.dumps(color_by)
    title_js = json.dumps(graph_title, ensure_ascii=False)
    total_nodes = len(node_data)
    isolated_count = len(isolated_node_ids)

    extra_html = f"""
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', Arial, sans-serif; overflow: hidden; }}

/* ── Left sidebar ── */
#sp-sidebar {{
  position: fixed; top: 0; left: 0; bottom: 0; width: 268px; z-index: 900;
  background: linear-gradient(180deg, #0d1526 0%, #0a1020 100%);
  border-right: 1px solid #1e3a5f;
  display: flex; flex-direction: column; overflow: hidden;
}}
#sp-brand {{
  padding: 16px 16px 12px;
  border-bottom: 1px solid #1e3a5f;
  flex-shrink: 0;
  background: linear-gradient(135deg, #1e1b4b 0%, #0d1526 100%);
}}
#sp-brand h1 {{
  font-size: 14px; font-weight: 700; color: #818cf8;
  letter-spacing: 0.5px; display: flex; align-items: center; gap: 6px;
}}
#sp-brand .subtitle {{
  font-size: 10px; color: #475569; margin-top: 3px;
}}
#sp-search-wrap {{
  padding: 10px 12px; border-bottom: 1px solid #1e3a5f; flex-shrink: 0;
}}
#sp-search {{
  width: 100%; background: #1e293b; border: 1px solid #334155;
  border-radius: 8px; padding: 7px 10px 7px 28px; color: #e2e8f0; font-size: 12px;
  outline: none; transition: border-color .2s;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23475569' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.35-4.35'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: 8px center;
}}
#sp-search:focus {{ border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99,102,241,0.2); }}
#sp-search::placeholder {{ color: #475569; }}

#sp-stats {{
  padding: 8px 14px; border-bottom: 1px solid #1e3a5f; flex-shrink: 0;
  display: grid; grid-template-columns: 1fr 1fr; gap: 6px;
}}
.stat-box {{
  background: #1e293b; border-radius: 6px; padding: 6px 8px; text-align: center;
}}
.stat-val {{ font-size: 18px; font-weight: 700; color: #818cf8; line-height: 1; }}
.stat-label {{ font-size: 9px; color: #64748b; margin-top: 2px; }}

#sp-legend {{ padding: 8px 14px; flex: 1; overflow-y: auto; min-height: 0; }}
#sp-legend h4 {{
  font-size: 10px; color: #64748b; text-transform: uppercase;
  letter-spacing: 0.8px; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;
}}
#sp-legend h4 span {{ color: #334155; font-weight: 400; text-transform: none; letter-spacing: 0; }}
.legend-item {{
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 5px; cursor: pointer; border-radius: 5px; padding: 4px 6px;
  transition: background .15s, transform .1s;
  user-select: none;
}}
.legend-item:hover {{ background: #1e293b; transform: translateX(2px); }}
.legend-item.active {{ background: #1e3a5f; border-left: 2px solid #fbbf24; }}
.legend-dot {{
  width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0;
  box-shadow: 0 0 6px currentColor;
}}
.legend-label {{ font-size: 11px; color: #cbd5e1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }}
.legend-count {{ font-size: 10px; color: #475569; flex-shrink: 0; }}

#sp-controls {{
  padding: 8px 10px; border-top: 1px solid #1e3a5f; flex-shrink: 0;
  display: grid; grid-template-columns: 1fr 1fr; gap: 5px;
}}
.ctrl-btn {{
  background: #1e293b; border: 1px solid #334155; border-radius: 6px;
  color: #94a3b8; font-size: 10px; padding: 6px 8px; cursor: pointer;
  text-align: center; transition: all .15s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.ctrl-btn:hover {{ background: #253347; border-color: #6366f1; color: #e2e8f0; }}
.ctrl-btn.active {{ background: #312e81; border-color: #6366f1; color: #c7d2fe; }}
.ctrl-btn.danger {{ border-color: #dc2626; }}
.ctrl-btn.danger:hover {{ background: #450a0a; color: #fca5a5; }}
.ctrl-btn-wide {{ grid-column: 1 / -1; }}

/* ── Canvas offset ── */
#mynetwork, div[id^="mynetwork"] {{
  margin-left: 268px !important;
  width: calc(100% - 268px) !important;
}}

/* ── Right detail panel ── */
#sp-detail {{
  position: fixed; top: 0; right: -370px; bottom: 0; width: 350px; z-index: 950;
  background: linear-gradient(180deg, #0d1526 0%, #0a1020 100%);
  border-left: 1px solid #1e3a5f;
  display: flex; flex-direction: column;
  transition: right .32s cubic-bezier(.4,0,.2,1);
  overflow: hidden;
}}
#sp-detail.open {{ right: 0; }}
#sp-detail-header {{
  padding: 14px 16px 12px; border-bottom: 1px solid #1e3a5f; flex-shrink: 0;
  background: linear-gradient(135deg, #1e1b4b 0%, #0d1526 100%);
}}
#sp-detail-titlerow {{
  display: flex; align-items: flex-start; gap: 10px; margin-bottom: 6px;
}}
#sp-detail-color {{
  width: 14px; height: 14px; border-radius: 50%; margin-top: 2px; flex-shrink: 0;
  box-shadow: 0 0 8px currentColor;
}}
#sp-detail-title {{
  font-size: 13px; font-weight: 600; color: #f1f5f9; line-height: 1.45; flex: 1;
}}
#sp-detail-close {{
  background: none; border: none; color: #475569; font-size: 18px; cursor: pointer;
  padding: 0 2px; line-height: 1; flex-shrink: 0; transition: color .15s;
}}
#sp-detail-close:hover {{ color: #e2e8f0; }}
#sp-detail-degree {{
  display: flex; gap: 12px; font-size: 10px; color: #64748b;
}}
#sp-detail-degree .dg-val {{ color: #818cf8; font-weight: 600; }}
#sp-detail-body {{ flex: 1; overflow-y: auto; padding: 14px 16px; }}
.detail-row {{
  display: flex; gap: 8px; align-items: baseline; margin-bottom: 9px; font-size: 12px;
}}
.detail-label {{ color: #64748b; min-width: 56px; flex-shrink: 0; font-size: 11px; }}
.detail-val {{ color: #cbd5e1; line-height: 1.4; }}
.detail-tags {{ display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 12px; }}
.tag-chip {{
  background: #1e3a5f; border-radius: 20px; padding: 3px 10px;
  font-size: 11px; color: #93c5fd; cursor: pointer; transition: background .15s;
}}
.tag-chip:hover {{ background: #1d4ed8; }}
#sp-detail-abstract {{
  font-size: 11px; color: #94a3b8; line-height: 1.65;
  border-top: 1px solid #1e3a5f; padding-top: 10px; margin-top: 6px;
  max-height: 180px; overflow-y: auto;
}}
#sp-detail-doi {{
  margin-top: 12px; font-size: 11px; padding-top: 10px; border-top: 1px solid #1e3a5f;
}}
#sp-detail-doi a {{ color: #6366f1; text-decoration: none; }}
#sp-detail-doi a:hover {{ text-decoration: underline; color: #818cf8; }}

/* ── Zoom label mode badge ── */
#sp-zoom-badge {{
  position: fixed; bottom: 60px; left: 50%;
  transform: translateX(-50%) translateX(134px);
  background: #1e293bcc; border: 1px solid #334155; border-radius: 6px;
  padding: 3px 10px; color: #64748b; font-size: 10px;
  pointer-events: none; z-index: 800; transition: opacity .3s;
  opacity: 0;
}}
#sp-zoom-badge.show {{ opacity: 1; }}

/* ── Hint bar ── */
#sp-hint {{
  position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%) translateX(134px);
  background: #1e293b99; border: 1px solid #334155; border-radius: 20px;
  padding: 5px 16px; color: #64748b; font-size: 10px; pointer-events: none;
  white-space: nowrap; z-index: 800; transition: opacity .5s;
}}

/* ── Flash animation for legend click ── */
@keyframes nodeFlash {{
  0%   {{ opacity: 1; }}
  25%  {{ opacity: 0.3; }}
  50%  {{ opacity: 1; }}
  75%  {{ opacity: 0.3; }}
  100% {{ opacity: 1; }}
}}
.legend-item.flashing {{ animation: nodeFlash 0.6s ease-in-out; }}
</style>

<!-- Left sidebar -->
<div id="sp-sidebar">
  <div id="sp-brand">
    <h1>&#128196; SmartPaper 知識圖譜</h1>
    <div class="subtitle" id="sp-graph-title">載入中…</div>
  </div>
  <div id="sp-search-wrap">
    <input id="sp-search" type="text" placeholder="搜尋論文標題…" autocomplete="off" />
  </div>
  <div id="sp-stats">
    <div class="stat-box">
      <div class="stat-val" id="stat-nodes">—</div>
      <div class="stat-label">論文節點</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" id="stat-edges">—</div>
      <div class="stat-label">關聯邊數</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" id="stat-isolated" style="color:#f59e0b;">{isolated_count}</div>
      <div class="stat-label">孤立節點</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" id="stat-selected" style="color:#34d399;">0</div>
      <div class="stat-label">已選取</div>
    </div>
  </div>
  <div id="sp-legend">
    <h4 id="sp-legend-title">標籤圖例 <span>點擊閃爍高亮</span></h4>
    <div id="sp-legend-items"></div>
  </div>
  <div id="sp-controls">
    <button class="ctrl-btn" id="btn-physics" onclick="togglePhysics()">⏸ 暫停模擬</button>
    <button class="ctrl-btn" onclick="fitView()">⊞ 重置視野</button>
    <button class="ctrl-btn" id="btn-isolated" onclick="toggleIsolated()">○ 隱藏孤立</button>
    <button class="ctrl-btn" onclick="resetHighlight()">↺ 清除高亮</button>
    <button class="ctrl-btn ctrl-btn-wide" id="btn-labels" onclick="cycleLabelMode()">🏷 標籤：自動</button>
  </div>
</div>

<!-- Right detail panel -->
<div id="sp-detail">
  <div id="sp-detail-header">
    <div id="sp-detail-titlerow">
      <div id="sp-detail-color"></div>
      <div id="sp-detail-title">點擊節點查看論文詳情</div>
      <button id="sp-detail-close" onclick="closeDetail()">✕</button>
    </div>
    <div id="sp-detail-degree">
      <span>度中心性：<span class="dg-val" id="sp-degree-val">—</span> 條邊</span>
      <span>引用數：<span class="dg-val" id="sp-cite-val">—</span></span>
    </div>
  </div>
  <div id="sp-detail-body">
    <div id="sp-detail-meta"></div>
    <div class="detail-tags" id="sp-detail-tags"></div>
    <div id="sp-detail-abstract"></div>
    <div id="sp-detail-doi"></div>
  </div>
</div>

<!-- Zoom badge -->
<div id="sp-zoom-badge"></div>
<!-- Hint bar -->
<div id="sp-hint">🖱 拖拽移動 &nbsp;🔍 滾輪縮放 &nbsp;⭐ 單擊高亮 &nbsp;🔄 雙擊還原 &nbsp;Esc 重置</div>

<script>
(function() {{
  // ── Injected data ────────────────────────────────────────────────────
  var _nodeData    = {node_data_js};
  var _legendItems = {legend_items_js};
  var _colorBy     = {color_by_js};
  var _graphTitle  = {title_js};
  var _tagNodes    = {tag_nodes_js};
  var _isolatedSet = new Set({isolated_nodes_js});

  var _physicsRunning  = true;
  var _showIsolated    = true;
  var _activeLegend    = null;  // currently highlighted tag
  var _focusedNode     = null;  // currently focused node id

  // Label modes: 'auto' | 'hidden' | 'short' | 'medium' | 'full'
  var _labelMode     = 'auto';
  var _labelModeManual = false;
  var _currentScale  = 1.0;
  var _labelTimer    = null;

  // ── Init title & legend ──────────────────────────────────────────────
  document.getElementById('sp-graph-title').textContent = _graphTitle;

  var legendEl      = document.getElementById('sp-legend-items');
  var legendTitleEl = document.getElementById('sp-legend-title');

  if (_colorBy === 'year') {{
    legendTitleEl.innerHTML = '顏色 = 年份';
    legendEl.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
      '<div style="width:80px;height:8px;border-radius:4px;background:linear-gradient(to right,#60a5fa,#f59e0b);"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:10px;color:#64748b;">' +
      '<span>較早</span><span>較近</span></div>';
  }} else if (_colorBy === 'citations') {{
    legendTitleEl.innerHTML = '顏色 = 引用數';
    legendEl.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
      '<div style="width:80px;height:8px;border-radius:4px;background:linear-gradient(to right,#94a3b8,#6366f1);"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:10px;color:#64748b;">' +
      '<span>低</span><span>高</span></div>';
  }} else {{
    legendTitleEl.innerHTML = '標籤圖例 <span>點擊閃爍高亮</span>';
    _legendItems.forEach(function(item) {{
      var count = (_tagNodes[item.tag] || []).length;
      var div = document.createElement('div');
      div.className = 'legend-item';
      div.dataset.tag = item.tag;
      div.innerHTML =
        '<div class="legend-dot" style="background:' + item.color + ';color:' + item.color + '"></div>' +
        '<span class="legend-label">' + item.tag + '</span>' +
        '<span class="legend-count">' + count + '</span>';
      div.addEventListener('click', function() {{ legendClick(item.tag, item.color, div); }});
      legendEl.appendChild(div);
    }});
  }}

  // ── Wait for vis.js network ──────────────────────────────────────────
  var _initCheck = setInterval(function() {{
    if (typeof network === 'undefined' || typeof nodes === 'undefined') return;
    clearInterval(_initCheck);
    _initGraph();
  }}, 100);

  function _initGraph() {{
    // Stats
    document.getElementById('stat-nodes').textContent = nodes.length;
    document.getElementById('stat-edges').textContent = edges.length;

    // ── Click: focus mode ────────────────────────────────────────────
    network.on('click', function(params) {{
      if (params.nodes.length === 0) {{
        // Click on empty space → reset
        resetHighlight();
        closeDetail();
        return;
      }}
      var nodeId = params.nodes[0];
      if (_focusedNode === nodeId) {{
        // Second click on same node → deselect
        resetHighlight();
        closeDetail();
        return;
      }}
      _focusedNode = nodeId;
      _highlightNeighbours(nodeId);
      _openDetail(nodeId);
      document.getElementById('stat-selected').textContent = '1';
    }});

    // ── Double-click: reset ──────────────────────────────────────────
    network.on('doubleClick', function(params) {{
      if (params.nodes.length === 0) {{
        resetHighlight();
        closeDetail();
      }} else {{
        // Double-click a node: zoom in to it
        network.focus(params.nodes[0], {{
          scale: 2.0,
          animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }},
        }});
      }}
    }});

    // ── Hover: enlarge node ──────────────────────────────────────────
    network.on('hoverNode', function(params) {{
      var id = params.node;
      var d = _nodeData[String(id)];
      if (d) {{
        nodes.update([{{ id: id, size: (d.size || 20) * 1.6 }}]);
      }}
      document.getElementById('sp-hint').style.opacity = '0';
    }});

    network.on('blurNode', function(params) {{
      var id = params.node;
      var d = _nodeData[String(id)];
      if (d) {{
        nodes.update([{{ id: id, size: d.size || 20 }}]);
      }}
    }});

    // ── Zoom: dynamic label management ──────────────────────────────
    network.on('zoom', function(params) {{
      _currentScale = params.scale;
      if (!_labelModeManual) {{
        if (_labelTimer) clearTimeout(_labelTimer);
        _labelTimer = setTimeout(function() {{
          _applyAutoLabels(_currentScale);
        }}, 80);
      }}
    }});

    // Stabilization progress
    network.on('stabilizationProgress', function(params) {{
      var pct = Math.round(params.iterations / params.total * 100);
      document.getElementById('sp-graph-title').textContent =
        _graphTitle + ' — 穩定中 ' + pct + '%';
    }});
    network.on('stabilizationIterationsDone', function() {{
      document.getElementById('sp-graph-title').textContent = _graphTitle;
      document.getElementById('stat-nodes').textContent = nodes.length;
      document.getElementById('stat-edges').textContent = edges.length;
    }});
  }}

  // ── Auto label management ────────────────────────────────────────────
  function _applyAutoLabels(scale) {{
    var newMode;
    if (scale < 0.20)      newMode = 'hidden';
    else if (scale < 0.45) newMode = 'short';   // 8 chars
    else if (scale < 0.85) newMode = 'medium';  // 15 chars
    else                   newMode = 'full';     // 25 chars

    _setLabelMode(newMode, false);
  }}

  function _setLabelMode(mode, manual) {{
    _labelModeManual = manual;
    _labelMode = mode;

    var labelMap = {{
      'hidden': function(title) {{ return ''; }},
      'short':  function(title) {{ return title.length > 8  ? title.substring(0,8)+'…'  : title; }},
      'medium': function(title) {{ return title.length > 15 ? title.substring(0,15)+'…' : title; }},
      'full':   function(title) {{ return title.length > 25 ? title.substring(0,25)+'…' : title; }},
    }};
    var fn = labelMap[mode] || labelMap['medium'];

    nodes.update(nodes.getIds().map(function(id) {{
      var d = _nodeData[String(id)];
      return {{ id: id, label: d ? fn(d.title) : '' }};
    }}));

    // Show badge
    var labels = {{ hidden:'標籤：隱藏', short:'標籤：極短', medium:'標籤：截短', full:'標籤：完整', auto:'標籤：自動' }};
    var badge = document.getElementById('sp-zoom-badge');
    badge.textContent = labels[mode] || '標籤：' + mode;
    badge.classList.add('show');
    clearTimeout(badge._timer);
    badge._timer = setTimeout(function() {{ badge.classList.remove('show'); }}, 1800);

    // Update button label
    var btnLabel = {{ hidden:'🏷 標籤：隱藏', short:'🏷 標籤：極短', medium:'🏷 標籤：截短', full:'🏷 標籤：完整' }};
    document.getElementById('btn-labels').textContent =
      manual ? (btnLabel[mode] || '🏷 標籤') : '🏷 標籤：自動';
    if (manual) {{
      document.getElementById('btn-labels').classList.add('active');
    }} else {{
      document.getElementById('btn-labels').classList.remove('active');
    }}
  }}

  window.cycleLabelMode = function() {{
    var modes = ['auto', 'full', 'medium', 'short', 'hidden'];
    var idx = modes.indexOf(_labelModeManual ? _labelMode : 'auto');
    var next = modes[(idx + 1) % modes.length];
    if (next === 'auto') {{
      _setLabelMode('auto', false);
      _applyAutoLabels(_currentScale);
    }} else {{
      _setLabelMode(next, true);
    }}
  }};

  // ── Focus mode: highlight neighbours ────────────────────────────────
  function _highlightNeighbours(nodeId) {{
    var connEdges = network.getConnectedEdges(nodeId);
    var connNodes = network.getConnectedNodes(nodeId);
    var edgeSet   = new Set(connEdges);
    var nodeSet   = new Set(connNodes.map(String));
    nodeSet.add(String(nodeId));

    nodes.update(nodes.getIds().map(function(id) {{
      var isConn = nodeSet.has(String(id));
      return {{ id: id, opacity: isConn ? 1.0 : 0.08 }};
    }}));
    edges.update(edges.getIds().map(function(id) {{
      return {{ id: id, opacity: edgeSet.has(id) ? 1.0 : 0.03 }};
    }}));
  }}

  window.resetHighlight = function() {{
    _focusedNode = null;
    _activeLegend = null;
    nodes.update(nodes.getIds().map(function(id) {{
      return {{ id: id, opacity: 1.0 }};
    }}));
    edges.update(edges.getIds().map(function(id) {{
      return {{ id: id, opacity: 1.0 }};
    }}));
    document.getElementById('stat-selected').textContent = '0';
    // Remove active class from all legend items
    document.querySelectorAll('.legend-item.active').forEach(function(el) {{
      el.classList.remove('active');
    }});
  }};

  // ── Legend click: flash + highlight tag group ────────────────────────
  window.legendClick = function(tag, color, divEl) {{
    if (_activeLegend === tag) {{
      // Second click → deselect
      resetHighlight();
      return;
    }}
    _activeLegend = tag;
    _focusedNode  = null;

    var tagNodeIds = _tagNodes[tag] || [];
    if (tagNodeIds.length === 0) return;
    var tagSet = new Set(tagNodeIds);

    // Visual: dim non-members, highlight members
    nodes.update(nodes.getIds().map(function(id) {{
      return {{ id: id, opacity: tagSet.has(String(id)) ? 1.0 : 0.08 }};
    }}));
    edges.update(edges.getIds().map(function(id) {{
      return {{ id: id, opacity: 0.05 }};
    }}));

    // Flash: briefly change border to gold × 2 cycles
    var flash1 = tagNodeIds.map(function(id) {{
      return {{ id: id, color: {{ border: '#fbbf24', background: _blend(id, '#fbbf24', 0.5) }} }};
    }});
    nodes.update(flash1);
    setTimeout(function() {{
      var restore1 = tagNodeIds.map(function(id) {{
        var d = _nodeData[id];
        return {{ id: id, color: {{ border: '#ffffff30', background: d ? d.color : '#60a5fa' }} }};
      }});
      nodes.update(restore1);
      setTimeout(function() {{
        nodes.update(flash1);
        setTimeout(function() {{
          nodes.update(tagNodeIds.map(function(id) {{
            var d = _nodeData[id];
            return {{ id: id, color: {{
              border: '#fbbf24',
              background: d ? d.color : '#60a5fa',
              highlight: {{ background: '#fbbf24', border: '#f59e0b' }},
            }} }};
          }}));
        }}, 200);
      }}, 200);
    }}, 200);

    // Update legend UI
    document.querySelectorAll('.legend-item').forEach(function(el) {{
      el.classList.remove('active');
    }});
    if (divEl) divEl.classList.add('active');

    document.getElementById('stat-selected').textContent = tagNodeIds.length + ' (' + tag + ')';

    // Fit to visible nodes
    network.fit({{
      nodes: tagNodeIds,
      animation: {{ duration: 500, easingFunction: 'easeInOutQuad' }},
    }});
  }};

  function _blend(id, targetColor, t) {{
    var d = _nodeData[String(id)];
    if (!d || !d.color) return targetColor;
    var c1 = d.color.replace('#','');
    var c2 = targetColor.replace('#','');
    function lerp(a, b, t) {{ return Math.round(parseInt(a,16) + (parseInt(b,16)-parseInt(a,16))*t); }}
    var r = lerp(c1.substring(0,2), c2.substring(0,2), t);
    var g = lerp(c1.substring(2,4), c2.substring(2,4), t);
    var b = lerp(c1.substring(4,6), c2.substring(4,6), t);
    return '#' + [r,g,b].map(function(v){{ return ('0'+v.toString(16)).slice(-2); }}).join('');
  }}

  // ── Isolated node filter ─────────────────────────────────────────────
  window.toggleIsolated = function() {{
    _showIsolated = !_showIsolated;
    var btn = document.getElementById('btn-isolated');
    nodes.update(nodes.getIds().map(function(id) {{
      return {{ id: id, hidden: !_showIsolated && _isolatedSet.has(String(id)) }};
    }}));
    if (_showIsolated) {{
      btn.textContent = '○ 隱藏孤立';
      btn.classList.remove('active');
    }} else {{
      btn.textContent = '● 顯示孤立';
      btn.classList.add('active');
    }}
    setTimeout(function() {{
      network.fit({{ animation: {{ duration: 400, easingFunction: 'easeInOutQuad' }} }});
    }}, 50);
  }};

  // ── Right detail panel ───────────────────────────────────────────────
  function _openDetail(nodeId) {{
    var d = _nodeData[String(nodeId)];
    if (!d) return;

    var colorEl = document.getElementById('sp-detail-color');
    colorEl.style.background = d.color || '#6366f1';
    colorEl.style.boxShadow  = '0 0 10px ' + (d.color || '#6366f1');

    document.getElementById('sp-detail-title').textContent = d.title || '';
    document.getElementById('sp-degree-val').textContent   = d.degree != null ? d.degree : '—';
    document.getElementById('sp-cite-val').textContent     = d.citation_count || '0';

    var meta = '';
    if (d.year)   meta += '<div class="detail-row"><span class="detail-label">年份</span><span class="detail-val">' + d.year + '</span></div>';
    if (d.authors) meta += '<div class="detail-row"><span class="detail-label">作者</span><span class="detail-val">' + String(d.authors).substring(0,100) + '</span></div>';
    if (d.venue)  meta += '<div class="detail-row"><span class="detail-label">期刊</span><span class="detail-val">' + d.venue + '</span></div>';
    document.getElementById('sp-detail-meta').innerHTML = meta;

    var tagsEl = document.getElementById('sp-detail-tags');
    tagsEl.innerHTML = '';
    (d.tags || []).forEach(function(t) {{
      var chip = document.createElement('span');
      chip.className = 'tag-chip';
      chip.textContent = t;
      chip.title = '點擊高亮此標籤';
      chip.addEventListener('click', function() {{
        legendClick(t, null, null);
      }});
      tagsEl.appendChild(chip);
    }});

    var absEl = document.getElementById('sp-detail-abstract');
    absEl.textContent = d.abstract ? d.abstract : '';

    var doiEl = document.getElementById('sp-detail-doi');
    doiEl.innerHTML = d.doi
      ? '<a href="https://doi.org/' + d.doi + '" target="_blank">🔗 DOI: ' + d.doi + '</a>'
      : '';

    document.getElementById('sp-detail').classList.add('open');
  }}

  window.closeDetail = function() {{
    document.getElementById('sp-detail').classList.remove('open');
  }};

  // ── Search ───────────────────────────────────────────────────────────
  var _searchTimer = null;
  document.getElementById('sp-search').addEventListener('input', function() {{
    clearTimeout(_searchTimer);
    var kw = this.value.trim().toLowerCase();
    _searchTimer = setTimeout(function() {{
      if (!kw) {{
        resetHighlight();
        return;
      }}
      var matchIds = [];
      nodes.getIds().forEach(function(id) {{
        var d = _nodeData[String(id)];
        if (d && d.title && d.title.toLowerCase().indexOf(kw) >= 0) matchIds.push(id);
      }});
      var matchSet = new Set(matchIds.map(String));
      nodes.update(nodes.getIds().map(function(id) {{
        return {{ id: id, opacity: matchSet.has(String(id)) ? 1.0 : 0.07 }};
      }}));
      edges.update(edges.getIds().map(function(id) {{
        return {{ id: id, opacity: 0.03 }};
      }}));
      document.getElementById('stat-selected').textContent = matchIds.length;
      if (matchIds.length > 0 && matchIds.length < 30) {{
        network.fit({{ nodes: matchIds, animation: {{ duration: 400 }} }});
      }}
    }}, 150);
  }});

  // ── Control buttons ──────────────────────────────────────────────────
  window.togglePhysics = function() {{
    _physicsRunning = !_physicsRunning;
    if (typeof network !== 'undefined') {{
      network.setOptions({{ physics: {{ enabled: _physicsRunning }} }});
    }}
    var btn = document.getElementById('btn-physics');
    if (_physicsRunning) {{
      btn.textContent = '⏸ 暫停模擬';
      btn.classList.remove('active');
    }} else {{
      btn.textContent = '▶ 繼續模擬';
      btn.classList.add('active');
    }}
  }};

  window.fitView = function() {{
    if (typeof network !== 'undefined') {{
      network.fit({{ animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }} }});
    }}
  }};

  // ── Keyboard shortcuts ───────────────────────────────────────────────
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{ resetHighlight(); closeDetail(); }}
    if (e.key === 'f' && !e.ctrlKey) {{ fitView(); }}
    if (e.key === ' ') {{ togglePhysics(); e.preventDefault(); }}
  }});

}})();
</script>
"""

    html = html_path.read_text(encoding="utf-8")
    html = html.replace("</body>", extra_html + "\n</body>")
    html_path.write_text(html, encoding="utf-8")
