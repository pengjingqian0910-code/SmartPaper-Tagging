"""
共用 fixtures — 所有測試共享
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from smartpaper.models import Paper
from smartpaper.database.sqlite_db import SQLiteDB
from smartpaper.database.chunk_store import ChunkStore


# ── 基本資料 fixtures ─────────────────────────────────────────────────

@pytest.fixture
def sample_paper():
    return Paper(
        title="Deep Learning for Natural Language Processing",
        abstract="This paper presents a deep learning approach to NLP tasks using neural networks.",
        doi="10.1234/dlnlp.2023",
        tags=["Deep Learning", "NLP", "Machine Learning"],
        authors=["Alice Smith", "Bob Jones"],
        venue="ICML",
        year=2023,
    )


@pytest.fixture
def sample_papers():
    return [
        Paper(
            title="Attention Is All You Need",
            abstract="We propose a new simple network architecture called the Transformer, based solely on attention mechanisms.",
            doi="10.1234/attn.2017",
            tags=["Transformer", "NLP", "Attention"],
            year=2017,
        ),
        Paper(
            title="BERT: Pre-training of Deep Bidirectional Transformers",
            abstract="We introduce BERT, a method of pre-training language representations.",
            doi="10.1234/bert.2018",
            tags=["BERT", "NLP", "Pre-training"],
            year=2018,
        ),
        Paper(
            title="ImageNet Classification with Deep Convolutional Neural Networks",
            abstract="We trained a large deep convolutional neural network to classify the ImageNet dataset.",
            doi="10.1234/alexnet.2012",
            tags=["Computer Vision", "CNN", "Deep Learning"],
            year=2012,
        ),
    ]


# ── 資料庫 fixtures ───────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    """使用暫存目錄的 SQLiteDB，測試後自動清除"""
    return SQLiteDB(db_path=tmp_path / "test_papers.db")


@pytest.fixture
def db_with_papers(db, sample_papers):
    """預先插入三篇論文的 DB"""
    for paper in sample_papers:
        db.insert(paper)
    return db


@pytest.fixture
def chunk_store(tmp_path):
    """使用暫存目錄的 ChunkStore"""
    return ChunkStore(db_path=tmp_path / "test_chunks.db")


# ── Mock fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def mock_gemini_response():
    """模擬 Gemini API 成功回傳"""
    resp = MagicMock()
    resp.text = '["Machine Learning", "Deep Learning", "Neural Networks", "NLP", "Transformer"]'
    return resp


@pytest.fixture
def mock_gemini_client(mock_gemini_response):
    """完整的 Gemini client mock"""
    client = MagicMock()
    client.models.generate_content.return_value = mock_gemini_response
    return client


@pytest.fixture
def mock_crossref_response():
    """模擬 Crossref API HTTP 回應"""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "message": {
            "items": [{
                "title": ["Deep Learning for NLP"],
                "DOI": "10.1234/test",
                "abstract": "<jats:p>A deep learning paper.</jats:p>",
                "author": [{"given": "Alice", "family": "Smith"}],
                "published": {"date-parts": [[2023]]},
                "container-title": ["ICML"],
            }],
            "total-results": 1,
        }
    }
    return resp


@pytest.fixture
def mock_vector_db():
    """模擬 VectorDB，避免真正啟動 ChromaDB / sentence-transformers"""
    vdb = MagicMock()
    vdb.search.return_value = []
    vdb.search_chunks.return_value = []
    vdb.count.return_value = 0
    vdb.fulltext_collection.count.return_value = 0
    return vdb


# ── 暫存 XLSX fixture ─────────────────────────────────────────────────

@pytest.fixture
def sample_xlsx(tmp_path):
    """建立含有 title / abstract / doi 三欄的 xlsx 測試檔"""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Title", "Abstract", "DOI", "Tags"])
    ws.append([
        "Attention Is All You Need",
        "Transformer-based architecture",
        "10.1234/attn.2017",
        "NLP, Transformer",
    ])
    ws.append([
        "BERT Pre-training",
        "Bidirectional language model",
        "10.1234/bert.2018",
        "NLP, BERT",
    ])
    path = tmp_path / "test_papers.xlsx"
    wb.save(path)
    return path
