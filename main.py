#!/usr/bin/env python3
"""
SmartPaper-Tagging CLI
智能學術文獻標籤管理系統命令列介面
"""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel

from smartpaper.config import validate_config, DATA_DIR
from smartpaper.database.sqlite_db import SQLiteDB
from smartpaper.database.vector_db import VectorDB
from smartpaper.services.pipeline import Pipeline
from smartpaper.services.search import SearchService
from smartpaper.services.classifier import ClassificationService
from smartpaper.services.writing_guide import WritingGuideService
from smartpaper.services.citation import CitationService
from smartpaper.services.concept_extractor import ConceptExtractor, TYPE_LABELS
from smartpaper.models import ProcessingStatus

console = Console()


def cmd_process(args):
    """處理 XLSX 檔案"""
    file_path = Path(args.file)
    if not file_path.exists():
        console.print(f"[red]錯誤：檔案不存在 - {file_path}[/red]")
        sys.exit(1)

    # 驗證配置
    if args.tags:
        errors = validate_config()
        if errors:
            console.print("[red]配置錯誤：[/red]")
            for err in errors:
                console.print(f"  - {err}")
            sys.exit(1)

    console.print(Panel.fit(
        f"[bold blue]處理檔案：[/bold blue] {file_path.name}",
        title="SmartPaper-Tagging",
    ))

    pipeline = Pipeline()

    # 進度回調
    def progress_callback(status: ProcessingStatus):
        pass  # 使用 rich progress bar 代替

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        # 先讀取檔案獲取總數
        from smartpaper.services.ingestion import XLSXIngestion
        with XLSXIngestion(file_path) as ingestion:
            titles = ingestion.read_titles(title_column=args.column)

        task = progress.add_task("處理論文中...", total=len(titles))

        def update_progress(status: ProcessingStatus):
            progress.update(task, completed=status.processed)

        result = pipeline.process_xlsx(
            file_path=file_path,
            title_column=args.column,
            skip_existing=not args.force,
            generate_tags=args.tags,
            progress_callback=update_progress,
        )

    # 顯示結果
    console.print()
    console.print(f"[green]✓ 處理完成[/green]")
    console.print(f"  總數：{result.total}")
    console.print(f"  成功：{result.success}")
    console.print(f"  失敗：{result.failed}")

    if result.errors:
        console.print(f"\n[yellow]錯誤訊息：[/yellow]")
        for err in result.errors[:5]:
            console.print(f"  - {err}")
        if len(result.errors) > 5:
            console.print(f"  ... 還有 {len(result.errors) - 5} 個錯誤")


def cmd_search(args):
    """搜尋論文"""
    query = " ".join(args.query)

    search_service = SearchService()

    if args.semantic:
        console.print(f"[blue]語義搜尋：[/blue] {query}\n")
        results = search_service.semantic_search(query, n_results=args.limit)

        if not results:
            console.print("[yellow]未找到相關論文[/yellow]")
            return

        table = Table(title="搜尋結果")
        table.add_column("相似度", style="cyan", width=8)
        table.add_column("標題", style="white")
        table.add_column("標籤", style="green")

        for sr in results:
            score = f"{sr.score:.2%}"
            tags = ", ".join(sr.paper.tags[:3]) if sr.paper.tags else "-"
            table.add_row(score, sr.paper.title[:60], tags)

        console.print(table)

    else:
        console.print(f"[blue]關鍵字搜尋：[/blue] {query}\n")
        papers = search_service.keyword_search(query)

        if not papers:
            console.print("[yellow]未找到相關論文[/yellow]")
            return

        table = Table(title="搜尋結果")
        table.add_column("ID", style="cyan", width=5)
        table.add_column("標題", style="white")
        table.add_column("標籤", style="green")

        for paper in papers[:args.limit]:
            tags = ", ".join(paper.tags[:3]) if paper.tags else "-"
            table.add_row(str(paper.id), paper.title[:60], tags)

        console.print(table)


