

import os
import sys

def handle_obfuscate(args):
    from swingft_cli.validator import check_permissions
    import swingft_cli.obfuscator as obf

    check_permissions(args.input, args.output)

    print("Start Swingft ...")
    print_banner()

    config_path = 'swingft_config.json' if args.exclude else None
    if args.exclude and not os.path.exists(config_path):
        print(f"Error: {config_path} not found. You can generate a sample file using the --json option.")
        sys.exit(1)

    obf.obfuscate(args.input, args.output, config_path)


def print_banner():
    banner = r"""
__     ____            _              __ _
\ \   / ___|_       _ (_)_ __   __ _ / _| |_
 \ \  \___  \ \ /\ / /| | '_ \ / _` | |_| __|
 / /   ___) |\ V  V / | | | | | (_) |  _| |_
/_/___|____/  \_/\_/  |_|_| |_|\__, |_|  \__|
 |_____|                       |___/
    """
    print(banner)