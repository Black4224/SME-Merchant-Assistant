from app.config import DATA_DIR
from evaluation.csv_eval import confirm, make_client, preview


def test_demo_import_file_behaves_exactly_as_the_demo_script_says():
    from app.main import app
    data = (DATA_DIR / "demo_import_with_errors.csv").read_bytes()
    c, engine = make_client()
    try:
        p = preview(c, data).json()
        assert p["counts"] == {"total": 5, "valid": 3, "duplicate": 0, "invalid": 2}
        assert sorted(e["row_number"] for e in p["errors"]) == [5, 6]
        assert p["will_create"]["customers"] == ["سعد الحيدري"]
        assert confirm(c, data).status_code == 422                                   # blocked until the user opts to skip bad rows
        done = confirm(c, data, skip_invalid="true")
        assert done.status_code == 201 and done.json()["imported"] == 3
        assert confirm(c, data).status_code == 409                                   # and the same file cannot be imported twice
    finally:
        app.dependency_overrides.clear()
