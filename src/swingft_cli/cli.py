
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

from swingft_cli.commands.json_cmd import handle_generate_json
from swingft_cli.commands.obfuscate_cmd import handle_obfuscate
from swingft_cli.commands.debug_report_cmd import handle_debug_report

def main():
    parser = argparse.ArgumentParser(description="Swingft CLI")
    parser.add_argument('--json', nargs='?', const='swingft_config.json', metavar='JSON_PATH',
                        help='Generate an example exclusion config JSON file and exit (default: swingft_config.json)')
    subparsers = parser.add_subparsers(dest='command')

    # Obfuscate command
    obfuscate_parser = subparsers.add_parser('obfuscate', help='Obfuscate Swift files')
    obfuscate_parser.add_argument('--input', '-i', required=True, help='Path to the input file or directory')
    obfuscate_parser.add_argument('--output', '-o', required=True, help='Path to the output file or directory')
    obfuscate_parser.add_argument('--exclude', action='store_true', 
                                  help='Use the exclusion list from swingft_config.json')

    # Debug-symbol report command
    report_parser = subparsers.add_parser('report-debug-symbols', help='디버깅 심볼을 찾아 리포트를 생성합니다.')
    report_parser.add_argument('--input', '-i', required=True, help='입력 파일 또는 디렉토리 경로')
    report_parser.add_argument('--output', '-o', default='debug_symbols_report.txt',
                               help='리포트 파일 경로 (기본: debug_symbols_report.txt)')
    report_parser.add_argument('--remove', action='store_true',
                               help='디버깅 심볼 줄을 삭제하고 .debugbak 백업을 생성합니다.')
    report_parser.add_argument('--restore', action='store_true',
                               help='.debugbak 백업으로부터 원본 파일을 복구합니다.')

    args = parser.parse_args()

    if args.json is not None:
        handle_generate_json(args.json)
        sys.exit(0)

    if args.command == 'obfuscate':
        handle_obfuscate(args)
    elif args.command == 'report-debug-symbols':
        handle_debug_report(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()