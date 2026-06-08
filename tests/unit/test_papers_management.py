"""
Unit tests — 論文管理相關功能
涵蓋：Paper 模型欄位、starred/read_status 操作、BM25 快取版本、
     搜尋個人化、SQLite 持久化欄位、篩選邏輯
"""

import pickle
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from smartpaper.models import Paper, SearchResult
from smartpaper.services.bm25_index import BM25Index, _CACHE_VERSION
from smartpaper.database.sqlite_db import SQLiteDB


# ── 模擬舊版 Paper（可被 pickle 的模組層級類別）────────────────────────

class _OldPaper:
    """模擬加入 starred/read_status 欄位之前的舊版 Paper 物件。"""
    def __init__(self):
        self.id = 1
        self.title = "Old Paper"
        self.abstract = "old abstract"
        # 故意不設 starred / read_status / personal_note


# ── 共用 helpers ──────────────────────────────────────────────────────

def _paper(pid: int = 1, **kwargs) -> Paper:
    defaults = dict(
        title=f"Paper {pid}",
        abstract="Some abstract text about deep learning.",
        year=2023,
    )
    defaults.update(kwargs)
    return Paper(id=pid, **defaults)


# ── Paper 模型欄位測試 ────────────────────────────────────────────────

class TestPaperModelFields:
    """確認 Paper 模型擁有所有個人化欄位，且有正確預設值。"""

    def test_starred_defaults_false(self):
        p = Paper(title="Test Paper")
        assert p.starred is False

    def test_read_status_defaults_unread(self):
        p = Paper(title="Test Paper")
        assert p.read_status == "unread"

    def test_personal_note_defaults_empty(self):
        p = Paper(title="Test Paper")
        assert p.personal_note == ""

    def test_starred_can_be_set_true(self):
        p = Paper(title="Test Paper", starred=True)
        assert p.starred is True

    def test_read_status_valid_values(self):
        for status in ("unread", "reading", "read"):
            p = Paper(title="Test", read_status=status)
            assert p.read_status == status

    def test_paper_has_required_attributes(self):
        p = Paper(title="Test")
        for attr in ("starred", "read_status", "personal_note", "id", "tags", "authors"):
            assert hasattr(p, attr), f"Paper missing attribute: {attr}"

    def test_toggle_starred(self):
        p = Paper(title="Test")
        p.starred = True
        assert p.starred is True
        p.starred = False
        assert p.starred is False


# ── SQLiteDB starred / read_status 持久化測試 ─────────────────────────

class TestSQLitePersonalization:
    """確認 starred、read_status、personal_note 能正確讀寫。"""

    def test_starred_defaults_to_false_after_insert(self, db):
        pid = db.insert(Paper(title="Starred Test"))
        p = db.get_by_id(pid)
        assert p.starred is False

    def test_update_star_true(self, db):
        pid = db.insert(Paper(title="Star True Test"))
        db.update_paper_star(pid, True)
        p = db.get_by_id(pid)
        assert p.starred is True

    def test_update_star_false(self, db):
        pid = db.insert(Paper(title="Star False Test"))
        db.update_paper_star(pid, True)
        db.update_paper_star(pid, False)
        p = db.get_by_id(pid)
        assert p.starred is False

    def test_update_read_status(self, db):
        pid = db.insert(Paper(title="Status Test"))
        for status in ("reading", "read", "unread"):
            db.update_paper_status(pid, status)
            p = db.get_by_id(pid)
            assert p.read_status == status, f"Expected {status}, got {p.read_status}"

    def test_update_personal_note(self, db):
        pid = db.insert(Paper(title="Note Test"))
        db.update_paper_note(pid, "My private annotation.")
        p = db.get_by_id(pid)
        assert p.personal_note == "My private annotation."

    def test_clear_personal_note(self, db):
        pid = db.insert(Paper(title="Note Clear"))
        db.update_paper_note(pid, "some note")
        db.update_paper_note(pid, "")
        p = db.get_by_id(pid)
        assert p.personal_note == ""

    def test_starred_survives_cache_eviction(self, db):
        pid = db.insert(Paper(title="Cache Test"))
        db.update_paper_star(pid, True)
        db._cache_evict(pid)          # 強制清除記憶體快取
        p = db.get_by_id(pid)         # 必須從 SQLite 重新讀取
        assert p.starred is True

    def test_get_all_preserves_starred(self, db):
        pid1 = db.insert(Paper(title="Starred One"))
        pid2 = db.insert(Paper(title="Not Starred"))
        db.update_paper_star(pid1, True)
        all_papers = db.get_all(limit=100)
        starred = [p for p in all_papers if p.id == pid1]
        not_starred = [p for p in all_papers if p.id == pid2]
        assert starred[0].starred is True
        assert not_starred[0].starred is False


