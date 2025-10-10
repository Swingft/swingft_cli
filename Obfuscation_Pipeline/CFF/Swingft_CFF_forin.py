from __future__ import annotations
import argparse, json, re, textwrap
from pathlib import Path
from typing import Any, List, Tuple


def collect(node: Any, acc: List[dict]):
    if isinstance(node, dict):
        if node.get("kind") == "forIn":
            acc.append(node)
        for ch in node.get("nestedLoops", []):
            collect(ch, acc)
    elif isinstance(node, list):
        for it in node:
            collect(it, acc)



def escape_ws_flex(s: str, star: bool=False) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i].isspace():
            j = i+1
            while j < len(s) and s[j].isspace(): j += 1
            out.append(r"\s*" if star else r"\s+")
            i = j
        else:
            out.append(re.escape(s[i]))
            i += 1
    return "".join(out)

def build_header_rx(header: str) -> re.Pattern:
    if " where " in header or " in " not in header:
        raise ValueError(f"invalid header {header!r}")
    pat, it = header.split(" in ", 1)
    pat_re = escape_ws_flex(pat.strip(), star=True)
    it_core = escape_ws_flex(it.strip(), star=True)
    it_re = rf"(?:\(\s*{it_core}\s*\)|{it_core})"
    return re.compile(rf"for\s+{pat_re}\s+in\s+{it_re}\s*{{", re.MULTILINE)

def find_block(src: str, brace_pos: int) -> Tuple[int,int]:
    assert src[brace_pos] == "{"
    depth = 0
    i = brace_pos
    n = len(src)
    while i < n:
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return brace_pos, i
        i += 1
    raise ValueError("matching '}' not found")

def detect_indent_at(src: str, pos: int) -> str:
    ls = src.rfind("\n", 0, pos) + 1
    le = src.find("\n", pos)
    if le == -1: le = len(src)
    line = src[ls:le]
    return line[:len(line)-len(line.lstrip())]

def strip_trailing_semicolons(s: str) -> str:
    return re.sub(r"[ \t]*;[ \t]*\n", "\n", s)

def body_text(src: str, lpos: int, rpos: int) -> str:
    return src[lpos+1:rpos]

def looks_like_outer_has_only_inner(outer_text: str, inner_text: str) -> bool:
    body_l = outer_text.find("{")
    if body_l < 0: return False
    depth = 0
    r = body_l
    while r < len(outer_text):
        if outer_text[r] == "{": depth += 1
        elif outer_text[r] == "}":
            depth -= 1
            if depth == 0: break
        r += 1
    body = outer_text[body_l+1:r]
    norm = re.sub(r"\s+", "", body.replace("continue", ""))
    norm_inner = re.sub(r"\s+", "", inner_text)
    return norm == norm_inner

def has_plain_break(body: str) -> bool:
    return re.search(r"\bbreak\b", body) is not None

def has_switch_keyword(body: str) -> bool:
    return re.search(r"\bswitch\b", body) is not None



def classify_pat(p: str) -> str:
    ps = p.strip()
    if ps.startswith("case "): return "case"
    if ps.startswith("(") and ps.endswith(")"): return "tuple"
    return "ident"

def pat_idents(p: str) -> set[str]:
    toks = set(re.findall(r"\b[a-zA-Z_]\w*\b", p))
    return {t for t in toks if t not in {"case","let","var","as","is","try","_"}}

def bind_step_lines(pat: str, itv: str, lbl: str, indent: str, on_exhaust: str) -> list[str]:
    
    kind = classify_pat(pat)
    if kind == "ident":
        return [f"{indent}guard let {pat} = {itv}.next() else {{ {on_exhaust} }}"]
    if kind == "tuple":
        return [
            f"{indent}guard let cffitem = {itv}.next() else {{ {on_exhaust} }}",
            f"{indent}let {pat} = cffitem",
        ]
    return [
        f"{indent}guard let cffitem = {itv}.next() else {{ {on_exhaust} }}",
        f"{indent}guard {pat} = cffitem else {{ continue {lbl} }}",
    ]

def relabel_break_to(body: str, label: str) -> str:
    def repl_line(m: re.Match) -> str:
        line = m.group(0)
        return re.sub(r"\bbreak\b", f"break {label}", line)
    return re.sub(
        r"(?m)^[ \t]*break[ \t]*;(?:[ \t]*//.*)?$|^[ \t]*break[ \t]*(?=}$)|^[ \t]*break[ \t]*$",
        repl_line,
        body,
    )



def extract_inner_body_from_text(loop_text: str) -> str:
    ib = loop_text.find("{")
    if ib == -1: return ""
    d=0; j=ib
    while j < len(loop_text):
        if loop_text[j] == "{": d+=1
        elif loop_text[j] == "}":
            d-=1
            if d==0: break
        j+=1
    return loop_text[ib+1:j]

