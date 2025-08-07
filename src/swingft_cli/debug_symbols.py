

"""
debug_symbols.py: Debug-symbol detection and report generation for Swift projects.
"""

from pathlib import Path
import sys
import shutil
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from pathlib import Path

from swingft_cli.parser import (
    detect_layout,
    spm_target_map_recursive,
    pbxproj_target_map,
)
from swingft_cli.utils import (
    DEBUG_FUNC_NAMES,
    PATTERN_MAP,
    SWIFT_PREFIX_PATTERNS,
    THREAD_STACK_RE,
    DEBUG_FUNC_DEF_RE,
    FUNC_DEF_RE,
    MAX_LOOKAHEAD_LINES,
    BACKUP_EXT,
    EXCLUDE_DIR_NAMES,
)

# ---------- Helpers for parsing code ----------
def _is_external(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)

def _collect_until_balanced(lines: List[str], i: int, col: int, limit: int = MAX_LOOKAHEAD_LINES) -> int:
    depth = 1
    for l in range(i, min(len(lines), i + limit)):
        start = col + 1 if l == i else 0
        for c in lines[l][start:]:
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return l
    return i

def _has_prefix_before(idx: int, line: str) -> bool:
    j = idx - 1
    while j >= 0 and line[j].isspace():
        j -= 1
    return j >= 0 and line[j] == '.'

def _find_matching_brace(lines: List[str], i: int, col: int = 0, limit: int = MAX_LOOKAHEAD_LINES) -> int:
    depth = 0
    for l in range(i, min(len(lines), i + limit)):
        for ch in lines[l][col:]:
            if ch == '{':
                depth += 1
            elif ch == '}' and depth > 0:
                return l
    return i

def is_comment_line(line: str) -> bool:
    ls = line.lstrip()
    return ls.startswith('//') or ls.startswith('/*') or ls.startswith('*')

def is_func_def_line(line: str) -> bool:
    return bool(FUNC_DEF_RE.match(line.lstrip()))

# ---------- Call detection ----------
def _regex_find_calls(
    fp: Path,
    user_defined_names: Set[str],
    *,
    fallback: bool,
    dir_shadowed: Dict[Path, Set[str]] = None,
    global_shadowed: Set[str] = None
) -> List[Tuple[int, int]]:
    try:
        lines = fp.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    spans: List[Tuple[int, int]] = []
    skip_until = -1
    for idx, line in enumerate(lines):
        if idx <= skip_until:
            continue
        if DEBUG_FUNC_DEF_RE.match(line):
            brace = line.find('{')
            if brace != -1:
                skip_until = _find_matching_brace(lines, idx, brace)
            continue
        if is_comment_line(line) or is_func_def_line(line):
            continue
        if THREAD_STACK_RE.search(line):
            spans.append((idx + 1, idx + 1))
            continue
        for name, pat in PATTERN_MAP.items():
            m = pat.search(line) or SWIFT_PREFIX_PATTERNS[name].search(line)
            swift_allowed = bool(SWIFT_PREFIX_PATTERNS[name].search(line))
            if not m:
                continue
            if name in user_defined_names and not swift_allowed:
                continue
            if fallback and global_shadowed and name in global_shadowed and not swift_allowed:
                continue
            if fallback and dir_shadowed and name in dir_shadowed.get(fp.parent, set()) and not swift_allowed:
                continue
            if _has_prefix_before(m.start(), line) and not swift_allowed:
                continue
            if line.count('(') == line.count(')'):
                spans.append((idx + 1, idx + 1))
            else:
                open_pos = line.find('(', m.start())
                end = _collect_until_balanced(lines, idx, open_pos if open_pos >= 0 else 0)
                spans.append((idx + 1, end + 1))
                skip_until = end
            break
    return spans

