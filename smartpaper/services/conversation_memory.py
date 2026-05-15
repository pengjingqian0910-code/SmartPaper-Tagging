"""
對話記憶模組（Episodic Memory for QA）

架構：
- MemoryEntry：一條記憶（內容 + 重要性 + 輪次 + 關聯論文）
- ConversationMemory：記憶庫，管理衰減排序與查詢
- 衰減公式：effective_score = importance × exp(−0.25 × age_turns)
"""

import math
import re
from dataclasses import dataclass, field
from typing import Optional


DECAY_RATE = 0.25      # 每輪衰減率（~3輪後分數減半）
MAX_ENTRIES = 40       # 最多保留記憶條數
TOP_K_INJECT = 4       # 每次注入 prompt 的記憶條數


@dataclass
class MemoryEntry:
    content: str                        # 萃取出的關鍵句
    importance: float                   # 0.0~1.0，由提取時評分
    turn: int                           # 第幾輪對話產生
    paper_ids: list[int] = field(default_factory=list)  # 關聯論文

    def effective_score(self, current_turn: int) -> float:
        age = max(0, current_turn - self.turn)
        return self.importance * math.exp(-DECAY_RATE * age)


class ConversationMemory:
    """
    對話記憶庫。

    使用方式：
        memory = ConversationMemory()
        memory.add_entries([...])           # 每輪回答後加入
        top = memory.get_top_k(turn, q)    # 查詢時取最相關記憶
        prompt_text = memory.to_prompt(top) # 格式化成 prompt 片段
    """

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries: list[MemoryEntry] = []
        self.max_entries = max_entries
        self.current_turn: int = 0

    # ── 寫入 ──────────────────────────────────────────────────────────

    def next_turn(self) -> int:
        self.current_turn += 1
        return self.current_turn

    def add_entries(self, entries: list[MemoryEntry]) -> None:
        self._entries.extend(entries)
        self._prune()

    def clear(self) -> None:
        self._entries.clear()
        self.current_turn = 0

    # ── 查詢 ──────────────────────────────────────────────────────────

    def get_top_k(
        self,
        query: str = "",
        k: int = TOP_K_INJECT,
    ) -> list[MemoryEntry]:
        if not self._entries:
            return []
        query_tokens = _tokenize(query)
        scored = []
        for entry in self._entries:
            decay_score = entry.effective_score(self.current_turn)
            overlap = _keyword_overlap(query_tokens, _tokenize(entry.content))
            # 加權：衰減 × (1 + 語意重疊加成)
            final = decay_score * (1.0 + 0.5 * overlap)
            scored.append((final, entry))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:k]]

    def to_prompt(self, entries: list[MemoryEntry]) -> str:
        if not entries:
            return ""
        lines = [f"  • {e.content}" for e in entries]
        return "【對話記憶（之前討論過的重點）】\n" + "\n".join(lines)

    def has_memory(self) -> bool:
        return bool(self._entries)

    # ── 私有 ──────────────────────────────────────────────────────────

    def _prune(self) -> None:
        if len(self._entries) <= self.max_entries:
            return
        # 依目前輪次的 effective_score 淘汰最低分
        self._entries.sort(
            key=lambda e: e.effective_score(self.current_turn),
            reverse=True,
        )
        self._entries = self._entries[:self.max_entries]


# ── 工具函數 ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """簡單分詞（英文 lowercase，中文單字）"""
    text = text.lower()
    en_words = set(re.findall(r"[a-z]+", text))
    zh_chars = set(re.findall(r"[一-鿿]", text))
    # 過濾停用詞
    stopwords = {"the", "a", "an", "is", "in", "of", "to", "and", "or",
                 "that", "this", "for", "with", "on", "at", "by", "are",
                 "was", "were", "been", "be", "have", "has", "had", "do"}
    return (en_words - stopwords) | zh_chars


def _keyword_overlap(q_tokens: set[str], m_tokens: set[str]) -> float:
    """Jaccard-style overlap，回傳 0.0~1.0"""
    if not q_tokens or not m_tokens:
        return 0.0
    intersection = len(q_tokens & m_tokens)
    union = len(q_tokens | m_tokens)
    return intersection / union if union else 0.0
