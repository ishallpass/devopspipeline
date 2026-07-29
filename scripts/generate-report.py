#!/usr/bin/env python3
"""Aggregate DevSecOps scan outputs into a single Markdown report.

This script reads the JSON/text reports produced by the pipeline tools
(Gitleaks, Semgrep, Trivy, njsscan, Nmap and the endpoint tester) from the
``reports/`` directory and consolidates them into ``reports/final_report.md``
with a severity breakdown, per-tool coverage and a findings table.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List

# A single normalized finding shared across every parser.
Finding = Dict[str, Any]

SEVERITY_ORDER: List[str] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"]
_KNOWN_SEVERITIES = set(SEVERITY_ORDER)


class ReportParsingError(Exception):
    """Raised when a tool report exists but cannot be parsed."""

    def __init__(self, filepath: str, reason: str) -> None:
        super().__init__(f"Failed to parse '{filepath}': {reason}")
        self.filepath = filepath
        self.reason = reason


def _normalize_severity(raw: str) -> str:
    """Map a tool-specific severity string onto our canonical scale.

    Args:
        raw: The severity value emitted by a scanner (any case).

    Returns:
        One of ``SEVERITY_ORDER``; ``UNKNOWN`` when unrecognized.
    """
    value = (raw or "").strip().upper()
    aliases = {
        "ERROR": "HIGH",
        "WARNING": "MEDIUM",
        "WARN": "MEDIUM",
        "INFORMATION": "INFO",
        "INFORMATIONAL": "INFO",
    }
    value = aliases.get(value, value)
    return value if value in _KNOWN_SEVERITIES else "UNKNOWN"


def parse_gitleaks(data: Any) -> List[Finding]:
    """Parse a Gitleaks JSON report.

    Gitleaks emits either a top-level list of findings (v8+) or an object with
    a ``leaks`` key (older versions); both shapes are handled.
    """
    findings: List[Finding] = []
    leaks = data.get("Findings", []) if isinstance(data, dict) else data
    if not isinstance(leaks, list):
        return findings
    for leak in leaks:
        findings.append(
            {
                "tool": "Gitleaks",
                "severity": "HIGH",
                "file": leak.get("File", leak.get("file", "")),
                "line": leak.get("StartLine", leak.get("line", 0)),
                "description": leak.get("RuleID", leak.get("rule", "secret detected")),
            }
        )
    return findings


def parse_semgrep(data: Any) -> List[Finding]:
    """Parse a Semgrep JSON report (``results`` array)."""
    findings: List[Finding] = []
    if not isinstance(data, dict):
        return findings
    for res in data.get("results", []):
        extra = res.get("extra", {})
        findings.append(
            {
                "tool": "Semgrep",
                "severity": _normalize_severity(extra.get("severity", "")),
                "file": res.get("path", ""),
                "line": res.get("start", {}).get("line", 0),
                "description": extra.get("message", res.get("check_id", "")),
            }
        )
    return findings


def parse_trivy(data: Any) -> List[Finding]:
    """Parse a Trivy JSON report (filesystem or container image)."""
    findings: List[Finding] = []
    if not isinstance(data, dict):
        return findings
    for result in data.get("Results", []) or []:
        target = result.get("Target", "")
        for vuln in result.get("Vulnerabilities", []) or []:
            findings.append(
                {
                    "tool": "Trivy",
                    "severity": _normalize_severity(vuln.get("Severity", "")),
                    "file": target,
                    "description": vuln.get("Title", vuln.get("Description", "")),
                    "vuln_id": vuln.get("VulnerabilityID", ""),
                }
            )
    return findings


def parse_njsscan(data: Any) -> List[Finding]:
    """Parse an njsscan JSON report.

    njsscan groups findings by rule id under the ``nodejs`` and ``templates``
    sections, with per-rule ``metadata`` and a list of matched ``files``.
    """
    findings: List[Finding] = []
    if not isinstance(data, dict):
        return findings
    for section in ("nodejs", "templates"):
        rules = data.get(section) or {}
        for rule_id, info in rules.items():
            metadata = info.get("metadata", {})
            severity = _normalize_severity(metadata.get("severity", ""))
            description = metadata.get("description", rule_id)
            for match in info.get("files", []):
                match_lines = match.get("match_lines") or [0]
                findings.append(
                    {
                        "tool": "njsscan",
                        "severity": severity,
                        "file": match.get("file_path", ""),
                        "line": match_lines[0],
                        "description": description,
                    }
                )
    return findings


def parse_nmap(text: str) -> List[Finding]:
    """Extract open/filtered ports from Nmap normal (``-oN``) output."""
    findings: List[Finding] = []
    for line in text.splitlines():
        if "open" not in line and "filtered" not in line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        port, state, service = parts[0], parts[1], parts[2]
        findings.append(
            {
                "tool": "Nmap",
                "severity": "INFO",
                "file": "nmap.txt",
                "description": f"Port {port} state: {state} ({service})",
            }
        )
    return findings


def parse_endpoint_test(text: str) -> List[Finding]:
    """Derive severities from HTTP status codes in the endpoint test log."""
    status_severity = {"2": "INFO", "3": "LOW", "4": "MEDIUM", "5": "HIGH"}
    findings: List[Finding] = []
    for line in text.splitlines():
        if "Status:" not in line:
            continue
        code = line.split("Status:", 1)[1].strip()
        severity = status_severity.get(code[:1], "UNKNOWN")
        findings.append(
            {
                "tool": "Endpoint Test",
                "severity": severity,
                "description": line.strip(),
            }
        )
    return findings


def load_json_report(filepath, parser):
    if not os.path.exists(filepath):
        return []
    with open(filepath) as f:
        data = json.load(f)
    if isinstance(data, dict):
        print(f"DEBUG: {filepath} keys = {list(data.keys())}")
    else:
        print(f"DEBUG: {filepath} is a {type(data)}")
    return parser(data)

def load_text_report(filepath: str, parser: Callable[[str], List[Finding]]) -> List[Finding]:
    """Load a plain-text report and parse it, tolerating a missing file."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
        return parser(text)
    except OSError as exc:
        print(f"WARNING: {ReportParsingError(filepath, str(exc))}", file=sys.stderr)
        return []