def extract_flattenable_chain(lp: dict, outer_text: str) -> Tuple[List[str], str]:

    headers: List[str] = []
    cur = lp
    cur_text = outer_text
    while True:
        h = cur.get("header") or ""
        if " where " in h or " in " not in h: break
        headers.append(h)
        nested = cur.get("nestedLoops") or []

        if not (len(nested) == 1 and nested[0].get("kind") == "forIn" and " where " not in (nested[0].get("header") or "")):
            
            inner_body = extract_inner_body_from_text(cur_text)
            return headers, inner_body
        inner = nested[0]
        inner_text = inner.get("text") or ""
        if not looks_like_outer_has_only_inner(cur_text, inner_text):
            inner_body = extract_inner_body_from_text(cur_text)
            return headers, inner_body
       
        cur = inner
        cur_text = inner_text

def chain_safe_to_single_while(headers: List[str]) -> bool:
    pats = []
    its  = []
    for h in headers:
        pat, it = [x.strip() for x in h.split(" in ", 1)]
        pats.append(pat); its.append(it)

    if any(classify_pat(p) == "case" for p in pats):
        return False

    captured: set[str] = set()
    for i, p in enumerate(pats):
        captured |= pat_idents(p)
        if i+1 < len(its):
            inners = its[i+1:]
            for it in inners:
                for name in captured:
                  
                    if re.search(rf"\b{re.escape(name)}\b", it):
                        return False
    return True



def build_switch_flat_single(header: str, body: str, indent: str, uid: int) -> str:
    if " in " not in header:
        raise ValueError("invalid header")
    pat, it = [x.strip() for x in header.split(" in ", 1)]
    itv  = f"cffIterFor{uid}"
    st   = f"cffStateFor{uid}"
    lbl  = f"cffLoopFor{uid}"

    body_core = strip_trailing_semicolons(body).strip("\n")
    if has_plain_break(body_core) and not has_switch_keyword(body_core):
        body_core = relabel_break_to(body_core, lbl)
    body_ind = textwrap.indent(body_core, indent + "            ")

    bind = "\n".join(bind_step_lines(pat, itv, lbl, indent + "            ", f"break {lbl}"))

    return (
        f"{indent}do {{\n"
        f"{indent}    var {itv} = ({it}).makeIterator()\n"
        f"{indent}    var {st} = 0\n"
        f"{indent}    {lbl}: while true {{\n"
        f"{indent}        switch {st} {{\n"
        f"{indent}        case 0:\n"
        f"{bind}\n"
        f"{body_ind}\n"
        f"{indent}            {st} = 0\n"
        f"{indent}            continue {lbl}\n"
        f"{indent}        default:\n"
        f"{indent}            break {lbl}\n"
        f"{indent}        }}\n"
        f"{indent}    }}\n"
        f"{indent}}}"
    )

def build_while_chain(headers: List[str], inner_body: str, indent: str, uid: int) -> str:
    
    n = len(headers)
    assert n >= 2
    lbls = [f"cffLoopFor{uid}_{i}" for i in range(n)]
    itvs = [f"cffIterFor{uid}_{i}" for i in range(n)]

    blocks_open: List[str] = []
    blocks_close: List[str] = []

   
    pat0, it0 = [x.strip() for x in headers[0].split(" in ", 1)]
    outer = []
    outer.append(f"{indent}do {{")
    outer.append(f"{indent}    var {itvs[0]} = ({it0}).makeIterator()")
    outer.append(f"{indent}    {lbls[0]}: while true {{")
    bind0 = "\n".join(bind_step_lines(pat0, itvs[0], lbls[0], indent + "        ", f"break {lbls[0]}"))
    outer.append(bind0)
    blocks_open.extend(outer)

  
    for i in range(1, n):
        pat, it = [x.strip() for x in headers[i].split(" in ", 1)]
        blocks_open.append(f"{indent}{'    '*i}    do {{")
        blocks_open.append(f"{indent}{'    '*i}        var {itvs[i]} = ({it}).makeIterator()")
        blocks_open.append(f"{indent}{'    '*i}        {lbls[i]}: while true {{")
        bind = "\n".join(bind_step_lines(pat, itvs[i], lbls[i], indent + "    "*(i+2), f"continue {lbls[i-1]}"))
        blocks_open.append(bind)


    body_core = strip_trailing_semicolons(inner_body).strip("\n")
    if has_plain_break(body_core) and not has_switch_keyword(body_core):
  
        body_core = relabel_break_to(body_core, lbls[-1])
    body_ind = textwrap.indent(body_core, indent + "    "*(n+2))
    blocks_open.append(body_ind)
    blocks_open.append(f"{indent}{'    '*(n+2)}continue {lbls[-1]}")

    for i in reversed(range(1, n)):
        blocks_close.append(f"{indent}{'    '*i}        }}")
        blocks_close.append(f"{indent}{'    '*i}    }}")
        blocks_close.append(f"{indent}{'    '*i}    continue {lbls[i-1]}")
    blocks_close.append(f"{indent}    }}")
    blocks_close.append(f"{indent}}}")

    return "\n".join(blocks_open + blocks_close)

