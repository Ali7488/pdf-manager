"""Tests for merging: order, bookmarks, contents page, page labels."""

from __future__ import annotations

import fitz
import pytest

from converter.context import JobContext
from converter.issues import ConversionError, IssueCode
from converter.merge import Part, merge_documents
from tests.helpers import page_texts, text_pdf


@pytest.fixture
def parts(tmp_path):
    a = text_pdf(tmp_path / "a.pdf", ["A one", "A two"], toc=[[1, "A intro", 1], [2, "A more", 2]])
    b = text_pdf(tmp_path / "b.pdf", ["B one", "B two", "B three"])
    return [Part("Report", a), Part("دواء notes", b)]


def test_order_text_and_nested_bookmarks(tmp_path, parts):
    out = tmp_path / "m.pdf"
    assert merge_documents(parts, out, JobContext()) == 5
    texts = page_texts(out)
    assert "A one" in texts[0] and "B three" in texts[4]
    with fitz.open(str(out)) as doc:
        assert doc.get_toc(simple=True) == [
            [1, "Report", 1],
            [2, "A intro", 1],
            [3, "A more", 2],
            [1, "دواء notes", 3],
        ]
        assert [doc[i].get_label() for i in range(5)] == ["1", "2", "3", "4", "5"]


def test_contents_page_links_labels_and_unicode(tmp_path, parts):
    out = tmp_path / "m.pdf"
    assert merge_documents(parts, out, JobContext(), contents_page=True) == 6
    with fitz.open(str(out)) as doc:
        contents = doc[0]
        text = contents.get_text()
        assert (
            "Contents" in text and "Report" in text and "Pages 1–2" in text and "Pages 3–5" in text
        )
        assert "notes" in text
        targets = [link["page"] for link in contents.get_links() if link["kind"] == fitz.LINK_GOTO]
        assert targets == [1, 3], "rows must jump to each part's first page"
        assert doc[0].get_label() == "i" and doc[1].get_label() == "1" and doc[5].get_label() == "5"
        toc = doc.get_toc(simple=True)
        assert toc[0] == [1, "Contents", 1] and toc[1] == [1, "Report", 2]


def test_contents_spills_onto_more_pages(tmp_path):
    src = text_pdf(tmp_path / "x.pdf", ["X"], size=(400, 300))
    many = [Part(f"Part {i}", src) for i in range(30)]
    out = tmp_path / "m.pdf"
    total = merge_documents(many, out, JobContext(), contents_page=True)
    with fitz.open(str(out)) as doc:
        lead = total - 30
        assert lead > 1
        links = [link["page"] for i in range(lead) for link in doc[i].get_links()]
        assert links == [lead + i for i in range(30)]
        assert doc[1].get_label() == "ii" and doc[lead].get_label() == "1"


def test_locked_input_is_a_clear_issue(tmp_path):
    locked = tmp_path / "locked.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(locked), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="o")
    with pytest.raises(ConversionError) as err:
        merge_documents([Part("Locked", locked)], tmp_path / "o.pdf", JobContext())
    assert err.value.issue.code is IssueCode.PASSWORD_PROTECTED
