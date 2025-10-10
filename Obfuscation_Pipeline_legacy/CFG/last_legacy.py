#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
last.py
- Minimal scaffold for per-file dynamic-call obfuscation.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import hashlib
import shutil
import sys
from typing import Dict, List, Optional, Tuple, Set
from fnmatch import fnmatchcase

# ---------- global settings ----------
APP_TAG = "[dyn_obf]"
DEFAULT_SKIP_DIRS = {".git", ".build", "DerivedData", "Pods", "Carthage", ".swiftpm", "__MACOSX", "node_modules", "vendor"}

OBF_BEGIN, OBF_END = "// OBF-BEGIN", "// OBF-END"


# ---------- small utilities ----------
def log(msg: str) -> None: print(f"{APP_TAG} {msg}")
def fail(msg: str, code: int = 1) -> None: print(f"{APP_TAG} ERROR: {msg}", file=sys.stderr); sys.exit(code)
def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f: return f.read()
def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: f.write(text)
def dump_json(path: str, data) -> None: write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
def dump_text(path: str, lines: List[str]) -> None: write_text(path, "\n".join(lines) + ("\n" if lines else ""))

# ---------- precompiled regex (module scope) ----------
TYPE_DECL_RE = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*(?P<mods>(?:\w+\s+)*)(?P<tkind>class|struct|enum|actor|extension|protocol)\s+(?P<type_name>\w+)(?P<generics>\s*<[^>]+>)?", re.MULTILINE)
FUNC_DECL_RE = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*(?P<mods>(?:\w+\s+)*)func\s+(?P<name>\w+)\s*(?:<[^>]+>)?\s*\((?P<params>[^)]*)\)\s*(?:(?:async|re?throws)\s*)*(?:->\s*(?P<ret>[^\{]+))?")

# ---------- argument parsing ----------
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Per-file dynamic-call obfuscation tool.")
    ap.add_argument("--src", required=True, help="Source project root.")
    ap.add_argument("--dst", required=True, help="Output project root.")
    ap.add_argument("--exceptions", nargs='+', help="JSON exception files.")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing destination.")
    ap.add_argument("--debug", action="store_true", help="Verbose logging.")
    ap.add_argument("--perfile-inject", action="store_true", help="Enable code injection.")
    ap.add_argument("--dry-run", action="store_true", help="Scan only, no file edits.")
    ap.add_argument("--no-skip-ui", action="store_true", help="Do not skip UI-related files (default: skip UI files).")
    ap.add_argument("--max-params", type=int, default=10, help="Max params for generated wrappers (default: 5)")
    ap.add_argument("--dump-funcs-json", help="Dump all discovered functions to a JSON file.")
    ap.add_argument("--dump-funcs-txt", help="Dump all discovered functions to a text file.")
    ap.add_argument("--dump-funcs-json-clean", help="Dump functions after removing exceptions (JSON).")
    ap.add_argument("--dump-funcs-txt-clean", help="Dump functions after removing exceptions (text).")
    ap.add_argument("--dump-funcs-json-excluded", help="Dump only excluded functions (JSON).")
    ap.add_argument("--dump-funcs-txt-excluded", help="Dump only excluded functions (text).")
    ap.add_argument("--dump-funcs-json-safe", help="Dump risk-filtered safe functions (JSON).")
    ap.add_argument("--dump-funcs-txt-safe", help="Dump risk-filtered safe functions (text).")
    ap.add_argument("--dump-funcs-json-risky", help="Dump risky functions (JSON).")
    ap.add_argument("--dump-funcs-txt-risky", help="Dump risky functions (text).")
    ap.add_argument("--risk-keep-overrides", action="store_true", help="Keep 'override' methods in SAFE set.")
    ap.add_argument("--include-packages", action="store_true", help="Include local Swift Packages (directories containing Package.swift) in scanning and injection (default: skipped)")
    ap.add_argument("--skip-external-extensions", dest="skip_external_extensions", action="store_true", help="Skip functions declared in extensions whose parent type is NOT declared in this project.")
    ap.add_argument("--allow-external-extensions", dest="skip_external_extensions", action="store_false", help="Allow functions in extensions of types not declared in this project.")
    ap.add_argument("--skip-external-protocol-reqs", action="store_true", help="Skip functions that implement requirements of protocols declared OUTSIDE this project (default: on).")
    ap.add_argument("--allow-internal-protocol-reqs", action="store_true", help="Allow functions that implement requirements of protocols declared INSIDE this project (default: off).")
    ap.add_argument("--skip-external-protocol-extension-members", action="store_true", help="When an extension adds conformance to an EXTERNAL protocol (extension T: P), skip all functions in that extension (default: on).")
    ap.set_defaults(
        skip_external_extensions=True,
        skip_external_protocol_reqs=True,
        allow_internal_protocol_reqs=True,
        skip_external_protocol_extension_members=True,
        perfile_inject=True,
        overwrite=True,
        include_packages=True,
        no_skip_ui=True
    )
    return ap
# ---------- new: collect local declared types ----------
def collect_local_declared_types(project_root: str, *, include_packages: bool, debug: bool) -> set:
    """
    Collect names of types (class/struct/enum/actor) declared in *this project* (dst tree).
    We intentionally exclude 'extension' and 'protocol' from this set.
    Only top-level type names are recorded (heuristic is sufficient for external-extension detection).
    """
    local_types: set = set()
    files = iter_swift_files(project_root, skip_ui=False, debug=debug, exclude_file_globs=None, include_packages=include_packages)
    # Reuse TYPE_DECL_RE but filter by kind
    for abs_path in files:
        try:
            text = read_text(abs_path)
        except Exception:
            continue
        for m in TYPE_DECL_RE.finditer(text):
            kind = m.group('tkind')
            name = m.group('type_name')
            if kind in ('class', 'struct', 'enum', 'actor'):
                local_types.add(name)
    if debug:
        log(f"prepass: local declared types={len(local_types)}")
    return local_types

# ---------- core logic ----------
def is_ui_path(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/").lower()
    if any(seg in p for seg in ("/view/", "/views/", "viewcontroller")): return True
    base = os.path.basename(p)
    return base.endswith("view.swift") or base.endswith("viewcontroller.swift")

def is_extension_file(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/").lower()
    return "/extension/" in p or "/extensions/" in p or "+" in os.path.basename(p)

def copy_project_tree(src: str, dst: str, overwrite: bool = False) -> None:
    abs_src, abs_dst = os.path.abspath(src), os.path.abspath(dst)
    if not os.path.isdir(abs_src): fail(f"source is not a directory: {abs_src}")
    if abs_src == abs_dst: fail("src and dst must be different paths")
    if os.path.exists(abs_dst):
        if overwrite:
            log(f"removing existing dst: {abs_dst}")
            shutil.rmtree(abs_dst)
        else:
            fail(f"dst already exists: {abs_dst} (pass --overwrite to replace)")
    def ignore_filter(d, names):
        ignored = [name for name in names if name in DEFAULT_SKIP_DIRS]
        # ✅ .swiftpm 은 복사되도록 예외 처리
        if ".swiftpm" in ignored:
            ignored.remove(".swiftpm")
        return ignored
    shutil.copytree(abs_src, abs_dst, ignore=ignore_filter)
    log(f"cloning project → {abs_dst}")

def load_exceptions(paths: Optional[List[str]]) -> List[Dict]:
    if not paths: return []
    all_rules: List[Dict] = []
    for path in paths:
        if not os.path.exists(path): fail(f"exceptions file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
            if isinstance(data, list): all_rules.extend(data)
            elif isinstance(data, dict) and "rules" in data: all_rules.extend(data["rules"])
            else: fail(f"exceptions file must be a JSON list or {{'rules': [...]}}: {path}")
        except Exception as e: fail(f"error reading exceptions file {path}: {e}")
    return all_rules

# --- File exclusion helpers ---
def build_file_exclude_patterns(exceptions: List[Dict]) -> List[str]:
    """
    Collect file/path glob patterns from exceptions.
    Accepted keys per rule: 'file', 'path', 'glob' OR kind=='file' with 'name'/'A_name'.
    Patterns are matched case-insensitively against the *relative* path from project root.
    """
    patterns: List[str] = []
    for r in exceptions or []:
        kind = (r.get("B_kind") or r.get("kind") or "").lower()
        name = (r.get("A_name") or r.get("name") or "")
        # Direct keys
        for key in ("file", "path", "glob"):
            val = r.get(key)
            if isinstance(val, str) and val.strip():
                patterns.append(val.replace("\\", "/").lower())
        # kind-based
        if kind == "file" and isinstance(name, str) and name.strip():
            patterns.append(name.replace("\\", "/").lower())
    return patterns

def _file_matches_any(rel_path: str, patterns: List[str]) -> bool:
    """
    Return True if rel_path matches any of the provided glob patterns.
    Both the full relative path and the basename are tested.
    """
    p = rel_path.replace("\\", "/").lower()
    base = os.path.basename(p)
    for g in patterns or []:
        if fnmatchcase(p, g) or fnmatchcase(base, g):
            return True
    return False

def iter_swift_files(root: str, skip_ui: bool, debug: bool, exclude_file_globs: Optional[List[str]] = None, include_packages: bool = False) -> List[str]:
    results: List[str] = []
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_SKIP_DIRS and not d.startswith(".")]
        # If include_packages is False, skip local Swift Package directories (contain Package.swift)
        if 'Package.swift' in filenames and not include_packages:
            if debug: log(f"Skipping Swift Package directory: {os.path.relpath(dirpath, root_abs)}")
            dirnames[:] = []  # stop descending into package subdirectories
            continue

        for fn in filenames:
            if not fn.endswith(".swift"): continue
            abs_path = os.path.join(dirpath, fn)
            rel_path = os.path.relpath(abs_path, root_abs)

            # Exclude by exceptions (file/path globs)
            if exclude_file_globs and _file_matches_any(rel_path, exclude_file_globs):
                if debug: log(f"Skipping by exceptions (file): {rel_path}")
                continue


            if skip_ui and is_ui_path(rel_path):
                if debug: log(f"Skipping UI file: {rel_path}")
                continue

            results.append(abs_path)
    return results

# --- helpers for parameter parsing ---
_def_default_re = re.compile(r"=\s*[^,\)\r\n]+")


def _strip_param_defaults(params_src: str) -> str:
    """Remove default-value fragments (e.g., `= nil`, `= 0`, `= compute()`) from a
    raw Swift parameter list source so that type extraction is not polluted by
    defaults. This is *only* for type signature building, not for wrapper header.
    """
    return _def_default_re.sub("", params_src or "")

# --- robust default-parameter detection (match generate_exceptions.py policy) ---
def _split_params_top(params_src: str) -> List[str]:
    """Split a Swift parameter list by top-level commas (ignoring commas inside (), [], <>).
    This lets us examine each parameter segment reliably even when the list spans lines
    or contains function types/tuples/generics.
    """
    parts: List[str] = []
    if not params_src:
        return parts
    buf = []
    d_par = d_brk = d_ang = 0
    i = 0
    while i < len(params_src):
        ch = params_src[i]
        if ch == '(': d_par += 1
        elif ch == ')': d_par = max(0, d_par - 1)
        elif ch == '[': d_brk += 1
        elif ch == ']': d_brk = max(0, d_brk - 1)
        elif ch == '<': d_ang += 1
        elif ch == '>': d_ang = max(0, d_ang - 1)
        if ch == ',' and d_par == 0 and d_brk == 0 and d_ang == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append(''.join(buf))
    return parts

def _has_param_default(params_src: str) -> bool:
    """Return True if any top-level parameter has a default value (contains '=' at top level).
    This avoids false positives from nested expressions and works across newlines.
    """
    for seg in _split_params_top(params_src or ""):
        if '=' in seg:
            return True
    return False

# --- Protocol helpers ---

def _strip_comments(text: str) -> str:
    # remove /* ... */ then // ...
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    return text

def _strip_comments_preserve_layout(text: str) -> str:
    """
    Remove comments but preserve newlines/character positions so brace depth and
    line-based parsing remain stable. Non-newline characters inside comments are
    replaced with spaces. This helps the scanner ignore any 'func ...' patterns
    that appear inside comments without breaking depth tracking.
    """
    # Block comments: keep '\n', replace other characters with spaces
    def _repl_block(m: re.Match) -> str:
        s = m.group(0)
        return "".join("\n" if ch == "\n" else " " for ch in s)
    text = re.sub(r"/\*.*?\*/", _repl_block, text, flags=re.DOTALL)

    # Line comments: replace everything from '//' to end-of-line with spaces (preserve newline)
    def _repl_line(m: re.Match) -> str:
        s = m.group(0)
        # Preserve the ending newline if present; otherwise make an equal-length spaces run
        if s.endswith("\n"):
            return " " * (len(s) - 1) + "\n"
        return " " * len(s)

    text = re.sub(r"//.*?$", _repl_line, text, flags=re.MULTILINE)
    return text

def _find_protocol_blocks(text: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for m in re.finditer(r"\bprotocol\s+([A-Za-z_]\w*)\b[^\\{]*\{", text):
        name = m.group(1)
        i = m.end() - 1
        depth = 0
        start_body = i + 1
        j = i
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    results.append({"name": name, "body": text[start_body:j]})
                    break
            j += 1
    return results

def _param_external_labels_list(params_src: str) -> List[str]:
    labels: List[str] = []
    for seg in _split_params_top(params_src or ""):
        seg = seg.strip()
        if not seg:
            continue
        left = seg.split(":", 1)[0].strip()
        if not left:
            labels.append("_")
            continue
        toks = [t for t in re.split(r"\s+", left) if t and t != "_"]
        if left.startswith("_"):
            labels.append("_")
        elif len(toks) >= 2:
            labels.append(toks[0])
        else:
            labels.append(toks[0] if toks else "_")
    return labels

def _func_key(name: str, params_src: str) -> Tuple[str, int, Tuple[str, ...]]:
    labels = _param_external_labels_list(params_src)
    return (name, len(labels), tuple(labels))

def collect_local_protocol_requirements(project_root: str, *, include_packages: bool, debug: bool) -> Dict[str, Set[Tuple[str, int, Tuple[str, ...]]]]:
    """
    Build a map: protocolName -> set of requirement keys (name, arity, labels).
    Only protocols declared inside this project (dst) are included.
    """
    reqs: Dict[str, Set[Tuple[str, int, Tuple[str, ...]]]] = {}
    files = iter_swift_files(project_root, skip_ui=False, debug=debug, exclude_file_globs=None, include_packages=include_packages)
    for abs_path in files:
        try:
            text = read_text(abs_path)
        except Exception:
            continue
        scrub = _strip_comments(text)
        for pb in _find_protocol_blocks(scrub):
            proto = pb["name"]
            body = pb["body"]
            for fm in FUNC_DECL_RE.finditer(body):
                name = fm.group("name")
                params_src = fm.group("params") or ""
                key = _func_key(name, params_src)
                reqs.setdefault(proto, set()).add(key)
    if debug:
        log(f"prepass: local protocols={len(reqs)} (with requirements)")
    return reqs

def scan_swift_functions(
    project_root: str,
    skip_ui: bool,
    debug: bool,
    exclude_file_globs: Optional[List[str]],
    args_include_packages: bool,
    known_actor_types: Optional[set] = None,
    known_global_actor_types: Optional[set] = None,
    local_declared_types: Optional[set] = None,
    local_protocol_reqs: Optional[Dict[str, Set[Tuple[str, int, Tuple[str, ...]]]]] = None,
) -> List[Dict]:
    files = iter_swift_files(project_root, skip_ui=skip_ui, debug=debug, exclude_file_globs=exclude_file_globs, include_packages=args_include_packages)
    # Use precompiled patterns
    type_decl_re = TYPE_DECL_RE
    func_decl_re = FUNC_DECL_RE
    results: List[Dict] = []
    pending_attrs: List[str] = []  # carries attributes like @MainActor that may precede declarations
    for abs_path in files:
        rel_path = os.path.relpath(abs_path, project_root)
        try:
            content = read_text(abs_path)
        except Exception:
            continue
        # Use a comment-stripped view for scanning so any 'func ...' inside comments is ignored.
        # Newlines/positions are preserved to keep brace-depth tracking stable.
        scan_text = _strip_comments_preserve_layout(content)

        brace, type_stack = 0, []
        for line in scan_text.splitlines():
            stripped = line.strip()
            # capture any leading attributes like @MainActor on this line
            attrs_on_line = re.findall(r"@([\w:]+)", line)
            # merge with any pending attributes from previous lines
            attrs = pending_attrs + attrs_on_line
            mtype = type_decl_re.match(line)
            if mtype:
                gens_raw = (mtype.group('generics') or '').strip()
                gens_list: List[str] = []
                if gens_raw:
                    # strip angle brackets and split by commas, keep only the identifier before any ':' constraint
                    inner = gens_raw[gens_raw.find('<')+1:gens_raw.rfind('>')]
                    for tok in [t.strip() for t in inner.split(',') if t.strip()]:
                        name = tok.split(':', 1)[0].strip()
                        # defensive: only simple identifiers
                        if re.match(r"^[A-Za-z_]\w*$", name):
                            gens_list.append(name)
                # detect global-actor on the type (e.g., @MainActor)
                has_global_actor = any(a.endswith('Actor') for a in attrs)
                ext_where = False
                trailing = line[mtype.end():]
                conforms: List[str] = []
                colon = trailing.find(':')
                if colon != -1:
                    inherits_part = trailing[colon+1:]
                    lb = inherits_part.find('{')
                    if lb != -1:
                        inherits_part = inherits_part[:lb]
                    for raw_item in inherits_part.split(','):
                        item = raw_item.strip()
                        if not item:
                            continue
                        if '<' in item:
                            item = item.split('<', 1)[0].strip()
                        item = item.split('where', 1)[0].strip()
                        m_id = re.match(r"^[A-Za-z_]\w*$", item)
                        if m_id:
                            conforms.append(item)
                if mtype.group('tkind') == "extension":
                    # Heuristic: if 'where' appears in the extension header line, treat as constrained extension
                    if re.search(r"\bwhere\b", trailing):
                        ext_where = True
                type_stack.append((mtype.group('type_name'), brace, gens_list, mtype.group('tkind'), has_global_actor, ext_where, conforms))
                pending_attrs = []
            mfunc = func_decl_re.match(line)
            if mfunc:
                # If inside a protocol body, these are requirement signatures, not implementations → skip
                if type_stack and type_stack[-1][3] == "protocol":
                    brace += line.count("{") - line.count("}")
                    while type_stack and brace <= type_stack[-1][1]:
                        type_stack.pop()
                    continue

                # Compute depth after accounting for any braces present on THIS line.
                open_cnt = line.count("{")
                close_cnt = line.count("}")
                brace_after = brace + open_cnt - close_cnt
                same_line_opens_body = ("{" in line)

                if type_stack:
                    type_depth = type_stack[-1][1]
                    # Accept if either:
                    #  - current depth is exactly inside the type body, OR
                    #  - after applying this line's braces it becomes exactly inside, OR
                    #  - we're at the type header line depth and this line opens the body.
                    if not (
                        brace == type_depth + 1
                        or brace_after == type_depth + 1
                        or (brace == type_depth and same_line_opens_body)
                    ):
                        # Not at the immediate type body → treat as nested/local and skip
                        brace = brace_after
                        while type_stack and brace <= type_stack[-1][1]:
                            type_stack.pop()
                        continue
                else:
                    # No enclosing type: allow only true file top-level functions
                    if not (brace == 0 or brace_after == 0 or (brace == 0 and same_line_opens_body)):
                        brace = brace_after
                        while type_stack and brace <= type_stack[-1][1]:
                            type_stack.pop()
                        continue
                mods = (mfunc.group('mods') or '').split()
                name, raw_params, ret = mfunc.group('name'), mfunc.group('params') or "", (mfunc.group('ret') or '').strip() or None
                # --- NEW: detect function-level global-actor annotation
                func_has_global_actor = any(a.endswith('Actor') for a in attrs)
                # Build param types from a version of params with defaults stripped,
                # so things like `= nil` do not leak into type signatures.
                clean_params = _strip_param_defaults(raw_params)
                param_types = []
                for part in clean_params.split(","):
                    if not part.strip():
                        continue
                    # take everything after ':' as the type annotation
                    if ":" in part:
                        type_part = part.split(":", 1)[1]
                    else:
                        # no explicit type (rare in func decl) – keep as-is
                        type_part = part
                    param_types.append(type_part.strip())
                parent = type_stack[-1][0] if type_stack else None
                parent_depth = len(type_stack)
                parent_qual = ".".join([t[0] for t in type_stack]) if type_stack else None
                # Also extract generics for parent type, if any
                parent_generics = type_stack[-1][2] if type_stack else []
                parent_kind     = type_stack[-1][3] if type_stack else None
                parent_has_global_actor_attr = type_stack[-1][4] if type_stack else False
                is_parent_extension = (parent_kind == "extension")
                is_parent_extension_constrained = (type_stack[-1][5] if (type_stack and is_parent_extension and len(type_stack[-1]) >= 6) else False)
                parent_conforms = type_stack[-1][6] if (type_stack and len(type_stack[-1]) >= 7) else []
                is_parent_generic = bool(parent_generics)
                # Parent actor/global-actor resolution:
                base_parent = parent or ""
                known_actor_types = known_actor_types or set()
                known_global_actor_types = known_global_actor_types or set()
                is_parent_actor = (parent_kind == "actor") or (is_parent_extension and base_parent in known_actor_types)
                parent_has_global_actor = bool(parent_has_global_actor_attr or (is_parent_extension and base_parent in known_global_actor_types))
                route_key = f"{parent+'.' if parent else ''}{name}({', '.join(param_types)})"
                if ret: route_key += f" -> {ret}"
                is_parent_local_declared = bool(parent) and (parent in (local_declared_types or set()))
                proto_reqs = local_protocol_reqs or {}
                func_key = _func_key(name, raw_params)
                matched_internal_protocols: List[str] = []
                external_protocols_in_scope: List[str] = []
                for p in (parent_conforms or []):
                    if p in proto_reqs:
                        if func_key in proto_reqs[p]:
                            matched_internal_protocols.append(p)
                    else:
                        external_protocols_in_scope.append(p)
                is_protocol_req_impl = len(matched_internal_protocols) > 0
                results.append({
                    "file": rel_path,
                    "parent_type": parent,
                    "name": name,
                    "params_src": raw_params,
                    "param_types": param_types,
                    "return_type": ret,
                    "is_static": any(tok in ('static', 'class') for tok in mods),
                    "modifiers": mods,
                    "route_key": route_key,
                    "parent_depth": parent_depth,
                    "parent_qual": parent_qual,
                    "parent_generics": parent_generics,
                    "is_parent_generic": is_parent_generic,
                    "is_parent_actor": is_parent_actor,
                    "is_parent_extension": bool(is_parent_extension),
                    "is_parent_extension_constrained": bool(is_parent_extension_constrained),
                    "is_parent_global_actor": bool(parent_has_global_actor),
                    "is_func_global_actor": bool(func_has_global_actor),
                    "is_parent_declared_in_project": bool(is_parent_local_declared),
                    "parent_conforms": parent_conforms,
                    "is_protocol_req_impl": bool(is_protocol_req_impl),
                    "matched_internal_protocols": matched_internal_protocols,
                    "has_external_protocols_in_scope": bool(external_protocols_in_scope),
                })
            pending_attrs = []
            # If this line is only attributes (starts with '@') and we didn't match a decl yet, keep them pending
            if stripped.startswith('@') and not mtype and not mfunc:
                pending_attrs = attrs_on_line or pending_attrs
            brace += line.count("{") - line.count("}")
            while type_stack and brace <= type_stack[-1][1]: type_stack.pop()
    return results


def collect_actor_and_global_types(project_root: str, *, include_packages: bool, debug: bool) -> Tuple[set, set]:
    """
    Pre-scan all Swift files to collect:
      - actor types declared as: 'actor TypeName { ... }'
      - types annotated with a global actor, e.g. '@MainActor class TypeName { ... }'
        (supports attribute on the same line or immediately preceding line)
    Returns (actor_types, global_actor_types).
    """
    actor_types: set = set()
    global_actor_types: set = set()

    files = iter_swift_files(project_root, skip_ui=False, debug=debug, exclude_file_globs=None, include_packages=include_packages)
    # Simple line-based scan with 'pending actor attribute' heuristic
    for abs_path in files:
        try:
            text = read_text(abs_path)
        except Exception:
            continue
        pending_actor_attr = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            # Detect global-actor attribute tokens
            if re.search(r"@\w+Actor\b", line):
                # If the type decl is on the same line, record immediately; otherwise mark pending for next decl.
                if re.search(r"\b(class|struct|enum)\s+([A-Za-z_]\w*)\b", line):
                    m = re.search(r"\b(class|struct|enum)\s+([A-Za-z_]\w*)\b", line)
                    if m: global_actor_types.add(m.group(2))
                    pending_actor_attr = False
                else:
                    pending_actor_attr = True
                continue

            # Actor type declaration
            m_actor = re.match(r"^\s*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?actor\s+([A-Za-z_]\w*)\b", raw)
            if m_actor:
                actor_types.add(m_actor.group(1))
                pending_actor_attr = False
                continue

            # Regular type declaration; if we had a pending global-actor attribute, attach it now
            if pending_actor_attr:
                m_type = re.match(r"^\s*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?(class|struct|enum)\s+([A-Za-z_]\w*)\b", raw)
                if m_type:
                    global_actor_types.add(m_type.group(2))
                    pending_actor_attr = False
                else:
                    # keep pending only if the line looks like an attribute continuation
                    if not raw.lstrip().startswith("@"):
                        pending_actor_attr = False
    if debug:
        log(f"prepass: actors={len(actor_types)} global-actors={len(global_actor_types)}")
    return actor_types, global_actor_types

def _rule_name(rule: Dict) -> Optional[str]: return rule.get("A_name") or rule.get("name")
def _rule_kind(rule: Dict) -> Optional[str]: return (rule.get("B_kind") or rule.get("kind") or "").lower() or None

def rule_matches_function(rule: Dict, fn: Dict) -> bool:
    rname, rkind, fname, fparent = _rule_name(rule) or "", _rule_kind(rule), fn.get("name") or "", fn.get("parent_type") or ""
    matches = lambda p, v: bool(p) and (p == v or fnmatchcase(v, p))
    if rkind == "function": return matches(rname, fname)
    if rkind in ["class", "struct", "enum", "protocol", "extension", "actor"]: return matches(rname, fparent)
    return matches(rname, fname) or matches(rname, fparent)

def partition_by_exceptions(funcs: List[Dict], exceptions: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    if not exceptions: return funcs, []
    included, excluded = [], []
    for fn in funcs:
        (excluded if any(rule_matches_function(r, fn) for r in exceptions) else included).append(fn)
    return included, excluded

def is_risky_function(fn: Dict, *, skip_overrides: bool = True) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    src = fn.get("params_src") or ""
    ret = (fn.get("return_type") or "").strip()
    param_types = fn.get("param_types") or []

    # 1) Closure params or escaping/inout are tricky for wrapper generation
    if "->" in src or "@escaping" in src:
        reasons.append("closure_param_or_escaping")
    if "inout" in src:
        reasons.append("inout_param")

    # 2) Any parameter default at top level (conservative; align with generate_exceptions)
    if _has_param_default(src):
        reasons.append("param_default")

    # 3) Opaque return types `some ...` are not representable in function-type casts
    if re.search(r"^some\b|\bsome\b", ret):
        reasons.append("opaque_return_some")

    # 4) Return Self at file scope is ambiguous
    if re.search(r"\bSelf\b", ret):
        reasons.append("return_Self")

    # 5) Context-associated identifiers (e.g., LabelStyle.Configuration) used unqualified
    if any(re.search(r"\bConfiguration\b", t) for t in param_types):
        reasons.append("context_assoc_type_in_params")

    # 6) Overrides (optional policy)
    if skip_overrides and "override" in (fn.get("modifiers") or []):
        reasons.append("override_method")

    return (len(reasons) > 0, reasons)

def partition_risky(funcs: List[Dict], *, skip_overrides: bool = True) -> Tuple[List[Dict], List[Dict]]:
    safe, risky = [], []
    for f in funcs:
        is_risky, reasons = is_risky_function(f, skip_overrides=skip_overrides)
        if is_risky:
            f["risk_reasons"] = reasons
            risky.append(f)
        else:
            safe.append(f)
    return safe, risky
    
def _file_scoped_id(rel_path: str) -> str:
    h = hashlib.sha1(rel_path.encode("utf-8")).hexdigest().upper()
    return h[:10]

def _swift_type(t: Optional[str]) -> str:
    t = (t or "").strip()
    return t if t else "Void"

def _param_var_names(params_src: str) -> List[str]:
    out: List[str] = []
    for part in [p.strip() for p in (params_src or "").split(",") if p.strip()]:
        if ":" not in part:
            toks = [x for x in re.split(r"\s+", part) if x and x != "_"]
            out.append(toks[-1] if toks else "arg")
            continue
        left = part.split(":", 1)[0].strip()
        toks = [x for x in re.split(r"\s+", left) if x and x != "_"]
        if len(toks) >= 2: out.append(toks[-1])
        elif toks: out.append(toks[0])
        else: out.append("arg")
    return out

def build_perfile_runtime(file_id: str, routes: List[str], max_params: int) -> str:
    enum_name = f"OBFF{file_id}"
    lines = [
        OBF_BEGIN,
        f"actor {enum_name} {{",
        "  static private var routes: [String: ([Any]) throws -> Any] = [:]",
        "  static private var didInstall = false",
        "  static private func install() {"] + [f"    {r}" for r in routes] + [
        "  }",
        "  static private func ensure() { if !didInstall { didInstall = true; install() } }",
        "",
        "  @discardableResult",
        "  static func register(_ key: String, _ fn: @escaping ([Any]) throws -> Any, overwrite: Bool = false) -> Bool {",
        "    if !overwrite, routes[key] != nil { return false }",
        "    routes[key] = fn",
        "    return true",
        "  }",
        "  static func call<R>(_ key: String, _ args: Any...) throws -> R {",
        "    ensure()",
        "    guard let fn = routes[key] else { preconditionFailure(\"[OBF] missing key: \\(key)\") }",
        "    let res = try fn(args)",
        "    guard let cast = res as? R else { preconditionFailure(\"[OBF] bad return for \\(key)\") }",
        "    return cast",
        "  }",
        "  static func callVoid(_ key: String, _ args: Any...) throws {",
        "    ensure()",
        "    guard let fn = routes[key] else { preconditionFailure(\"[OBF] missing key: \\(key)\") }",
        "    _ = try fn(args)",
        "  }"
    ]
    for n in range(max_params + 1):
        t_params = ", ".join([chr(ord('A') + i) for i in range(n)])
        a_params = ", ".join([f"a{i}" for i in range(n)])
        guards = [f"      guard let a{i} = args[{i}] as? {chr(ord('A') + i)} else {{ preconditionFailure(\"[OBF] cast at {i}\") }}" for i in range(n)]
        precondition = "      precondition(args.isEmpty)" if n == 0 else f"      precondition(args.count == {n})"
        lines.extend([
            f"  static func wrap{n}<{t_params}{', ' if t_params else ''}R>(_ function: @escaping ({t_params}) -> R) -> ([Any]) throws -> Any {{",
            "    return { args in",
            precondition] + guards + [
            f"      return function({a_params})",
            "    }",
            "  }"
        ])
    for n in range(max_params + 1):
        t_params = ", ".join([chr(ord('A') + i) for i in range(n)])
        s_t_params = f"S{', ' + t_params if t_params else ''}"
        a_params = ", ".join([f"a{i}" for i in range(n)])
        guards = [f"      guard let a{i} = args[{i+1}] as? {chr(ord('A') + i)} else {{ preconditionFailure(\"[OBF] cast at {i}\") }}" for i in range(n)]
        lines.extend([
            f"  static func wrapM{n}<{s_t_params}, R>(_ function: @escaping (S) -> ({t_params}) -> R) -> ([Any]) throws -> Any {{",
            "    return { args in",
            f"      precondition(args.count == {n+1})",
            "      guard let owner = args[0] as? S else { preconditionFailure(\"[OBF] cast self\") }"] + guards + [
            f"      return function(owner)({a_params})",
            "    }",
            "  }"
        ])
    lines.extend(["}", OBF_END])
    return "\n".join(lines)

def inject_or_replace_block(original_text: str, block_text: str) -> str:
    start = original_text.find(OBF_BEGIN)
    end = original_text.find(OBF_END, start + len(OBF_BEGIN)) if start != -1 else -1
    if start != -1 and end != -1:
        return original_text[:start] + block_text + original_text[end + len(OBF_END):]
    return block_text + "\n\n" + original_text
def _rename_and_add_wrapper(src: str, *, name: str, parent_type: Optional[str], is_static: bool, params_src: str, return_type: Optional[str], route_key: str, file_id: str, modifiers: List[str]) -> Tuple[str, bool]:
    """
    Preserve declaration-leading attributes (e.g., @IBAction, @IBSegueAction, @...Actor) by re-applying them to the
    generated wrapper function, while removing them from the implementation function. This version is careful to:
      - Extract attribute *tokens* only (e.g., "@IBAction"), not whole lines.
      - Never touch parameter attributes such as `@escaping` or `@Sendable`.
      - Preserve line breaks when removing attribute lines to avoid token concatenation like `@bescaping`.
    """
    lines = src.splitlines(keepends=True)
    # --- Pre-pass: bind attribute-only lines to the *next* declaration line (func/init/subscript/type) ---
    def _attribute_owner_map(lines_: List[str]) -> Dict[int, List[int]]:
        owner: Dict[int, List[int]] = {}
        pending: List[int] = []
        # permissive decl detectors
        func_any = re.compile(r"^\s*(?:@[^\n]*\s*)*\s*func\s+\w+\s*\(")
        init_any = re.compile(r"^\s*(?:@[^\n]*\s*)*\s*(?:convenience\s+|required\s+)?init\b")
        subscript_any = re.compile(r"^\s*(?:@[^\n]*\s*)*\s*subscript\b")
        type_any = re.compile(r"^\s*(?:@[^\n]*\s*)*\s*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?(?:class|struct|enum|actor|protocol|extension)\b")

        def _line_is_spacer(s: str) -> bool:
            st = s.strip()
            return (not st) or st.startswith('///') or st.startswith('/**') or st.startswith('*') or st.startswith('*/') or st.startswith('#if') or st.startswith('#endif') or st.startswith('#else')

        for idx, raw in enumerate(lines_):
            st = raw.strip()
            if st.startswith('@'):
                # attribute line (allow trailing comments/keywords)
                pending.append(idx)
                continue
            if _line_is_spacer(raw):
                # spacer keeps the block pending
                continue
            # declaration?
            if func_any.match(raw) or init_any.match(raw) or subscript_any.match(raw) or type_any.match(raw):
                if pending:
                    owner[idx] = list(pending)
                    pending.clear()
                # after binding, continue scanning
            else:
                # met regular code → pending attrs are not considered preceding this decl
                pending.clear()
        return owner
    # func decl matcher: allow any number of attribute tokens immediately before `func`
    func_pat = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*func\s+" + re.escape(name) + r"\s*\(")
    func_idx = -1
    for i, line in enumerate(lines):
        if func_pat.match(line):
            func_idx = i
            break
    if func_idx == -1:
        impl = f"obfImpl_{name}"
        func_pat2 = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*func\s+" + re.escape(impl) + r"\s*\(")
        for i, line in enumerate(lines):
            if func_pat2.match(line):
                return src, False
        return src, False

    # --- Collect declaration-leading attribute *tokens* ---
    def _attr_tokens_from_line(s: str) -> List[str]:
        # Capture full attribute segments robustly (e.g., '@IBAction', '@objc(name)', etc.)
        return re.findall(r"(?:(?<=^)@|(?<=\s)@)[\w:]+(?:\s*\([^)]*\))?", s)

    def _is_spacer_line(s: str) -> bool:
        st = s.strip()
        # empty, doc-comments and conditional-compilation lines are considered spacers
        return (not st) or st.startswith('///') or st.startswith('/**') or st.startswith('*') or st.startswith('*/') or st.startswith('#if') or st.startswith('#endif') or st.startswith('#else')

    # tokens on the same line as `func`
    inline_tokens = _attr_tokens_from_line(lines[func_idx])

    # Use pre-bound attribute ownership instead of upward heuristic scan
    owner_map = _attribute_owner_map(lines)
    owned_attr_idxs: List[int] = owner_map.get(func_idx, [])

    above_tokens: List[str] = []
    above_attr_lines: Dict[int, List[str]] = {}
    for j in owned_attr_idxs:
        rawj = lines[j]
        toksj = _attr_tokens_from_line(rawj)
        above_attr_lines[j] = toksj if toksj else ["@unknown"]
        above_tokens.extend(toksj)

    # We only preserve declaration-leading attributes that should stay on the wrapper
    def _is_preserved(tok: str) -> bool:
        # Preserve UI/runtime/actor attributes and Objective-C exposure
        # - Keep @objc and @objc(...) so selectors keep working after wrapping
        # - Keep IBAction/IBSegueAction and any global-actor (…Actor)
        base = tok.strip()
        return base.startswith("@objc") or base in ("@IBAction", "@IBSegueAction") or base.endswith("Actor")

    preserved = [t for t in (above_tokens + inline_tokens) if _is_preserved(t)]

    # --- Build the implementation function line: remove only the preserved tokens from the decl line
    orig_func_line = lines[func_idx]
    new_func_line = orig_func_line
    for tok in preserved:
        # Replace token with a single space boundary-safe; keep surrounding whitespace
        new_func_line = re.sub(rf"(?:(?<=^)\s*|\s+){re.escape(tok)}(?=\s|$)", " ", new_func_line)

    # Rename to obfImpl_<name>
    impl = f"obfImpl_{name}"
    if re.search(r"\bfunc\s+" + re.escape(impl) + r"\s*\(", src, re.MULTILINE):
        return src, False
    new_func_line_renamed, nsubs = re.subn(r"(\bfunc\s+)" + re.escape(name) + r"(\s*\()", r"\1" + impl + r"\2", new_func_line, count=1)
    if nsubs == 0:
        return src, False

    # Reconstruct lines: replace function line; for attribute-only lines above, remove only those containing preserved tokens
    new_lines: List[str] = []
    to_delete_idx: Set[int] = set()
    # Only delete attribute-only lines that contain preserved tokens; keep others (e.g., @available)
    for idx, toks in above_attr_lines.items():
        if any(t in preserved for t in toks):
            to_delete_idx.add(idx)

    for idx, l in enumerate(lines):
        if idx == func_idx:
            new_lines.append(new_func_line_renamed)
        elif idx in to_delete_idx:
            new_lines.append("\n" if l.endswith("\n") else l[:0])
        else:
            new_lines.append(l)
    new_src = "".join(new_lines)

    # If access modifier is `private`, relax to `fileprivate` for the impl (same heuristic as before)
    m2 = re.search(r"(\bfunc\s+)" + re.escape(impl) + r"(\s*\()", new_src, re.MULTILINE)
    if not m2:
        return src, False
    if 'private' in modifiers:
        prev_brace_pos = new_src.rfind('}', 0, m2.start(1))
        search_start = prev_brace_pos + 1 if prev_brace_pos != -1 else 0
        modifier_block = new_src[search_start:m2.start(1)]
        new_modifier_block, rep = re.subn(r"\bprivate\b", "fileprivate", modifier_block)
        if rep > 0:
            new_src = new_src[:search_start] + new_modifier_block + new_src[m2.start(1):]
            m2 = re.search(r"(\bfunc\s+)" + re.escape(impl) + r"(\s*\()", new_src, re.MULTILINE)
            if not m2:
                return src, False

    # Figure out insertion point (closing brace of the parent type body)
    insert_at = -1
    if parent_type:
        impl_pos = m2.start(1)
        type_pat = re.compile(
            rf"^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?"
            rf"(class|struct|enum|actor|extension)\s+{re.escape(parent_type)}\b[\s\S]*?\{{",
            re.MULTILINE | re.DOTALL,
        )
        for match in type_pat.finditer(new_src):
            open_brace_pos = match.end() - 1
            depth, k = 1, open_brace_pos + 1
            body_start_pos = k
            body_end_pos = -1
            while k < len(new_src):
                ch = new_src[k]
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        body_end_pos = k
                        break
                k += 1
            if body_end_pos != -1 and body_start_pos <= impl_pos < body_end_pos:
                insert_at = body_end_pos
                break
    if insert_at == -1:
        return src, False

    ret = _swift_type(return_type)
    access = next((t for t in modifiers if t in {"public","internal","fileprivate","private","open"}), "")
    wrapper_hdr = f"{access+' ' if access else ''}{'static ' if is_static and parent_type else ''}func {name}({params_src})"
    if ret != "Void":
        wrapper_hdr += f" -> {ret}"

    arg_names = _param_var_names(params_src)
    call_args = (["self"] if parent_type and not is_static else []) + arg_names
    call_joined = ", ".join(call_args)
    call_prefix = f'("{route_key}"{", " if call_joined else ""}{call_joined})'

    if ret != "Void":
        body = f"{{\n  return try! OBFF{file_id}.call{call_prefix}\n}}"
    else:
        body = f"{{\n  try! OBFF{file_id}.callVoid{call_prefix}\n}}"

    # Reconstruct preserved attribute *text* from the original source lines when possible
    preserved_line_texts: List[str] = []
    # If there were attribute-only lines above the func that we decided to delete, take their exact text
    for idx in sorted(to_delete_idx):
        # keep the original line as-is (it already contains its newline)
        preserved_line_texts.append(lines[idx])
    # If some preserved tokens were inline on the func line (e.g., '@objc' on the same line),
    # synthesize a single-line attribute string from those tokens and prefer it before the above lines.
    inline_preserved = [t for t in inline_tokens if _is_preserved(t)]
    if inline_preserved:
        synthesized = "".join(t + "\n" for t in inline_preserved)
        # put synthesized inline attrs before the collected above-lines so order resembles original intent
        preserved_line_texts.insert(0, synthesized)
    attrs_prefix = "".join(preserved_line_texts)
    wrapper = f"\n\n{attrs_prefix}{wrapper_hdr}\n{body}\n"
    return new_src[:insert_at] + wrapper + new_src[insert_at:], True

def inject_per_file(file_abs: str, file_rel: str, targets: List[Dict], *, debug: bool, dry_run: bool, max_params: int, skip_external_extensions: bool, skip_external_protocol_reqs: bool, allow_internal_protocol_reqs: bool, skip_external_protocol_extension_members: bool) -> Tuple[bool, int]:
    if not targets: return (False, 0)
    try: original = read_text(file_abs)
    except Exception: return (False, 0)
    file_id, text, routes, wrapped_count = _file_scoped_id(file_rel), original, [], 0
    # --- helpers for conservative skipping of bare nested types (lowest risk) ---
    nested_type_cache: Dict[str, set] = {}

    def _strip_type_tokens(tp: Optional[str]) -> str:
        tp = (tp or "").strip()
        # remove optional/implicitly-unwrapped marks
        tp = tp.rstrip("?!")
        # strip array/dictionary sugar in a conservative way
        if tp.startswith("[") and tp.endswith("]"):
            tp = tp[1:-1].strip()
        # take the base identifier before generics
        if '<' in tp:
            tp = tp.split('<', 1)[0].strip()
        return tp

    def _find_parent_body(src: str, parent_name: str) -> Optional[str]:
        # find the top-level declaration of the parent type and return its body text
        m = re.search(
            rf'^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?'
            rf'(?:class|struct|enum|actor|extension)\s+{re.escape(parent_name)}\b.*?\{{',
            src,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return None
        i = m.end() - 1  # at '{'
        depth, j = 0, i
        start = i + 1
        while j < len(src):
            ch = src[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return src[start:j]
            j += 1
        return None

    def _collect_nested_types_for_parent(src: str, parent_name: str) -> set:
        key = parent_name
        if key in nested_type_cache:
            return nested_type_cache[key]
        body = _find_parent_body(src, parent_name)
        names: set = set()
        if body:
            for mt in re.finditer(r"\b(class|struct|enum|actor)\s+([A-Za-z_]\w*)\b", body):
                names.add(mt.group(2))
        nested_type_cache[key] = names
        return names

    def _uses_bare_nested_type(t: Dict) -> bool:
        parent = t.get("parent_type")
        if not parent:
            return False
        nested = _collect_nested_types_for_parent(original, parent)
        if not nested:
            return False
        # examine param types and return type for bare identifiers that equal a nested type name
        for p in (t.get("param_types") or []):
            base = _strip_type_tokens(p)
            # skip qualified types like Parent.Node
            if not base or '.' in base:
                continue
            if base in nested:
                return True
        ret = _strip_type_tokens(t.get("return_type"))
        if ret and '.' not in ret and ret in nested:
            return True
        return False

    # --- additional conservative guard: bare Capitalized identifier that isn't a top-level type in this file ---
    _top_level_types: Optional[set] = None

    def _collect_top_level_types(src: str) -> set:
        nonlocal _top_level_types
        if _top_level_types is not None:
            return _top_level_types
        names: set = set()
        depth = 0
        for line in src.splitlines():
            # update depth first to ignore inner/nested declarations
            open_cnt, close_cnt = line.count('{'), line.count('}')
            if depth == 0:
                m = re.match(r"^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?(class|struct|enum|actor|protocol|typealias)\s+([A-Za-z_]\w*)\b", line)
                if m:
                    names.add(m.group(2))
            depth += open_cnt - close_cnt
            if depth < 0:
                depth = 0
        _top_level_types = names
        return names

    def _uses_bare_unknown_capitalized_type(t: Dict) -> bool:
        # If a parameter/return type is a single Capitalized identifier without qualification (no '.')
        # and that identifier is NOT declared as a top-level type in this file, conservatively skip.
        parent = t.get("parent_type")
        if not parent:
            return False
        toplv = _collect_top_level_types(original)
        std_whitelist = {"String", "Int", "Double", "Float", "Bool", "Character", "UInt", "UInt8", "UInt16", "UInt32", "UInt64", "Int8", "Int16", "Int32", "Int64", "Date", "Data", "URL", "UUID", "Any", "AnyObject", "Never", "Void"}
        def is_bare_cap(tok: str) -> bool:
            return tok and tok[0].isupper() and '.' not in tok and '[' not in tok and ']' not in tok
        # params
        for p in (t.get("param_types") or []):
            base = _strip_type_tokens(p)
            if is_bare_cap(base) and base not in toplv and base not in std_whitelist:
                return True
        # return type
        base_r = _strip_type_tokens(t.get("return_type"))
        if is_bare_cap(base_r) and base_r not in toplv and base_r not in std_whitelist:
            return True
        return False
    for t in targets:
        if len(t.get("param_types") or []) > max_params:
            continue

        parent = t.get("parent_type")

        # SAFETY FILTERS
        if parent:
            # 1) Skip generic parent types entirely for instance methods (e.g., DoublyLinkedList<T>)
            if t.get("is_parent_generic") and not t.get("is_static"):
                if debug: log(f"Skip instance method in generic parent type: {parent} in {file_rel}")
                continue
            # Legacy angle-bracket heuristic (defensive)
            if "<" in parent or ">" in parent:
                if debug: log(f"Skip generic parent type target: {parent} in {file_rel}")
                continue
            # 2) Skip members of nested types (e.g., Outer.Inner) until fully-qualified injection is implemented
            if (t.get("parent_depth") or 1) > 1:
                if debug: log(f"Skip member in nested type: {parent} in {file_rel}")
                continue
            # 3) Ensure this file actually declares or extends the parent type at top level
            if not re.search(rf'^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?(?:class|struct|enum|actor|extension)\s+{re.escape(parent)}\b', original, re.MULTILINE):
                if debug: log(f"Skip target (parent type not declared here): {parent} in {file_rel}")
                continue
        # (A) If this is an extension that adds conformance to EXTERNAL protocol(s), optionally skip all members in that extension
        if skip_external_protocol_extension_members and t.get("is_parent_extension") and t.get("has_external_protocols_in_scope"):
            if debug: log(f"Skip members in extension adding EXTERNAL protocol conformance: {parent} in {file_rel}")
            continue

        # (B) Implementations of INTERNAL protocol requirements → skip unless explicitly allowed
        if t.get("is_protocol_req_impl"):
            if not allow_internal_protocol_reqs:
                if debug: log(f"Skip INTERNAL protocol requirement impl: {parent}.{t.get('name')} in {file_rel}")
                continue
        else:
            # (C) If there are EXTERNAL protocols in scope for this extension, and requested to be conservative, skip
            if skip_external_protocol_reqs and t.get("has_external_protocols_in_scope") and t.get("is_parent_extension"):
                if debug: log(f"Skip member in extension with EXTERNAL protocols in scope: {parent}.{t.get('name')} in {file_rel}")
                continue
        # 2a) If requested, skip members declared in extension blocks whose parent type is not declared in this project (external type extensions)
        if skip_external_extensions and t.get("is_parent_extension") and not t.get("is_parent_declared_in_project"):
            if debug: log(f"Skip external extension member: {parent} in {file_rel}")
            continue
        # 2b) Skip only members declared inside *constrained* extensions (extension ... where ...)
        if t.get("is_parent_extension_constrained"):
            if debug: log(f"Skip constrained extension member: {parent} in {file_rel}")
            continue
        # 3b) Skip isolated instance methods on actor or global-actor parents unless explicitly nonisolated
        if parent and not t.get("is_static"):
            if (t.get("is_parent_actor") or t.get("is_parent_global_actor") or t.get("is_func_global_actor")) and "nonisolated" not in (t.get("modifiers") or []):
                if debug: log(f"Skip actor/global-actor isolated instance method: {parent}.{t.get('name')} in {file_rel}")
                continue

        # 4) Skip functions that reference bare nested type names (e.g., parameter type `Node` when parent has `class Node`)
        #    This is the lowest-risk policy: avoid qualifying automatically; simply skip to prevent 'Cannot find type ...' errors.
        if _uses_bare_nested_type(t):
            if debug: log(f"Skip uses bare nested type in signature: {parent}.{t.get('name')} in {file_rel}")
            continue

        # 5) Skip functions that reference bare Capitalized identifiers not declared top-level in this file
        if _uses_bare_unknown_capitalized_type(t):
            if debug: log(f"Skip uses bare unknown capitalized type in signature: {parent}.{t.get('name')} in {file_rel}")
            continue

        new_text, did = _rename_and_add_wrapper(text, name=t["name"], parent_type=t.get("parent_type"), is_static=t.get("is_static"), params_src=t.get("params_src"), return_type=t.get("return_type"), route_key=t.get("route_key"), file_id=file_id, modifiers=t.get("modifiers"))
        if not did: continue
        text, wrapped_count = new_text, wrapped_count + 1
        impl, n, parent, is_static = f"obfImpl_{t['name']}", len(t.get("param_types") or []), t.get("parent_type"), t.get("is_static")
        param_types_str, ret_str = ", ".join(t.get("param_types") or []), _swift_type(t.get("return_type"))
        if parent and not is_static:
            needs_isolated = (t.get("is_parent_actor") or t.get("is_parent_global_actor") or t.get("is_func_global_actor")) and "nonisolated" not in (t.get("modifiers") or [])
            owner_ty = f"(isolated {parent})" if needs_isolated else f"({parent})"
            sig, wrapper_name = f"{owner_ty} -> ({param_types_str}) -> {ret_str}", f"wrapM{n}"
            fnref = f"{parent}.{impl} as {sig}"
        else:
            sig, wrapper_name = f"({param_types_str}) -> {ret_str}", f"wrap{n}"
            fnref = (f"{parent}.{impl}" if parent and is_static else impl) + f" as {sig}"
        routes.append(f'_ = OBFF{file_id}.register("{t.get("route_key")}", OBFF{file_id}.{wrapper_name}({fnref}))')
    if wrapped_count == 0: return (False, 0)
    final_text = inject_or_replace_block(text, build_perfile_runtime(file_id, routes, max_params))
    if not dry_run: write_text(file_abs, final_text)
    return (True, wrapped_count)

def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()
    copy_project_tree(args.src, args.dst, overwrite=args.overwrite)
    exceptions = load_exceptions(args.exceptions)
    log(f"loaded {len(exceptions)} exception rules")

    file_excludes = build_file_exclude_patterns(exceptions)
    if args.debug:
        log(f"file exclusion patterns: {len(file_excludes)}")

    skip_ui = not args.no_skip_ui
    # Prepass: collect actor/global-actor types across the project (for extension resolution)
    actor_types, global_actor_types = collect_actor_and_global_types(args.dst, include_packages=args.include_packages, debug=args.debug)
    local_declared_types = collect_local_declared_types(args.dst, include_packages=args.include_packages, debug=args.debug)
    local_protocol_reqs = collect_local_protocol_requirements(args.dst, include_packages=args.include_packages, debug=args.debug)
    funcs = scan_swift_functions(
        args.dst,
        skip_ui=skip_ui,
        debug=args.debug,
        exclude_file_globs=file_excludes,
        args_include_packages=args.include_packages,
        known_actor_types=actor_types,
        known_global_actor_types=global_actor_types,
        local_declared_types=local_declared_types,
        local_protocol_reqs=local_protocol_reqs,
    )
    log(f"discovered {len(funcs)} functions{' (UI files skipped)' if skip_ui else ''}")

    default_dump_dir = os.path.join(args.dst, "_dyn_obf_scan_dumps")
    os.makedirs(default_dump_dir, exist_ok=True)

    dump_json(args.dump_funcs_json or os.path.join(default_dump_dir, "all_funcs.json"), funcs)
    dump_text(args.dump_funcs_txt or os.path.join(default_dump_dir, "all_funcs.txt"), [f['route_key'] for f in funcs])

    included, excluded = partition_by_exceptions(funcs, exceptions)
    dump_json(args.dump_funcs_json_clean or os.path.join(default_dump_dir, "clean_funcs.json"), included)
    dump_text(args.dump_funcs_txt_clean or os.path.join(default_dump_dir, "clean_funcs.txt"), [f['route_key'] for f in included])
    dump_json(args.dump_funcs_json_excluded or os.path.join(default_dump_dir, "excluded_funcs.json"), excluded)
    dump_text(args.dump_funcs_txt_excluded or os.path.join(default_dump_dir, "excluded_funcs.txt"), [f['route_key'] for f in excluded])

    safe, risky = partition_risky(included, skip_overrides=not args.risk_keep_overrides)
    dump_json(args.dump_funcs_json_safe or os.path.join(default_dump_dir, "safe_funcs.json"), safe)
    dump_text(args.dump_funcs_txt_safe or os.path.join(default_dump_dir, "safe_funcs.txt"), [f['route_key'] for f in safe])
    dump_json(args.dump_funcs_json_risky or os.path.join(default_dump_dir, "risky_funcs.json"), risky)
    dump_text(args.dump_funcs_txt_risky or os.path.join(default_dump_dir, "risky_funcs.txt"), [f['route_key'] for f in risky])

    log(f"found {len(safe)} safe functions to obfuscate")

    if args.perfile_inject:
        by_file: Dict[str, List[Dict]] = {}
        for f in safe: by_file.setdefault(f["file"], []).append(f)

        all_swift_files = iter_swift_files(args.dst, skip_ui=False, debug=args.debug, exclude_file_globs=file_excludes, include_packages=args.include_packages)
        if args.debug and file_excludes:
            log("Note: Files matching exclusion patterns are skipped from scanning and injection.")
        touched_files, wrapped_total = 0, 0

        for abs_path in all_swift_files:
            rel = os.path.relpath(abs_path, args.dst)
            if skip_ui and is_ui_path(rel): continue

            targets = by_file.get(rel, [])
            if not targets: continue

            touched, wrapped = inject_per_file(
                abs_path, rel, targets,
                debug=args.debug,
                dry_run=args.dry_run,
                max_params=args.max_params,
                skip_external_extensions=args.skip_external_extensions,
                skip_external_protocol_reqs=args.skip_external_protocol_reqs,
                allow_internal_protocol_reqs=args.allow_internal_protocol_reqs,
                skip_external_protocol_extension_members=args.skip_external_protocol_extension_members,
            )
            if touched: touched_files += 1
            wrapped_total += wrapped
        log(f"in-file injection complete: files_touched={touched_files}, wrapped_funcs={wrapped_total}")
    log(f"output project: {os.path.abspath(args.dst)}")

if __name__ == "__main__":
    main()
