from __future__ import annotations

_ALLOWED_AST_FIELDS = {"symbolName", "symbolKind", "typeSignature", "references", "calls_out", "conforms"}

def _sanitize_ast_entry(entry: dict) -> dict:
    if not isinstance(entry, dict):
        return {}
    return {k: v for k, v in entry.items() if k in _ALLOWED_AST_FIELDS}
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
find_identifiers_and_ast_dual.py

- 원래 리포트(JSON) 생성 기능 유지
- ✅ 모든 식별자/스니펫/AST를 한 파일(payload.json)로 합쳐서 생성
- ✅ AST Symbol Information을 식별자별로 '정의/참조/호출' 라인 및 코드 일부까지 포함해 LLM 판단에 직결되도록 구성
- ✅ 선언부 기준(decl_file/decl_line) 메타를 보고에 추가하고, payload 작성 시 선언 파일을 우선 사용
"""



import os
import sys
import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import difflib
def _basename(s: str) -> str:
    # strip parameter lists like "save(x:)" -> "save"
    return s.split("(")[0].strip() if isinstance(s, str) else ""

def _best_ast_name_match(ident: str, ast_list: List[dict]) -> Optional[str]:
    cand_names = []
    for it in ast_list:
        nm = it.get("symbolName")
        if isinstance(nm, str):
            cand_names.append(nm)
    # exact match first
    if ident in cand_names:
        return ident
    # base-name exact match
    ident_base = _basename(ident)
    for nm in cand_names:
        if _basename(nm) == ident_base and ident_base:
            return nm
    # fuzzy match (handles small typos like 'Present' vs 'Preset')
    close = difflib.get_close_matches(ident, cand_names, n=1, cutoff=0.85)
    if close:
        return close[0]
    # try again on base names
    cand_bases = list({ _basename(nm) for nm in cand_names })
    close2 = difflib.get_close_matches(ident_base, cand_bases, n=1, cutoff=0.85)
    if close2:
        # return the first full name with this base
        base = close2[0]
        for nm in cand_names:
            if _basename(nm) == base:
                return nm
    return None

# Support both package execution (-m) and direct script execution
try:
    # When executed as a module within a package
    from .find_identifiers_and_ast import build_report_for_identifiers  # type: ignore
except Exception:
    # Fallback for direct script execution: add repo src root to sys.path
    from pathlib import Path as _P
    import sys as _S
    _FILE = _P(__file__).resolve()
    # .../src/swingft_cli/core/preflight/find_identifiers_and_ast_dual.py -> parents[4] == src
    _SRC_ROOT = _FILE.parents[4]
    if str(_SRC_ROOT) not in _S.path:
        _S.path.insert(0, str(_SRC_ROOT))
    from swingft_cli.core.preflight.find_identifiers_and_ast import build_report_for_identifiers  # type: ignore

INSTRUCTION = (
    "In the following Swift code, find all identifiers related to sensitive logic. Provide the names and reasoning as a JSON object."
)

# -------------------------
# Helpers to enrich symbols
# -------------------------

_DEF_PATTERNS = [
    # struct/class/enum
    (lambda name: re.compile(rf'\bstruct\s+{re.escape(name)}\b')),
    (lambda name: re.compile(rf'\bclass\s+{re.escape(name)}\b')),
    (lambda name: re.compile(rf'\benum\s+{re.escape(name)}\b')),
    # method (allow params)
    (lambda name: re.compile(rf'\bfunc\s+{re.escape(name)}\b')),
    # variable
    (lambda name: re.compile(rf'\b(?:let|var)\s+{re.escape(name)}\b')),
    # @State private var foo
    (lambda name: re.compile(rf'@State\s+private\s+var\s+{re.escape(name)}\b')),
]

def _load_lines(file_path: str) -> List[str]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()
    except Exception:
        return []

def _is_definition_line(name: str, line: str) -> bool:
    for mk in _DEF_PATTERNS:
        if mk(name).search(line):
            return True
    return False

def _is_call_usage(name: str, line: str) -> bool:
    # foo( ... )  (avoid func definition)
    if re.search(rf'\b{re.escape(name)}\s*\(', line) and not re.search(rf'\bfunc\s+{re.escape(name)}\b', line):
        return True
    return False

def _occurrences_for_symbol(name: str, lines: List[str]) -> List[Dict[str, Any]]:
    """
    Return occurrences across the file:
      - role: definition | reference | call
      - line: 1-based line number
      - code: the exact line text trimmed
    """
    occ: List[Dict[str, Any]] = []
    pat_word = re.compile(rf'\b{re.escape(name)}\b')
    for idx, raw in enumerate(lines):
        if not pat_word.search(raw):
            continue
        code_line = raw.rstrip("\n")
        role = "reference"
        if _is_definition_line(name, raw):
            role = "definition"
        elif _is_call_usage(name, raw):
            role = "call"
        occ.append({
            "role": role,
            "line": idx + 1,
            "code": code_line.strip()
        })
    return occ

def _method_body_range(name: str, lines: List[str]) -> Optional[Tuple[int, int]]:
    """
    If symbol is a method, find its body range by line-wise brace counting.
    Returns (start_line, end_line) 1-based inclusive.
    """
    header_pat = re.compile(rf'\bfunc\s+{re.escape(name)}\b')
    start_idx = None
    for i, ln in enumerate(lines):
        if header_pat.search(ln):
            start_idx = i
            break
    if start_idx is None:
        return None
    # From header line onward, find first '{' then match until depth returns to 0
    depth = 0
    seen_open = False
    end_idx = None
    for i in range(start_idx, len(lines)):
        ln = lines[i]
        for ch in ln:
            if ch == '{':
                depth += 1
                seen_open = True
            elif ch == '}':
                depth -= 1
                if seen_open and depth == 0:
                    end_idx = i
                    break
        if end_idx is not None:
            break
    if end_idx is None:
        return None
    # Convert 0-based to 1-based inclusive
    return (start_idx + 1, end_idx + 1)

def _refs_in_body(name: str, lines: List[str], body_range: Tuple[int, int], candidates: List[str]) -> List[str]:
    s, e = body_range  # 1-based
    body_text = "".join(lines[s-1:e])
    out: List[str] = []
    seen = set()
    for cand in candidates:
        if cand == name:
            continue
        if re.search(rf'\b{re.escape(cand)}\b', body_text):
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
        if len(out) >= 12:
            break
    return out

def _kind_lookup_from_ast_list(ast_list: Any) -> Dict[str, str]:
    """
    From heuristic/external AST (list of {"symbolName","symbolKind"}), produce a name->kind map.
    """
    mp: Dict[str, str] = {}
    if isinstance(ast_list, list):
        for item in ast_list:
            if isinstance(item, dict):
                nm = item.get("symbolName")
                kd = item.get("symbolKind")
                if isinstance(nm, str) and isinstance(kd, str):
                    mp[nm] = kd
    return mp

# -------------------------
# Declaration metadata augmenter
# -------------------------
def _augment_report_with_declarations(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-process the report to record declaration file/line for each identifier.
    Adds:
      - decl_file: path to file that contains the declaration/header of the identifier
      - decl_line: 1-based line number of the declaration/header
    Fallbacks:
      - If exact header not found, try best-name match.
      - If still not found, keep original file and omit decl_line.
    """
    id_map = (report or {}).get("identifiers", {}) or {}
    for ident, info in list(id_map.items()):
        try:
            if not isinstance(info, dict) or not info.get("found"):
                continue
            file_path = info.get("file", "")
            if not file_path or not os.path.exists(file_path):
                continue
            lines = _load_lines(file_path)
            # Try exact declaration line
            decl_idx = None
            for i, ln in enumerate(lines):
                if _is_definition_line(ident, ln):
                    decl_idx = i + 1  # 1-based
                    break
            # If not found, try best-name match using AST names if available
            if decl_idx is None:
                ast_any = info.get("ast_full")
                if ast_any is None:
                    ast_any = info.get("ast")
                cand_list = []
                if isinstance(ast_any, list):
                    cand_list = [x for x in ast_any if isinstance(x, dict)]
                elif isinstance(ast_any, dict):
                    cand_list = [ast_any]
                best = _best_ast_name_match(ident, cand_list) if cand_list else None
                if best:
                    for i, ln in enumerate(lines):
                        if _is_definition_line(_basename(best), ln) or _is_definition_line(best, ln):
                            decl_idx = i + 1
                            break
            # If still not found and it might be a method, try body header search
            if decl_idx is None:
                rng = _method_body_range(ident, lines)
                if rng:
                    decl_idx = rng[0]
            # Write back
            if decl_idx is not None:
                info["decl_file"] = file_path
                info["decl_line"] = decl_idx
            else:
                # keep at least decl_file for consistency
                info["decl_file"] = file_path
        except Exception:
            # best-effort; do not break pipeline
            continue
    return report

