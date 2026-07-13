
import json
from pathlib import Path

import pytest

import tools.coverage_gate as coverage_gate
import tools.mutation_gate as mutation_gate
import tools.verify_docs as docs_gate
import tools.verify_text_integrity as text_gate
from tools.coverage_gate import branch_percentage, evaluate
from tools.mutation_gate import mutation_score
from tools.verify_docs import verify
from tools.verify_text_integrity import inspect


def test_packaged_app_contains_both_media_tool_manifests():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "mariana-cli.spec").read_text(encoding="utf-8")
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    resources = {entry["to"] for entry in package["build"]["extraResources"]}

    assert 'tools" / "manifest.json' in spec
    assert 'tools" / "bootstrap-manifest.json' in spec
    assert {"tools/manifest.json", "tools/bootstrap-manifest.json"} <= resources


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


def test_coverage_gate_cli_passes_and_fails_honestly(tmp_path, monkeypatch, capsys):
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps({"files": {"module.py": {"summary": {"num_branches": 20, "covered_branches": 19}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["coverage_gate", str(report), "--minimum", "95", "--module", "module.py"],
    )
    coverage_gate.main()
    assert "95.0%" in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv",
        ["coverage_gate", str(report), "--minimum", "96", "--module", "module.py"],
    )
    with pytest.raises(SystemExit, match=r"requires 96\.0%"):
        coverage_gate.main()


def test_mutation_gate_cli_passes_and_fails_honestly(tmp_path, monkeypatch, capsys):
    report = tmp_path / "mutations.json"
    report.write_text(json.dumps({"total": 10, "killed": 8, "skipped": 0}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["mutation_gate", str(report), "--minimum", "80"])
    mutation_gate.main()
    assert "80.0%" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["mutation_gate", str(report), "--minimum", "81"])
    with pytest.raises(SystemExit, match=r"below 81\.0%"):
        mutation_gate.main()


def test_documentation_gate_main_and_ignored_trees(tmp_path, monkeypatch, capsys):
    (tmp_path / "README.md").write_text("root", encoding="utf-8")
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "dependency.md").write_text("ignored", encoding="utf-8")
    test_temporary = tmp_path / ".test-tmp-example"
    test_temporary.mkdir()
    (test_temporary / "fixture.md").write_text("ignored", encoding="utf-8")
    generated = tmp_path / "temp"
    generated.mkdir()
    (generated / "fixture.md").write_text("ignored", encoding="utf-8")
    assert docs_gate.markdown_files(tmp_path) == [tmp_path / "README.md"]
    monkeypatch.setattr(docs_gate, "verify", lambda _root: [])
    docs_gate.main()
    assert "consistent" in capsys.readouterr().out
    monkeypatch.setattr(docs_gate, "verify", lambda _root: ["broken"])
    with pytest.raises(SystemExit, match="broken"):
        docs_gate.main()


def test_documentation_gate_ignores_external_and_fragment_links(tmp_path):
    commands = " ".join(sorted(docs_gate.REQUIRED_COMMAND_FAMILIES))
    aliases = " ".join(
        f"`{alias}`" for entry in docs_gate.ALIAS_COMPATIBILITY for alias in entry.aliases
    )
    (tmp_path / "README.md").write_text(commands, encoding="utf-8")
    (tmp_path / "help.md").write_text(
        commands
        + " "
        + aliases
        + "\n[web](https://example.test) [mail](mailto:test@example.test) [fragment](#part) "
        + "[local](README.md#part)",
        encoding="utf-8",
    )
    assert docs_gate.verify(tmp_path) == []


def test_text_gate_discovers_tracked_text_and_main_paths(tmp_path, monkeypatch, capsys):
    result = type("Result", (), {"stdout": b"one.py\0image.png\0README.md\0"})()
    monkeypatch.setattr(text_gate.subprocess, "run", lambda *_args, **_kwargs: result)
    assert text_gate.tracked_text_files(tmp_path) == [tmp_path / "one.py", tmp_path / "README.md"]

    monkeypatch.setattr(text_gate, "tracked_text_files", lambda _root: [])
    text_gate.main()
    assert "valid UTF-8" in capsys.readouterr().out
    monkeypatch.setattr(text_gate, "inspect", lambda _paths: ["bad marker"])
    with pytest.raises(SystemExit, match="bad marker"):
        text_gate.main()


def test_text_gate_skips_deleted_paths_and_reports_every_marker(tmp_path):
    broken = tmp_path / "broken.txt"
    broken.write_text("bad \u00e2\u20ac\u201d and \ufffd", encoding="utf-8")
    failures = text_gate.inspect([tmp_path / "deleted.txt", broken])
    assert len(failures) == 2
