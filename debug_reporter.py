import re
import os
import argparse
import shutil
from collections import defaultdict
from pathlib import Path

# 디버깅 심볼 함수 이름 목록
DEBUG_FUNC_NAMES = ["print", "debugPrint", "NSLog", "assert", "assertionFailure", "dump"]

# prefix(식별자.)가 붙은 호출은 제외하기 위한 정규식 (부정형 lookbehind)
PATTERN_MAP = {
    "print": re.compile(r'(?<![\w\.])print\s*\('),
    "debugPrint": re.compile(r'(?<![\w\.])debugPrint\s*\('),
    "NSLog": re.compile(r'(?<![\w\.])NSLog\s*\('),
    "assert": re.compile(r'(?<![\w\.])assert\s*\('),
    "assertionFailure": re.compile(r'(?<![\w\.])assertionFailure\s*\('),
    "dump": re.compile(r'(?<![\w\.])dump\s*\('),
}

SWIFT_PREFIX_PATTERNS = {name: re.compile(r'\bSwift\.' + name + r'\s*\(') for name in DEBUG_FUNC_NAMES}

THREAD_STACK_RE = re.compile(r'Thread\.callStackSymbols')

# match 위치 앞에 접두어(식별자 + '.')가 있는지 검사
def _has_prefix_before(start_idx: int, line: str) -> bool:
    i = start_idx - 1
    # 공백 건너뛰기
    while i >= 0 and line[i].isspace():
        i -= 1
    return i >= 0 and line[i] == '.'

def _module_name(file_path: str, project_root: str) -> str:
    """
    Heuristic:
      ‑ If path contains .../Sources/<TargetName>/...  → return <TargetName>
      ‑ Else                                        → return 'Default'
    Works well for SwiftPM layout; for other layouts falls back gracefully.
    """
    parts = Path(file_path).parts
    try:
        idx = parts.index('Sources')
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass
    return "Default"

MAX_LOOKAHEAD_LINES = 40  # 여러 줄 호출 탐색 시 최대 라인 수 제한

BACKUP_EXT = ".debugbak"   # extension for backup copies

SKIP_DIR_KEYWORDS = ["Pods/", ".build/", "Carthage/", "DerivedData/", "checkouts/"]
FUNC_DEF_RE = re.compile(r'^\s*(?:public|internal|private|fileprivate)?\s*(?:final\s+)?(?:static\s+)?func\b')

DEBUG_FUNC_DEF_RE = re.compile(
    r'^\s*(?:public|internal|private|fileprivate)?\s*(?:final\s+)?(?:static\s+)?func\s+('
    + "|".join(DEBUG_FUNC_NAMES) + r')\b'
)

def collect_until_balanced(lines, start_idx: int, start_col: int, max_lines: int = MAX_LOOKAHEAD_LINES) -> int:
    """start_idx/start_col 위치에서 여는 괄호 '(' 이후, 가장 바깥 괄호가 닫히는 줄 인덱스를 반환합니다.
    제한 라인 수(max_lines)를 넘으면 start_idx를 그대로 반환합니다."""
    depth = 1
    line_count = len(lines)
    end_line = min(line_count, start_idx + max_lines)
    for i in range(start_idx, end_line):
        line = lines[i]
        j = start_col + 1 if i == start_idx else 0
        while j < len(line):
            c = line[j]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i
            j += 1
    return start_idx

def find_matching_brace(lines, start_idx: int, start_col: int = -1, max_lines: int = MAX_LOOKAHEAD_LINES) -> int:
    """
    From `start_idx` (optionally from `start_col` on that line), find the line index
    where the opening '{' encountered first is balanced by its corresponding '}'.
    Returns the ending line index. Falls back to `start_idx` if not found within
    `max_lines`.
    """
    depth = 0
    line_count = len(lines)
    end_line = min(line_count, start_idx + max_lines)

    # prime the search to locate the first '{'
    i = start_idx
    col = start_col if start_col >= 0 else 0
    found_open = False

    while i < end_line:
        line = lines[i]
        j = col
        while j < len(line):
            c = line[j]
            if c == '{':
                depth += 1
                found_open = True
            elif c == '}':
                depth -= 1
                if found_open and depth == 0:
                    return i
            j += 1
        i += 1
        col = 0  # reset column after first line
    return start_idx

def is_func_definition_line(line: str) -> bool:
    return bool(FUNC_DEF_RE.match(line.lstrip()))

def is_comment_line(line: str) -> bool:
    ls = line.lstrip()
    return ls.startswith('//') or ls.startswith('///') or ls.startswith('/*') or ls.startswith('*')

def find_swift_files(root_dir):
    """
    주어진 디렉토리에서 모든 .swift 파일 경로를 찾습니다.
    """
    swift_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".swift"):
                full_path = os.path.join(dirpath, filename)
                if any(skip in full_path for skip in SKIP_DIR_KEYWORDS):
                    continue
                swift_files.append(full_path)
    return swift_files

