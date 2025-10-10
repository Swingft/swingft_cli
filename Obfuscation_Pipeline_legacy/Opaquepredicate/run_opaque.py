import sys, re, json, hashlib, random, os
from pathlib import Path
from typing import Optional, List, Set, Tuple

def hval(s: str) -> int:
    return int(hashlib.sha1(s.encode("utf-8")).hexdigest(), 16)

def is_ident_char(c: str) -> bool:
    return c.isalnum() or c == '_'

OPQ_PREFIX = "opq"

OPQ_TOKEN_RE = re.compile(r'\b(OPQ[A-Za-z]+)\b')
OPQ_CALL_RE  = re.compile(r'\b(OPQ[A-Za-z]+)\s*\(')

MAX_CASE_EDITS_PER_SWITCH = 2


INLINE_STD_POOL = [
    'CommandLine.arguments.count >= 1',
    'CommandLine.arguments.isEmpty == false',
]
INLINE_FND_POOL = [
    'ProcessInfo.processInfo.activeProcessorCount > 0',
    'Date().timeIntervalSince1970 >= 0',
    'UUID().uuidString.isEmpty == false',
    'Bundle.main.bundlePath.isEmpty == false',
]
FOUNDATION_IMPORT_RE = re.compile(r'(?m)^\s*import\s+Foundation\b')

def ensure_import_foundation(text: str) -> Tuple[str, bool]:
    if FOUNDATION_IMPORT_RE.search(text): return text, False
    idx = top_insertion_index(text)
    return text[:idx] + "import Foundation\n" + text[idx:], True