def cmd_list(args):
    """列出論文"""
    db = SQLiteDB()

    if args.tag:
        papers = db.get_by_tag(args.tag)
        console.print(f"[blue]標籤篩選：[/blue] {args.tag}\n")
    else:
        papers = db.get_all(limit=args.limit)

    if not papers:
        console.print("[yellow]沒有論文資料[/yellow]")
        return

    table = Table(title=f"論文清單 (共 {len(papers)} 篇)")
    table.add_column("ID", style="cyan", width=5)
    table.add_column("標題", style="white", max_width=50)
    table.add_column("DOI", style="dim", max_width=25)
    table.add_column("標籤", style="green", max_width=30)

    for paper in papers:
        doi = paper.doi[:25] + "..." if paper.doi and len(paper.doi) > 25 else (paper.doi or "-")
        tags = ", ".join(paper.tags[:3]) if paper.tags else "-"
        title = paper.title[:50] + "..." if len(paper.title) > 50 else paper.title
        table.add_row(str(paper.id), title, doi, tags)

    console.print(table)


def cmd_tags(args):
    """列出所有標籤"""
    db = SQLiteDB()
    tags = db.get_all_tags()

    if not tags:
        console.print("[yellow]沒有標籤資料[/yellow]")
        return

    console.print(f"[bold]所有標籤 (共 {len(tags)} 個)：[/bold]\n")

    # 每行顯示 4 個標籤
    for i in range(0, len(tags), 4):
        row_tags = tags[i:i+4]
        console.print("  " + "  |  ".join(f"[green]{t}[/green]" for t in row_tags))


def cmd_stats(args):
    """顯示統計資訊"""
    pipeline = Pipeline()
    stats = pipeline.get_statistics()

    console.print(Panel.fit(
        "[bold]系統統計資訊[/bold]",
        title="SmartPaper-Tagging",
    ))
    console.print()
    console.print(f"  論文總數：[cyan]{stats['total_papers']}[/cyan]")
    console.print(f"  有摘要：[cyan]{stats['with_abstract']}[/cyan]")
    console.print(f"  有標籤：[cyan]{stats['with_tags']}[/cyan]")
    console.print(f"  向量數量：[cyan]{stats['total_vectors']}[/cyan]")
    console.print(f"  獨立標籤：[cyan]{stats['unique_tags']}[/cyan]")

    if stats['tags']:
        console.print(f"\n  常用標籤：[green]{', '.join(stats['tags'][:10])}[/green]")


def cmd_export(args):
    """匯出論文到 XLSX"""
    output_path = Path(args.output)

    pipeline = Pipeline()
    pipeline.export_to_xlsx(output_path)

    console.print(f"[green]✓ 已匯出到：{output_path}[/green]")


