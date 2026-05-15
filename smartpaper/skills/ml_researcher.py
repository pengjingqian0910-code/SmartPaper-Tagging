from .base_skill import SkillConfig

ML_RESEARCHER = SkillConfig(
    id="ml_researcher",
    name="機器學習研究員",
    description="專精於 ML/DL/NLP/CV，從模型架構與實驗結果角度分析論文",
    system_prompt=(
        "你是一位 NeurIPS、ICML、ACL、CVPR 等頂會審稿人等級的機器學習研究員。"
        "你對模型架構設計、訓練技巧、評測方法、SOTA 比較有深入理解，"
        "能精確判斷一篇論文的技術創新性與研究嚴謹度。"
    ),
    tag_categories=[
        "Transformer", "Attention Mechanism", "Large Language Model", "BERT", "GPT",
        "Reinforcement Learning", "Generative Model", "GAN", "Diffusion Model",
        "Few-shot Learning", "Transfer Learning", "Self-supervised Learning",
        "Graph Neural Network", "Contrastive Learning", "Prompt Engineering",
        "Multimodal", "Benchmark", "Efficiency", "Interpretability",
    ],
    classification_criteria=(
        "1. 論文是否提出新的模型架構、訓練方法或學習策略\n"
        "2. 論文是否在公認 benchmark 上有嚴謹的實驗結果與比較\n"
        "3. 論文的核心問題是否屬於 ML/DL/NLP/CV 的研究範疇\n"
        "注意：應用 ML 解決其他領域問題（如醫療影像）也算相關，"
        "但重點應在 ML 方法本身而非應用領域"
    ),
    summary_style=(
        "請從以下三個角度分析：\n"
        "【核心創新】提出了什麼新的模型架構或訓練方法？解決了什麼技術難題？\n"
        "【實驗驗證】在哪些 benchmark 上測試？與 SOTA 相比有多少提升？\n"
        "【影響與局限】這項研究的潛在影響是什麼？有哪些已知局限？"
    ),
)
