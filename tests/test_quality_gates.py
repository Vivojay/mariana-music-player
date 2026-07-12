
from tools.coverage_gate import branch_percentage, evaluate
from tools.mutation_gate import mutation_score
from tools.verify_docs import verify
from tools.verify_text_integrity import inspect


def test_branch_percentage_uses_branches_only():
    assert branch_percentage({"num_branches": 20, "covered_branches": 19}) == 95
    assert branch_percentage({"num_branches": 0, "covered_branches": 0}) == 100


def test_coverage_gate_is_independent_per_module():
    report = {
        "files": {
            "good.py": {"summary": {"num_branches": 20, "covered_branches": 19}},
            "bad.py": {"summary": {"num_branches": 100, "covered_branches": 94}},
        }
    }
    lines, failures = evaluate(report, ("good.py", "bad.py", "missing.py"), 95)
    assert lines == [
        "good.py: 95.0% branch coverage",
        "bad.py: 94.0% branch coverage",
        "missing.py: absent from coverage report",
    ]
    assert len(failures) == 2


def test_text_integrity_rejects_invalid_utf8_and_mojibake(tmp_path):
    valid = tmp_path / "valid.md"
    valid.write_text("Electron → PTY; close ×; timer ◷\n", encoding="utf-8")  # noqa: RUF001
    broken = tmp_path / "broken.md"
    broken.write_text("release gate\u00e2\u20ac\u201dfailed\n", encoding="utf-8")
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"broken: \xff")
    failures = inspect([valid, broken, invalid])
    assert not any(str(valid) in failure for failure in failures)
    assert any("mojibake" in failure and str(broken) in failure for failure in failures)
    assert any("invalid UTF-8" in failure and str(invalid) in failure for failure in failures)


def test_mutation_score_is_conservative():
    assert mutation_score({"total": 10, "killed": 8, "skipped": 0}) == 80
    assert mutation_score({"total": 2, "killed": 0, "skipped": 2}) == 100


def test_docs_verifier_reports_links_and_command_drift(tmp_path):
    (tmp_path / "README.md").write_text("queue radio")
    (tmp_path / "help.md").write_text("queue radio [missing](gone.md)")
    failures = verify(tmp_path)
    assert any("broken local link" in failure for failure in failures)
    assert any("broadcast" in failure for failure in failures)