def cmd_classify(args):
    """根據主題分類論文"""
    topics = args.topics

    if not topics:
        console.print("[yellow]請提供至少一個主題關鍵字[/yellow]")
        console.print("範例：python main.py classify 'Machine Learning' 'Healthcare' 'NLP'")
        sys.exit(1)

    # 決定分類方法
    method = args.method

    # 驗證配置
    errors = validate_config()
    if errors:
        if method in ("two_stage", "llm"):
            console.print("[red]錯誤：兩階段分類和 LLM 分類需要設定 Gemini API Key[/red]")
            sys.exit(1)
        if not args.no_summary:
            console.print("[yellow]警告：未設定 Gemini API Key，將跳過主題總結[/yellow]")
            args.no_summary = True

    # 顯示使用的方法
    method_names = {
        "semantic": "語意搜尋（快速）",
        "two_stage": "兩階段 RAG（先搜標題，再分析摘要）★推薦",
        "llm": "純 LLM 分類（最精確但最慢）",
    }

    console.print(Panel.fit(
        f"[bold blue]論文分類[/bold blue]\n"
        f"主題：{', '.join(topics)}\n"
        f"方法：{method_names.get(method, method)}",
        title="SmartPaper-Tagging",
    ))

    classifier = ClassificationService()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("分類中...", total=None)

        def progress_callback(topic, current, total):
            progress.update(task, description=f"分類中... [{current}/{total}] {topic}")

        report = classifier.get_classification_report(
            topics=topics,
            method=method,
            include_summary=not args.no_summary,
            progress_callback=progress_callback if method == "two_stage" else None,
        )

        progress.update(task, completed=True)

    # 顯示結果
    console.print()

    # 統計資訊
    stats = report["statistics"]
    console.print(f"[bold]統計：[/bold]")
    console.print(f"  論文總數：{stats['total_papers']}")
    console.print(f"  已分類：{stats['classified_papers']}")
    console.print(f"  未分類：{stats['unclassified_papers']}")
    console.print()

    # 各主題結果
    for topic, data in report["topics"].items():
        console.print(f"[bold cyan]【{topic}】[/bold cyan] ({data['count']} 篇)")

        # 顯示論文列表
        table = Table(show_header=True, header_style="bold")
        table.add_column("信心度", width=8)
        table.add_column("標題", max_width=50)

        # 兩階段分類會有理由欄位
        if method == "two_stage":
            table.add_column("理由", max_width=30)
        else:
            table.add_column("標籤", max_width=25)

        for paper in data["papers"][:args.limit]:
            score = f"{paper['score']:.1%}"
            title = paper["title"][:50] + "..." if len(paper["title"]) > 50 else paper["title"]

            if method == "two_stage":
                reason = paper.get("reason", "-")[:30]
                table.add_row(score, title, reason)
            else:
                tags = ", ".join(paper["tags"][:2]) if paper["tags"] else "-"
                table.add_row(score, title, tags)

        console.print(table)

        # 顯示論文與主題的關聯摘要（兩階段分類特有）
        if method == "two_stage" and args.show_details:
            for paper in data["papers"][:args.limit]:
                topic_summary = paper.get("topic_summary", "")
                if topic_summary:
                    console.print(f"\n  [dim]📄 {paper['title'][:40]}...[/dim]")
                    console.print(f"     [italic]{topic_summary}[/italic]")

        # 顯示總結
        if "summary" in data and data["summary"]:
            console.print(f"\n[dim]📝 主題總結：[/dim]")
            console.print(Panel(data["summary"], border_style="dim"))

        console.print()

    # 未分類的論文
    if report.get("unclassified") and args.show_unclassified:
        console.print(f"[yellow]【未分類】[/yellow] ({len(report['unclassified'])} 篇)")
        for paper in report["unclassified"][:5]:
            console.print(f"  - {paper['title'][:60]}")
        if len(report["unclassified"]) > 5:
            console.print(f"  ... 還有 {len(report['unclassified']) - 5} 篇")


def cmd_suggest_topics(args):
    """建議分類主題"""
    errors = validate_config()
    has_llm = not errors

    classifier = ClassificationService()

    console.print("[blue]根據現有標籤分析建議的主題...[/blue]\n")

    topics = classifier.suggest_topics(num_topics=args.num)

    if not topics:
        console.print("[yellow]資料庫中沒有足夠的標籤來建議主題[/yellow]")
        return

    console.print("[bold]建議的分類主題：[/bold]")
    for i, topic in enumerate(topics, 1):
        console.print(f"  {i}. [green]{topic}[/green]")

    console.print("\n[dim]使用方式：[/dim]")
    console.print(f"  python main.py classify {' '.join(repr(t) for t in topics[:3])}")