# -------------------------
# Payload writer
# -------------------------

def write_combined_payload_file(report: dict, out_path: Path, target_ids: List[str]):
    all_id_map = report.get("identifiers", {}) or {}
    records = []
    for ident in target_ids:
        info = all_id_map.get(ident, {})
        if not info.get("found"):
            continue
        file_path = info.get("decl_file") or info.get("file", "")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                code_block = f.read().rstrip()
        except Exception:
            code_block = ""

        # resolve kind
        kind = info.get("kind")
        if kind is None:
            ast_list = info.get("ast")
            if isinstance(ast_list, list):
                for item in ast_list:
                    if isinstance(item, dict) and item.get("symbolName") == ident:
                        kind = item.get("symbolKind", None)
                        break
        if kind is None:
            # fallback textual inference
            kind = "unknown"
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
            except Exception:
                txt = ""
            if re.search(rf'\bfunc\s+{re.escape(ident)}\b', txt):
                kind = "method"
            elif re.search(rf'\b(?:let|var)\s+{re.escape(ident)}\b', txt):
                kind = "variable"
            elif re.search(rf'\bstruct\s+{re.escape(ident)}\b', txt):
                kind = "struct"
            elif re.search(rf'\bclass\s+{re.escape(ident)}\b', txt):
                kind = "class"
            elif re.search(rf'\benum\s+{re.escape(ident)}\b', txt):
                kind = "enum"
            elif re.search(rf'\bextension\s+{re.escape(ident)}\b', txt):
                kind = "extension"

        # pick single AST entry for the target identifier
        ast_any = info.get("ast_full")
        if ast_any is None:
            ast_any = info.get("ast")
        ast_entry = {}
        if isinstance(ast_any, list):
            for item in ast_any:
                if isinstance(item, dict) and item.get("symbolName") == ident:
                    ast_entry = _sanitize_ast_entry(item)
                    break
        elif isinstance(ast_any, dict) and ast_any.get("symbolName") == ident:
            ast_entry = _sanitize_ast_entry(ast_any)
        if not ast_entry:
            ast_entry = _sanitize_ast_entry({"symbolName": ident, "symbolKind": kind or "unknown"})

        pretty_ast_entry = json.dumps(ast_entry, ensure_ascii=False, indent=2)

        record = {
            "instruction": INSTRUCTION,
            "input": (
                f"**Swift Source Code:**\n```swift\n{code_block}\n```\n\n"
                f"**AST Symbol Information (Target: `{ident}`):**\n```json\n{pretty_ast_entry}\n```\n\n"
                f"**Target Identifier:** `{ident}`"
            ),
            "output": "{\n  \"is_sensitive\": true|false,\n  \"reasoning\": \"<explanation>\"\n}"
        }
        records.append(record)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"records": records}, f, ensure_ascii=False, indent=2)
    print(f"  ↳ wrote combined payload: {out_path}")

