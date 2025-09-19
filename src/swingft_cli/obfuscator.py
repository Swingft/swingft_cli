"""
obfuscator.py: Swift code obfuscation stub and project file extraction.
"""

import os
import plistlib
import re
import sys
from typing import Dict, List
from swingft_cli.core.project import EXCLUDE_DIR_NAMES, iter_swift_files, collect_project_sidecar_files
from swingft_cli.core.fs import read_plist_as_text, read_text_fallback, flatten_relpath_for_sidecar
from swingft_cli.core.engine import apply_obfuscation

try:
    # 선택적 의존: 규칙 추출만 사용
    from swingft_cli.config import extract_rule_patterns
except Exception:  # 런타임 환경에 따라 미존재 가능
    extract_rule_patterns = None  # type: ignore

# Directories to ignore moved to core.project.EXCLUDE_DIR_NAMES

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
        return collect_project_sidecar_files(root_dir, exts)

    def read_plist_as_text_local(plist_path: str) -> str:
        return read_plist_as_text(plist_path)

    def save_project_file_as_text(src_path: str, rel_path: str, output_dir: str) -> None:
        flat_name = flatten_relpath_for_sidecar(rel_path)
        dst_path = os.path.join(output_dir, 'project_info', flat_name)
        if src_path.endswith('.plist'):
            text = read_plist_as_text_local(src_path)
        else:
            text, mode = read_text_fallback(src_path)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(dst_path, mode) as f:
            f.write(text)

    # Determine log file path and open log file
    log_path = os.path.join(output_path, 'obfuscator.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_file = open(log_path, 'w', encoding='utf-8')

    patterns: Dict[str, List[str]] = {}
    if exclude_json and extract_rule_patterns is not None:
        # config 로더에서 규칙을 가져오되, 이 함수는 파일을 다시 열지 않는다
        try:
            import json
            with open(exclude_json, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            patterns = extract_rule_patterns(cfg)
        except Exception:
            patterns = {}

    try:
        # Handle single file
        if os.path.isfile(input_path):
            with open(input_path, 'r', encoding='utf-8') as infile:
                code = infile.read()
            # TODO: 실제 난독화 로직 적용 전, 규칙 존재 여부 로그 남김
            if patterns:
                log_file.write("[info] rules loaded for single-file processing\n")
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            transformed = apply_obfuscation(code, patterns)
            with open(output_path, 'w', encoding='utf-8') as outfile:
                outfile.write(transformed)
            log_file.write(f"{output_path}\n")
        # Handle directory
        elif os.path.isdir(input_path):
            # Gather all .swift files first
            swift_files = list(iter_swift_files(input_path))
            total = len(swift_files)
            for idx, (src_file, rel_path) in enumerate(swift_files):
                dst_file = os.path.join(output_path, rel_path)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                with open(src_file, 'r', encoding='utf-8') as infile:
                    code = infile.read()
                transformed = apply_obfuscation(code, patterns)
                with open(dst_file, 'w', encoding='utf-8') as outfile:
                    outfile.write(transformed)
                # Write to log and print progress bar
                log_file.write(f"{rel_path}\n")
                # 최소 규칙 적용 스텁: include/exclude 문자열이 파일 경로에 매칭되면 로그에 표시
                if patterns:
                    matched = []
                    for key, arr in patterns.items():
                        for p in arr:
                            if _match_wildcard(rel_path, p):
                                matched.append(f"{key}:{p}")
                    if matched:
                        log_file.write("[match] " + ", ".join(matched) + "\n")
                bar = ('#' * ((idx + 1) * 20 // total)).ljust(20, ' ')
                percent = (idx + 1) * 100 // total if total > 0 else 100
                print(f"\r[{bar}] {percent}%", end='', flush=True)
            print()  # finish progress line
            # Collect project-related files
            project_files = find_project_files(input_path)
            for src_path in project_files:
                rel_path = os.path.relpath(src_path, input_path)
                save_project_file_as_text(src_path, rel_path, output_path)
                flat = flatten_relpath_for_sidecar(rel_path)
                log_file.write(f"{os.path.join('project_info', flat)}\n")
        else:
            print("Error: Input path is neither file nor directory")
    finally:
        log_file.close()


def _match_wildcard(text: str, pattern: str) -> bool:
    """간단한 와일드카드 매칭 ('*'만 지원)"""
    if pattern == "*":
        return True
    # 여러 개의 '*'를 지원하기 위해 분해 후 순서 포함 여부 확인
    parts = pattern.split('*')
    if not parts:
        return text == pattern
    pos = 0
    for i, part in enumerate(parts):
        if not part:
            continue
        idx = text.find(part, pos)
        if idx < 0:
            return False
        pos = idx + len(part)
    # 패턴이 '*'로 끝나지 않으면 마지막 부분 이후로 텍스트가 끝나야 한다는 제약을 두지 않는다
    return True