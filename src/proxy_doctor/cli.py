"""CLI entry point for proxy-doctor.

Usage:
    proxy-doctor check [--json | --human] [--editor NAME]
    proxy-doctor fix [--editor NAME]
    proxy-doctor editors
"""

from __future__ import annotations

import argparse
import json
import sys

from proxy_doctor import __version__
from proxy_doctor.core import run_diagnosis
from proxy_doctor.editors import list_editors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proxy-doctor",
        description="Diagnose proxy misconfigurations that break AI coding tools.",
    )
    parser.add_argument(
        "--version", action="version", version=f"proxy-doctor {__version__}",
    )

    sub = parser.add_subparsers(dest="command")

    # check
    p_check = sub.add_parser("check", help="Run proxy diagnosis")
    fmt = p_check.add_mutually_exclusive_group()
    fmt.add_argument("--json", dest="output_json", action="store_true", default=True,
                     help="Output JSON (default)")
    fmt.add_argument("--human", dest="output_json", action="store_false",
                     help="Output human-readable text")
    p_check.add_argument("--editor", default="cursor",
                         help="Editor to check (default: cursor)")
    p_check.add_argument("--markdown", metavar="FILE",
                         help="Also write markdown report to FILE")

    # fix
    p_fix = sub.add_parser("fix", help="Show recommended fixes")
    p_fix.add_argument("--editor", default="cursor",
                       help="Editor to check (default: cursor)")

    # editors
    sub.add_parser("editors", help="List supported editors")

    return parser


def cmd_check(args: argparse.Namespace) -> int:
    report = run_diagnosis(args.editor)

    if args.output_json:
        print(report.to_json())
    else:
        print(report.to_human())

    if args.markdown:
        try:
            with open(args.markdown, "w", encoding="utf-8") as f:
                f.write(f"# proxy-doctor report\n\n```\n{report.to_human()}\n```\n\n")
                f.write(f"## Evidence (JSON)\n\n```json\n{report.to_json()}\n```\n")
            print(f"\nReport written to {args.markdown}", file=sys.stderr)
        except OSError as e:
            print(f"Failed to write report: {e}", file=sys.stderr)

    return 0 if report.diagnosis.status == "healthy" else 1


def cmd_fix(args: argparse.Namespace) -> int:
    report = run_diagnosis(args.editor)

    if not report.diagnosis.fixes:
        print(json.dumps({"status": "healthy", "fixes": []}, indent=2))
        return 0

    fixes_out = {
        "status": report.diagnosis.status,
        "case": report.diagnosis.case,
        "fixes": [
            {
                "fix_id": f.fix_id,
                "description": f.description,
                "command": f.command,
                "risk": f.risk,
                "layer": f.layer,
            }
            for f in report.diagnosis.fixes
        ],
    }
    print(json.dumps(fixes_out, indent=2))
    return 0 if report.diagnosis.status == "healthy" else 1


def cmd_editors(_args: argparse.Namespace) -> int:
    editors = list_editors()
    print(json.dumps({"supported_editors": editors}, indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    dispatch = {
        "check": cmd_check,
        "fix": cmd_fix,
        "editors": cmd_editors,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
