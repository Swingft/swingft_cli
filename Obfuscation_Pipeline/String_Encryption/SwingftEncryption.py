
import os
import re
import sys
import base64
import random
import shutil
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, List, Set

try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
except ImportError:
    import subprocess
    venv_dir = os.path.join(os.getcwd(), "venv")
    python_executable = os.path.join(venv_dir, "bin", "python")
    if not os.path.exists(venv_dir):
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.check_call([python_executable, "-m", "pip", "install", "--upgrade", "pip", "-q"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.check_call([python_executable, "-m", "pip", "install", "cryptography", "-q"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.execv(python_executable, [python_executable] + sys.argv)
    # subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

KEY_BYTE_LEN = 32

SWIFT_SIMPLE_ESCAPES = {
    r'\n': '\n',
    r'\r': '\r',
    r'\t': '\t',
    r'\"': '"',
    r"\'": "'",
    r'\\': '\\',
    r'\0': '\0',
}



def load_build_target_from_config(cfg_path: Optional[str]) -> Optional[str]:
    if not cfg_path:
        return None
    p = Path(cfg_path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        bt = (((data or {}).get("project") or {}).get("build_target") or "").strip()
        return bt or None
    except Exception:
        return None

def load_targets_map(targets_json_path: Optional[str]) -> Dict[str, List[str]]:
    if not targets_json_path:
        return {}
    p = Path(targets_json_path)
    if not p.exists():
        return {}
    try:
        m = json.loads(p.read_text(encoding='utf-8'))

        out: Dict[str, List[str]] = {}
        for k, v in (m or {}).items():
            if isinstance(v, list):
                out[str(k)] = [str(x) for x in v]
        return out
    except Exception:
        return {}

def choose_target_name(cands: List[str], want: str) -> Optional[str]:

    if want in cands:
        return want
    lw = want.lower()
    ic = [c for c in cands if c.lower() == lw]
    if ic:
        return ic[0]
    sub = [c for c in cands if lw in c.lower()]
    if len(sub) == 1:
        return sub[0]
    return None

def pick_files_for_target(cfg_path: Optional[str], targets_json_path: Optional[str]) -> List[str]:

    bt = load_build_target_from_config(cfg_path)
    if not bt:
        return []
    tmap = load_targets_map(targets_json_path)
    if not tmap:
        return []
    name = choose_target_name(list(tmap.keys()), bt)
    if not name:
        print(f"[WARNING] build_target '{bt}' not found in targets map. Fallback to project-wide.")
        return []
    paths = [os.path.realpath(p) for p in (tmap.get(name) or [])]
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        print(f"[WARNING] target '{name}' has no existing files. Fallback to project-wide.")
        return []
    #print(f"[Swingft] Using target-scoped files ({name}): {len(paths)} files")
    return sorted(set(paths))



def ensure_import(swift_file: str) -> bool:
    p = Path(swift_file)
    try:
        s = p.read_text(encoding='utf-8')
    except Exception:
        return False
    if 'import StringSecurity' in s:
        return False
    lines = s.splitlines(True)
    first_import_idx = next((i for i, line in enumerate(lines)
                             if line.lstrip().startswith('import ')), 0)
    lines.insert(first_import_idx, 'import StringSecurity\n')
    try:
        p.write_text(''.join(lines), encoding='utf-8')
        return True
    except Exception:
        return False

def swift_unescape(s: str) -> str:
    def _u(m):
        return chr(int(m.group(1), 16))
    s = re.sub(r'\\u\{([0-9A-Fa-f]+)\}', _u, s)
    for k, v in SWIFT_SIMPLE_ESCAPES.items():
        s = s.replace(k, v)
    return s

def load_included_from_json(path: str):
    in_strings = defaultdict(set)   
    in_lines   = defaultdict(set)   

    with open(path, encoding='utf-8') as f:
        items = json.load(f)

    for obj in items:
        if (obj.get("kind") or "").upper() != "STR":
            continue
        file_raw = obj.get("file", "")
        file_raw = re.sub(r"^(?:STR|NUM)\s*:\s*", "", file_raw)
        abs_file = os.path.realpath(file_raw)
        line = obj.get("line")
        value = obj.get("value")
        if not abs_file or value is None:
            continue
        if isinstance(line, int) and line > 0:
            in_lines[abs_file].add(line)
        in_strings[abs_file].add(str(value))
    return in_strings, in_lines

def insert_import_and_key(path: str, chunk_count: int):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()

    has_import = any('import StringSecurity' in l for l in lines)
    has_key    = any('enum SwingftKey' in l for l in lines)

    if not has_import:
        first_import_idx = next((i for i, line in enumerate(lines)
                                 if line.lstrip().startswith('import ')), 0)
        lines.insert(first_import_idx, 'import StringSecurity\n')

    if not has_key:
        last_import_plus = 0
        for i, line in enumerate(lines):
            if line.lstrip().startswith('import '):
                last_import_plus = i + 1
            elif last_import_plus:
                break

        encoded_vars = ", ".join(f"encoded{i+1}" for i in range(chunk_count))
        mask_vars = ", ".join(f"mask{i+1}" for i in range(chunk_count))
      
        key_code = f'''
enum SwingftKey {{
    static func combinedKey() -> Data {{
        var key = [UInt8]()
        let encodedParts: [[UInt8]] = [{encoded_vars}]
        let maskParts: [[UInt8]] = [{mask_vars}]
        for findI in 0..<encodedParts.count {{
            for findJ in 0..<encodedParts[findI].count {{
                key.append(encodedParts[findI][findJ] ^ maskParts[findI][findJ])
            }}
        }}
        return Data(key)
    }}
}}
'''.lstrip()
        lines[last_import_plus:last_import_plus] = key_code.splitlines(keepends=True)

    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def detect_main_entry(files: List[str]):
    for path in files:
        try:
            with open(path, encoding='utf-8') as f:
                content = f.read()
            if re.search(r'@main\s+(struct|class)\s+\w+\s*:\s*App', content):
                return path, 'swiftui'
            if re.search(r'class\s+\w+\s*:\s*UIResponder\s*,\s*UIApplicationDelegate', content):
                return path, 'uikit'
        except Exception:
            continue
    return None, None

def patch_uikit_delegate(path):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()

    class_start = -1
    for i, line in enumerate(lines):
        if re.search(r'\bclass\s+\w+\s*:\s*UIResponder\s*,\s*UIApplicationDelegate\b', line):
            class_start = i
            break
    if class_start == -1:
        return

    depth = 0
    class_end = -1
    for i in range(class_start, len(lines)):
        depth += lines[i].count('{')
        depth -= lines[i].count('}')
        if depth == 0 and i > class_start:
            class_end = i
            break
    if class_end == -1:
        class_end = len(lines) - 1

    def find_method_range(token: str):
        method_start = -1
        for i in range(class_start, class_end + 1):
            if token in lines[i]:
                method_start = i
                depth = 0
                body_seen = False
                for k in range(i, class_end + 1):
                    depth += lines[k].count('{')
                    depth -= lines[k].count('}')
                    if '{' in lines[k]:
                        body_seen = True
                    if body_seen and depth == 0:
                        return method_start, k
                break
        return -1, -1

    def has_config_call(start, end):
        if start == -1:
            return False
        return any('SwingftEncryption.configure' in lines[j] for j in range(start, end + 1))

    def insert_config_in_method(start, end):
        for j in range(start, end + 1):
            brace_index = lines[j].find('{')
            if brace_index != -1:
                indent = re.match(r'\s*', lines[j]).group(0) + '    '
                insert_at = j + 1
                insert_lines = [
                    f'{indent}let key = SwingftKey.combinedKey()\n',
                    f'{indent}SwingftEncryption.configure(key: key)\n'
                ]
                lines[insert_at:insert_at] = insert_lines
                return True
        return False

    will_start, will_end = find_method_range('willFinishLaunchingWithOptions')
    if will_start != -1:
        if not has_config_call(will_start, will_end):
            if insert_config_in_method(will_start, will_end):
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
        return

    did_start, did_end = find_method_range('didFinishLaunchingWithOptions')
    if did_start != -1:
        if not has_config_call(did_start, did_end):
            if insert_config_in_method(did_start, did_end):
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
        return

    class_indent = re.match(r'\s*', lines[class_start]).group(0)
    method_indent = class_indent + '    '
    new_func = [
        '\n',
        f'{method_indent}func application(_ application: UIApplication,\n',
        f'{method_indent}                     willFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {{\n',
        f'{method_indent}    let key = SwingftKey.combinedKey()\n',
        f'{method_indent}    SwingftEncryption.configure(key: key)\n',
        f'{method_indent}    return true\n',
        f'{method_indent}}}\n'
    ]
    lines[class_end:class_end] = new_func
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def patch_swiftui_struct(path):
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    inserted = False
    INIT_DECL_RE = re.compile(r'^\s*(?:public|internal|private|fileprivate)?\s*(?:override\s+)?(?:convenience\s+)?init\s*\([^)]*\)\s*(?:\{|$)')
    for i, line in enumerate(lines):
        if INIT_DECL_RE.search(line):   
            for j in range(i, len(lines)):
                if '{' in lines[j]:
                    lines.insert(j + 1, '        let key = SwingftKey.combinedKey()\n')
                    lines.insert(j + 2, '        SwingftEncryption.configure(key: key)\n')
                    inserted = True
                    break
            break
    if not inserted:
        for i, line in enumerate(lines):
            if 'struct' in line and ': App' in line:
                for j in range(i, len(lines)):
                    if '{' in lines[j]:
                        insert_at = j + 1
                        init_func = [
                            '    init() {\n',
                            '        let key = SwingftKey.combinedKey()\n',
                            '        SwingftEncryption.configure(key: key)\n',
                            '    }\n'
                        ]
                        lines[insert_at:insert_at] = init_func
                        inserted = True
                        break
                break
    if inserted:
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

def patch_entry(files: List[str], chunk_count: int):
    entry_path, entry_type = detect_main_entry(files)
    if not entry_path:
        return None, None
    insert_import_and_key(entry_path, chunk_count)
    if entry_type == 'uikit':
        patch_uikit_delegate(entry_path)
    elif entry_type == 'swiftui':
        patch_swiftui_struct(entry_path)
    return entry_path, entry_type

def copy_StringSecurity_folder(source_root):
    local_path = os.path.join(os.path.dirname(__file__), "StringSecurity")
    if not os.path.exists(local_path):
        return
    for dirpath, dirnames, _ in os.walk(source_root):
        for d in dirnames:
            if d.endswith(('.xcodeproj', '.xcworkspace')):
                target = os.path.join(dirpath, "StringSecurity")
                if not os.path.exists(target):
                    shutil.copytree(local_path, target)
                return

def line_no_of(text: str, pos: int) -> int:
    return text.count('\n', 0, pos) + 1



def encrypt_and_insert(source_root: str, included_json_path: str,
                       cfg_path: Optional[str] = None,
                       targets_json_path: Optional[str] = None):
    desired_bt = load_build_target_from_config(cfg_path)
    if desired_bt:
        tmap = load_targets_map(targets_json_path)
        name = choose_target_name(list(tmap.keys()), desired_bt) if tmap else None
        if not name:
            print(f"[Warning] build_target '{desired_bt}' not found in targets map. Skip encryption and exit.")
            return
    in_strings, in_lines = load_included_from_json(included_json_path)
    STRING_RE = re.compile(r'("""(?:\\.|"(?!""")|[^"])*?"""|"(?:\\.|[^"\\])*")', re.DOTALL)

    target_root = None
    for dirpath, dirnames, _ in os.walk(source_root):
        if any(d.endswith(('.xcodeproj', '.xcworkspace')) for d in dirnames):
            target_root = dirpath
            break
    if not target_root:
        return

   
    swift_files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(target_root):
        dirnames[:] = [d for d in dirnames if not d.startswith("Framework")]
        for fn in filenames:
            if fn.endswith(".swift") and fn != "Package.swift" and not fn.startswith("."):
                swift_files.append(os.path.join(dirpath, fn))

    target_scoped_files = pick_files_for_target(cfg_path, targets_json_path)
    if target_scoped_files:
        existing = {os.path.realpath(p) for p in target_scoped_files if os.path.isfile(p)}
        swift_files = sorted(existing)
        if not swift_files:
            print("[WARNING] Target-scoped Swift files not found. Nothing to encrypt.")
            return

    if not swift_files:
        return

    key = ChaCha20Poly1305.generate_key()
    cipher = ChaCha20Poly1305(key)
    modified_files: Set[str] = set()

    for file_path in swift_files:
        if "StringSecurity" in file_path:
            continue
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            abs_path = os.path.realpath(file_path)
            in_contents = in_strings.get(abs_path, set())
     
            allowed_lines = in_lines.get(abs_path, set())
            allowed_window = allowed_lines | {ln + 1 for ln in allowed_lines}

            def replace_string(m):
                raw = m.group(0)
                around = content[max(0, m.start()-30):m.start()]
                if 'SwingftEncryption.resolve("' in around:
                    return raw
                if raw not in in_contents:
                    return raw
                if not allowed_window:
                    return raw
                current_line = line_no_of(content, m.start())
                if current_line not in allowed_window:
                    return raw
                inner = raw[3:-3] if raw.startswith('"""') else raw[1:-1]
                inner_runtime = swift_unescape(inner)
                nonce = os.urandom(12)
                ct = cipher.encrypt(nonce, inner_runtime.encode(), None)
                b64 = base64.b64encode(nonce + ct).decode()
                return f'SwingftEncryption.resolve("{b64}")'

            new_content = re.sub(STRING_RE, replace_string, content)
            if new_content != content:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                modified_files.add(file_path)
        except Exception:
            pass

    if not modified_files:
        print("[WARNING] No resolve() usages found - skipping imports/entry/vendoring.")
        return

    
    for _p in modified_files:
        ensure_import(_p)

  
    target_scoped_files = pick_files_for_target(cfg_path, targets_json_path)
    pool: List[str] = target_scoped_files if target_scoped_files else swift_files

    
    count = 1 if len(pool) == 1 else 2 if len(pool) < 4 else 4
    chunk_size = KEY_BYTE_LEN // count
    
    chunks = [key[i*chunk_size:(i+1)*chunk_size] for i in range(count-1)] + [key[(count-1)*chunk_size:KEY_BYTE_LEN]]
    masks = [os.urandom(len(ch)) for ch in chunks]
    encoded_chunks = [bytes(c ^ m for c, m in zip(chunk, mask)) for chunk, mask in zip(chunks, masks)]

    entry_path, entry_type = patch_entry(pool, count)
    if not entry_path:
       
        fallback_host = pool[0]
        insert_import_and_key(fallback_host, count)
        print("[WARNING] No @main/AppDelegate found in selected scope. Inserted SwingftKey in:", fallback_host)
        copy_StringSecurity_folder(source_root)
    else:
        copy_StringSecurity_folder(source_root)

   
    preferred = [p for p in pool if (entry_path is None or p != entry_path)] or pool
    random.shuffle(preferred)

    used: Set[str] = set()
    for i in range(count):
        ef = next((p for p in preferred if p not in used), pool[0]); used.add(ef)
        mf = next((p for p in preferred if p not in used), ef);        used.add(mf)
        with open(ef, "a", encoding="utf-8") as f:
            f.write(f"\nextension SwingftKey {{\n    static let encoded{i+1}: [UInt8] = [{', '.join(str(b) for b in encoded_chunks[i])}]\n}}\n")
        with open(mf, "a", encoding="utf-8") as f:
            f.write(f"\nextension SwingftKey {{\n    static let mask{i+1}: [UInt8] = [{', '.join(str(b) for b in masks[i])}]\n}}\n")



if __name__ == "__main__":
    
    if len(sys.argv) < 3:
        print("Usage: python SwingftEncryption.py <source_root> <strings.json> [Swingft_config.json] [targets_swift_paths.json]")
        sys.exit(1)

    source_root = sys.argv[1]
    strings_json = sys.argv[2]
    cfg_path = sys.argv[3] if len(sys.argv) >= 4 else ("Swingft_config.json" if Path("Swingft_config.json").exists() else None)
    targets_json = sys.argv[4] if len(sys.argv) >= 5 else ("targets_swift_paths.json" if Path("targets_swift_paths.json").exists() else None)

    encrypt_and_insert(source_root, strings_json, cfg_path, targets_json)
