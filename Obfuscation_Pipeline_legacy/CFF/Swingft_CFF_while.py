import json
import sys
import re
from pathlib import Path
import subprocess

KEYWORDS_OR_CTRL = {
    "if", "for", "while", "switch", "guard", "func", "return", "break", "continue",
    "defer", "catch", "throw", "try", "await", "init", "deinit", "case", "default",
    "in", "where", "else"
}

CALL_CANDIDATE_RE = re.compile(r'(?<![\.\w])([a-z_]\w*)\s*\(')

def is_pure_bool(cond: str) -> bool:
    if cond is None:
        return False
    c = cond.strip()
    banned = [
        " let ", "let(", " var ", "var(", "case ", " try", " await",
        "\tlet ", "\tvar ", "\tcase "
    ]
    c_pad = f" {c} "
    return not any(b in c_pad for b in banned)

def parse_let_var_binding(cond: str):
    if not cond:
        return None
    m = re.match(r'^\s*(let|var)\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$', cond.strip())
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None

def extract_body(loop_text: str) -> str:
    start = loop_text.find('{')
    if start == -1:
        raise ValueError("No '{' in loop text")
    depth = 0
    for i in range(start, len(loop_text)):
        ch = loop_text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return loop_text[start+1:i]
    raise ValueError("No matching '}' found")

def make_label_name(i: int) -> str:
    return f"cffLoopWhile{i}"

def make_state_name(i: int) -> str:
    return f"cffStateWhile{i}"


def add_self_if_needed(line: str) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in KEYWORDS_OR_CTRL:
            return m.group(0)  
        return f"{name}("

    return CALL_CANDIDATE_RE.sub(repl, line)

def transform_body_lines(body_src: str, base_indent: str, label: str, state_var: str, use_state_reset: bool) -> list:

    out = []
    for ln in body_src.splitlines():
        raw = ln.rstrip("\n")
        stripped = raw.strip()

        if re.fullmatch(r'continue;?', stripped):
            if use_state_reset:
                out.append(f"{base_indent}        {state_var} = 0")
            out.append(f"{base_indent}        continue {label}")
            continue

        if re.fullmatch(r'break;?', stripped):
            out.append(f"{base_indent}        break {label}")
            continue

        safe = add_self_if_needed(raw)
        out.append(f"{base_indent}        {safe}")

    return out


def build_flattened_for_pure_bool(loop_text: str, cond: str, idx: int) -> str:
    first_line = loop_text.splitlines()[0]
    indent = first_line[:len(first_line) - len(first_line.lstrip())]
    body_src = extract_body(loop_text)
    label = make_label_name(idx)
    state_var = make_state_name(idx)

    lines = []
    lines.append(f"{indent}var {state_var} = 0")
    lines.append(f"{indent}{label}: while true {{")
    lines.append(f"{indent}    switch {state_var} {{")
    lines.append(f"{indent}    case 0:")
    lines.append(f"{indent}        guard {cond} else {{ break {label} }}")
    lines.append(f"{indent}        {state_var} = 1")
    lines.append(f"{indent}        continue {label}")
    lines.append(f"{indent}    case 1:")
    lines.extend(transform_body_lines(body_src, indent, label, state_var, use_state_reset=True))
    lines.append(f"{indent}        {state_var} = 0")
    lines.append(f"{indent}        continue {label}")
    lines.append(f"{indent}    default:")
    lines.append(f'{indent}        preconditionFailure("unreachable cff state")')
    lines.append(f"{indent}    }}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)

def build_flattened_for_let_var(loop_text: str, kw: str, name: str, expr: str, idx: int) -> str:
    first_line = loop_text.splitlines()[0]
    indent = first_line[:len(first_line) - len(first_line.lstrip())]
    body_src = extract_body(loop_text)
    label = make_label_name(idx)
    state_var = make_state_name(idx)  

    lines = []
    lines.append(f"{indent}var {state_var} = 0")
    lines.append(f"{indent}{label}: while true {{")
    lines.append(f"{indent}    switch {state_var} {{")
    lines.append(f"{indent}    case 0:")
    lines.append(f"{indent}        if {kw} {name} = {expr} {{")
    lines.extend(transform_body_lines(body_src, indent, label, state_var, use_state_reset=False))
    lines.append(f"{indent}            continue {label}")
    lines.append(f"{indent}        }} else {{")
    lines.append(f"{indent}            break {label}")
    lines.append(f"{indent}        }}")
    lines.append(f"{indent}    default:")
    lines.append(f"{indent}        break {label}")
    lines.append(f"{indent}    }}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def replace_once(file_path: Path, original: str, replacement: str) -> bool:
    try:
        src = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[ERROR] read failed: {file_path} ({e})")
        return False
    if original not in src:
        return False
    new_src = src.replace(original, replacement, 1)
    try:
        file_path.write_text(new_src, encoding="utf-8")
    except Exception as e:
        print(f"[ERROR] write failed: {file_path} ({e})")
        return False
    return True

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/ast.json")
        sys.exit(1)

    ast_path = Path(sys.argv[1])
    data = json.loads(ast_path.read_text(encoding="utf-8"))

    count_ok = 0
    count_skip = 0
    count_missing = 0
    idx = 0

    for loop in data.get("loops", []):
        if loop.get("kind") != "whileLoop":
            continue

        cond = loop.get("header", "") or ""
        file_path = Path(loop.get("path", ""))
        loop_text = loop.get("text", "") or ""

        if not file_path.exists():
            
            count_skip += 1
            continue
        if not loop_text.strip().startswith("while"):
            
            count_skip += 1
            continue

        lv = parse_let_var_binding(cond)
        if lv:
            kw, name, expr = lv
            flattened = build_flattened_for_let_var(loop_text, kw, name, expr, idx)
            idx += 1
            ok = replace_once(file_path, loop_text, flattened)
            if ok:
                
                count_ok += 1
            else:
               
                count_missing += 1
            continue

        if is_pure_bool(cond):
            flattened = build_flattened_for_pure_bool(loop_text, cond, idx)
            idx += 1
            ok = replace_once(file_path, loop_text, flattened)
            if ok:
                
                count_ok += 1
            else:
                
                count_missing += 1
        else:
            
            count_skip += 1

if __name__ == "__main__":
    main()
