"""
RAG 問答系統評估腳本
═══════════════════
自動從論文庫生成測試問題，評估檢索準確率。

評估指標：
  Hit@k  — 正確論文是否出現在前 k 個結果
  MRR    — Mean Reciprocal Rank（越高越好，最高 1.0）
  平均排名 — 正確結果平均排在第幾位

三個評估維度：
  1. 標題查詢：  "XXX 這篇論文研究什麼？"
  2. 摘要查詢：  用摘要第一句話查詢
  3. 跨論文比較：用 tag 構造跨論文問題

執行方式：
  python eval_rag.py                  # 快速評估（前 30 篇）
  python eval_rag.py --n 50           # 評估 50 篇
  python eval_rag.py --verbose        # 顯示每題詳情
  python eval_rag.py --no-rerank      # 關掉 reranker 對比
"""

import argparse
import time
from collections import defaultdict

from smartpaper.database.sqlite_db import SQLiteDB
from smartpaper.database.vector_db import VectorDB
from smartpaper.database.chunk_store import ChunkStore
from smartpaper.services.search import SearchService
from smartpaper.services.reranker import Reranker


# ─────────────────────────────────────────────────────────────────
# 測試案例生成
# ─────────────────────────────────────────────────────────────────

def make_title_queries(papers) -> list[dict]:
    """用論文標題構造查詢，預期應該檢索到該論文"""
    cases = []
    for p in papers:
        if not p.title:
            continue
        # 三種標題查詢格式
        queries = [
            p.title,
            f"What is the main contribution of {p.title}?",
            f"Summarize the paper: {p.title}",
        ]
        for q in queries:
            cases.append({
                "query": q,
                "expected_paper_id": p.id,
                "expected_title": p.title,
                "query_type": "title",
            })
    return cases


def make_abstract_queries(papers) -> list[dict]:
    """用摘要前兩句話查詢，預期應該檢索到該論文"""
    cases = []
    for p in papers:
        if not p.abstract or len(p.abstract) < 80:
            continue
        # 取前兩句
        import re
        sentences = re.split(r'(?<=[.!?])\s+', p.abstract.strip())
        first_two = " ".join(sentences[:2])
        if len(first_two) < 40:
            continue
        cases.append({
            "query": first_two,
            "expected_paper_id": p.id,
            "expected_title": p.title,
            "query_type": "abstract",
        })
    return cases


def make_tag_queries(papers) -> list[dict]:
    """用 tag 構造查詢（一個 tag → 應找到有該 tag 的任一篇論文）"""
    from collections import defaultdict
    tag_papers = defaultdict(list)
    for p in papers:
        for t in (p.tags or []):
            tag_papers[t].append(p)

    cases = []
    for tag, tagged in tag_papers.items():
        if len(tagged) < 2:  # tag 只有一篇沒意義
            continue
        cases.append({
            "query": f"papers about {tag}",
            "expected_paper_ids": {p.id for p in tagged},
            "tag": tag,
            "query_type": "tag",
            "n_relevant": len(tagged),
        })
    return cases[:20]  # 最多 20 個 tag 案例


# ─────────────────────────────────────────────────────────────────
# 檢索函數
# ─────────────────────────────────────────────────────────────────

def retrieve_abstract(search_svc: SearchService, query: str,
                      top_k: int = 10, use_rerank: bool = True) -> list[int]:
    """用 hybrid_search 檢索論文（摘要路徑）"""
    results = search_svc.hybrid_search(query, n_results=top_k, use_rerank=use_rerank)
    return [r.paper.id for r in results if r.paper]


def retrieve_chunks(vector_db: VectorDB, query: str, top_k: int = 10) -> list[int]:
    """用 fulltext chunk 搜尋論文（全文路徑）"""
    results = vector_db.search_chunks(query, n_results=top_k * 3)
    seen, paper_ids = set(), []
    for r in results:
        pid = r.get("paper_id")
        if pid and pid not in seen:
            seen.add(pid)
            paper_ids.append(pid)
        if len(paper_ids) >= top_k:
            break
    return paper_ids


# ─────────────────────────────────────────────────────────────────
# 指標計算
# ─────────────────────────────────────────────────────────────────

def reciprocal_rank(retrieved: list[int], relevant: set[int]) -> float:
    for rank, pid in enumerate(retrieved, 1):
        if pid in relevant:
            return 1.0 / rank
    return 0.0


def hit_at_k(retrieved: list[int], relevant: set[int], k: int) -> bool:
    return any(pid in relevant for pid in retrieved[:k])


# ─────────────────────────────────────────────────────────────────
# 主評估流程
# ─────────────────────────────────────────────────────────────────

