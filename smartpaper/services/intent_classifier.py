"""
意圖分類器 — 三層分類策略

意圖類別：
  qa       → 問答、查詢知識（→ Classic RAG，安全預設）
  action   → 明確操作指令（→ Function Calling，需高信心才觸發）
  chitchat → 閒聊問候（→ 直接回應，完全跳過 RAG）

分層策略（由快到慢）：
  Layer 1: 正則規則比對（~0.01 ms，無 API 呼叫）→ 高信心直接回傳
  Layer 2: 長度 / 標點啟發式（~0.01 ms）
  Layer 3: LLM 確認（~500 ms，opt-in）→ 僅在規則不確定時呼叫

設計原則：
  - 預設傾向 qa（寧可多跑 RAG，也不誤觸 action）
  - action 門檻設高（conf ≥ 0.75 才切換 FC 模式）
  - chitchat 門檻設低（確認閒聊就跳過 RAG，省資源）
"""

from __future__ import annotations

import re
from typing import Literal, Optional

IntentType = Literal["qa", "action", "chitchat"]


# ── 高信心動作指令模式 ─────────────────────────────────────────────────
_ACTION_PATTERNS = [
    # 加入 / 匯入
    r"(幫我|請|麻煩).{0,6}(加入|新增|匯入|儲存|加到|放入)",
    r"(加入|新增|匯入|加到)(文獻庫|資料庫|書庫|系統|paper)",
    r"把.{0,15}(加|存|匯入)(進|到|入|去)",
    # 刪除 / 更新
    r"(刪除|移除|清除|刪掉).{0,10}(論文|文獻|paper|這篇|這個)",
    r"(更新|修改|編輯).{0,10}(標籤|資訊|metadata)",
    # 明確搜尋指令（帶「幫我」）
    r"幫我(搜尋|找出|查詢|列出|顯示).{0,20}(論文|文獻|paper)",
    # 匯出 / 下載
    r"(匯出|export|下載|輸出).{0,10}(bibtex|ris|excel|csv|論文|文獻)",
    # 標籤操作
    r"(幫我|請).{0,6}(自動|重新)?(標籤|tagging|tag)",
]

# ── 高信心問答模式 ─────────────────────────────────────────────────────
_QA_PATTERNS = [
    # 疑問詞開頭
    r"^(什麼是|什麼叫|為什麼|如何|怎樣|怎麼|何謂|哪些|哪篇|有哪|有沒有)",
    # 解釋 / 說明
    r"(解釋|說明|介紹|描述|闡述)(一下|一些|給我)?",
    # 比較
    r"(比較|差異|區別|不同|優缺點|pros|cons)",
    # 論文相關提問
    r"(論文|文獻|paper|研究|study)(說|顯示|指出|發現|提出|提到|提及|認為)",
    r"(這篇|這些|它們).{0,10}(說|講|提到|認為|結論)",
    r"(方法|結果|結論|實驗|摘要|abstract|method|result).{0,10}(是什麼|說什麼|如何|怎樣)",
    # 學術問句
    r"(請問|想知道|想了解|想請問)",
    r"(研究|實驗|模型).{0,10}(表現|效果|準確|性能|performance)",
]

# ── 高信心閒聊模式 ─────────────────────────────────────────────────────
_CHITCHAT_PATTERNS = [
    r"^(你好|嗨|hi|hello|哈囉|hey|早安|午安|晚安)[!！。\s]*$",
    r"^(謝謝|感謝|多謝|thank[s]?)[!！。\s,，你]*$",
    r"^(好的|ok|okay|好|嗯|了解|明白|收到)[!！。\s]*$",
    r"^(再見|拜拜|bye|掰掰)[!！。\s]*$",
    r"你(是誰|叫什麼名字|是什麼|可以做什麼)",
    r"^(哈哈|呵呵|嘻嘻|lol)[!！。\s]*$",
]

_RE_ACTION  = [re.compile(p, re.IGNORECASE) for p in _ACTION_PATTERNS]
_RE_QA      = [re.compile(p, re.IGNORECASE) for p in _QA_PATTERNS]
_RE_CHAT    = [re.compile(p, re.IGNORECASE) for p in _CHITCHAT_PATTERNS]


