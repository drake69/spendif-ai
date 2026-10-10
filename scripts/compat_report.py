#!/usr/bin/env python3
"""Turn a test report filed as an issue into a row of the compatibility table.

WHY IT EXISTS
    A tester runs the application, opens the Diagnostics page and sends the
    report through the issue form. Without this, someone reads each report and
    copies operating system, card, outcome and timings into a table by hand,
    which is exactly the work that stops being done after the fifth report.

WHAT IT TRUSTS, AND WHAT NOT
    The issue form is public: anyone can open one, and the body is whatever
    they typed. It is therefore read as untrusted data from start to finish:
      - the XML is refused if it declares a DOCTYPE or an entity, and above a
        size no real report reaches;
      - only named fields are read, each one capped in length, and nothing
        walks the document;
      - every value that reaches the table is reduced to characters that
        cannot form a link, an image or HTML in Markdown.
    The workflow that runs this never puts the body on a command line, and the
    result reaches the repository only through a pull request someone merges.

STANDARD LIBRARY ONLY
    It runs in a workflow without installing the project, so it imports
    nothing outside Python itself.

USAGE
    python scripts/compat_report.py --event "$GITHUB_EVENT_PATH" \\
        --store docs/compatibility/reports.jsonl --docs docs
    python scripts/compat_report.py --store docs/compatibility/reports.jsonl --docs docs --render-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_XML_BYTES = 64 * 1024
MAX_FIELD = 80
KNOWN_SCHEMAS = {"1", "2"}

# Checkbox labels in .github/ISSUE_TEMPLATE/test_report.yml, in order.
OUTCOMES = (
    ("installed", "Installed"),
    ("started", "Started from the application menu or icon"),
    ("imported", "Imported a statement"),
    ("uninstalled", "Uninstalled cleanly"),
)


class ReportError(ValueError):
    """The issue does not carry a report this script can read."""


# --------------------------------------------------------------------------
# Reading the issue
# --------------------------------------------------------------------------

def extract_xml(body: str) -> str:
    """The report from the issue body: the fenced block the form produces."""
    m = re.search(r"```(?:xml)?\s*\n(.*?)\n\s*```", body or "", re.DOTALL)
    text = (m.group(1) if m else body or "").strip()
    start = text.find("<")
    if start < 0:
        raise ReportError("no XML document in the issue")
    return text[start:]


def extract_outcomes(body: str) -> dict[str, bool]:
    ticked = {
        line.split("]", 1)[1].strip()
        for line in (body or "").splitlines()
        if re.match(r"\s*-\s*\[[xX]\]", line)
    }
    return {key: label in ticked for key, label in OUTCOMES}


def _clean(value: object, limit: int = MAX_FIELD) -> str:
    """Letters, digits and a few separators: nothing Markdown can turn into markup.

    No brackets, so no link or image; no angle brackets, so no HTML; no colon,
    so no "https://" for GitHub to turn into a link on its own.
    """
    text = re.sub(r"[^\w .,;+/()@-]", " ", str(value or ""), flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _number(value: str | None) -> float | None:
    try:
        return round(float(value), 4) if value not in (None, "") else None
    except ValueError:
        return None


def parse_report(xml: str) -> dict[str, object]:
    """The fields the table needs, read one by one from the report."""
    if len(xml.encode("utf-8")) > MAX_XML_BYTES:
        raise ReportError("report larger than any real one")
    if re.search(r"<!(DOCTYPE|ENTITY)", xml, re.IGNORECASE):
        raise ReportError("report declares a DOCTYPE or an entity")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ReportError(f"report is not well-formed XML ({exc})") from exc
    if root.tag != "spendifai_report":
        raise ReportError(f"unexpected document: <{_clean(root.tag, 40)}>")
    schema = root.get("schema", "")
    if schema not in KNOWN_SCHEMAS:
        raise ReportError(f"unknown report schema {_clean(schema, 10)!r}")

    def text(path: str) -> str:
        node = root.find(path)
        return _clean(node.text if node is not None else "")

    devices = [_clean(n.text, 20) for n in root.findall("graphics/inference_devices/item")][:8]
    # Seconds per row of the slowest phase, categorizing: the last import when
    # the report has it, the average otherwise.
    per_row = _number(text("imports/last_job/per_row_seconds/categorizing")) \
        or _number(text("imports/per_row_seconds/categorizing"))
    rating = root.find("user_rating")

    return {
        "schema": schema,
        "generated_at": _clean(root.get("generated_at", ""), 30),
        "version": text("application/version"),
        "install_method": text("application/install_method"),
        "os_name": text("system/os_name") or text("system/os_version"),
        "os_id": text("system/os_id") or text("system/os"),
        "arch": text("system/arch"),
        "ram_gb": _number(text("system/ram_gb")),
        "gpu": text("graphics/gpu"),
        "acceleration": text("graphics/acceleration_active") == "True",
        "devices": devices,
        "llama_cpp_version": text("inference/llama_cpp_version"),
        "model": text("inference/model"),
        "categorizing_s_per_row": per_row,
        "stars": _number(rating.get("stars")) if rating is not None else None,
    }


def row_from_event(event: dict) -> dict[str, object]:
    issue = event.get("issue") or {}
    body = issue.get("body") or ""
    row = parse_report(extract_xml(body))
    row["outcome"] = extract_outcomes(body)
    row["issue"] = int(issue.get("number") or 0)
    return row


# --------------------------------------------------------------------------
# Store and table
# --------------------------------------------------------------------------

def load_store(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_store(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: r.get("issue", 0))
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                    encoding="utf-8")


def upsert(rows: list[dict], row: dict) -> list[dict]:
    """One row per issue: an edited issue replaces what it said before."""
    return [r for r in rows if r.get("issue") != row.get("issue")] + [row]


def _arch(value: str) -> str:
    v = str(value).lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(v, v)


def _runs_on(row: dict) -> str:
    if not row.get("acceleration"):
        return "CPU"
    accel = [d for d in row.get("devices", []) if d.upper() != "CPU"]
    return re.sub(r"\d+$", "", accel[0]) if accel else "GPU"


def latest_per_configuration(rows: list[dict]) -> list[dict]:
    """The newest report for each machine configuration, newest first."""
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("os_id"), _arch(r.get("arch", "")), r.get("gpu"),
               r.get("install_method"), _runs_on(r))
        if key not in best or (r.get("generated_at", ""), r.get("issue", 0)) > \
                (best[key].get("generated_at", ""), best[key].get("issue", 0)):
            best[key] = r
    return sorted(best.values(), key=lambda r: (r.get("os_id", ""), _arch(r.get("arch", ""))))


TEXT = {
    "en": {
        "title": "Compatibility",
        "intro": ("Machines Spendif.ai has been installed on, one row per configuration, newest report "
                  "first. Generated from the test reports filed through the issue form: do not edit by hand."),
        "how": ("To add yours: Diagnostics page, then **Send as a test report on GitHub**."),
        "cols": ["Version", "Operating system", "Arch", "Graphics card", "Runs on", "Installed with",
                 "Install", "Start", "Import", "Uninstall", "s/row (categorizing)", "Report"],
        "empty": "No reports yet.",
        "yes": "yes", "no": "-",
    },
    "it": {
        "title": "Compatibilita'",
        "intro": ("I computer su cui Spendif.ai e' stato installato, una riga per configurazione, il resoconto "
                  "piu' recente per primo. Generata dai resoconti di prova inviati con il modulo delle issue: "
                  "non modificarla a mano."),
        "how": ("Per aggiungere il tuo: pagina Informazioni tecniche, poi **Invia come resoconto di prova su GitHub**."),
        "cols": ["Versione", "Sistema operativo", "Arch", "Scheda grafica", "Gira su", "Installato con",
                 "Installa", "Avvio", "Import", "Disinstalla", "s/riga (categorie)", "Resoconto"],
        "empty": "Ancora nessun resoconto.",
        "yes": "si'", "no": "-",
    },
}


def render(rows: list[dict], lang: str) -> str:
    t = TEXT[lang]
    out = [f"# {t['title']}", "", t["intro"], "", t["how"], ""]
    table = latest_per_configuration(rows)
    if not table:
        return "\n".join(out + [t["empty"], ""])
    out.append("| " + " | ".join(t["cols"]) + " |")
    out.append("|" + "---|" * len(t["cols"]))
    for r in table:
        outcome = r.get("outcome", {})
        per_row = r.get("categorizing_s_per_row")
        out.append("| " + " | ".join([
            _clean(r.get("version")),
            _clean(r.get("os_name")),
            _clean(_arch(r.get("arch", ""))),
            _clean(r.get("gpu")) or "-",
            _runs_on(r),
            _clean(r.get("install_method")),
            *(t["yes"] if outcome.get(k) else t["no"] for k, _ in OUTCOMES),
            f"{per_row:.3f}" if isinstance(per_row, (int, float)) else "-",
            f"#{int(r.get('issue', 0))}",
        ]) + " |")
    return "\n".join(out + [""])


def write_docs(rows: list[dict], docs: Path) -> None:
    (docs / "compatibility.md").write_text(render(rows, "en"), encoding="utf-8")
    (docs / "compatibility.it.md").write_text(render(rows, "it"), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--event", type=Path, help="GitHub event payload (issues)")
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--docs", type=Path, required=True)
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--summary", type=Path, help="write a one-line summary here for the issue comment")
    args = ap.parse_args(argv)

    rows = load_store(args.store)
    if not args.render_only:
        if not args.event:
            ap.error("--event is required unless --render-only")
        try:
            row = row_from_event(json.loads(args.event.read_text(encoding="utf-8")))
        except ReportError as exc:
            if args.summary:
                args.summary.write_text(f"error: {exc}\n", encoding="utf-8")
            print(f"not a readable report: {exc}", file=sys.stderr)
            return 2
        rows = upsert(rows, row)
        save_store(args.store, rows)
        if args.summary:
            args.summary.write_text(
                f"{row['version']} | {row['os_name']} | {_arch(row['arch'])} | "
                f"{row['gpu'] or '-'} | {_runs_on(row)} | {row['install_method']}\n",
                encoding="utf-8",
            )
    write_docs(rows, args.docs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