def build_chain_switch_flat(headers: List[str], inner_body: str, indent: str, uid: int) -> str:
   
    n = len(headers)
    assert n >= 2
    lbl = f"cffLoopFor{uid}"
    st  = f"cffStateFor{uid}"
    itvs = [f"cffIterFor{uid}_{i}" for i in range(n)]

    pats: List[str] = []
    its:  List[str] = []
    for h in headers:
        p, it = [x.strip() for x in h.split(" in ", 1)]
        pats.append(p); its.append(it)

    lines = []
    lines.append(f"{indent}do {{")

    for i in range(n):
        lines.append(f"{indent}    var {itvs[i]} = ({its[i]}).makeIterator()")
    lines.append(f"{indent}    var {st} = 0")
    lines.append(f"{indent}    {lbl}: while true {{")
    lines.append(f"{indent}        switch {st} {{")

    
    for i in range(n-1):
        lines.append(f"{indent}        case {i}:")
        on_exhaust = f"break {lbl}" if i == 0 else f"{st} = {i-1}; continue {lbl}"
        bind = "\n".join(bind_step_lines(pats[i], itvs[i], lbl, indent + "            ", on_exhaust))
        lines.append(bind)
        lines.append(f"{indent}            {st} = {i+1}")
        lines.append(f"{indent}            continue {lbl}")

    body_core = strip_trailing_semicolons(inner_body).strip("\n")
    if has_plain_break(body_core) and not has_switch_keyword(body_core):
        body_core = relabel_break_to(body_core, lbl)
    body_ind = textwrap.indent(body_core, indent + "            ")

    lines.append(f"{indent}        case {n-1}:")
    on_exhaust = f"{st} = {n-2}; continue {lbl}" if n >= 2 else f"break {lbl}"
    bind = "\n".join(bind_step_lines(pats[-1], itvs[-1], lbl, indent + "            ", on_exhaust))
    lines.append(bind)
    lines.append(body_ind)
    lines.append(f"{indent}            {st} = {n-1}")
    lines.append(f"{indent}            continue {lbl}")

    lines.append(f"{indent}        default:")
    lines.append(f"{indent}            break {lbl}")
    lines.append(f"{indent}        }}")
    lines.append(f"{indent}    }}")
    lines.append(f"{indent}}}")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ast", required=True, help="Path to ast.json")
    args = ap.parse_args()

    ast = json.loads(Path(args.ast).read_text(encoding="utf-8"))
    loops: List[dict] = []
    collect(ast.get("loops", []), loops)

    uid_per_file: dict[Path,int] = {}
    modified = 0

    for lp in loops:
        header = lp.get("header") or ""
        if " where " in header:
            continue

        path = Path(lp.get("path") or "")
        if not path.exists():
            print(f"[MISS] 파일 없음: {path}")
            continue

        src = path.read_text(encoding="utf-8")

        try:
            rx = build_header_rx(header)
        except Exception:
            continue
        m = rx.search(src)
        if not m:
            continue
        brace = src.find("{", m.start())
        if brace == -1:
            continue
        lpos, rpos = find_block(src, brace)
        outer_text = src[m.start(): rpos+1]
        outer_indent = detect_indent_at(src, m.start())

        headers_chain, inner_body = extract_flattenable_chain(lp, outer_text)
        if len(headers_chain) >= 2:
            uid = uid_per_file.get(path, 0); uid_per_file[path] = uid+1
            try:
                if chain_safe_to_single_while(headers_chain):
                    replacement = build_chain_switch_flat(headers_chain, inner_body, outer_indent, uid)
                    tag = "CHAIN_SWITCH"
                else:
                    replacement = build_while_chain(headers_chain, inner_body, outer_indent, uid)
                    tag = "CHAIN_WHILE"
            except Exception as e:
                
                continue

            new_src = src[:m.start()] + replacement + src[rpos+1:]
            path.write_text(new_src, encoding="utf-8")
           
            modified += 1
            continue

        body = body_text(src, lpos, rpos)
        uid = uid_per_file.get(path, 0); uid_per_file[path] = uid+1
        try:
            replacement = build_switch_flat_single(header, body, outer_indent, uid)
        except Exception as e:
           
            continue

        new_src = src[:m.start()] + replacement + src[rpos+1:]
        path.write_text(new_src, encoding="utf-8")
        
        modified += 1

    


if __name__ == "__main__":
    main()