# ── BM25 快取版本與防禦性載入 ─────────────────────────────────────────

class TestBM25CacheVersion:
    """確認快取版本機制能阻止舊版 Paper 物件造成 AttributeError。"""

    def test_save_includes_version(self, tmp_path):
        idx = BM25Index()
        idx.build([_paper(1, title="Deep Learning", abstract="neural networks")])
        path = tmp_path / "bm25.pkl"
        idx.save(path)
        with open(path, "rb") as f:
            data = pickle.load(f)
        assert "version" in data
        assert data["version"] == _CACHE_VERSION

    def test_load_correct_version_succeeds(self, tmp_path):
        idx = BM25Index()
        idx.build([_paper(1, title="Attention", abstract="transformer architecture")])
        path = tmp_path / "bm25.pkl"
        idx.save(path)
        idx2 = BM25Index()
        assert idx2.load(path) is True
        assert idx2.is_built

    def test_load_wrong_version_returns_false_and_deletes(self, tmp_path):
        path = tmp_path / "bm25.pkl"
        # 手動寫入舊格式（無 version 欄位）；bm25 用真實物件（MagicMock 不可 pickle）
        idx_tmp = BM25Index()
        idx_tmp.build([_paper(1, title="old", abstract="old abstract")])
        with open(path, "wb") as f:
            pickle.dump({"papers": idx_tmp._papers, "bm25": idx_tmp._bm25}, f)
        idx = BM25Index()
        result = idx.load(path)
        assert result is False
        assert not path.exists(), "舊版快取應被自動刪除"

    def test_load_missing_starred_attribute_returns_false(self, tmp_path):
        """模擬舊版 Paper 物件（unpickle 後缺少 starred 屬性）。"""
        path = tmp_path / "bm25_old.pkl"

        idx_tmp = BM25Index()
        idx_tmp.build([_paper(1, title="placeholder", abstract="placeholder abstract")])
        stale_data = {
            "version": _CACHE_VERSION,  # 版本號正確但物件不完整
            "papers": [_OldPaper()],    # 缺少 starred 等新欄位
            "bm25": idx_tmp._bm25,
        }
        with open(path, "wb") as f:
            pickle.dump(stale_data, f)

        idx = BM25Index()
        result = idx.load(path)
        assert result is False

    def test_load_nonexistent_file_returns_false(self, tmp_path):
        idx = BM25Index()
        assert idx.load(tmp_path / "nonexistent.pkl") is False

    def test_invalidate_deletes_file(self, tmp_path):
        path = tmp_path / "bm25.pkl"
        path.write_bytes(b"dummy")
        BM25Index.invalidate_cache(path)
        assert not path.exists()


# ── SearchService._personalize 防禦性 getattr ─────────────────────────