def scan_used_opq_names(project_root: Path) -> Set[str]:
    used: Set[str] = set()
    for p in project_root.rglob("*.swift"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in OPQ_TOKEN_RE.finditer(text):
            used.add(m.group(1))
    return used

class NameAllocator:
    def __init__(self, pool: List[str], already_used: Set[str]):
        self.pool = [n for n in pool if isinstance(n, str) and n.isidentifier() and n.startswith(OPQ_PREFIX)]
        self.skip = set(already_used)
        self.idx = 0
        self.n = len(self.pool)
    def next(self) -> str:
        while self.idx < self.n and self.pool[self.idx] in self.skip:
            self.idx += 1
        if self.idx >= self.n:
            raise RuntimeError("Name pool exhausted: no more unique opq names available.") 
        name = self.pool[self.idx]
        self.skip.add(name)
        self.idx += 1
        return name

def top_insertion_index(text: str) -> int:
    def skip_ws_comments(t, i):
        n=len(t)
        while i<n:
            if t.startswith("//", i):
                j=t.find("\n", i); i=n if j==-1 else j+1
            elif t.startswith("/*", i):
                j=t.find("*/", i+2); i=n if j==-1 else j+2
            elif i<n and t[i] in " \t\r\n":
                i+=1
            else:
                break
        return i
    def find_endif(t,i):
        m=re.match(r'#if\b', t[i:])
        if not m: return None
        d,j,n=1,i+m.end(),len(t)
        while j<n:
            if t.startswith("/*", j):
                e=t.find("*/", j+2); j=n if e==-1 else e+2; continue
            if t.startswith("//", j):
                e=t.find("\n", j); j=n if e==-1 else e+1; continue
            if t.startswith("#if", j): d+=1; j+=3; continue
            if t.startswith("#endif", j):
                d-=1; j+=6
                if d==0:
                    if j<n and t[j:j+1]=="\n": j+=1
                    return j
                continue
            j+=1
        return None

    i = 1 if text.startswith("\ufeff") else 0
    if text.startswith("#!", i):
        nl=text.find("\n", i); i=len(text) if nl==-1 else nl+1
    while True:
        old=i
        i=skip_ws_comments(text,i)
        if text.startswith("#if", i):
            e=find_endif(text,i)
            if e is None: break
            i=e; continue
        moved=False
        while True:
            m=re.match(r'[ \t]*import[ \t].*\n?', text[i:])
            if not m: break
            i+=m.end(); moved=True
        if not moved and i==old: break
    return i

def insert_predicate_funcs(text: str, names: List[str]) -> str:
    if not names: return text
    idx = top_insertion_index(text)
    bodies = []
    for i, nm in enumerate(names):
        if re.search(rf'\bfunc\s+{re.escape(nm)}\s*\(\s*\)\s*->\s*Bool\b', text):
            continue
        kind = i % 3
        if kind == 0:
            body = (
                f"@inline(never)\nfileprivate func {nm}() -> Bool {{\n"
                f"    var opTmp = 1; opTmp ^= 1; opTmp ^= 1\n"
                f"    return (opTmp | 1) == 1\n"
                f"}}\n\n"
            )
        elif kind == 1:
            body = (
                f"@inline(never)\nfileprivate func {nm}() -> Bool {{\n"
                f"    var isTrue = 0\n"
                f"    for makeTrue in 0..<1 {{ isTrue += makeTrue }}\n"
                f"    return (isTrue | 1) == 1\n"
                f"}}\n\n"
            )
        else:
            body = (
                f"@inline(never)\nfileprivate func {nm}() -> Bool {{\n"
                f"    var isActivate = [1]\n"
                f"    isActivate.append(1); isActivate.removeLast()\n"
                f"    return isActivate.count >= 1\n"
                f"}}\n\n"
            )
        bodies.append(body)
    return text[:idx] + "".join(bodies) + text[idx:]

class SwitchNode:
    __slots__ = ("s", "obr", "e", "children")
    def __init__(self, s: int, obr: int, e: int):
        self.s = s
        self.obr = obr
        self.e = e
        self.children: List["SwitchNode"] = []

def find_matching_brace(text: str, ob: int, limit: Optional[int]=None) -> Optional[int]:
    n = len(text) if limit is None else limit
    i = ob
    depth = 0
    in_sl = in_ml = in_str = False
    esc = False
    while i < n:
        ch = text[i]
        if in_sl:
            if ch == '\n': in_sl = False
        elif in_ml:
            if ch == '*' and i+1 < n and text[i+1] == '/':
                in_ml = False; i += 1
        elif in_str:
            if esc: esc=False
            elif ch == '\\': esc=True
            elif ch == '"': in_str=False
        else:
            if ch == '/' and i+1 < n and text[i+1] == '/':
                in_sl = True; i += 1
            elif ch == '/' and i+1 < n and text[i+1] == '*':
                in_ml = True; i += 1
            elif ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None

def next_switch_token(text: str, i: int, limit: Optional[int]=None) -> Optional[int]:
    n = len(text) if limit is None else limit
    in_sl = in_ml = in_str = False
    esc = False
    while i < n:
        ch = text[i]
        if in_sl:
            if ch == '\n': in_sl = False
            i += 1; continue
        if in_ml:
            if ch == '*' and i+1<n and text[i+1]=='/': in_ml=False; i+=2; continue
            i += 1; continue
        if in_str:
            if esc: esc=False
            elif ch == '\\': esc=True
            elif ch == '"': in_str=False
            i += 1; continue

        if ch == '/' and i+1<n and text[i+1]=='/': in_sl=True; i+=2; continue
        if ch == '/' and i+1<n and text[i+1]=='*': in_ml=True; i+=2; continue
        if ch == '"': in_str=True; i+=1; continue

        if text.startswith("switch", i):
            left_ok  = (i==0 or not is_ident_char(text[i-1]))
            right_ok = (i+6>=n or not is_ident_char(text[i+6]))
            if left_ok and right_ok:
                return i
        i += 1
    return None

def build_switch_tree(text: str, start: int=0, end: Optional[int]=None) -> List[SwitchNode]:
    if end is None: end = len(text)
    nodes: List[SwitchNode] = []
    i = start
    while True:
        pos = next_switch_token(text, i, end)
        if pos is None: break
        j = pos + 6
        in_sl = in_ml = in_str = False
        esc = False
        obr = None
        while j < end:
            ch = text[j]
            if in_sl:
                if ch == '\n': in_sl = False
            elif in_ml:
                if ch == '*' and j+1<end and text[j+1]=='/': in_ml=False; j += 1
            elif in_str:
                if esc: esc=False
                elif ch=='\\': esc=True
                elif ch=='"': in_str=False
            else:
                if ch=='/' and j+1<end and text[j+1]=='/': in_sl=True; j+=1
                elif ch=='/' and j+1<end and text[j+1]=='*': in_ml=True; j+=1
                elif ch=='"': in_str=True
                elif ch=='{':
                    obr = j; break
            j += 1
        if obr is None:
            i = pos + 6; continue
        cb = find_matching_brace(text, obr, end)
        if cb is None:
            i = obr + 1; continue
        node = SwitchNode(pos, obr, cb+1)
        node.children = build_switch_tree(text, obr+1, cb)
        nodes.append(node)
        i = cb + 1
    return nodes

def body_has_top_level_default(text: str, body_start: int, body_end: int) -> bool:
    i = body_start
    in_sl = in_ml = in_str = False
    esc = False
    depth = 0
    while i < body_end:
        ch = text[i]
        if in_sl:
            if ch == '\n': in_sl = False
        elif in_ml:
            if ch == '*' and i+1<body_end and text[i+1]=='/': in_ml=False; i += 1
        elif in_str:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
        else:
            if ch=='/' and i+1<body_end and text[i+1]=='/': in_sl=True; i+=1
            elif ch=='/' and i+1<body_end and text[i+1]=='*': in_ml=True; i+=1
            elif ch=='"': in_str=True
            elif ch=='{': depth += 1
            elif ch=='}': depth = max(0, depth-1)
            else:
                if depth==0 and text.startswith("default", i):
                    left_ok  = (i==body_start or text[i-1] in " \t\r\n")
                    right = i+7
                    if left_ok:
                        j = right
                        while j < body_end:
                            if text[j] in " \t": j += 1; continue
                            if text.startswith("/*", j):
                                k = text.find("*/", j+2, body_end)
                                if k == -1: break
                                j = k + 2
                                continue
                            break
                        if j < body_end and text[j] == ':':
                            return True
        i += 1
    return False

def subtree_all_have_default(node: SwitchNode, text: str) -> bool:
    if not body_has_top_level_default(text, node.obr+1, node.e-1):
        return False
    return all(subtree_all_have_default(ch, text) for ch in node.children)


IF_HEADER_RE = re.compile(r'(?m)^(?P<i>\s*)(?P<e>else\s+)?if(?P<h>[\s\S]*?)\{', re.UNICODE)
ARG_LABEL_WHERE_RE = re.compile(r'\b(where\s*:|comment\s+where\b)', re.UNICODE)
NSLOCALIZED_RE = re.compile(r'\bNSLocalizedString\s*\(', re.UNICODE)
GENERIC_CALL_RE = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\s*\(', re.UNICODE)
TRAILING_CLOSURE_RE = re.compile(r'\.\s*(first|map|filter|sorted|compactMap)\s*$', re.UNICODE)

def has_top_level_binding(head: str) -> bool:
    depth = 0; i = 0; n = len(head)
    in_sl = in_ml = in_str = False; esc = False
    while i < n:
        ch = head[i]
        if in_sl:
            if ch == '\n': in_sl = False
        elif in_ml:
            if ch == '*' and i+1<n and head[i+1]=='/': in_ml=False; i += 1
        elif in_str:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
        else:
            if ch=='/' and i+1<n and head[i+1]=='/': in_sl=True; i+=1
            elif ch=='/' and i+1<n and head[i+1]=='*': in_ml=True; i+=1
            elif ch=='"': in_str=True
            elif ch=='(':
                depth += 1
            elif ch==')':
                depth = max(0, depth-1)
            elif depth == 0:
                for kw in ("let", "var", "case"):
                    k = len(kw)
                    if head.startswith(kw, i) and (i==0 or not is_ident_char(head[i-1])) and (i+k==n or not is_ident_char(head[i+k])):
                        return True
        i += 1
    return False

def header_has_our_marks(s: str) -> bool:
    return OPQ_CALL_RE.search(s) is not None

def has_top_level_where(s: str) -> bool:
    i=0; n=len(s)
    in_sl=in_ml=in_str=False; esc=False; depth=0
    while i<n:
        ch=s[i]
        if in_sl:
            if ch=='\n': in_sl=False; i+=1; continue
            i+=1; continue
        if in_ml:
            if ch=='*' and i+1<n and s[i+1]=='/': in_ml=False; i+=2; continue
            i+=1; continue
        if in_str:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
            i+=1; continue
        if ch=='/' and i+1<n and s[i+1]=='/': in_sl=True; i+=2; continue
        if ch=='/' and i+1<n and s[i+1]=='*': in_ml=True; i+=2; continue
        if ch=='"': in_str=True; i+=1; continue
        if ch=='(':
            depth+=1; i+=1; continue
        if ch==')':
            depth=max(0,depth-1); i+=1; continue
        if depth==0 and s.startswith("where", i):
            left_ok = (i==0 or not is_ident_char(s[i-1]))
            right_ok = (i+5>=n or not is_ident_char(s[i+5]))
            if left_ok and right_ok:
                return True
        i+=1
    return False

def find_if_block_open_brace(text: str, start: int) -> Optional[int]:
   
    i = start
    n = len(text)
    in_sl = in_ml = in_str = False
    esc = False
    paren = 0
    inner_brace = 0

    while i < n:
        ch = text[i]
        if in_sl:
            if ch == '\n': in_sl = False
            i += 1; continue
        if in_ml:
            if ch == '*' and i+1 < n and text[i+1] == '/': in_ml = False; i += 2; continue
            i += 1; continue
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
            i += 1; continue

        if ch == '/' and i+1 < n and text[i+1] == '/': in_sl = True; i += 2; continue
        if ch == '/' and i+1 < n and text[i+1] == '*': in_ml = True; i += 2; continue
        if ch == '"': in_str = True; i += 1; continue

        if ch == '(':
            paren += 1; i += 1; continue
        if ch == ')':
            paren = max(0, paren-1); i += 1; continue
        if ch == '{':
            if paren == 0 and inner_brace == 0:
                return i
            inner_brace += 1; i += 1; continue
        if ch == '}':
            if inner_brace > 0: inner_brace -= 1
            i += 1; continue

        i += 1
    return None

def choose_predicate_snippet(ctx: 'FileCtx', site_key: str, prefer_func_first: bool) -> Tuple[str, bool]:
    if prefer_func_first and ctx.first_flag:
        ctx.first_flag = False
        return f"{ctx.choose_func_name()}()", True
    score = hval(site_key)
    use_func = (score % 3 != 0)
    if use_func:
        return f"{ctx.choose_func_name()}()", True
    else:
        return f"({ctx.choose_inline_expr(site_key)})", False

def transform_if_headers(text: str, ctx: 'FileCtx') -> Tuple[str,int]:
    edits=0; out=[]; pos=0
    for m in IF_HEADER_RE.finditer(text):
        head_start = m.start('h')
        real_brace = find_if_block_open_brace(text, head_start)
        if real_brace is None:
            s, e = m.span()
            out.append(text[pos:e]); pos = e
            continue

        out.append(text[pos:m.start()])

        indent = m.group('i') or ''
        elsekw = m.group('e') or ''
        head   = text[head_start:real_brace]
        if '#' in head:
            out.append(text[m.start():real_brace+1])
            pos = real_brace + 1
            continue
        
        if header_has_our_marks(head) or has_top_level_where(head) or ARG_LABEL_WHERE_RE.search(head):
            out.append(text[m.start():real_brace+1])
            pos = real_brace + 1
            continue
            
        if NSLOCALIZED_RE.search(head) or GENERIC_CALL_RE.search(head):
            out.append(text[m.start():real_brace+1])
            pos = real_brace + 1
            continue

        hs_trim = head.rstrip()
        if TRAILING_CLOSURE_RE.search(hs_trim):
            out.append(text[m.start():real_brace+1])
            pos = real_brace + 1
            continue


        hs = head.rstrip()
        pred_snippet, _is_func = choose_predicate_snippet(ctx, text[m.start():real_brace], prefer_func_first=True)

        if has_top_level_binding(hs):
            new_head = f"{hs}, {pred_snippet}"
        else:
            new_head = f"{hs} && {pred_snippet}"

        out.append(f"{indent}{elsekw or ''}if{new_head}" + "{")
        edits += 1
        pos = real_brace + 1

    out.append(text[pos:])
    return ''.join(out), edits

def transform_switch_body_cases(body: str, ctx: 'FileCtx') -> Tuple[str,int]:
    labels=[]
    i=0; n=len(body)
    in_sl=in_ml=in_str=False; esc=False; depth=0
    while i<n:
        ch=body[i]
        if in_sl:
            if ch=='\n': in_sl=False; i+=1; continue
            i+=1; continue
        if in_ml:
            if ch=='*' and i+1<n and body[i+1]=='/': in_ml=False; i+=2; continue
            i+=1; continue
        if in_str:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
            i+=1; continue
        if ch=='/' and i+1<n and body[i+1]=='/': in_sl=True; i+=2; continue
        if ch=='/' and i+1<n and body[i+1]=='*': in_ml=True; i+=2; continue
        if ch=='"': in_str=True; i+=1; continue
        if ch=='{': depth+=1; i+=1; continue
        if ch=='}': depth=max(0,depth-1); i+=1; continue

        if depth==0 and body.startswith("case", i):
            left_ok=(i==0 or body[i-1] in " \t\r\n")
            right_ok=(i+4>=n or not is_ident_char(body[i+4]))
            if left_ok and right_ok:
                j=i; colon=None
                while j<n and body[j] != '\n':
                    if body[j]==':': colon=j; break
                    j+=1
                if colon is not None:
                    header = body[i:colon]
                    labels.append((i, colon, header))
                    i = colon + 1
                    continue
        i+=1

    cands=[]
    for (s, colon, header) in labels:
        if header_has_our_marks(header): continue
        if has_top_level_where(header): continue
        if NSLOCALIZED_RE.search(header) or GENERIC_CALL_RE.search(header):
            continue

        if TRAILING_CLOSURE_RE.search(header.rstrip()):
            continue
        cands.append((s, colon, header, hval(header)))

    if not cands: return body,0
    cands.sort(key=lambda x:x[3])
    chosen=cands[:MAX_CASE_EDITS_PER_SWITCH]

    parts=[]; pos=0; edits=0
    for s,colon,header,_score in sorted(chosen,key=lambda x:x[0]):
        parts.append(body[pos:s])
        pred_snippet, _is_func = choose_predicate_snippet(ctx, header, prefer_func_first=True)
        new_header = f"{header} where {pred_snippet}"
        parts.append(new_header + body[colon:colon+1])
        pos = colon + 1
        edits += 1
    parts.append(body[pos:])
    return ''.join(parts), edits

def rewrite_switch_subtree(text: str, node: SwitchNode, allow_transform: bool, ctx: 'FileCtx') -> Tuple[str,int]:
    header = text[node.s: node.obr+1]
    body   = text[node.obr+1: node.e-1]
    footer = text[node.e-1: node.e]

    out=[]; last=0; case_edits_total=0
    for ch in node.children:
        rs = ch.s - (node.obr+1)
        re = ch.e - (node.obr+1)
        out.append(body[last:rs])
        child_allow = allow_transform and subtree_all_have_default(ch, text)
        sub_txt, ed = rewrite_switch_subtree(text, ch, child_allow, ctx)
        out.append(sub_txt)
        case_edits_total += ed
        last = re
    out.append(body[last:])
    mid = ''.join(out)

    if allow_transform:
        new_body, ed = transform_switch_body_cases(mid, ctx)
        case_edits_total += ed
    else:
        new_body = mid

    return header + new_body + footer, case_edits_total

class FileCtx:
    __slots__ = ("allocator","top_names","rng","first_flag","need_foundation")
    def __init__(self, allocator: NameAllocator, file_key: str):
        self.allocator = allocator
        self.top_names: List[str] = []
        self.rng = random.Random(hval(file_key))
        self.first_flag = True
        self.need_foundation = False

    def ensure_top_names(self):
        if self.top_names:
            return
        k = 1 + (self.rng.randint(0, 2))
        for _ in range(k):
            self.top_names.append(self.allocator.next())

    def choose_func_name(self) -> str:
        self.ensure_top_names()
        return self.rng.choice(self.top_names)

    def choose_inline_expr(self, site_key: str) -> str:
        s = hval(site_key + str(self.rng.random()))
        if (s & 1) == 0 and len(INLINE_FND_POOL) > 0:
            self.need_foundation = True
            return INLINE_FND_POOL[s % len(INLINE_FND_POOL)]
        return INLINE_STD_POOL[(s >> 1) % len(INLINE_STD_POOL)]

def process_file(p: Path, allocator: NameAllocator) -> dict:
    try:
        text = p.read_text(encoding='utf-8')
    except Exception:
        text = p.read_text(encoding='latin-1', errors='ignore')

    ctx = FileCtx(allocator, file_key=str(p.resolve()))

    roots = build_switch_tree(text)

    out=[]; last=0; case_edits_total=0
    for node in roots:
        out.append(text[last:node.s])
        allow = subtree_all_have_default(node, text)
        sub_txt, ed = rewrite_switch_subtree(text, node, allow, ctx)
        out.append(sub_txt)
        case_edits_total += ed
        last = node.e
    out.append(text[last:])
    mid = ''.join(out)

    after_if, if_edits = transform_if_headers(mid, ctx)

    total_edits = case_edits_total + if_edits
    final_stage = after_if

    if total_edits > 0 and ctx.need_foundation:
        final_stage, _ = ensure_import_foundation(final_stage)

    if total_edits > 0:
        ctx.ensure_top_names()
        final_stage = insert_predicate_funcs(final_stage, ctx.top_names)

    if final_stage != text:
        p.write_text(final_stage, encoding='utf-8')

    return {
        "file": str(p),
        "case_where_edits": case_edits_total,
        "if_edits": if_edits,
        "top_funcs_declared": len(ctx.top_names),
        "foundation_imported": ctx.need_foundation
    }

def run_opaque(root):
    root = Path(root)
    names_path = "./Opaquepredicate/opaque_predicate_names.json"
    if not os.path.exists(names_path):
        print(f"[ERR] names JSON not found: {names_path}", file=sys.stderr); sys.exit(2)

    try:
        with open(names_path, "r", encoding="utf-8") as f:
            pool = json.load(f)
        # pool = json.loads(names_path.read_text(encoding="utf-8"))
        if not isinstance(pool, list) or not all(isinstance(x, str) for x in pool):
            raise ValueError("names JSON must be a JSON array of strings")
    except Exception as e:
        print(f"[ERR] failed to load names JSON: {e}", file=sys.stderr); sys.exit(2)

    already_used = scan_used_opq_names(root)
    allocator = NameAllocator(pool, already_used)

    swift_files = [p for p in root.rglob("*.swift")
                   if all(seg not in p.as_posix() for seg in ["/.build/","/DerivedData/","/Pods/","/pods/"])]

    mod = 0
    for p in swift_files:
        r = process_file(p, allocator)
        if r["case_where_edits"] + r["if_edits"] > 0:
            mod += 1