def evaluate(n_papers: int = 30, verbose: bool = False, use_rerank: bool = True):
    print("\n" + "═" * 60)
    print("  SmartPaper RAG 檢索評估")
    print("═" * 60)

    db = SQLiteDB()
    vector_db = VectorDB()
    chunk_store = ChunkStore()
    search_svc = SearchService(db, vector_db)

    all_papers = db.get_all(limit=5000)
    papers = all_papers[:n_papers]
    fulltext_ids = set(chunk_store.papers_with_fulltext())

    print(f"\n論文庫：{len(all_papers)} 篇，評估前 {len(papers)} 篇")
    print(f"有全文 chunk：{len(fulltext_ids)} 篇")
    print(f"CrossEncoder reranker：{'開啟' if use_rerank else '關閉'}\n")

    # 生成測試案例
    title_cases = make_title_queries(papers)
    abstract_cases = make_abstract_queries(papers)
    tag_cases = make_tag_queries(papers)

    print(f"測試案例：標題 {len(title_cases)} / 摘要 {len(abstract_cases)} / 標籤 {len(tag_cases)}")
    print("─" * 60)

    results_by_type = defaultdict(lambda: {
        "mrr": [], "hit1": [], "hit3": [], "hit5": [],
        "latency": [], "failures": [],
    })

    # ── 評估標題 + 摘要查詢（摘要路徑）
    for case in title_cases + abstract_cases:
        qtype = case["query_type"]
        expected = {case["expected_paper_id"]}

        t0 = time.time()
        retrieved = retrieve_abstract(search_svc, case["query"],
                                      top_k=10, use_rerank=use_rerank)
        latency = time.time() - t0

        rr = reciprocal_rank(retrieved, expected)
        h1 = hit_at_k(retrieved, expected, 1)
        h3 = hit_at_k(retrieved, expected, 3)
        h5 = hit_at_k(retrieved, expected, 5)

        results_by_type[qtype]["mrr"].append(rr)
        results_by_type[qtype]["hit1"].append(h1)
        results_by_type[qtype]["hit3"].append(h3)
        results_by_type[qtype]["hit5"].append(h5)
        results_by_type[qtype]["latency"].append(latency)

        if not h5:
            results_by_type[qtype]["failures"].append({
                "query": case["query"][:80],
                "expected": case["expected_title"][:60],
                "got": retrieved[:3],
            })

        if verbose:
            rank_str = f"rank={retrieved.index(case['expected_paper_id']) + 1}" \
                       if case["expected_paper_id"] in retrieved else "未找到"
            mark = "✓" if h5 else "✗"
            print(f"  {mark} [{qtype}] {case['query'][:60]}")
            print(f"      → {rank_str}  MRR={rr:.2f}  ({latency*1000:.0f}ms)")

    # ── 評估全文 chunk 路徑（有上傳 PDF 的論文）
    chunk_cases = [c for c in title_cases
                   if c["expected_paper_id"] in fulltext_ids][:20]
    for case in chunk_cases:
        expected = {case["expected_paper_id"]}
        t0 = time.time()
        retrieved = retrieve_chunks(vector_db, case["query"], top_k=10)
        latency = time.time() - t0

        rr = reciprocal_rank(retrieved, expected)
        results_by_type["chunk"]["mrr"].append(rr)
        results_by_type["chunk"]["hit1"].append(hit_at_k(retrieved, expected, 1))
        results_by_type["chunk"]["hit3"].append(hit_at_k(retrieved, expected, 3))
        results_by_type["chunk"]["hit5"].append(hit_at_k(retrieved, expected, 5))
        results_by_type["chunk"]["latency"].append(latency)

    # ── 評估標籤查詢
    for case in tag_cases:
        expected = case["expected_paper_ids"]
        t0 = time.time()
        retrieved = retrieve_abstract(search_svc, case["query"],
                                      top_k=10, use_rerank=use_rerank)
        latency = time.time() - t0

        rr = reciprocal_rank(retrieved, expected)
        results_by_type["tag"]["mrr"].append(rr)
        results_by_type["tag"]["hit1"].append(hit_at_k(retrieved, expected, 1))
        results_by_type["tag"]["hit3"].append(hit_at_k(retrieved, expected, 3))
        results_by_type["tag"]["hit5"].append(hit_at_k(retrieved, expected, 5))
        results_by_type["tag"]["latency"].append(latency)

    # ── 打印結果
    print("\n" + "═" * 60)
    print(f"  {'類型':<12} {'MRR':>6} {'Hit@1':>6} {'Hit@3':>6} {'Hit@5':>6} {'延遲(ms)':>9} {'案例數':>6}")
    print("─" * 60)

    overall_mrr, overall_h5, n_total = [], [], 0
    type_labels = {
        "title": "標題查詢", "abstract": "摘要查詢",
        "chunk": "全文chunk", "tag": "標籤查詢",
    }
    for qtype, metrics in results_by_type.items():
        n = len(metrics["mrr"])
        if n == 0:
            continue
        mrr   = sum(metrics["mrr"]) / n
        h1    = sum(metrics["hit1"]) / n * 100
        h3    = sum(metrics["hit3"]) / n * 100
        h5    = sum(metrics["hit5"]) / n * 100
        lat   = sum(metrics["latency"]) / n * 1000

        label = type_labels.get(qtype, qtype)
        print(f"  {label:<12} {mrr:>6.3f} {h1:>5.1f}% {h3:>5.1f}% {h5:>5.1f}% {lat:>8.0f} {n:>6}")

        if qtype in ("title", "abstract"):
            overall_mrr.extend(metrics["mrr"])
            overall_h5.extend(metrics["hit5"])
            n_total += n

    if overall_mrr:
        print("─" * 60)
        print(f"  {'整體':<12} {sum(overall_mrr)/len(overall_mrr):>6.3f}"
              f" {'':>6} {'':>6} {sum(overall_h5)/len(overall_h5)*100:>5.1f}%"
              f" {'':>9} {n_total:>6}")

    # ── 失敗案例分析
    print("\n" + "═" * 60)
    print("  失敗案例分析（Hit@5 未命中）")
    print("─" * 60)
    failure_count = 0
    for qtype, metrics in results_by_type.items():
        for f in metrics["failures"][:3]:
            print(f"\n  [{type_labels.get(qtype, qtype)}]")
            print(f"  查詢：{f['query']}")
            print(f"  預期：{f['expected']}")
            print(f"  實際前3：{f['got']}")
            failure_count += 1

    if failure_count == 0:
        print("  沒有失敗案例！")

    # ── 改進建議
    print("\n" + "═" * 60)
    print("  診斷與改進建議")
    print("─" * 60)
    _diagnose(results_by_type, fulltext_ids, papers)
    print()


