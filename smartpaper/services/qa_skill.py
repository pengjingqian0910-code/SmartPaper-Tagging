"""
QA Skill：對話記憶萃取器

用已載入的 sentence-transformers（allenai/specter）對每輪問答做
extractive summarization，找出最具代表性的句子存入 ConversationMemory。

萃取流程：
1. 把 answer 切成句子
2. 用 bi-encoder embed 所有句子（複用 allenai/specter，不新增依賴）
3. 計算 centroid（所有 sentence embedding 的平均向量）
4. 每句 score = cos_sim(sentence, centroid) × entity_boost × length_factor
5. Top-2 句 → MemoryEntry，importance 由 score 決定

衡量指標：
- 語意中心度（cosine similarity to centroid）：代表性高
- 實體加成（數字、年份、%、論文關鍵詞）：重要事實更重要
- 長度懲罰（過短 < 15 char 或過長 > 300 char 的句子扣分）
"""

import re
import threading
from typing import Optional, TYPE_CHECKING

import numpy as np

from .conversation_memory import ConversationMemory, MemoryEntry

if TYPE_CHECKING:
    from .qa_service import SourceChunk

# 來自 sources 的論文關鍵詞（用於 entity boost）
_ENTITY_PATTERNS = [
    (r"\b\d{4}\b", 0.15),               # 年份
    (r"\d+\.?\d*\s*%", 0.20),           # 百分比
    (r"\b(accuracy|f1|bleu|rouge|mrr|ndcg|recall|precision)\b", 0.15),  # 指標
    (r"\b(transformer|bert|gpt|llm|cnn|rnn|attention|embedding)\b", 0.10),  # 常見模型
    (r"[「」『』\"'].{5,60}[「」『』\"']", 0.20),  # 引號包住的詞（論文名/概念）
    (r"\d+\s*(篇|個|種|層|億|萬)", 0.10),  # 中文數量詞
]

# paraphrase-multilingual 對對話句子的語意捕捉比 specter（學術引用訓練）好很多
# 支援中英混合，420MB，首次使用時自動下載
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
TOP_SENTENCES = 2       # 每輪萃取幾句
MIN_SENTENCE_LEN = 15   # 句子最少字元
MAX_SENTENCE_LEN = 280  # 句子最多字元


