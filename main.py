import argparse
import sys
import os
from obfuscator import obfuscate
from config_json import write_config_json
from validator import check_permissions
from debug_reporter import generate_debug_report
from debug_reporter import restore_backups


def main():
    parser = argparse.ArgumentParser(description="Swingft CLI")
    parser.add_argument('--json', nargs='?', const='swingft_config.json', metavar='JSON_PATH',
                        help='Generate an example exclusion config JSON file and exit (default: swingft_config.json)')
    subparsers = parser.add_subparsers(dest='command')

    obfuscate_parser = subparsers.add_parser('obfuscate', help='Obfuscate Swift files')
    obfuscate_parser.add_argument('--input', '-i', required=True, help='Path to the input file or directory')
    obfuscate_parser.add_argument('--output', '-o', required=True, help='Path to the output file or directory')
    obfuscate_parser.add_argument('--exclude', action='store_true',
                                  help='Use the exclusion list from swingft_config.json')

    report_parser = subparsers.add_parser('report-debug-symbols', help='디버깅 심볼을 찾아 리포트를 생성합니다.')
    report_parser.add_argument('--input', '-i', required=True, help='입력 파일 또는 디렉토리 경로')
    report_parser.add_argument('--output', '-o', default='debug_symbols_report.txt', help='리포트 파일 경로 (기본: debug_symbols_report.txt)')
    report_parser.add_argument('--remove', action='store_true',
                               help='디버깅 심볼 줄을 삭제하고 .debugbak 백업을 생성합니다.')
    report_parser.add_argument('--restore', action='store_true',
                               help='.debugbak 백업으로부터 원본 파일을 복구합니다.')

    args = parser.parse_args()

    if args.json is not None:
        write_config_json(args.json)
        sys.exit(0)

    if args.command == 'obfuscate':
        check_permissions(args.input, args.output)
        # Fancy banner
        banner = r"""
__     ____            _              __ _
\ \   / ___|_       _ (_)_ __   __ _ / _| |_
 \ \  \___  \ \ /\ / /| | '_ \ / _` | |_| __|
 / /   ___) |\ V  V / | | | | | (_) |  _| |_
/_/___|____/  \_/\_/  |_|_| | |\__, |_|  \__|
 |_____|                       |___/
"""
        print("Start Swingft ...")
        print(banner)
        exclude_json = None
        if args.exclude:
            config_path = 'swingft_config.json'
            if not os.path.exists(config_path):
                print(f"Error: {config_path} not found. You can generate a sample file using the --json option.")
                sys.exit(1)
            exclude_json = config_path
        obfuscate(args.input, args.output, exclude_json)
    elif args.command == 'report-debug-symbols':
        # Mutual exclusivity check
        if args.remove and args.restore:
            print("Error: --remove and --restore cannot be used together.")
            sys.exit(1)

        if args.restore:
            restore_backups(args.input)
        else:
            generate_debug_report(args.input,
                                  args.output,
                                  apply_removal=args.remove)

if __name__ == "__main__":
    main()