def _write_per_identifier_payload_files_from_report(report: dict, out_dir: Path, target_ids: List[str], ctx_lines: int):
    """
    각 식별자마다 payload JSON을 별도로 생성한다.
    - 코드: 해당 식별자가 속한 **소스코드 전체 파일**
    - AST: **대상 식별자 1개**의 AST 심볼만 포함
    파일명: <identifier>.json
    """
    all_id_map = report.get("identifiers", {}) or {}
    out_dir.mkdir(parents=True, exist_ok=True)

    def infer_kind_from_text(file_path: str, ident: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            return "unknown"
        if re.search(rf'\bfunc\s+{re.escape(ident)}\b', text):
            return "method"
        if re.search(rf'\b(?:let|var)\s+{re.escape(ident)}\b', text):
            return "variable"
        if re.search(rf'\bstruct\s+{re.escape(ident)}\b', text):
            return "struct"
        if re.search(rf'\bclass\s+{re.escape(ident)}\b', text):
            return "class"
        if re.search(rf'\benum\s+{re.escape(ident)}\b', text):
            return "enum"
        if re.search(rf'\bextension\s+{re.escape(ident)}\b', text):
            return "extension"
        return "unknown"

    for ident in target_ids:
        info = all_id_map.get(ident, {})
        if not info.get("found"):
            continue

        file_path = info.get("decl_file") or info.get("file", "")
        # 전체 파일 내용
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                code_block = f.read().rstrip()
        except Exception:
            code_block = ""

        # resolve kind
        kind = info.get("kind")
        ast_full = info.get("ast_full")
        ast_any = ast_full if ast_full is not None else info.get("ast")

        # Try to resolve kind if not present
        if kind is None:
            # Try to find kind from AST
            if isinstance(ast_any, list):
                for x in ast_any:
                    if isinstance(x, dict) and x.get("symbolName") == ident:
                        kind = x.get("symbolKind")
                        break
            elif isinstance(ast_any, dict):
                if ast_any.get("symbolName") == ident:
                    kind = ast_any.get("symbolKind")
        if kind is None:
            kind = infer_kind_from_text(file_path, ident)

        # Build a single ast_entry for the target only
        ast_entry = None
        if isinstance(ast_any, list):
            # try exact match
            for x in ast_any:
                if isinstance(x, dict) and x.get("symbolName") == ident:
                    ast_entry = _sanitize_ast_entry(x)
                    break
            # try best match if still None
            if ast_entry is None:
                best = _best_ast_name_match(ident, [x for x in ast_any if isinstance(x, dict)])
                if best and best != ident:
                    print(f"[notice] target_identifier '{ident}' not found in AST. Using closest match '{best}' for kind inference.", file=sys.stderr)
                    for x in ast_any:
                        if isinstance(x, dict) and x.get("symbolName") == best:
                            ast_entry = _sanitize_ast_entry(x)
                            break
        elif isinstance(ast_any, dict):
            if ast_any.get("symbolName") == ident:
                ast_entry = _sanitize_ast_entry(ast_any)
        # If ast_entry is still None, synthesize minimal entry
        if ast_entry is None:
            ast_entry = _sanitize_ast_entry({"symbolName": ident, "symbolKind": kind or "unknown"})

        payload = {
            "swift_code": code_block,
            "ast_symbols": [ast_entry],
            "target_identifier": ident
        }

        out_file = out_dir / f"{ident}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        #print(f"  ↳ wrote per-identifier payload: {out_file}")

def write_per_identifier_payload_files(project_root: str, identifiers, out_dir: str, ctx_lines: int = 300):
    """
    Wrapper for loader usage.
    Builds a report from project_root + identifiers, then writes per-identifier payloads to out_dir.
    Accepts keyword argument `identifiers` as used by loader.py.
    """
    # normalize identifiers
    ids = []
    for x in (identifiers or []):
        try:
            s = str(x).strip()
            if s:
                ids.append(s)
        except Exception:
            continue
    # de-duplicate while preserving order
    ids = list(dict.fromkeys(ids))
    # build report and write payloads
    rpt = build_report_for_identifiers(project_root, ids, ctx_lines=ctx_lines)
    _write_per_identifier_payload_files_from_report(rpt, Path(out_dir), ids, ctx_lines)

# -------------------------
# CLI
# -------------------------

def main():
    ap = argparse.ArgumentParser(description="Find identifiers and produce AST/snippet + single combined payload.json (with occurrences).")
    ap.add_argument("project_root", type=str)
    ap.add_argument("--id", action="append", dest="ids")
    ap.add_argument("--ids-csv", type=str)
    ap.add_argument("--ctx-lines", type=int, default=30)
    ap.add_argument("--output", type=str, default="report.json")
    ap.add_argument("--payload-out", type=str, default="payload.json", help="Single combined payload file path")
    ap.add_argument("--per-id-dir", type=str, default="payloads", help="Directory to write per-identifier payload JSON files")
    args = ap.parse_args()

    ids: List[str] = []
    if args.ids:
        ids.extend(args.ids)
    if args.ids_csv:
        ids.extend([x.strip() for x in args.ids_csv.split(",") if x.strip()])
    if not ids:
        print("No identifiers provided", file=sys.stderr)
        sys.exit(2)
    ids = list(dict.fromkeys(ids))

    report = build_report_for_identifiers(args.project_root, ids, ctx_lines=args.ctx_lines)
    report = _augment_report_with_declarations(report)

    # 전체 리포트 파일
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ wrote main report: {args.output}")

    # 전체를 하나의 payload.json으로 생성 (occurrences 포함)
    write_combined_payload_file(report, Path(args.payload_out), ids)
    print("✅ combined payload generation complete.")

    # 각 식별자별 payload 파일도 생성
    _write_per_identifier_payload_files_from_report(report, Path(args.per_id_dir), ids, args.ctx_lines)

if __name__ == "__main__":
    main()