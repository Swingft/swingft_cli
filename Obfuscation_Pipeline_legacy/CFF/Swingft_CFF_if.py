import json
import sys
import re
from pathlib import Path

def is_pure_bool(cond: str) -> bool:
    if cond is None:
        return True
    c = cond.strip()
    banned = [" let ", " var ", "case "]
    c_pad = f" {c} "
    return not any(tok in c_pad for tok in banned)

def clean(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.splitlines())

def squeeze_blank_lines(s: str) -> str:
    s = re.sub(r"[ \t]+(?=\n)", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip("\n")

def indent_block(text: str, level: int = 1, unit: str = "    ") -> str:
    pad = unit * level
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.splitlines())

def detect_indent(snippet_first_line: str) -> str:
    return snippet_first_line[:len(snippet_first_line) - len(snippet_first_line.lstrip())]

def chain_is_eligible(node) -> bool:
    for clause in node.get("clauses", []):
        role = clause.get("role")
        cond = clause.get("condition")
        if role in ("if", "elseif"):
            if not is_pure_bool(cond):
                return False
    return True

def escape_ws_flex(s: str, star: bool=False) -> str:
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            j = i + 1
            while j < len(s) and s[j].isspace():
                j += 1
            out.append(r"\s*" if star else r"\\s+")
            i = j
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)

def render_child(child) -> str:
    if not child:
        return ""
    if chain_is_eligible(child):
        rendered = render_chain_flatten(child)
        if rendered:
            return rendered
    return clean(child.get("text",""))

def render_chain_flatten(node, state_counter=[0]):
    if not chain_is_eligible(node):
        return None

    clauses = node.get("clauses", [])
    if not clauses:
        return None

    text_snippet = node.get("text","")
    first_line = text_snippet.splitlines()[0] if text_snippet else ""
    base_indent = detect_indent(first_line)

    idx = state_counter[0]; state_counter[0] += 1
    label = f"cffLoopIf{idx}"
    state_var = f"cffStateIf{idx}"
    exec_cases = []
    next_case_num = 1
    for clause in clauses:
        role = clause.get("role")
        cond = clause.get("condition")
        statements = [clean(s) for s in clause.get("statements", [])]
        children = clause.get("children", [])
        if role in ("if","elseif","else"):
            exec_cases.append((next_case_num, role, cond, statements, children))
            next_case_num += 1

    out = []
    out.append(f"{base_indent}var {state_var} = 0")
    out.append(f"{base_indent}{label}: while true {{")
    out.append(f"{base_indent}    switch {state_var} {{")

    out.append(f"{base_indent}    case 0:")
    ladder_lines = []
    for i, (case_num, role, cond, _stmts, _children) in enumerate(exec_cases):
        if role == "else":
            ladder_lines.append(f"else {{")
            ladder_lines.append(f"    {state_var} = {case_num}")
            ladder_lines.append(f"    continue {label}")
            ladder_lines.append(f"}}")
        else:
            prefix = "if" if i == 0 else "else if"
            cond_str = cond or "true"
            ladder_lines.append(f"{prefix} {cond_str} {{")
            ladder_lines.append(f"    {state_var} = {case_num}")
            ladder_lines.append(f"    continue {label}")
            ladder_lines.append(f"}}")
    if not any(role == "else" for _, role, *_ in exec_cases):
        ladder_lines.append(f"else {{")
        ladder_lines.append(f"    break {label}")
        ladder_lines.append(f"}}")
    for ln in ladder_lines:
        out.append(f"{base_indent}        {ln}")

    marker_tpl = "__CFF_CHILD_{i}__"
    for case_num, role, cond, statements, children in exec_cases:
        out.append(f"{base_indent}    case {case_num}:")

        stmt_src = "\n".join(statements)
        found_any = False
        markers = []
        for i, ch in enumerate(children):
            ch_text = clean(ch.get("text",""))
            if not ch_text:
                markers.append(None)
                continue
            pat = escape_ws_flex(ch_text.strip(), star=True)
            marker = marker_tpl.format(i=i)
            try:
                stmt_src, subs = re.subn(pat, marker, stmt_src, count=1, flags=re.DOTALL)
            except re.error:
                if ch_text in stmt_src:
                    stmt_src = stmt_src.replace(ch_text, marker, 1)
                    subs = 1
                else:
                    subs = 0
            markers.append(marker if subs == 1 else None)
            if subs == 1:
                found_any = True

        stmt_src = squeeze_blank_lines(stmt_src)

        if stmt_src.strip():
            parts = re.split("(" + "|".join([re.escape(m) for m in markers if m]) + ")", stmt_src) if found_any else [stmt_src]
        else:
            parts = []

        def emit_segment(seg: str):
            if not seg: return
            for ln in seg.splitlines():
                out.append(f"{base_indent}        {ln}")

        if not found_any:
            
            for ln in stmt_src.splitlines():
                out.append(f"{base_indent}        {ln}")
            for ch in children:
                child_block = render_child(ch)
                if child_block:
                    out.append(indent_block(child_block, 2).replace(" \n", "\n"))
        else:
            
            i_map = {markers[i]: i for i in range(len(markers)) if markers[i]}
            buf = ""
            for token in parts:
                if token in i_map:
                   
                    emit_segment(buf); buf = ""
                    ch_idx = i_map[token]
                    ch = children[ch_idx]
                    child_block = render_child(ch)
                    if child_block:
                        out.append(indent_block(child_block, 2).replace(" \n", "\n"))
                else:
                    buf += token
            emit_segment(buf)

        out.append(f"{base_indent}        break {label}")

    out.append(f"{base_indent}    default:")
    out.append(f'{base_indent}        preconditionFailure("unreachable cff state")')
    out.append(f"{base_indent}    }}")
    out.append(f"{base_indent}}}")

    return "\n".join(out)

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/ast.json")
        sys.exit(1)

    ast_path = Path(sys.argv[1])
    with ast_path.open(encoding="utf-8") as f:
        ast = json.load(f)

    replaced = 0
    skipped = 0
    missing = 0

    for chain in ast.get("ifChains", []):
        file_path = Path(chain.get("path","") or "")
        old = chain.get("text"," ")

        new_text = render_chain_flatten(chain)
        if not new_text:
            #print(f"[SKIP] {file_path} (ineligible by condition)")
            skipped += 1
            continue

        if not file_path.exists():
            #print(f"[SKIP] not found: {file_path}")
            skipped += 1
            continue

        src = file_path.read_text(encoding="utf-8")
        if old not in src:
            #print(f"[MISS] original snippet not found in {file_path}")
            missing += 1
            continue

        new_src = src.replace(old, new_text, 1)
        file_path.write_text(new_src, encoding="utf-8")
        #print(f"[OK] replaced in {file_path}")
        replaced += 1

    #print("=== Summary ===")
    #print(f"  Replaced: {replaced}")
    #print(f"  Skipped:  {skipped}")
    #print(f"  Missing:  {missing}")

if __name__ == "__main__":
    main()

