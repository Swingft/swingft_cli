"""
obfuscator.py: Swift code obfuscation stub and project file extraction.
"""

import os
import plistlib
import re
import sys

# Directories to ignore when collecting project files
EXCLUDE_DIR_NAMES = {'.build', 'Pods', 'Carthage', 'Checkouts', '.swiftpm', 'DerivedData', 'Tuist', '.xcodeproj'}

def obfuscate(input_path: str, output_path: str, exclude_json: str = None) -> None:
    """
    Read input_path (file or directory), perform obfuscation (currently no-op),
    and write to output_path. If exclude_json is provided, use it for exclusion rules.
    Also collects project-related files into a project_info folder.
    """
    def find_project_files(root_dir, exts=(
        '.plist', '.xcodeproj', '.xcworkspace', '.swiftpm',
        '.pbxproj', '.xcconfig', '.entitlements', '.modulemap',
        '.xcsettings', '.xcuserstate', '.xcworkspacedata',
        '.xcscheme', '.xctestplan', '.xcassets', '.storyboard',
        '.xcdatamodeld', '.xcappdata', '.xcfilelist',
        '.xcplayground', '.xcplaygroundpage', '.xctemplate',
        '.xcsnippet', '.xcstickers', '.xcstickersicon',
        '.xcuserdatad'
    )):
        project_files = []
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Skip external or build directories
            parts = set(dirpath.split(os.sep))
            if parts & EXCLUDE_DIR_NAMES:
                continue
            for filename in filenames:
                if filename.endswith(exts):
                    project_files.append(os.path.join(dirpath, filename))
        return project_files

    def read_plist_as_text(plist_path: str) -> str:
        with open(plist_path, 'rb') as f:
            try:
                data = plistlib.load(f)
                return str(data)
            except Exception:
                f.seek(0)
                return f.read().decode('utf-8', errors='replace')

    def save_project_file_as_text(src_path: str, rel_path: str, output_dir: str) -> None:
        flat_name = re.sub(r'[\\/]', '_', rel_path) + '.txt'
        dst_path = os.path.join(output_dir, 'project_info', flat_name)
        if src_path.endswith('.plist'):
            text = read_plist_as_text(src_path)
        else:
            try:
                with open(src_path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except Exception:
                with open(src_path, 'rb') as f:
                    text = f.read()
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        mode = 'w' if isinstance(text, str) else 'wb'
        with open(dst_path, mode) as f:
            f.write(text)

    # Determine log file path and open log file
    log_path = os.path.join(output_path, 'obfuscator.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_file = open(log_path, 'w', encoding='utf-8')

    try:
        # Handle single file
        if os.path.isfile(input_path):
            with open(input_path, 'r', encoding='utf-8') as infile:
                code = infile.read()
            # TODO: apply exclude_json rules here
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as outfile:
                outfile.write(code)
            log_file.write(f"{output_path}\n")
        # Handle directory
        elif os.path.isdir(input_path):
            # Gather all .swift files first
            swift_files = []
            for dirpath, _, filenames in os.walk(input_path):
                parts = set(dirpath.split(os.sep))
                if parts & EXCLUDE_DIR_NAMES:
                    continue
                for filename in filenames:
                    if filename.endswith('.swift'):
                        src_file = os.path.join(dirpath, filename)
                        rel_path = os.path.relpath(src_file, input_path)
                        swift_files.append((src_file, rel_path))
            total = len(swift_files)
            for idx, (src_file, rel_path) in enumerate(swift_files):
                dst_file = os.path.join(output_path, rel_path)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                with open(src_file, 'r', encoding='utf-8') as infile:
                    code = infile.read()
                with open(dst_file, 'w', encoding='utf-8') as outfile:
                    outfile.write(code)
                # Write to log and print progress bar
                log_file.write(f"{rel_path}\n")
                bar = ('#' * ((idx + 1) * 20 // total)).ljust(20, ' ')
                percent = (idx + 1) * 100 // total if total > 0 else 100
                print(f"\r[{bar}] {percent}%", end='', flush=True)
            print()  # finish progress line
            # Collect project-related files
            project_files = find_project_files(input_path)
            for src_path in project_files:
                rel_path = os.path.relpath(src_path, input_path)
                save_project_file_as_text(src_path, rel_path, output_path)
                flat = re.sub(r'[\\/]', '_', rel_path) + '.txt'
                log_file.write(f"{os.path.join('project_info', flat)}\n")
        else:
            print("Error: Input path is neither file nor directory")
    finally:
        log_file.close()