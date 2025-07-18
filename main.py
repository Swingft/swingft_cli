import argparse
import sys
import os
from obfuscator import obfuscate
from config_json import write_config_json
from validator import check_permissions


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

    args = parser.parse_args()

    if args.json is not None:
        write_config_json(args.json)
        sys.exit(0)

    if args.command == 'obfuscate':
        check_permissions(args.input, args.output)
        exclude_json = None
        if args.exclude:
            config_path = 'swingft_config.json'
            if not os.path.exists(config_path):
                print(f"Error: {config_path} not found. You can generate a sample file using the --json option.")
                sys.exit(1)
            exclude_json = config_path
        obfuscate(args.input, args.output, exclude_json)

if __name__ == "__main__":
    main()