#!/usr/bin/env python3
import os
import sys
# Ensure 'src' is on sys.path so `-m swingft_cli.cli` works without installation
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir))
src_dir = os.path.join(project_root, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import argparse
import json
from pathlib import Path

from swingft_cli.commands.json_cmd import handle_generate_json
from swingft_cli.commands.obfuscate_cmd import handle_obfuscate
# from swingft_cli.commands.debug_report_cmd import handle_debug_report  # 디버깅 심볼 기능 연결 해제

# ------------------------------
# Preflight: ast_node.json vs swingft_config.json overlap check
# ------------------------------



def _collect_config_sets(cfg: dict):
    """Pick include/exclude sets from swingft_config.json structure.
    Expected keys: include.obfuscation, exclude.obfuscation, include.encryption, exclude.encryption (each list[str]).
    Returns a dict of 4 sets.
    """
    inc = cfg.get("include", {}) if isinstance(cfg.get("include"), dict) else {}
    exc = cfg.get("exclude", {}) if isinstance(cfg.get("exclude"), dict) else {}

    def _as_set(d: dict, key: str):
        arr = d.get(key, []) if isinstance(d, dict) else []
        return set(x.strip() for x in arr if isinstance(x, str) and x.strip())

    return {
        "inc_obf": _as_set(inc, "obfuscation"),
        "exc_obf": _as_set(exc, "obfuscation"),
        "inc_enc": _as_set(inc, "encryption"),
        "exc_enc": _as_set(exc, "encryption"),
    }


def _preflight_check_exceptions(config_path: Path, ast_path: Path, *, fail_on_conflict: bool = False):
    """Load config & ast_node JSON, report overlaps. Optionally abort on conflicts."""
    if not ast_path.exists():
        print(f"[preflight] warning: AST node file not found: {ast_path}")
        return
    if not config_path.exists():
        print(f"[preflight] warning: config not found: {config_path}")
        return

    try:
        ast_list = json.loads(ast_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[preflight] warning: malformed AST node file ({ast_path}): {e}")
        return

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[preflight] warning: malformed config ({config_path}): {e}")
        return

    # Extract excluded identifiers from AST nodes (isException: 1)
    exc_all_names = set()
    if isinstance(ast_list, list):
        for item in ast_list:
            if isinstance(item, dict):
                name = str(item.get("A_name", "")).strip()
                is_exception = item.get("isException", 0)
                if name and is_exception == 1:
                    exc_all_names.add(name)

    cfg_sets = _collect_config_sets(cfg)

    conflicts = {
        "obf_include_vs_exception": cfg_sets["inc_obf"] & exc_all_names,
        "obf_exclude_vs_exception": cfg_sets["exc_obf"] & exc_all_names,
        "enc_include_vs_exception": cfg_sets["inc_enc"] & exc_all_names,
        "enc_exclude_vs_exception": cfg_sets["exc_enc"] & exc_all_names,
    }

    any_conflict = any(conflicts[k] for k in conflicts)
    if any_conflict:
        print("\n[preflight] ⚠️  제외 대상과 config 겹침 발견")
        for key, vals in conflicts.items():
            if vals:
                sample = ", ".join(sorted(list(vals))[:10])
                print(f"  - {key}: {len(vals)}건 (예: {sample})")
        if fail_on_conflict:
            raise SystemExit("[preflight] conflicts detected; aborting due to fail_on_conflict=True")
    else:
        print("[preflight] 제외 대상과 config 충돌 없음 ✅")

def main():
    parser = argparse.ArgumentParser(description="Swingft CLI")
    parser.add_argument('--json', nargs='?', const='swingft_config.json', metavar='JSON_PATH',
                        help='Generate an example exclusion config JSON file and exit (default: swingft_config.json)')
    subparsers = parser.add_subparsers(dest='command')

    # Obfuscate command
    obfuscate_parser = subparsers.add_parser('obfuscate', help='Obfuscate Swift files')
    obfuscate_parser.add_argument('--input', '-i', required=True, help='Path to the input file or directory')
    obfuscate_parser.add_argument('--output', '-o', required=True, help='Path to the output file or directory')
    obfuscate_parser.add_argument('--config', '-c', nargs='?', const='swingft_config.json',
                                  help='Path to config JSON (default when flag present: swingft_config.json)')
    obfuscate_parser.add_argument('--check-rules', action='store_true',
                                  help='Scan project and print which identifiers from config are present')
    obfuscate_parser.add_argument('--encryption-only', action='store_true',
                                  help='Show only encryption-related logs')

    # Debug-symbol report command 비활성화: 난독화 파이프라인으로 이관됨
    # report_parser = subparsers.add_parser('report-debug-symbols', help='디버깅 심볼을 찾아 리포트를 생성합니다.')
    # report_parser.add_argument('--input', '-i', required=True, help='입력 파일 또는 디렉토리 경로')
    # report_parser.add_argument('--output', '-o', default='debug_symbols_report.txt',
    #                            help='리포트 파일 경로 (기본: debug_symbols_report.txt)')
    # report_parser.add_argument('--remove', action='store_true',
    #                            help='디버깅 심볼 줄을 삭제하고 .debugbak 백업을 생성합니다.')
    # report_parser.add_argument('--restore', action='store_true',
    #                            help='.debugbak 백업으로부터 원본 파일을 복구합니다.')

    args = parser.parse_args()

    if args.json is not None:
        handle_generate_json(args.json)
        sys.exit(0)

    if args.command == 'obfuscate':
        # --- Sync CLI paths into config via env; config.py will write back to JSON ---
        inp = getattr(args, 'input', None)
        out = getattr(args, 'output', None)
        if inp:
            os.environ["SWINGFT_PROJECT_INPUT"] = inp
        if out:
            os.environ["SWINGFT_PROJECT_OUTPUT"] = out
        # Ensure JSON gets updated for future runs
        os.environ.setdefault("SWINGFT_WRITE_BACK", "1")

        # 규칙 검사 출력 비활성화: 프리플라이트만 유지
        if hasattr(args, 'check_rules') and args.check_rules:
            args.check_rules = False

        # Preflight checks are now handled in obfuscate_cmd.py

        handle_obfuscate(args)
    # elif args.command == 'report-debug-symbols':
    #     handle_debug_report(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()