class ConversationSkill:
    """
    對話技能：從 Q&A 萃取記憶，非同步寫入 ConversationMemory。

    使用方式：
        skill = ConversationSkill()
        skill.extract_async(turn, question, answer, sources, memory)
        # extract_async 在背景執行，不阻塞回答顯示
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self._model_name = model_name
        self._model = None           # 延遲載入
        self._lock = threading.Lock()

    @property
    def model(self):
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
        return self._model

    # ── 公開方法 ──────────────────────────────────────────────────────

    def extract_async(
        self,
        turn: int,
        question: str,
        answer: str,
        sources: "list[SourceChunk]",
        memory: ConversationMemory,
    ) -> None:
        """非同步在背景執行萃取，不阻塞主執行緒"""
        t = threading.Thread(
            target=self._extract_and_store,
            args=(turn, question, answer, sources, memory),
            daemon=True,
        )
        t.start()

    def extract_sync(
        self,
        turn: int,
        question: str,
        answer: str,
        sources: "list[SourceChunk]",
        memory: ConversationMemory,
    ) -> list[MemoryEntry]:
        """同步版本（測試用）"""
        return self._extract_and_store(turn, question, answer, sources, memory)

    # ── 私有方法 ──────────────────────────────────────────────────────

    def _extract_and_store(
        self,
        turn: int,
        question: str,
        answer: str,
        sources: "list[SourceChunk]",
        memory: ConversationMemory,
    ) -> list[MemoryEntry]:
        paper_ids = list({sc.paper.id for sc in sources if sc.paper.id})
        sentences = _split_sentences(answer)
        sentences = [s for s in sentences if MIN_SENTENCE_LEN <= len(s) <= MAX_SENTENCE_LEN]

        if not sentences:
            # fallback：問題本身作為記憶
            entry = MemoryEntry(
                content=question[:200],
                importance=0.4,
                turn=turn,
                paper_ids=paper_ids,
            )
            memory.add_entries([entry])
            return [entry]

        try:
            entries = self._score_and_pick(sentences, turn, paper_ids)
        except Exception as e:
            print(f"[QASkill] embedding 失敗，退回規則式: {e}")
            entries = _rule_fallback(sentences, turn, paper_ids)

        memory.add_entries(entries)
        return entries

    def _score_and_pick(
        self,
        sentences: list[str],
        turn: int,
        paper_ids: list[int],
    ) -> list[MemoryEntry]:
        # 1. Embed（使用已載入的 specter 模型）
        embeddings = self.model.encode(sentences, convert_to_numpy=True,
                                       show_progress_bar=False, normalize_embeddings=True)

        # 2. Centroid（語意中心）
        centroid = embeddings.mean(axis=0)
        centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-9)

        # 3. 每句評分
        scored = []
        for i, (sent, emb) in enumerate(zip(sentences, embeddings)):
            cos_sim = float(np.dot(emb, centroid_norm))      # 語意中心度 0~1
            entity_boost = _entity_score(sent)                # 0~0.8
            length_factor = _length_factor(sent)              # 0.5~1.0
            score = cos_sim * (1.0 + entity_boost) * length_factor
            scored.append((score, sent))

        # 4. 取 Top-N，去重（避免連續重複句子）
        scored.sort(key=lambda x: -x[0])
        picked: list[MemoryEntry] = []
        seen_prefixes: set[str] = set()
        for score, sent in scored:
            prefix = sent[:30]
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            # importance = score clipped to [0.2, 1.0]
            importance = min(1.0, max(0.2, score))
            picked.append(MemoryEntry(
                content=sent.strip(),
                importance=importance,
                turn=turn,
                paper_ids=paper_ids,
            ))
            if len(picked) >= TOP_SENTENCES:
                break

        return picked if picked else _rule_fallback(sentences, turn, paper_ids)


# ── 工具函數 ──────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """切句：中英文標點都處理"""
    # 先用標點切，再過濾
    parts = re.split(r"(?<=[。！？.!?])\s*|(?<=\n)\s*", text)
    result = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # 長句再切（逗號分割，保留前半）
        if len(p) > MAX_SENTENCE_LEN:
            sub = re.split(r"[，,；;]", p)
            result.extend(s.strip() for s in sub if s.strip())
        else:
            result.append(p)
    return result


def _entity_score(sentence: str) -> float:
    """實體偵測加成，回傳 0.0~0.8"""
    total = 0.0
    s_lower = sentence.lower()
    for pattern, boost in _ENTITY_PATTERNS:
        if re.search(pattern, s_lower):
            total += boost
    return min(0.8, total)


def _length_factor(sentence: str) -> float:
    """長度因子：太短或太長都扣分，30~150 字最佳"""
    n = len(sentence)
    if n < 20:
        return 0.5
    if n < 30:
        return 0.75
    if n <= 150:
        return 1.0
    if n <= 220:
        return 0.85
    return 0.65


def _rule_fallback(
    sentences: list[str],
    turn: int,
    paper_ids: list[int],
) -> list[MemoryEntry]:
    """純規則式 fallback：按長度 + 實體分數排序"""
    scored = [((_entity_score(s) + _length_factor(s)), s) for s in sentences]
    scored.sort(key=lambda x: -x[0])
    return [
        MemoryEntry(
            content=s.strip(),
            importance=min(1.0, max(0.2, sc * 0.5)),
            turn=turn,
            paper_ids=paper_ids,
        )
        for sc, s in scored[:TOP_SENTENCES]
    ]