def cmd_sort_by_tags(args):
    """根據標籤排序論文"""
    classifier = ClassificationService()

    if args.group:
        # 分組顯示
        console.print("[bold blue]論文按標籤分組[/bold blue]\n")

        grouped = classifier.get_papers_grouped_by_tag()

        for tag, papers in grouped.items():
            if tag == "_no_tags":
                console.print(f"\n[yellow]【無標籤】[/yellow] ({len(papers)} 篇)")
            else:
                console.print(f"\n[bold cyan]【{tag}】[/bold cyan] ({len(papers)} 篇)")

            table = Table(show_header=False)
            table.add_column("ID", width=5)
            table.add_column("標題", max_width=70)

            for paper in papers[:args.limit]:
                title = paper["title"][:70] + "..." if len(paper["title"]) > 70 else paper["title"]
                table.add_row(str(paper["id"]), title)

            console.print(table)

            if len(papers) > args.limit:
                console.print(f"  [dim]... 還有 {len(papers) - args.limit} 篇[/dim]")

    else:
        # 排序顯示
        sort_names = {
            "tag_count": "標籤數量（多到少）",
            "tag_alpha": "標籤字母順序",
        }

        console.print(f"[bold blue]論文排序[/bold blue] - {sort_names.get(args.sort, args.sort)}\n")

        papers = classifier.get_papers_sorted_by_tags(
            sort_order=args.sort,
            tag_filter=args.tag,
        )

        if not papers:
            console.print("[yellow]沒有找到論文[/yellow]")
            return

        table = Table(title=f"共 {len(papers)} 篇論文")
        table.add_column("ID", width=5)
        table.add_column("標題", max_width=50)
        table.add_column("標籤", max_width=40)
        table.add_column("數量", width=6)

        for paper in papers[:args.limit]:
            title = paper["title"][:50] + "..." if len(paper["title"]) > 50 else paper["title"]
            tags = ", ".join(paper["tags"][:3]) if paper["tags"] else "-"
            if len(paper["tags"]) > 3:
                tags += f" (+{len(paper['tags']) - 3})"

            table.add_row(
                str(paper["id"]),
                title,
                tags,
                str(paper["tag_count"]),
            )

        console.print(table)


def cmd_export_classification(args):
    """匯出分類報告到 Excel"""
    topics = args.topics

    if not topics:
        console.print("[yellow]請提供至少一個主題關鍵字[/yellow]")
        console.print("範例：python main.py export-classify 'Machine Learning' 'Healthcare' -o report.xlsx")
        sys.exit(1)

    errors = validate_config()
    if errors:
        console.print("[red]錯誤：需要設定 Gemini API Key[/red]")
        sys.exit(1)

    output_path = Path(args.output)

    console.print(Panel.fit(
        f"[bold blue]匯出分類報告[/bold blue]\n"
        f"主題：{', '.join(topics)}\n"
        f"輸出：{output_path}",
        title="SmartPaper-Tagging",
    ))

    classifier = ClassificationService()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("分類中...", total=None)

        def progress_callback(topic, current, total):
            progress.update(task, description=f"分類中 [{current}/{total}] {topic}...")

        report = classifier.get_classification_report(
            topics=topics,
            method="two_stage",
            include_summary=True,
            progress_callback=progress_callback,
        )

        progress.update(task, description="匯出中...")
        classifier.export_classification_report(report, str(output_path))

    console.print(f"\n[green]✓ 已匯出到：{output_path}[/green]")
    console.print(f"  - 包含 {len(report['topics'])} 個主題")
    console.print(f"  - 已分類 {report['statistics']['classified_papers']} 篇論文")


def cmd_build_citations(args):
    """建立引用關係圖"""
    errors = validate_config()
    db = SQLiteDB()
    papers_with_doi = [p for p in db.get_all(limit=5000) if p.doi]

    if not papers_with_doi:
        console.print("[yellow]資料庫中沒有含 DOI 的論文[/yellow]")
        return

    console.print(Panel.fit(
        f"[bold blue]建立引用關係圖[/bold blue]\n"
        f"有 DOI 的論文：{len(papers_with_doi)} 篇\n"
        f"資料來源：Semantic Scholar API",
        title="SmartPaper-Tagging",
    ))

    service = CitationService(sqlite_db=db)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("取得引用資料...", total=len(papers_with_doi))

        def progress_callback(title, current, total):
            progress.update(task, completed=current,
                            description=f"[{current}/{total}] {title[:40]}...")

        result = service.build_citation_graph(
            progress_callback=progress_callback,
            skip_existing=not args.force,
        )

    console.print(f"\n[green]✓ 完成[/green]")
    console.print(f"  處理：{result['processed']} 篇")
    console.print(f"  跳過（已有資料）：{result['skipped']} 篇")
    console.print(f"  引用連結總數：{result['total_links']} 條")
    console.print(f"  對應到資料庫內：{result['resolved_internal']} 條")


