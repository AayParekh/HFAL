import zipfile

from hfal.extract import extract_docx


def test_extract_docx(tmp_path):
    p = tmp_path / "a.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document><w:body><w:p><w:r><w:t>Financial Assistance Policy</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>Patients up to 400% FPL &amp; more qualify for free or discounted care.</w:t></w:r></w:p>'
                   '</w:body></w:document>')
    pages, needs_ocr = extract_docx(p)
    assert pages[0].splitlines()[:2] == ["Financial Assistance Policy", "Patients up to 400% FPL & more qualify for free or discounted care."]
    assert needs_ocr is False