def _group_entries_for_report(entries: Dict[Path, List[Tuple[int, int]]]) -> List[str]:
    """
    Group detected spans into report lines, using filename only
    and adjusting for an initial blank line in files.
    Format: "<filename>:<start>-<end>: <snippet>"
    """
    out: List[str] = []
    for fp, spans in entries.items():
        # Read original lines and trim leading blank if present
        orig_lines = fp.read_text(encoding="utf-8").splitlines()
        if orig_lines and orig_lines[0].strip() == "":
            lines = orig_lines[1:]
            adjust = True
        else:
            lines = orig_lines
            adjust = False

        for (s, e) in spans:
            # Adjust span numbers if trimmed
            if adjust:
                s_adj = max(1, s - 1)
                e_adj = max(1, e - 1)
            else:
                s_adj = s
                e_adj = e

            snippet = lines[s_adj - 1].lstrip().rstrip() if 1 <= s_adj <= len(lines) else ""
            out.append(f"{fp.name}:{s_adj}-{e_adj}: {snippet}")
    return out

# ---------- Main report generation ----------
def generate_debug_report(
    project_path: str,
    out_path: str,
    *,
    apply_removal: bool = False,
    wrap_in_debug: bool = False
) -> None:
    root = Path(project_path).resolve()
    if not root.exists():
        sys.exit(f"Path not found: {root}")

    layout, anchor = detect_layout(root)

    # Single Swift file mode
    if layout == "file":
        target_map = {"(FILE)": {anchor}}
        fallback = False
    else:
        if layout == "spm":
            target_map = spm_target_map_recursive(root)
        else:
            pbx = anchor if anchor.suffix == ".pbxproj" else None
            target_map = pbxproj_target_map(pbx) if pbx else {}
        if not target_map or not any(target_map.values()):
            all_swift = [p for p in root.rglob("*.swift") if not _is_external(p)]
            target_map = {"(ALL)": set(all_swift)}
            fallback = True
        else:
            fallback = False

    # Store target_map as is for later grouping
    original_target_map = target_map

    # Collect user-defined overrides
    all_files: Set[Path] = set().union(*target_map.values())
    user_defined: Set[str] = set()
    for fp in all_files:
        for line in fp.read_text(encoding="utf-8").splitlines():
            if m := DEBUG_FUNC_DEF_RE.match(line):
                user_defined.add(m.group(1))

    # Grouped detection: module_entries[module_name][fp] = list of spans
    module_entries: Dict[str, Dict[Path, List[Tuple[int, int]]]] = {}
    for module_name, file_set in original_target_map.items():
        entries: Dict[Path, List[Tuple[int, int]]] = defaultdict(list)
        for fp in file_set:
            spans = _regex_find_calls(
                fp,
                user_defined,
                fallback=fallback,
                dir_shadowed=None,
                global_shadowed=None
            )
            if spans:
                entries[fp].extend(spans)
        module_entries[module_name] = entries

    # Log module separation
    for module_name, entries in module_entries.items():
        total = sum(len(spans) for spans in entries.values())
        print(f"[Module] {module_name}: {total} debug symbols")

    # Write report: grouped by module and save per-module files
    for_module_lines = {}
    for module_name in original_target_map:
        entries = module_entries[module_name]
        lines = _group_entries_for_report(entries)
        for_module_lines[module_name] = lines
        # write per-module file
        module_file = out_path.replace(".txt", f"_{module_name}.txt")
        with open(module_file, "w", encoding="utf-8") as mf:
            if lines:
                mf.write("\n".join(lines))
            else:
                mf.write("No debug symbols found.\n")
        print(f"[Saved] {module_file}")

    # Combined report
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Layout: {layout}\n")
        for module_name in original_target_map:
            f.write(f"## Module: {module_name}\n")
            f.write("# --------------------------------------\n")
            lines = for_module_lines[module_name]
            if lines:
                f.write("\n".join(lines) + "\n")
            else:
                f.write("No debug symbols found.\n")

def restore_debug_files(root_dir: str | None = None) -> None:
    """
    Restore original files from backups (.debugbak).
    """
    base = Path(root_dir).resolve() if root_dir else Path.cwd()
    restored = 0
    for bak in base.rglob(f"*{BACKUP_EXT}"):
        orig = bak.with_suffix(bak.suffix[:-len(BACKUP_EXT)])
        try:
            shutil.move(bak, orig)
            restored += 1
            print(f"[RESTORED] {orig}")
        except Exception as e:
            print(f"[WARN] {bak} → {orig}: {e}")
    if restored == 0:
        print("No backups found.")
    else:
        print(f"✔ Restored {restored} file(s).")