def _diagnose(results_by_type, fulltext_ids, papers):
    title_mrr = results_by_type["title"]["mrr"]
    abstract_mrr = results_by_type["abstract"]["mrr"]
    chunk_mrr = results_by_type["chunk"]["mrr"]

    t_avg = sum(title_mrr) / len(title_mrr) if title_mrr else 0
    a_avg = sum(abstract_mrr) / len(abstract_mrr) if abstract_mrr else 0
    c_avg = sum(chunk_mrr) / len(chunk_mrr) if chunk_mrr else 0

    print(f"\n  [MRR] 標題查詢={t_avg:.3f}  摘要查詢={a_avg:.3f}  全文chunk={c_avg:.3f}")

    issues = []
    suggestions = []

    if t_avg < 0.5:
        issues.append("! 標題查詢準確率低（< 0.5）")
        suggestions.append(
            "→ [嵌入模型] 目前用的是 all-MiniLM-L6-v2（通用），\n"
            "     換成 allenai/specter2 或 BAAI/bge-m3 對學術文章更好"
        )

    if a_avg < 0.4:
        issues.append("摘要查詢準確率低（< 0.4）")
        suggestions.append(
            "→ [Chunk 策略] 目前 MAX_CHUNK_CHARS=1200 太大，\n"
            "     改為 500-600 字可以讓每個 chunk 更聚焦，提升精準度"
        )

    if c_avg < t_avg and chunk_mrr:
        issues.append("全文 chunk 路徑比摘要路徑還差")
        suggestions.append(
            "→ [chunk 重疊] 目前 OVERLAP_CHARS=80 較少，\n"
            "     增加到 150-200 可減少段落邊界造成的資訊缺失"
        )

    if not fulltext_ids:
        issues.append("沒有任何論文上傳全文")
        suggestions.append(
            "→ 上傳 PDF 全文後，chunk 路徑能提供章節級精準檢索，\n"
            "     比僅用摘要準確很多"
        )

    no_abstract = sum(1 for p in papers if not p.abstract)
    if no_abstract > len(papers) * 0.3:
        issues.append(f"{no_abstract} 篇論文沒有摘要（佔 {no_abstract/len(papers)*100:.0f}%）")
        suggestions.append(
            "→ 沒有摘要的論文在摘要路徑完全無法被找到，\n"
            "     建議從 Crossref 補齊摘要"
        )

    # 通用改進建議（不管指標如何都建議）
    suggestions.append(
        "→ [HyDE] Hypothetical Document Embedding：先讓 LLM 根據問題\n"
        "     生成一段假設答案，再用假設答案去做向量搜尋，通常提升 10-20%"
    )
    suggestions.append(
        "→ [查詢擴展] 用 LLM 把問題改寫成 3 種不同說法，取聯集再 rerank"
    )

    if not issues:
        print("  ✓ 指標正常，沒有明顯問題")
    else:
        print("  發現問題：")
        for i in issues:
            print(f"    ⚠ {i}")

    print("\n  改進建議：")
    for s in suggestions:
        print(f"  {s}")


# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=30, help="評估前 N 篇論文")
    parser.add_argument("--verbose", action="store_true", help="顯示每題詳情")
    parser.add_argument("--no-rerank", action="store_true", help="關掉 CrossEncoder reranker")
    args = parser.parse_args()
    evaluate(n_papers=args.n, verbose=args.verbose, use_rerank=not args.no_rerank)
