#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pipeline.py

Generate exceptions then run obfuscation with default flags.
This script also accepts common last.py flags directly and forwards them.
Enhanced with CFGWrappingUtils integration.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd: list[str]) -> int:
    print("[dyn_pipeline] $", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except FileNotFoundError as e:
        print(f"[dyn_pipeline] ERROR: command not found: {cmd[0]}", file=sys.stderr)
        return 127



def main() -> None:
    ap = argparse.ArgumentParser(description="Generate exceptions then run obfuscation with default flags.")
    
    # Core arguments
    ap.add_argument("--src", required=True, help="Swift project root to scan")
    ap.add_argument("--dst", required=True, help="Output directory for obfuscated project")
    
    
    # Exception handling
    ap.add_argument("--exceptions", help="Path to internal_list.json. If omitted, a temp file is used by default.")
    ap.add_argument("--store-exceptions-in-dst", action="store_true", 
                   help="If set and --exceptions is not given, store JSON at <dst>/.obf/internal_list.json instead of a temp dir.")
    
    # Generate exceptions options
    ap.add_argument("--gx-exclude-extensions", action="store_true",
                   help="Name-based: exclude functions declared inside extension blocks when generating exceptions JSON (default: OFF).")
    ap.add_argument("--gx-exclude-protocol-reqs", action="store_true",
                   help="Name-based: exclude protocol requirement names found in protocol declarations (default: OFF).")
    ap.add_argument("--gx-exclude-actors", action="store_true",
                   help="Name-based: exclude actor-isolated instance method names (default: OFF).")
    ap.add_argument("--gx-exclude-global-actors", action="store_true",
                   help="Name-based: exclude functions annotated with global actors (default: OFF).")
    
    # Last.py options
    ap.add_argument("--perfile-inject", action="store_true", help="Forward to last.py: enable code injection.")
    ap.add_argument("--overwrite", action="store_true", help="Forward to last.py: overwrite existing dst.")
    ap.add_argument("--debug", action="store_true", help="Forward to last.py: verbose logging.")
    ap.add_argument("--include-packages", action="store_true", help="Forward to last.py: include local Swift Packages in scan/injection (default: skipped).")
    ap.add_argument("--allow-internal-protocol-reqs", action="store_true",
                   help="Forward to last.py: allow implementations of INTERNAL protocol requirements.")
    ap.add_argument("--allow-external-extensions", action="store_true",
                   help="Forward to last.py: allow members declared in extensions whose parent type is NOT declared in this project.")
    ap.add_argument("--no-skip-ui", action="store_true",
                   help="Forward to last.py: include UI files in scanning/injection (default: skipped).")
    
    # Passthrough arguments
    ap.add_argument("last_passthrough", nargs="*", 
                   help="All args after '--' are forwarded verbatim to last.py.")
    
    args = ap.parse_args()

    gen_py = str(ROOT / "generate_exceptions.py")
    last_py = str(ROOT / "last.py")

    # Determine exceptions file path
    if args.exceptions:
        exceptions_file = args.exceptions
    elif args.store_exceptions_in_dst:
        exceptions_file = str(Path(args.dst) / ".obf" / "internal_list.json")
        os.makedirs(os.path.dirname(exceptions_file), exist_ok=True)
    else:
        # Use temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            exceptions_file = f.name

    # 1) generate exceptions
    step1 = [sys.executable, gen_py, "--project", args.src, "--output-json", exceptions_file]
    
    # Add generate exceptions options
    if args.gx_exclude_extensions:
        step1.append("--exclude-extensions")
    if args.gx_exclude_protocol_reqs:
        step1.append("--exclude-protocol-reqs")
    if args.gx_exclude_actors:
        step1.append("--exclude-actors")
    if args.gx_exclude_global_actors:
        step1.append("--exclude-global-actors")
    
    rc1 = run(step1)
    if rc1 != 0:
        sys.exit(rc1)


    # 2) run last.py using the generated exceptions
    step2 = [
        sys.executable, last_py,
        "--src", args.src,
        "--dst", args.dst,
        "--exceptions", exceptions_file,
    ]

    # Add last.py options
    if args.perfile_inject:
        step2.append("--perfile-inject")
    if args.overwrite:
        step2.append("--overwrite")
    if args.debug:
        step2.append("--debug")
    if args.include_packages:
        step2.append("--include-packages")
    if args.allow_internal_protocol_reqs:
        step2.append("--allow-internal-protocol-reqs")
    if args.allow_external_extensions:
        step2.append("--allow-external-extensions")
    if args.no_skip_ui:
        step2.append("--no-skip-ui")

    # Add passthrough arguments
    step2.extend(args.last_passthrough)

    rc2 = run(step2)
    if rc2 != 0:
        sys.exit(rc2)

    print("[dyn_pipeline] pipeline complete")


if __name__ == "__main__":
    main()