def _delete_symbols_from_source(found_symbols: list[str]):
    """
    Remove lines containing the detected debug‑symbol calls from each file **in‑place**.
    """
    per_file: dict[str, set[int]] = defaultdict(set)
    for entry in found_symbols:
        try:
            # format: <file>:<line>: ...
            file_part, rest = entry.split(':', 1)
            line_no = int(rest.split(':', 1)[0])
            per_file[file_part].add(line_no)
        except ValueError:
            continue  # skip malformed

    for path, lines_to_remove in per_file.items():
        try:
            # create a single‑file backup once
            backup_path = path + BACKUP_EXT
            if not os.path.exists(backup_path):
                try:
                    shutil.copy2(path, backup_path)
                except Exception as e:
                    print(f"[WARN] Could not back up {path}: {e}")
            with open(path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()

            with open(path, 'w', encoding='utf-8') as f:
                for idx, content in enumerate(all_lines, 1):
                    if idx in lines_to_remove:
                        continue  # delete this line
                    f.write(content)
        except Exception as e:
            print(f"[WARN] Could not modify {path}: {e}")


# Helper to restore backup files
def restore_backups(root_dir: str):
    """
    Restore all *.debugbak backups under `root_dir`.
    """
    restored = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if not fn.endswith(BACKUP_EXT):
                continue
            backup_path = os.path.join(dirpath, fn)
            original_path = backup_path[:-len(BACKUP_EXT)]
            try:
                shutil.move(backup_path, original_path)
                restored += 1
                print(f"Restored {original_path}")
            except Exception as e:
                print(f"[WARN] Could not restore {original_path}: {e}")
    if restored == 0:
        print("No backups found to restore.")
    else:
        print(f"{restored} file(s) restored.")

def generate_debug_report(input_path, output_file, *, apply_removal=False):
    """
    입력 경로(.swift 파일 또는 디렉토리)에서 디버깅 심볼을 찾아 리포트 파일을 생성합니다.
    정규식 라인 매칭을 우선 사용하고, 괄호가 닫히지 않은 경우에만 최소 범위로 확장합니다.
    """
    if os.path.isfile(input_path):
        files_to_scan = [input_path]
    elif os.path.isdir(input_path):
        files_to_scan = find_swift_files(input_path)
    else:
        print(f"Error: Input path is not a valid file or directory: {input_path}")
        return

    # -------------------------------------------------
    # PASS 1. Collect custom debug function names per module
    # -------------------------------------------------
    module_user_defined: dict[str, set[str]] = defaultdict(set)
    project_root = input_path if os.path.isdir(input_path) else os.path.dirname(input_path)

    for p in files_to_scan:
        mod = _module_name(p, project_root)
        try:
            with open(p, "r", encoding="utf-8") as f:
                for ln in f:
                    m = DEBUG_FUNC_DEF_RE.match(ln)
                    if m:
                        module_user_defined[mod].add(m.group(1))
        except Exception:
            continue

    found_symbols = []
    for full_path in files_to_scan:
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            skip_until = -1
            for idx, line in enumerate(lines):
                if idx <= skip_until:
                    continue

                # Skip the body of user‑defined debug functions to avoid
                # flagging Swift.print/NSLog calls inside them.
                if DEBUG_FUNC_DEF_RE.match(line):
                    brace_pos = line.find('{')
                    end_idx = find_matching_brace(lines, idx, brace_pos)
                    skip_until = end_idx
                    continue

                if is_comment_line(line) or is_func_definition_line(line):
                    continue

                # 먼저 Thread.callStackSymbols 개별 처리
                if THREAD_STACK_RE.search(line):
                    found_symbols.append(f"{full_path}:{idx+1}: {line.rstrip()}")
                    continue

                current_module = _module_name(full_path, project_root)
                defined_in_module = module_user_defined.get(current_module, set())

                for name, pattern in PATTERN_MAP.items():
                    m = pattern.search(line)
                    swift_allowed = False
                    if not m:
                        m = SWIFT_PREFIX_PATTERNS[name].search(line)
                        if not m:
                            continue
                        swift_allowed = True

                    if name in defined_in_module and not swift_allowed:
                        continue
                    else:
                        # Not user-defined, so no special treatment needed here
                        pass

                    # logger.print / XXX.print 등 접두어(.)가 붙은 호출은 제외하되, Swift.는 허용
                    if _has_prefix_before(m.start(), line) and not swift_allowed:
                        continue

                    # 한 줄 내 괄호가 닫히면 그대로 기록
                    if line.count('(') == line.count(')'):
                        found_symbols.append(f"{full_path}:{idx+1}: {line.rstrip()}")
                        break

                    # 여러 줄에 걸친 호출 처리
                    open_pos = line.find('(', m.start())
                    if open_pos == -1:
                        found_symbols.append(f"{full_path}:{idx+1}: {line.rstrip()}")
                        break

                    end_idx = collect_until_balanced(lines, idx, open_pos)
                    for j in range(idx, end_idx + 1):
                        found_symbols.append(f"{full_path}:{j+1}: {lines[j].rstrip()}")
                    skip_until = end_idx
                    break
        except Exception as e:
            print(f"Warning: Could not read file: {full_path} - {e}")

    # 결과 리포트 파일 작성
    with open(output_file, "w", encoding="utf-8") as out:
        if found_symbols:
            out.write("\n".join(found_symbols))
        else:
            out.write("No debug symbols found.")
    
    print(f"Debug symbol report generated at: {output_file}")

    # Optional automatic removal
    if apply_removal and found_symbols:
        _delete_symbols_from_source(found_symbols)
        print("Debug symbol lines have been removed from source files.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Swift debug symbol reporter / remover")
    parser.add_argument("path", help="File or directory to scan")
    parser.add_argument("-o", "--output", default="debug_symbols_report.txt",
                        help="Destination report file (default: %(default)s)")
    parser.add_argument("--remove", action="store_true",
                        help="Delete detected debug‑symbol lines from source files")
    parser.add_argument("--restore", action="store_true",
                        help="Restore previously removed lines from backup files")
    args = parser.parse_args()

    if args.remove and args.restore:
        parser.error("Options --remove and --restore are mutually exclusive.")

    if args.restore:
        restore_backups(args.path)
        raise SystemExit(0)

    generate_debug_report(args.path, args.output, apply_removal=args.remove)