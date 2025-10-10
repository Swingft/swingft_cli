import sys
import os
import json
import subprocess
import difflib
import shutil
from pathlib import Path


def run_streamed(cmd, tag):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert p.stdout is not None
    for line in p.stdout:
        print(f"[{tag}] {line.rstrip()}")
    p.wait()
    return p.returncode


def gather_paths(ast_json):
    files = set()
    for it in ast_json.get("ifChains", []):
        p = it.get("path")
        if p:
            files.add(p)
    for lp in ast_json.get("loops", []):
        p = lp.get("path")
        if p:
            files.add(p)
    return [Path(p) for p in files]


def safe_relpath(p: Path) -> Path:
    try:
        return p.resolve().relative_to(Path.cwd().resolve())
    except Exception:
        parts = [seg for seg in p.as_posix().lstrip("/").split("/") if seg]
        return Path("Swingft_CFF_Dump") / Path(*parts)


def unified_diff_text(rel: Path, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=str(rel),
        tofile=str(rel),
        lineterm=""
    )
    return "".join(diff)


def flat_name_for_diff(rel: Path) -> str:
    base = rel.as_posix().lstrip("./").replace("/", "__").replace(":", "_")
    if not base:
        base = "root"
    return f"{base}.diff"

def main():
    here = Path(__file__).resolve().parent

    env_ast = os.environ.get("CFF_AST")
    if not env_ast:
        print("[ERROR] CFF_AST is required.", flush=True)
        sys.exit(2)
    ast_raw = Path(env_ast).expanduser()
    ast_path = (ast_raw if ast_raw.is_absolute() else (Path.cwd() / ast_raw)).resolve()
    if not ast_path.exists():
        print(f"[ERROR] CFF_AST not found: {ast_path}", flush=True)
        sys.exit(2)
    #print(f"Using AST: {ast_path}", flush=True)

    env_out = os.environ.get("CFF_DIFF_DIR")
    if not env_out:
        print("[ERROR] CFF_DIFF_DIR is required.", flush=True)
        sys.exit(2)
    out_raw = Path(env_out).expanduser()
    out_root = (out_raw if out_raw.is_absolute() else (Path.cwd() / out_raw)).resolve()


    try:
        ast = json.loads(ast_path.read_text(encoding="utf-8"))
    except Exception as e:
        #print(f"[ERROR] Failed to read AST json: {e}", flush=True)
        sys.exit(2)

    
    target_files = [p for p in gather_paths(ast) if p.exists()]
    #print(f"Collected target files: {len(target_files)}", flush=True)

   
    before_map = {}
    for f in target_files:
        try:
            before_map[f] = f.read_text(encoding="utf-8")
        except Exception:
            pass

    while_py = here / "Swingft_CFF_while.py"
    forin_py = here / "Swingft_CFF_forin.py"
    if_py    = here / "Swingft_CFF_if.py"
    for s in (while_py, forin_py, if_py):
        if not s.exists():
            print(f"ERROR: Required script not found: {s.name}", flush=True)
            sys.exit(2)

    rc1 = run_streamed([sys.executable, str(while_py), str(ast_path)], tag="WHILE")
    if rc1 != 0:
        sys.exit(rc1)
    rc2 = run_streamed([sys.executable, str(forin_py), "--ast", str(ast_path)], tag="FORIN")
    if rc2 != 0:
        sys.exit(rc2)
    rc3 = run_streamed([sys.executable, str(if_py), str(ast_path)], tag="IF")
    if rc3 != 0:
        sys.exit(rc3)

    created = False
    changed = 0
    for f, before in before_map.items():
        try:
            after = f.read_text(encoding="utf-8")
        except Exception:
            continue

        if after != before:
            if not created:
                out_root.mkdir(parents=True, exist_ok=True)
                #print(f"[OUT] Writing diffs to: {out_root}", flush=True)
                created = True

            rel = safe_relpath(f)
            diff_name = flat_name_for_diff(rel)
            diff_path = out_root / diff_name
            diff_text = unified_diff_text(rel, before, after)
            try:
                diff_path.write_text(diff_text, encoding="utf-8")
                #print(f"[DIFF] {f} -> {diff_name}", flush=True)
                changed += 1
            except Exception as e:
                print(f"[WARN] Failed to write diff for {f}: {e}", flush=True)

    print(f"Swingft_CFF completed. Changed files: {changed}", flush=True)

    ast_path = "ast.json"
    if os.path.exists(ast_path):
        os.remove(ast_path)

if __name__ == "__main__":
    main()
