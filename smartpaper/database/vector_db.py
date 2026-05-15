"""
ChromaDB 向量資料庫操作模組
處理論文摘要的向量化存儲與語義搜尋
"""

from typing import Optional
import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from ..config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION, EMBEDDING_MODEL
from ..models import Paper, SearchResult

FULLTEXT_COLLECTION = "papers_fulltext"


class VectorDB:
    """ChromaDB 向量資料庫管理類"""

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        """
        初始化 ChromaDB 連接

        Args:
            persist_dir: 持久化目錄路徑
            collection_name: 集合名稱
        """
        persist_dir = persist_dir or str(CHROMA_PERSIST_DIR)
        collection_name = collection_name or CHROMA_COLLECTION

        # 初始化 ChromaDB 客戶端 (使用本地持久化存儲)
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )

        # 使用 allenai-specter 學術領域專用嵌入模型
        embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL,
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
            metadata={"description": "SmartPaper academic paper abstracts"},
        )

        # 全文 chunk collection（獨立，避免壓過摘要搜尋）
        self.fulltext_collection = self.client.get_or_create_collection(
            name=FULLTEXT_COLLECTION,
            embedding_function=embedding_fn,
            metadata={"description": "SmartPaper PDF fulltext chunks"},
        )

    def add(self, paper_id: int, abstract: str, metadata: Optional[dict] = None) -> None:
        """
        新增論文摘要向量

        Args:
            paper_id: 論文 ID (SQLite 中的 ID)
            abstract: 論文摘要文字
            metadata: 額外的 metadata
        """
        if not abstract or not abstract.strip():
            return

        doc_id = f"paper_{paper_id}"
        meta = metadata or {}
        meta["paper_id"] = paper_id

        # 檢查是否已存在
        existing = self.collection.get(ids=[doc_id])
        if existing and existing["ids"]:
            # 更新現有文檔
            self.collection.update(
                ids=[doc_id],
                documents=[abstract],
                metadatas=[meta],
            )
        else:
            # 新增文檔
            self.collection.add(
                ids=[doc_id],
                documents=[abstract],
                metadatas=[meta],
            )

    def search(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        語義搜尋

        Args:
            query: 搜尋查詢文字
            n_results: 回傳結果數量
            where: 過濾條件

        Returns:
            搜尋結果清單，包含 paper_id, distance, metadata
        """
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )

        search_results = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                paper_id = int(doc_id.replace("paper_", ""))
                distance = results["distances"][0][i] if results["distances"] else 0
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                document = results["documents"][0][i] if results["documents"] else ""

                # 將距離轉換為相似度分數 (0-1，越高越相似)
                # ChromaDB 預設使用 L2 距離，需要轉換
                score = 1 / (1 + distance)

                search_results.append({
                    "paper_id": paper_id,
                    "score": score,
                    "distance": distance,
                    "metadata": metadata,
                    "document": document,
                })

        return search_results

    def delete(self, paper_id: int) -> None:
        """
        刪除論文向量

        Args:
            paper_id: 論文 ID
        """
        doc_id = f"paper_{paper_id}"
        try:
            self.collection.delete(ids=[doc_id])
        except Exception:
            pass  # 如果不存在則忽略

    def count(self) -> int:
        """取得向量資料庫中的文檔數量"""
        return self.collection.count()

    def clear(self) -> None:
        """清空集合中的所有資料"""
        # 取得所有 ID
        all_data = self.collection.get()
        if all_data and all_data["ids"]:
            self.collection.delete(ids=all_data["ids"])

    # ── Fulltext chunk 方法 ────────────────────────────────────────────────

    def add_chunks_batch(
        self,
        paper_id: int,
        chunks: list[dict],
        batch_size: int = 64,
    ) -> None:
        """
        批次新增全文 chunks（比逐個 add 快 10-20x）。

        chunks: list of {chunk_index, chunk_text, section, page_num, is_table}
        """
        valid = [c for c in chunks if c.get("chunk_text", "").strip()]
        if not valid:
            return

        for start in range(0, len(valid), batch_size):
            batch = valid[start: start + batch_size]
            ids = [f"chunk_{paper_id}_{c['chunk_index']}" for c in batch]
            docs = [c["chunk_text"] for c in batch]
            metas = [
                {
                    "paper_id": paper_id,
                    "section": c["section"],
                    "chunk_index": c["chunk_index"],
                    "page_num": c.get("page_num") or 0,
                    "is_table": 1 if c.get("is_table") else 0,
                    "section_type": c.get("section_type", "other"),
                    "importance_weight": float(c.get("importance_weight", 1.0)),
                }
                for c in batch
            ]
            self.fulltext_collection.add(ids=ids, documents=docs, metadatas=metas)

    def add_chunk(
        self,
        paper_id: int,
        chunk_index: int,
        chunk_text: str,
        section: str,
        page_num: Optional[int] = None,
        is_table: bool = False,
    ) -> None:
        """單筆新增（向下相容保留，新程式請用 add_chunks_batch）"""
        self.add_chunks_batch(paper_id, [{
            "chunk_index": chunk_index,
            "chunk_text": chunk_text,
            "section": section,
            "page_num": page_num,
            "is_table": is_table,
        }])

    def search_chunks(
        self,
        query: str,
        n_results: int = 15,
        paper_id_filter: Optional[list[int]] = None,
    ) -> list[dict]:
        """
        搜尋全文 chunks，回傳 list of dict：
        {paper_id, section, chunk_index, page_num, is_table, chunk_text, score}
        """
        total = self.fulltext_collection.count()
        if total == 0:
            return []
        n = min(n_results, total)

        where = None
        if paper_id_filter:
            where = {"paper_id": {"$in": paper_id_filter}}

        try:
            results = self.fulltext_collection.query(
                query_texts=[query],
                n_results=n,
                where=where,
            )
        except Exception:
            return []

        out = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0
                doc = results["documents"][0][i] if results["documents"] else ""
                out.append({
                    "paper_id": meta.get("paper_id"),
                    "section": meta.get("section", ""),
                    "section_type": meta.get("section_type", "other"),
                    "importance_weight": float(meta.get("importance_weight", 1.0)),
                    "chunk_index": meta.get("chunk_index", 0),
                    "page_num": meta.get("page_num", 0),
                    "is_table": bool(meta.get("is_table", 0)),
                    "chunk_text": doc,
                    "score": 1 / (1 + distance),
                })
        return out

    def delete_chunks_by_paper(self, paper_id: int) -> None:
        """刪除某篇論文的所有全文 chunks"""
        try:
            all_ids = self.fulltext_collection.get(
                where={"paper_id": paper_id}
            )
            if all_ids and all_ids["ids"]:
                self.fulltext_collection.delete(ids=all_ids["ids"])
        except Exception:
            pass

    def has_fulltext(self, paper_id: int) -> bool:
        """該論文是否已有全文向量"""
        try:
            results = self.fulltext_collection.get(
                where={"paper_id": paper_id}, limit=1
            )
            return bool(results and results["ids"])
        except Exception:
            return False

    def fulltext_chunk_count(self, paper_id: int) -> int:
        """回傳某篇論文的全文 chunk 數量"""
        try:
            results = self.fulltext_collection.get(where={"paper_id": paper_id})
            return len(results["ids"]) if results and results["ids"] else 0
        except Exception:
            return 0

    def get_by_paper_id(self, paper_id: int) -> Optional[dict]:
        """
        根據論文 ID 取得向量資料

        Args:
            paper_id: 論文 ID

        Returns:
            向量資料或 None
        """
        doc_id = f"paper_{paper_id}"
        result = self.collection.get(ids=[doc_id], include=["documents", "metadatas"])

        if result and result["ids"]:
            return {
                "paper_id": paper_id,
                "document": result["documents"][0] if result["documents"] else None,
                "metadata": result["metadatas"][0] if result["metadatas"] else None,
            }
        return None
