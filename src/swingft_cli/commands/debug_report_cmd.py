
from pathlib import Path
from swingft_cli.module_debug_runner import find_module_roots


import sys

from swingft_cli.debug_symbols import restore_debug_files
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from last_version import generate_debug_report

def handle_debug_report(args):
    """
    Handle the 'report-debug-symbols' command.
    Supports generating a report, deleting debug calls, or restoring from backups.
    """
    # --remove and --restore are mutually exclusive
    if args.remove and args.restore:
        print("Error: --remove and --restore cannot be used together.")
        sys.exit(1)

    # Restore from backups
    if args.restore:
        restore_debug_files(args.input)
        return

    project_root = Path(args.input).resolve()

    # Discover modules
    modules = find_module_roots(project_root)
    if not modules:
        # Fallback to single report
        generate_debug_report(
            project_path=args.input,
            out_path=args.output,
            apply_removal=args.remove,
            wrap_in_debug=False
        )
        print(f"[완료] 보고서 생성: {args.output}")
        return

    # Initialize combined report
    with open(args.output, "w", encoding="utf-8") as mainf:
        mainf.write("# Combined Debug Symbol Report\n\n")

    # Generate per-module and merge
    for mod in modules:
        rel = mod.relative_to(project_root)
        tmp = project_root / f".tmp_debug_{rel.name}.txt"
        print(f">>> Generating module: {rel}")
        generate_debug_report(
            project_path=str(mod),
            out_path=str(tmp),
            apply_removal=args.remove,
            wrap_in_debug=False
        )
        with open(args.output, "a", encoding="utf-8") as mainf, \
             open(tmp, "r", encoding="utf-8") as tf:
            mainf.write(f"## Module: {rel}\n")
            mainf.write(tf.read() + "\n\n")
        tmp.unlink()

    print(f"[완료] 통합 보고서 생성: {args.output}")