class IntentClassifier:
    """
    快速三層意圖分類器。

    使用範例：
        clf = IntentClassifier()
        intent, conf = clf.classify("幫我把這篇論文加入文獻庫")
        # → ("action", 0.90)

        intent, conf = clf.classify("deep learning 在醫療影像的應用是什麼？")
        # → ("qa", 0.83)
    """

    def __init__(self, use_llm_fallback: bool = False):
        self._use_llm = use_llm_fallback

    def classify(self, text: str) -> tuple[IntentType, float]:
        """
        回傳 (intent, confidence)。
        confidence: 0.0–1.0，越高越確定。
        """
        text = text.strip()
        if not text:
            return "chitchat", 1.0

        # ── Layer 1: 閒聊快速閘門 ────────────────────────────────────
        if any(r.search(text) for r in _RE_CHAT):
            return "chitchat", 0.95

        # ── Layer 1: 規則計分 ─────────────────────────────────────────
        action_hits = sum(1 for r in _RE_ACTION if r.search(text))
        qa_hits     = sum(1 for r in _RE_QA     if r.search(text))

        # 明確 action（幫我操作 / 動詞指令）
        if action_hits >= 2:
            return "action", min(0.75 + action_hits * 0.05, 0.95)
        if action_hits == 1 and qa_hits == 0:
            return "action", 0.78

        # 明確問句
        if qa_hits >= 2:
            return "qa", min(0.72 + qa_hits * 0.06, 0.95)
        if qa_hits == 1:
            return "qa", 0.70

        # 混合情況（既有 action 又有 qa 模式）
        if action_hits >= 1 and qa_hits >= 1:
            # 更傾向 qa，避免誤觸 FC
            return "qa", 0.62

        # ── Layer 2: 啟發式輔助 ───────────────────────────────────────
        # 問號結尾 → 強烈問句訊號
        if text.endswith("?") or text.endswith("？"):
            return "qa", 0.65

        # 短句（< 8 字）且無問號 → 可能是動作指令或閒聊
        if len(text) < 8:
            return "qa", 0.55

        # ── Layer 3: LLM fallback（opt-in）──────────────────────────
        if self._use_llm:
            llm_intent = self._llm_classify(text)
            if llm_intent:
                return llm_intent, 0.82

        # ── 預設：qa（最保守的選擇）────────────────────────────────
        return "qa", 0.55

    def _llm_classify(self, text: str) -> Optional[IntentType]:
        """LLM 意圖分類（備用，不影響主路徑效能）"""
        try:
            from ..api.gemini import GeminiTagger
            gemini = GeminiTagger()
            prompt = (
                "請將以下用戶訊息分類為三類之一（只回傳一個詞）：\n"
                "- qa：用戶在詢問知識或論文內容\n"
                "- action：用戶在發出明確操作指令（如加入/刪除/搜尋論文）\n"
                "- chitchat：閒聊或問候\n\n"
                f"用戶訊息：「{text}」\n\n"
                "只回傳 qa、action 或 chitchat 之一，不要其他文字。"
            )
            resp = gemini.client.models.generate_content(
                model=gemini.model_name, contents=prompt
            )
            word = resp.text.strip().lower()
            if word in ("qa", "action", "chitchat"):
                return word  # type: ignore[return-value]
        except Exception:
            pass
        return None

    # ── 便利方法 ────────────────────────────────────────────────────────

    def needs_rag(self, text: str) -> bool:
        """是否需要 RAG 檢索（qa 或 action 都需要）"""
        intent, _ = self.classify(text)
        return intent != "chitchat"

    def needs_fc(self, text: str) -> bool:
        """是否達到啟動 Function Calling 的門檻（action + 高信心）"""
        intent, conf = self.classify(text)
        return intent == "action" and conf >= 0.75

    def label(self, text: str) -> str:
        """回傳人類可讀標籤，用於 UI 顯示。"""
        intent, conf = self.classify(text)
        icon = {"qa": "🔍", "action": "⚡", "chitchat": "💬"}.get(intent, "")
        label = {"qa": "問答", "action": "操作指令", "chitchat": "閒聊"}.get(intent, intent)
        return f"{icon} {label} ({conf:.0%})"
