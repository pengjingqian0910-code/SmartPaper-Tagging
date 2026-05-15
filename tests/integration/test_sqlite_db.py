"""
Integration tests — smartpaper/database/sqlite_db.py
使用暫存目錄的真實 SQLite，測試 CRUD、搜尋、引用、概念
"""
import pytest
from smartpaper.database.sqlite_db import SQLiteDB
from smartpaper.models import Paper


class TestInsertAndGet:
    def test_insert_returns_id(self, db, sample_paper):
        pid = db.insert(sample_paper)
        assert isinstance(pid, int)
        assert pid > 0

    def test_get_by_id_round_trip(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_id(pid)
        assert fetched is not None
        assert fetched.title == sample_paper.title
        assert fetched.abstract == sample_paper.abstract
        assert fetched.doi == sample_paper.doi

    def test_get_by_id_missing_returns_none(self, db):
        assert db.get_by_id(99999) is None

    def test_get_by_doi(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_doi(sample_paper.doi)
        assert fetched is not None
        assert fetched.id == pid

    def test_get_by_doi_missing(self, db):
        assert db.get_by_doi("10.0000/nonexistent") is None

    def test_tags_preserved(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_id(pid)
        assert set(fetched.tags) == set(sample_paper.tags)

    def test_authors_preserved(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_id(pid)
        assert fetched.authors == sample_paper.authors

    def test_year_preserved(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_id(pid)
        assert fetched.year == sample_paper.year


class TestExistsAndDuplication:
    def test_exists_by_title(self, db, sample_paper):
        db.insert(sample_paper)
        assert db.exists(title=sample_paper.title)

    def test_exists_by_doi(self, db, sample_paper):
        db.insert(sample_paper)
        assert db.exists(doi=sample_paper.doi)

    def test_not_exists(self, db):
        assert not db.exists(title="This Title Does Not Exist XYZ")

    def test_duplicate_doi_not_inserted(self, db, sample_paper):
        db.insert(sample_paper)
        p2 = Paper(title="Different Title", doi=sample_paper.doi)
        try:
            db.insert(p2)
        except Exception:
            pass  # duplicate DOI rejected by UNIQUE constraint
        count = db.count()
        assert count == 1  # 第二筆被忽略或跳過


class TestUpdate:
    def test_update_title(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_id(pid)
        fetched.title = "Updated Title"
        db.update(fetched)
        updated = db.get_by_id(pid)
        assert updated.title == "Updated Title"

    def test_update_tags(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_id(pid)
        fetched.tags = ["New Tag A", "New Tag B"]
        db.update(fetched)
        updated = db.get_by_id(pid)
        assert "New Tag A" in updated.tags

    def test_update_abstract(self, db, sample_paper):
        pid = db.insert(sample_paper)
        fetched = db.get_by_id(pid)
        fetched.abstract = "Completely new abstract."
        db.update(fetched)
        updated = db.get_by_id(pid)
        assert updated.abstract == "Completely new abstract."


class TestDelete:
    def test_delete_removes_paper(self, db, sample_paper):
        pid = db.insert(sample_paper)
        db.delete(pid)
        assert db.get_by_id(pid) is None

    def test_delete_decrements_count(self, db, sample_papers):
        ids = [db.insert(p) for p in sample_papers]
        initial = db.count()
        db.delete(ids[0])
        assert db.count() == initial - 1

    def test_delete_nonexistent_no_error(self, db):
        db.delete(99999)  # 不應拋出例外


class TestSearch:
    def test_search_by_title_keyword(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        results = db.search_by_title("Attention")
        assert len(results) >= 1
        assert any("Attention" in p.title for p in results)

    def test_search_by_title_no_match(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        results = db.search_by_title("QuantumFogzXZQ")
        assert results == []

    def test_get_by_tag(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        results = db.get_by_tag("NLP")
        assert len(results) >= 1
        assert all("NLP" in p.tags for p in results)

    def test_get_by_tag_missing(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        results = db.get_by_tag("TagThatDoesNotExist")
        assert results == []


class TestPagination:
    def test_get_all_returns_all(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        all_papers = db.get_all(limit=100)
        assert len(all_papers) == len(sample_papers)

    def test_get_all_limit(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        limited = db.get_all(limit=2)
        assert len(limited) <= 2

    def test_get_all_offset(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        page1 = db.get_all(limit=2, offset=0)
        page2 = db.get_all(limit=2, offset=2)
        ids1 = {p.id for p in page1}
        ids2 = {p.id for p in page2}
        assert ids1.isdisjoint(ids2)

    def test_count_matches_inserted(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        assert db.count() == len(sample_papers)


class TestGetAllTags:
    def test_returns_unique_tags(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        tags = db.get_all_tags()
        assert len(tags) == len(set(tags))  # 無重複

    def test_all_tags_included(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        tags = db.get_all_tags()
        assert "NLP" in tags


class TestCitations:
    def test_add_and_get_citation(self, db, sample_papers):
        ids = [db.insert(p) for p in sample_papers]
        citing_id, cited_id = ids[0], ids[1]
        db.add_citation(citing_id, cited_paper_id=cited_id)
        refs = db.get_references(citing_id)
        ref_ids = [r["cited_paper_id"] for r in refs]
        assert cited_id in ref_ids

    def test_citing_papers(self, db, sample_papers):
        ids = [db.insert(p) for p in sample_papers]
        citing_id, cited_id = ids[0], ids[1]
        db.add_citation(citing_id, cited_paper_id=cited_id)
        citers = db.get_citing_papers(cited_id)
        citer_ids = [p.id for p in citers]
        assert citing_id in citer_ids

    def test_has_citations_true(self, db, sample_papers):
        ids = [db.insert(p) for p in sample_papers]
        db.add_citation(ids[0], cited_paper_id=ids[1])
        assert db.has_citations(ids[0])

    def test_has_citations_false(self, db, sample_paper):
        pid = db.insert(sample_paper)
        assert not db.has_citations(pid)

    def test_duplicate_citation_ignored(self, db, sample_papers):
        ids = [db.insert(p) for p in sample_papers]
        db.add_citation(ids[0], cited_paper_id=ids[1])
        db.add_citation(ids[0], cited_paper_id=ids[1])
        refs = db.get_references(ids[0])
        assert len(refs) == 1


class TestConcepts:
    def test_upsert_creates_concept(self, db):
        cid = db.upsert_concept("BERT", "method")
        assert isinstance(cid, int)

    def test_upsert_idempotent(self, db):
        cid1 = db.upsert_concept("BERT", "method")
        cid2 = db.upsert_concept("BERT", "method")
        assert cid1 == cid2

    def test_replace_paper_concepts(self, db, sample_paper):
        pid = db.insert(sample_paper)
        concepts = {
            "method": ["Transformer", "Attention"],
            "dataset": ["ImageNet"],
            "metric": ["Accuracy"],
            "task": ["Classification"],
        }
        db.replace_paper_concepts(pid, concepts)
        stored = db.get_paper_concepts(pid)
        assert "Transformer" in stored.get("method", [])
        assert "ImageNet" in stored.get("dataset", [])

    def test_has_concepts_true(self, db, sample_paper):
        pid = db.insert(sample_paper)
        db.replace_paper_concepts(pid, {"method": ["SVM"]})
        assert db.has_concepts(pid)

    def test_has_concepts_false(self, db, sample_paper):
        pid = db.insert(sample_paper)
        assert not db.has_concepts(pid)