def collect_findings(report_dir: str) -> List[Finding]:
    print(f"DEBUG: report_dir = {report_dir}")
    print(f"DEBUG: files in {report_dir}: {os.listdir(report_dir) if os.path.exists(report_dir) else 'dir missing'}")
    """Load and merge findings from every known report in ``report_dir``."""
    findings: List[Finding] = []
    findings.extend(load_json_report(os.path.join(report_dir, "gitleaks.json"), parse_gitleaks))
    findings.extend(load_json_report(os.path.join(report_dir, "semgrep.json"), parse_semgrep))
    findings.extend(load_json_report(os.path.join(report_dir, "trivy-fs.json"), parse_trivy))
    findings.extend(load_json_report(os.path.join(report_dir, "trivy-container.json"), parse_trivy))
    findings.extend(load_json_report(os.path.join(report_dir, "njsscan.json"), parse_njsscan))
    findings.extend(load_text_report(os.path.join(report_dir, "nmap.txt"), parse_nmap))
    findings.extend(load_text_report(os.path.join(report_dir, "endpoint-test.txt"), parse_endpoint_test))
    return findings


def _write_summary(handle: Any, findings: List[Finding]) -> None:
    """Write the executive summary, severity breakdown and tool coverage."""
    severity_counts: Dict[str, int] = defaultdict(int)
    tool_counts: Dict[str, int] = defaultdict(int)
    for finding in findings:
        severity_counts[finding["severity"]] += 1
        tool_counts[finding["tool"]] += 1

    handle.write("## Executive Summary\n\n")
    handle.write(f"**Total Findings:** {len(findings)}\n\n")

    if severity_counts:
        handle.write("### Severity Breakdown\n\n")
        handle.write("| Severity | Count |\n| --- | --- |\n")
        for severity in SEVERITY_ORDER:
            if severity in severity_counts:
                handle.write(f"| {severity} | {severity_counts[severity]} |\n")
        handle.write("\n")

    if tool_counts:
        handle.write("### Findings per Tool\n\n")
        handle.write("| Tool | Findings |\n| --- | --- |\n")
        for tool, count in sorted(tool_counts.items()):
            handle.write(f"| {tool} | {count} |\n")
        handle.write("\n")


def _write_findings_table(handle: Any, findings: List[Finding], limit: int = 100) -> None:
    """Write a truncated table of individual findings."""
    handle.write("## Detailed Findings\n\n")
    if not findings:
        handle.write("No findings detected.\n\n")
        return

    handle.write("| # | Tool | Severity | File | Line | Description |\n")
    handle.write("| --- | --- | --- | --- | --- | --- |\n")
    for index, finding in enumerate(findings[:limit], start=1):
        description = str(finding.get("description", "")).replace("|", "\\|").replace("\n", " ")
        handle.write(
            f"| {index} | {finding.get('tool', 'Unknown')} | {finding.get('severity', 'UNKNOWN')} "
            f"| {finding.get('file', '')} | {finding.get('line', '')} | {description[:160]} |\n"
        )
    handle.write("\n")
    if len(findings) > limit:
        handle.write(f"*... and {len(findings) - limit} more findings.*\n\n")


def generate_report(report_dir: str = "reports") -> str:
    """Generate the consolidated Markdown report.

    Args:
        report_dir: Directory holding the individual tool reports; the final
            report is written here as ``final_report.md``.

    Returns:
        The path to the generated Markdown report.
    """
    os.makedirs(report_dir, exist_ok=True)
    findings = collect_findings(report_dir)
    output_path = os.path.join(report_dir, "final_report.md")

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("# DevSecOps Pipeline Report\n\n")
        handle.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        _write_summary(handle, findings)
        _write_findings_table(handle, findings)

        handle.write("## Available Reports\n\n")
        report_files = [
            name
            for name in sorted(os.listdir(report_dir))
            if name.endswith((".json", ".txt", ".html", ".md"))
        ]
        for name in report_files:
            handle.write(f"- `{name}`\n")

    print(f"Final report generated: {output_path}")
    print(f"Total findings: {len(findings)}")
    return output_path


if __name__ == "__main__":
    generate_report()
