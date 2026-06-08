"""
公式語義化轉譯模組

流程：
  PDF 解析後的 chunks → 偵測 LaTeX 公式 → Gemini 批次翻譯成白話文
  → 在 chunk 文字末尾附加 [數學標注]，使向量嵌入能「理解」數學語意

使用方式（由 PDFIngestionService 呼叫）：
    from smartpaper.processing.math_annotator import annotate_chunks
    annotated = annotate_chunks(parse_result.chunks, api_key=GEMINI_API_KEY)
"""

import json
import re
from typing import Optional

MAX_FORMULAS_PER_PAPER = 40   # 每篇論文最多翻譯幾個公式
MAX_FORMULA_LEN = 200         # 超過此長度的公式略過（通常是解析錯誤）
MIN_MATH_CHARS = 5            # 公式至少需有幾個字元才值得翻譯

# ── LaTeX 偵測正則 ────────────────────────────────────────────────────

# $$...$$（顯示公式，優先於 $...$）
_RE_DISPLAY = re.compile(r'\$\$(.+?)\$\$', re.DOTALL)
# $...$ 行內公式
_RE_INLINE = re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)')
# \begin{equation/align/gather/eqnarray}...\end{...}
_RE_ENV = re.compile(
    r'\\begin\{(equation|align|gather|eqnarray)\*?\}'
    r'(.+?)'
    r'\\end\{\1\*?\}',
    re.DOTALL | re.IGNORECASE,
)
# 獨立的 \mathbf{...} \frac{...}{...} 等（非公式區塊內但含數學命令）
_RE_CMD = re.compile(
    r'\\(?:mathbf|mathit|mathcal|mathrm|mathbb|frac|sum|prod|int|lim|sqrt'
    r'|alpha|beta|gamma|delta|epsilon|theta|lambda|mu|sigma|omega|phi|psi|tau|eta|xi|rho|pi'
    r'|nabla|partial|infty|forall|exists|rightarrow|leftarrow|Rightarrow|Leftrightarrow'
    r'|leq|geq|neq|approx|propto|sim)'
    r'(?:\{[^}]*\})?',
)

# 判斷是否為「數學論文」的簡易評分
_MATH_SIGNALS = re.compile(
    r'(\$|\\\(|\\\[|\\begin\{|\\alpha|\\beta|\\sum|\\int|\\frac|\\mathbf|\\nabla'
    r'|\\theta|\\sigma|\\lambda|\\mu|\\epsilon)'
)


def math_density(text: str) -> float:
    """
    回傳文字中數學符號的密度（0~1）。
    > 0.01 表示有顯著數學內容。
    """
    if not text:
        return 0.0
    hits = len(_MATH_SIGNALS.findall(text))
    return hits / max(len(text) / 10, 1)


def extract_formulas(text: str) -> list[str]:
    """
    從文字中抽出所有 LaTeX 公式字串（已去重、排除過短/過長）。
    回傳順序大致依出現順序。
    """
    seen: set[str] = set()
    results: list[str] = []

    def _add(formula: str) -> None:
        f = formula.strip()
        if not f or len(f) < MIN_MATH_CHARS or len(f) > MAX_FORMULA_LEN:
            return
        if f not in seen:
            seen.add(f)
            results.append(f)

    for m in _RE_DISPLAY.finditer(text):
        _add(m.group(1))
    for m in _RE_ENV.finditer(text):
        _add(m.group(2))
    for m in _RE_INLINE.finditer(text):
        _add(m.group(1))

    return results


def _build_prompt(formulas: list[str]) -> str:
    numbered = "\n".join(f"{i+1}. {f}" for i, f in enumerate(formulas))
    return f"""以下是學術論文中出現的 LaTeX 數學公式。
請對每一個公式，用一句繁體中文白話說明「這個公式在描述什麼概念或操作」。
目標讀者是不熟悉數學符號的人，說明需讓人理解語意（15-35 字即可，勿逐字翻譯符號）。

公式列表：
{numbered}

請以 JSON 格式回傳，格式如下（保持 formulas 陣列與輸入順序相同）：
{{
  "formulas": [
    {{"index": 1, "latex": "...", "description": "..."}},
    ...
  ]
}}

只回傳 JSON，不要有任何其他文字。"""


def _call_gemini(formulas: list[str], api_key: str, model: str) -> dict[str, str]:
    """
    呼叫 Gemini 批次翻譯公式。
    回傳 {latex_string: description_string}，失敗時回傳空 dict。
    """
    try:
        from google import genai as _genai
        from ..api._retry import gemini_call_with_retry

        client = _genai.Client(api_key=api_key)
        prompt = _build_prompt(formulas)

        resp = gemini_call_with_retry(
            lambda: client.models.generate_content(model=model, contents=prompt)
        )
        raw = resp.text.strip()

        # 去除 markdown 程式碼區塊
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        data = json.loads(raw.strip())
        items = data.get("formulas", [])
        return {item["latex"].strip(): item["description"].strip() for item in items
                if "latex" in item and "description" in item}

    except Exception as e:
        print(f"[MathAnnotator] Gemini 翻譯失敗，跳過公式標注：{e}")
        return {}


def annotate_chunks(
    chunks,                           # list[ParsedChunk]（直接修改 .text 欄位）
    api_key: str,
    model: str = "gemini-2.0-flash",
    progress_callback=None,
) -> int:
    """
    偵測 chunks 中的 LaTeX 公式，呼叫 Gemini 批次翻譯，
    並將標注附加到每個含公式的 chunk 文字末尾。

    Args:
        chunks:            ParsedChunk 列表（in-place 修改）
        api_key:           Gemini API Key
        model:             Gemini 模型名稱
        progress_callback: 進度回呼 callback(msg: str)

    Returns:
        實際被標注的 chunk 數量（0 表示論文無數學內容）
    """
    def _prog(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    # ── 1. 收集每個 chunk 的公式（保留 chunk index）─────────────────
    chunk_formulas: list[list[str]] = []   # chunk_formulas[i] = 該 chunk 的公式列表
    all_unique: list[str] = []
    unique_set: set[str] = set()

    for chunk in chunks:
        fmls = extract_formulas(chunk.text)
        chunk_formulas.append(fmls)
        for f in fmls:
            if f not in unique_set:
                unique_set.add(f)
                all_unique.append(f)

    if not all_unique:
        return 0   # 論文無數學公式，不呼叫 Gemini

    # 截斷避免超長 prompt
    if len(all_unique) > MAX_FORMULAS_PER_PAPER:
        all_unique = all_unique[:MAX_FORMULAS_PER_PAPER]

    _prog(f"偵測到 {len(all_unique)} 個數學公式，呼叫 Gemini 翻譯...")

    # ── 2. Gemini 批次翻譯 ───────────────────────────────────────────
    translations = _call_gemini(all_unique, api_key=api_key, model=model)
    if not translations:
        return 0

    _prog(f"翻譯完成（{len(translations)}/{len(all_unique)} 個公式）")

    # ── 3. 將標注注入 chunk 文字 ─────────────────────────────────────
    annotated_count = 0
    for chunk, fmls in zip(chunks, chunk_formulas):
        lines = []
        for f in fmls:
            if f in translations and f in all_unique:  # 只用有翻譯的
                lines.append(f"• {f} → {translations[f]}")
        if lines:
            chunk.text = chunk.text.rstrip() + "\n\n[數學標注]\n" + "\n".join(lines)
            annotated_count += 1

    return annotated_count