class TestPersonalizeDefensive:
    """確認 _personalize 在 Paper 缺少 starred/read_status 時不崩潰。"""

    def _make_results(self, papers):
        return [SearchResult(paper=p, score=0.5) for p in papers]

    def test_normal_starred_paper_boosts_score(self):
        from smartpaper.services.search import SearchService
        svc = SearchService.__new__(SearchService)  # 不呼叫 __init__

        p = _paper(1, starred=True)
        results = self._make_results([p])
        out = svc._personalize(results)
        assert out[0].score > 0.5, "已星號的論文分數應提高"

    def test_read_paper_gets_small_boost(self):
        from smartpaper.services.search import SearchService
        svc = SearchService.__new__(SearchService)

        p = _paper(2, read_status="read")
        results = self._make_results([p])
        out = svc._personalize(results)
        assert out[0].score > 0.5, "已讀論文應獲得小幅加成"

    def test_unread_paper_no_boost(self):
        from smartpaper.services.search import SearchService
        svc = SearchService.__new__(SearchService)

        p = _paper(3, starred=False, read_status="unread")
        results = self._make_results([p])
        out = svc._personalize(results)
        assert out[0].score == pytest.approx(0.5), "未讀未星號論文分數不應改變"

    def test_paper_missing_starred_does_not_raise(self):
        """模擬舊版 Paper（缺少 starred 屬性），確認 getattr 防禦有效。"""
        from smartpaper.services.search import SearchService
        svc = SearchService.__new__(SearchService)

        p = _paper(4)
        # 強制刪除 starred 模擬舊版物件
        object.__delattr__(p, "__dict__")  # Pydantic 物件無法刪 __dict__；改用 mock
        old_paper = MagicMock(spec=[])     # spec=[] → 沒有任何屬性
        old_paper.id = 4
        old_paper.title = "Old"

        sr = SearchResult(paper=_paper(4), score=0.5)
        # 手動替換 paper 為缺少屬性的物件
        object.__setattr__(sr, "paper", old_paper)

        # 不應拋出 AttributeError
        try:
            out = svc._personalize([sr])
        except AttributeError as e:
            pytest.fail(f"_personalize raised AttributeError: {e}")


# ── starred 篩選邏輯 ───────────────────────────────────────────────────

class TestStarredFilter:
    """確認 starred 篩選邏輯正確，且對缺少屬性的物件不崩潰。"""

    def _filter_starred(self, papers):
        return [p for p in papers if getattr(p, "starred", False)]

    def test_filters_only_starred(self):
        p1 = _paper(1, starred=True)
        p2 = _paper(2, starred=False)
        p3 = _paper(3)  # starred 預設 False
        result = self._filter_starred([p1, p2, p3])
        assert len(result) == 1
        assert result[0].id == 1

    def test_empty_list(self):
        assert self._filter_starred([]) == []

    def test_all_starred(self):
        papers = [_paper(i, starred=True) for i in range(5)]
        assert len(self._filter_starred(papers)) == 5

    def test_none_starred(self):
        papers = [_paper(i, starred=False) for i in range(5)]
        assert len(self._filter_starred(papers)) == 0

    def test_missing_starred_attribute_does_not_raise(self):
        """模擬舊版物件缺少 starred 屬性。"""
        old = MagicMock(spec=[])  # 無任何屬性
        result = self._filter_starred([old])
        assert result == [], "缺少 starred 的物件應被視為 False（不加星）"


# ── SQLiteDB get_by_ids 批次查詢 ──────────────────────────────────────

class TestGetByIds:
    def test_get_by_ids_returns_all(self, db):
        p1 = Paper(title="A", abstract="abstract A")
        p2 = Paper(title="B", abstract="abstract B")
        id1 = db.insert(p1)
        id2 = db.insert(p2)
        result = db.get_by_ids([id1, id2])
        assert id1 in result
        assert id2 in result

    def test_get_by_ids_empty_list(self, db):
        result = db.get_by_ids([])
        assert result == {}

    def test_get_by_ids_missing_id(self, db):
        pid = db.insert(Paper(title="Exists"))
        result = db.get_by_ids([pid, 99999])
        assert pid in result
        assert 99999 not in result

    def test_get_by_ids_starred_preserved(self, db):
        pid = db.insert(Paper(title="Star Test"))
        db.update_paper_star(pid, True)
        db._cache_evict(pid)
        result = db.get_by_ids([pid])
        assert result[pid].starred is True