def cmd_extract_concepts(args):
    """萃取所有論文的概念並建立倒排索引"""
    errors = validate_config()
    if errors:
        console.print("[red]需要設定 Gemini API Key[/red]")
        sys.exit(1)

    db = SQLiteDB()
    all_papers = db.get_all(limit=5000)

    console.print(Panel.fit(
        f"[bold blue]概念萃取[/bold blue]\n"
        f"論文總數：{len(all_papers)} 篇\n"
        f"使用 LLM 萃取方法、資料集、評測指標、研究任務",
        title="SmartPaper-Tagging",
    ))

    extractor = ConceptExtractor(sqlite_db=db)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("萃取概念...", total=len(all_papers))

        def progress_callback(title, current, total):
            progress.update(task, completed=current,
                            description=f"[{current}/{total}] {title[:40]}...")

        result = extractor.build_index(
            papers=all_papers,
            progress_callback=progress_callback,
            skip_existing=not args.force,
        )

    console.print(f"\n[green]✓ 完成[/green]")
    console.print(f"  處理：{result['processed']} 篇")
    console.print(f"  跳過（已有資料）：{result['skipped']} 篇")
    console.print(f"  萃取概念總數：{result['total_concepts']} 個")

    # 顯示概念統計
    if args.show_stats:
        console.print()
        for ctype in ["method", "dataset", "metric", "task"]:
            concepts = extractor.get_all_concepts(ctype)[:10]
            if concepts:
                label = TYPE_LABELS.get(ctype, ctype)
                console.print(f"[bold]{label} Top 10：[/bold]")
                for c in concepts:
                    console.print(f"  {c['name']} ({c['paper_count']} 篇)")
                console.print()


def cmd_concept_search(args):
    """用概念名稱搜尋論文"""
    query = " ".join(args.query)
    extractor = ConceptExtractor()
    papers = extractor.search_by_concept(query)

    if not papers:
        console.print(f"[yellow]未找到使用「{query}」概念的論文[/yellow]")
        return

    console.print(f"[bold]找到 {len(papers)} 篇使用「[cyan]{query}[/cyan]」的論文：[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", width=5)
    table.add_column("標題", max_width=55)
    table.add_column("概念", max_width=30)

    db = SQLiteDB()
    for paper in papers[:args.limit]:
        concepts = db.get_paper_concepts(paper.id)
        # 找出符合查詢的概念
        matched = [
            n for names in concepts.values() for n in names
            if query.lower() in n.lower()
        ]
        concept_str = ", ".join(matched[:3])
        title = paper.title[:55] + "..." if len(paper.title) > 55 else paper.title
        table.add_row(str(paper.id), title, concept_str)

    console.print(table)


