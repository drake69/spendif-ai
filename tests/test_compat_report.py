"""The compatibility table is built from issue bodies anyone can write.

These tests feed the parser a report exactly as the Diagnostics page produces
it, wrapped the way the GitHub issue form wraps it, and then the shapes a
hostile or careless body can take.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from services import diagnostics_service as diagnostics

_SPEC = importlib.util.spec_from_file_location(
    "compat_report", Path(__file__).resolve().parent.parent / "scripts" / "compat_report.py"
)
compat = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(compat)


def _report(**over) -> dict:
    report = {
        "generated_at": "2026-10-10 14:32:07 UTC",
        "application": {"version": "0.3.1", "build_time": "2026-10-09 10:00",
                        "install_method": "deb", "packaged_build": True},
        "system": {"os": "Linux", "os_name": "Debian GNU/Linux 13 (trixie)", "os_id": "debian-13",
                   "os_version": "Linux-6.12-aarch64-with-glibc2.41", "arch": "aarch64",
                   "ram_gb": 8, "emulated_x64_on_arm": False, "python_version": "3.13.7"},
        "graphics": {"gpu": "unknown", "vram_gb": 0, "gpu_cores": 0,
                     "acceleration_active": False, "inference_devices": ["CPU"]},
        "inference": {"llama_cpp_version": "0.3.35", "backend": "local_llama_cpp",
                      "n_ctx": "(auto)", "n_gpu_layers": "(auto)", "model": "qwen.gguf", "phases": {}},
        "ledger": {"transactions": 10},
        "imports": {"jobs": 2, "files": 2, "rows": 200,
                    "per_row_seconds": {"categorizing": 0.5},
                    "last_job": {"rows": 100, "per_row_seconds": {"categorizing": 0.25}}},
    }
    for key, value in over.items():
        report[key] = {**report[key], **value}
    return report


def _issue_body(xml: str, ticked=("Installed", "Imported a statement")) -> str:
    boxes = "\n".join(
        f"- [{'X' if label in ticked else ' '}] {label}" for _, label in compat.OUTCOMES
    )
    return f"### Report\n\n```xml\n{xml}\n```\n\n### Outcome\n\n{boxes}\n\n### Notes\n\n_No response_\n"


def _event(body: str, number: int = 7) -> dict:
    return {"issue": {"number": number, "body": body}}


def test_a_real_report_becomes_a_row():
    xml = diagnostics.to_xml(_report(), stars=4)
    row = compat.row_from_event(_event(_issue_body(xml)))
    assert row["os_name"] == "Debian GNU/Linux 13 (trixie)"
    assert row["arch"] == "aarch64"
    assert row["install_method"] == "deb"
    assert row["acceleration"] is False
    # The last import, not the average: that is the number a comparison reads.
    assert row["categorizing_s_per_row"] == pytest.approx(0.25)
    assert row["outcome"] == {"installed": True, "started": False,
                              "imported": True, "uninstalled": False}
    assert row["stars"] == 4
    assert row["issue"] == 7


def test_schema_1_reports_still_read():
    xml = diagnostics.to_xml(_report()).replace('schema="2"', 'schema="1"')
    xml = xml.replace("<os_name>Debian GNU/Linux 13 (trixie)</os_name>", "")
    row = compat.parse_report(compat.extract_xml(_issue_body(xml)))
    assert row["os_name"].startswith("Linux-6.12")


@pytest.mark.parametrize("xml", [
    '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><spendifai_report schema="2"/>',
    '<other schema="2"/>',
    '<spendifai_report schema="99"/>',
    '<spendifai_report schema="2"><unclosed></spendifai_report>',
    "<spendifai_report schema=\"2\">" + "a" * (70 * 1024) + "</spendifai_report>",
], ids=["doctype-entity", "other-root", "unknown-schema", "malformed", "oversized"])
def test_unreadable_or_hostile_reports_are_refused(xml):
    with pytest.raises(compat.ReportError):
        compat.parse_report(xml)


def test_body_without_xml_is_refused():
    with pytest.raises(compat.ReportError):
        compat.row_from_event(_event("just some text"))


def test_values_cannot_inject_markdown():
    xml = diagnostics.to_xml(_report(graphics={
        "gpu": "![x](https://evil.example/p.png) <img src=x> | [link](javascript:1)",
        "acceleration_active": True, "inference_devices": ["Vulkan0", "CPU"],
    }))
    row = compat.row_from_event(_event(_issue_body(xml)))
    table = compat.render([row], "en")
    for bad in ("![", "](", "<img", "https://", "javascript:", "| [link"):
        assert bad not in table


def test_one_row_per_configuration_newest_wins(tmp_path):
    old = compat.row_from_event(_event(_issue_body(diagnostics.to_xml(
        _report(application={"version": "0.3.0"}, imports={}) | {"generated_at": "2026-09-01 10:00:00 UTC"}
    )), number=1))
    new = compat.row_from_event(_event(_issue_body(diagnostics.to_xml(_report())), number=2))
    rows = compat.upsert(compat.upsert([], old), new)
    table = compat.render(rows, "en")
    assert "0.3.1" in table and "0.3.0" not in table
    assert "#2" in table


def test_edited_issue_replaces_its_row(tmp_path):
    store = tmp_path / "reports.jsonl"
    body = _issue_body(diagnostics.to_xml(_report()))
    for ticked in ((), ("Installed",)):
        event = tmp_path / "event.json"
        event.write_text(json.dumps(_event(_issue_body(diagnostics.to_xml(_report()), ticked))))
        assert compat.main(["--event", str(event), "--store", str(store), "--docs", str(tmp_path)]) == 0
    rows = compat.load_store(store)
    assert len(rows) == 1 and rows[0]["outcome"]["installed"] is True
    assert (tmp_path / "compatibility.md").exists()
    assert (tmp_path / "compatibility.it.md").exists()
    assert body  # the body itself is never stored, only the parsed row
    assert "```" not in store.read_text()


def test_unreadable_issue_exits_with_a_summary(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps(_event("no report here")))
    summary = tmp_path / "summary.txt"
    code = compat.main(["--event", str(event), "--store", str(tmp_path / "s.jsonl"),
                        "--docs", str(tmp_path), "--summary", str(summary)])
    assert code == 2
    assert summary.read_text().startswith("error:")
