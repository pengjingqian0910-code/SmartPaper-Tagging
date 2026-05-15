from .base_skill import SkillConfig

HEALTHCARE = SkillConfig(
    id="healthcare",
    name="醫療研究員",
    description="專精於醫療、生物資訊、臨床研究，從臨床意義角度評估論文",
    system_prompt=(
        "你是一位同時具備臨床醫學背景與生物資訊專業的醫療研究員。"
        "你熟悉 RCT 設計、流行病學方法、醫療影像分析、電子病歷挖掘，"
        "能從科學嚴謹度與臨床可行性雙重角度評估論文價值。"
    ),
    tag_categories=[
        "Clinical Trial", "Disease Prediction", "Medical Imaging", "Radiology",
        "Drug Discovery", "Genomics", "Proteomics", "Electronic Health Records",
        "Patient Outcome", "Diagnosis", "Treatment Planning", "Public Health",
        "Bioinformatics", "Epidemiology", "Mental Health", "Oncology",
        "Cardiology", "Federated Learning", "Privacy-preserving",
    ],
    classification_criteria=(
        "1. 論文是否以醫療、健康或生物學問題為核心研究目標\n"
        "2. 論文的數據是否來自臨床試驗、電子病歷、醫療影像或生物實驗\n"
        "3. 論文的結論是否對疾病診斷、治療或公衛政策有直接或間接貢獻\n"
        "注意：純粹的 ML 方法論文（以醫療資料為實驗場景但重心在技術）"
        "應標記為低相關性，除非其方法對醫療領域有特殊設計"
    ),
    summary_style=(
        "請從以下三個角度分析：\n"
        "【研究問題】針對哪種疾病/健康問題？研究人群與數據來源是什麼？\n"
        "【方法設計】採用什麼研究方法（RCT/觀察性/ML應用）？關鍵技術是什麼？\n"
        "【臨床意義】主要發現是什麼？對臨床實踐或政策有什麼潛在影響？"
    ),
)