def cmd_related_work(args):
    """為指定論文推薦 Related Work 候選"""
    db = SQLiteDB()
    paper = db.get_by_id(args.paper_id)
    if not paper:
        console.print(f"[red]找不到 ID={args.paper_id} 的論文[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold blue]Related Work 推薦[/bold blue]\n{paper.title[:70]}",
        title="SmartPaper-Tagging",
    ))

    citation_svc = CitationService(sqlite_db=db)
    concept_ext = ConceptExtractor(sqlite_db=db)

    # 引用關係推薦
    citation_related = citation_svc.find_related_work(paper.id, top_k=args.limit)
    # 概念共享推薦
    concept_related = concept_ext.find_papers_sharing_concepts(paper.id, top_k=args.limit)

    if citation_related:
        console.print("\n[bold cyan]引用關係推薦：[/bold cyan]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("關係", width=10)
        table.add_column("標題", max_width=55)
        table.add_column("權重", width=6)
        for r in citation_related:
            title = r["paper"].title[:55] + "..." if len(r["paper"].title) > 55 else r["paper"].title
            table.add_row(r["relation"], title, f"{r['weight']:.0f}")
        console.print(table)
    else:
        console.print("\n[dim]無引用關係資料（請先執行 build-citations）[/dim]")

    if concept_related:
        console.print("\n[bold green]概念共享推薦：[/bold green]")
        table2 = Table(show_header=True, header_style="bold")
        table2.add_column("共享概念數", width=10)
        table2.add_column("標題", max_width=45)
        table2.add_column("共享概念", max_width=30)
        for r in concept_related:
            title = r["paper"].title[:45] + "..." if len(r["paper"].title) > 45 else r["paper"].title
            shared = ", ".join(r["shared_concepts"][:3])
            table2.add_row(str(r["shared_count"]), title, shared)
        console.print(table2)
    else:
        console.print("\n[dim]無概念資料（請先執行 extract-concepts）[/dim]")


def cmd_write_guide(args):
    """生成寫作引用導引"""
    sections = args.sections

    if not sections:
        console.print("[yellow]請提供至少一個段落描述[/yellow]")
        console.print("範例：python main.py write-guide '引言：深度學習背景' '相關工作：現有方法' '方法：模型架構'")
        sys.exit(1)

    errors = validate_config()
    if errors:
        console.print("[yellow]警告：未設定 Gemini API Key，將僅回傳語意搜尋結果（不含 LLM 分析）[/yellow]")

    console.print(Panel.fit(
        f"[bold blue]寫作引用導引[/bold blue]\n"
        f"段落數：{len(sections)}\n"
        f"每段候選：{args.n_candidates} 篇",
        title="SmartPaper-Tagging",
    ))

    service = WritingGuideService()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("分析中...", total=None)

        def progress_callback(section, current, total):
            progress.update(task, description=f"分析 [{current}/{total}] {section[:35]}...")

        guides = service.generate_outline_guide(
            sections=sections,
            n_candidates=args.n_candidates,
            progress_callback=progress_callback,
        )

    console.print()

    for i, guide in enumerate(guides, 1):
        console.print(f"[bold cyan]{'─' * 60}[/bold cyan]")
        console.print(f"[bold]{i}. {guide.section}[/bold]")

        if guide.writing_hint:
            console.print(Panel(guide.writing_hint, border_style="yellow", title="寫作建議"))

        if not guide.citations:
            console.print("[dim]未找到相關論文[/dim]")
            continue

        console.print(f"  [green]建議引用 {len(guide.citations)} 篇論文：[/green]")
        console.print()

        for c in guide.citations:
            title = c.paper.title[:60] + "..." if len(c.paper.title) > 60 else c.paper.title
            console.print(f"  [bold blue]📄 {title}[/bold blue]")
            console.print(f"     引用時機：{c.cite_reason}")
            console.print(f"     引用概念：[cyan]{c.key_concept}[/cyan]")
            console.print(f"     段落位置：[yellow]{c.cite_position}[/yellow]")
            if c.paper.doi:
                console.print(f"     DOI：[dim]{c.paper.doi}[/dim]")
            console.print()

    # 匯出 Markdown
    if args.output:
        output_path = Path(args.output)
        service.export_guide_to_markdown(guides, str(output_path))
        console.print(f"[green]✓ 已匯出到：{output_path}[/green]")


def cmd_ui(args):
    """啟動圖形介面（桌面模式）"""
    try:
        import flet as ft
        from smartpaper.ui.app import main as ui_main

        console.print("[blue]啟動圖形介面...[/blue]")
        ft.app(target=ui_main, view=ft.AppView.FLET_APP)
    except ImportError:
        console.print("[red]錯誤：請先安裝 Flet - pip install flet[/red]")
        sys.exit(1)


def cmd_ui_web(args):
    """啟動圖形介面（Web 瀏覽器模式，用於 Docker 部署）"""
    try:
        import flet as ft
        from smartpaper.ui.app import main as ui_main

        port = int(getattr(args, "port", None) or 8550)
        console.print(f"[blue]啟動 Web 介面，請開啟瀏覽器：http://localhost:{port}[/blue]")
        ft.app(target=ui_main, port=port, view=ft.AppView.WEB_BROWSER)
    except ImportError:
        console.print("[red]錯誤：請先安裝 Flet - pip install flet[/red]")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SmartPaper-Tagging - 智能學術文獻標籤管理系統",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # process 命令
    process_parser = subparsers.add_parser("process", help="處理 XLSX 檔案")
    process_parser.add_argument("file", help="XLSX 檔案路徑")
    process_parser.add_argument("-c", "--column", default="A", help="標題欄位 (預設: A)")
    process_parser.add_argument("--no-tags", dest="tags", action="store_false", help="不自動生成標籤")
    process_parser.add_argument("-f", "--force", action="store_true", help="強制重新處理已存在的論文")
    process_parser.set_defaults(func=cmd_process)

    # search 命令
    search_parser = subparsers.add_parser("search", help="搜尋論文")
    search_parser.add_argument("query", nargs="+", help="搜尋關鍵字")
    search_parser.add_argument("-s", "--semantic", action="store_true", help="使用語義搜尋")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="結果數量限制 (預設: 10)")
    search_parser.set_defaults(func=cmd_search)

    # list 命令
    list_parser = subparsers.add_parser("list", help="列出論文")
    list_parser.add_argument("-t", "--tag", help="根據標籤篩選")
    list_parser.add_argument("-n", "--limit", type=int, default=20, help="顯示數量限制 (預設: 20)")
    list_parser.set_defaults(func=cmd_list)

    # tags 命令
    tags_parser = subparsers.add_parser("tags", help="列出所有標籤")
    tags_parser.set_defaults(func=cmd_tags)

    # stats 命令
    stats_parser = subparsers.add_parser("stats", help="顯示統計資訊")
    stats_parser.set_defaults(func=cmd_stats)

    # export 命令
    export_parser = subparsers.add_parser("export", help="匯出論文到 XLSX")
    export_parser.add_argument("-o", "--output", default="export.xlsx", help="輸出檔案路徑 (預設: export.xlsx)")
    export_parser.set_defaults(func=cmd_export)

    # classify 命令
    classify_parser = subparsers.add_parser("classify", help="根據主題關鍵字分類論文")
    classify_parser.add_argument("topics", nargs="*", help="主題關鍵字 (例如: 'Machine Learning' 'Healthcare')")
    classify_parser.add_argument(
        "-m", "--method",
        choices=["semantic", "two_stage", "llm"],
        default="two_stage",
        help="分類方法: semantic(快速), two_stage(先搜標題再分析摘要,推薦), llm(最精確) (預設: two_stage)"
    )
    classify_parser.add_argument("--no-summary", action="store_true", help="不生成主題總結")
    classify_parser.add_argument("-n", "--limit", type=int, default=10, help="每個主題顯示的論文數量 (預設: 10)")
    classify_parser.add_argument("--show-unclassified", action="store_true", help="顯示未分類的論文")
    classify_parser.add_argument("--show-details", action="store_true", help="顯示每篇論文與主題的關聯摘要（兩階段分類）")
    classify_parser.set_defaults(func=cmd_classify)

    # suggest-topics 命令
    suggest_parser = subparsers.add_parser("suggest-topics", help="根據現有標籤建議分類主題")
    suggest_parser.add_argument("-n", "--num", type=int, default=5, help="建議的主題數量 (預設: 5)")
    suggest_parser.set_defaults(func=cmd_suggest_topics)

    # sort-tags 命令
    sort_parser = subparsers.add_parser("sort-tags", help="根據標籤排序或分組論文")
    sort_parser.add_argument(
        "-s", "--sort",
        choices=["tag_count", "tag_alpha"],
        default="tag_count",
        help="排序方式: tag_count(標籤數量), tag_alpha(字母順序) (預設: tag_count)"
    )
    sort_parser.add_argument("-t", "--tag", help="只顯示包含此標籤的論文")
    sort_parser.add_argument("-g", "--group", action="store_true", help="按標籤分組顯示")
    sort_parser.add_argument("-n", "--limit", type=int, default=10, help="每組顯示的論文數量 (預設: 10)")
    sort_parser.set_defaults(func=cmd_sort_by_tags)

    # export-classify 命令
    export_cls_parser = subparsers.add_parser("export-classify", help="分類論文並匯出報告到 Excel")
    export_cls_parser.add_argument("topics", nargs="*", help="主題關鍵字")
    export_cls_parser.add_argument("-o", "--output", default="classification_report.xlsx", help="輸出檔案路徑")
    export_cls_parser.set_defaults(func=cmd_export_classification)

    # build-citations 命令
    bc_parser = subparsers.add_parser("build-citations", help="從 Semantic Scholar 建立論文引用關係圖")
    bc_parser.add_argument("-f", "--force", action="store_true", help="強制重新取得（包含已有資料的論文）")
    bc_parser.set_defaults(func=cmd_build_citations)

    # extract-concepts 命令
    ec_parser = subparsers.add_parser("extract-concepts", help="用 LLM 萃取論文概念並建立倒排索引")
    ec_parser.add_argument("-f", "--force", action="store_true", help="強制重新萃取（包含已有概念的論文）")
    ec_parser.add_argument("--show-stats", action="store_true", help="顯示概念統計")
    ec_parser.set_defaults(func=cmd_extract_concepts)

    # concept-search 命令
    cs_parser = subparsers.add_parser("concept-search", help="用概念名稱搜尋論文（倒排索引）")
    cs_parser.add_argument("query", nargs="+", help="概念名稱（如 BERT、ImageNet、F1-score）")
    cs_parser.add_argument("-n", "--limit", type=int, default=15, help="結果數量（預設 15）")
    cs_parser.set_defaults(func=cmd_concept_search)

    # related-work 命令
    rw_parser = subparsers.add_parser("related-work", help="為指定論文推薦 Related Work 候選")
    rw_parser.add_argument("paper_id", type=int, help="論文 ID")
    rw_parser.add_argument("-n", "--limit", type=int, default=10, help="推薦數量（預設 10）")
    rw_parser.set_defaults(func=cmd_related_work)

    # write-guide 命令
    wg_parser = subparsers.add_parser("write-guide", help="為寫作大綱各段落生成引用導引")
    wg_parser.add_argument(
        "sections", nargs="+",
        help="段落描述（每個引號為一個段落）"
    )
    wg_parser.add_argument(
        "-n", "--n-candidates", type=int, default=8,
        help="每個段落取的候選論文數量（預設: 8）"
    )
    wg_parser.add_argument(
        "-o", "--output",
        help="匯出 Markdown 的路徑（例如 writing_guide.md）"
    )
    wg_parser.set_defaults(func=cmd_write_guide)

    # ui 命令
    ui_parser = subparsers.add_parser("ui", help="啟動圖形介面（桌面模式）")
    ui_parser.set_defaults(func=cmd_ui)

    # ui-web 命令（Docker 部署用）
    uiw_parser = subparsers.add_parser("ui-web", help="啟動 Web 介面（Docker 部署）")
    uiw_parser.add_argument("--port", type=int, default=8550, help="監聽埠號（預設 8550）")
    uiw_parser.set_defaults(func=cmd_ui_web)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # 執行對應的命令
    args.func(args)


if __name__ == "__main__":
    main()
