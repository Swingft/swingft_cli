
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Tuple, List


def read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))

def to_bool(v) -> bool:
    if isinstance(v, bool): return v
    if isinstance(v, str): return v.strip().lower() in {"1","true","yes","y","on"}
    if isinstance(v, (int, float)): return bool(v)
    return False

def find_key_ci(obj, key_name: str) -> Optional[bool]:
    
    target = key_name.lower()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() == target:
                return to_bool(v)
        for v in obj.values():
            r = find_key_ci(v, key_name)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = find_key_ci(it, key_name)
            if r is not None:
                return r
    return None

def run_streamed(cmd: List[str], cwd: Optional[Path], tag: str) -> int:
    # Ensure Swift tool receives env to redirect stderr→stdout inside process (if supported)
    env = os.environ.copy()
    env.setdefault("SWINGFT_ENC_STDERR_TO_STDOUT", "1")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        # Print Swift (and helper) output lines exactly as received
        print(line, end='', flush=True)
    return proc.wait()

def run_parallel(cmdA: List[str], tagA: str,
                 cmdB: List[str], tagB: str,
                 cwd: Optional[Path]) -> Tuple[int, int]:
    rcA = rcB = 999
    def ta():
        nonlocal rcA
        rcA = run_streamed(cmdA, cwd, tagA)
    def tb():
        nonlocal rcB
        rcB = run_streamed(cmdB, cwd, tagB)

    t1 = threading.Thread(target=ta, daemon=True)
    t2 = threading.Thread(target=tb, daemon=True)
    t1.start(); t2.start()
    t1.join();  t2.join()
    return rcA, rcB

def newest_matching(root: Path, pattern: re.Pattern) -> Optional[Path]:
    newest_p, newest_t = None, -1
    for p in root.rglob("*.json"):
        if not pattern.search(p.name):
            continue
        try:
            t = p.stat().st_mtime
        except Exception:
            continue
        if t > newest_t:
            newest_p, newest_t = p, t
    return newest_p

def main():
    build_marker_file = ".build/build_path.txt"
    previous_build_path = ""
    if os.path.exists(build_marker_file):
        with open(build_marker_file, "r") as f:
            previous_build_path = f.read().strip()
    
    current_build_path = os.path.abspath(".build")
    if previous_build_path != current_build_path or previous_build_path == "":
        subprocess.run(["swift", "package", "clean"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(".build", ignore_errors=True)
        subprocess.run(["swift", "build"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(build_marker_file, "w") as f:
            f.write(current_build_path)

    ap = argparse.ArgumentParser(description="Run Swingft pipeline, gated by Encryption_strings")
    ap.add_argument("root_path", help="Project root path")
    ap.add_argument("config_path", help="Swingft_config.json path")
    args = ap.parse_args()

    root = Path(args.root_path).resolve()
    cfg  = Path(args.config_path).resolve()
    cfg_dir = Path(os.getcwd())

    if not cfg.exists():
        #print(f"[Swingft_String_Encryption] ERROR: config not found: {cfg}")
        sys.exit(2)

    try:
        cfg_json = read_json(cfg)
    except Exception as e:
        #print(f"[Swingft_String_Encryption] ERROR: cannot parse config: {cfg} ({e})")
        sys.exit(2)

    flag = find_key_ci(cfg_json, "Encryption_strings")
    if not flag:
        print("[Swingft_String_Encryption] Encryption_strings is false (or missing) → nothing to do.")
        return

    # Prefer running the built binary directly to avoid SwiftPM build logs
    bin_path = Path(current_build_path) / "debug" / "Swingft_Encryption"
    if bin_path.exists():
        cmd_a = [str(bin_path), str(root), str(cfg)]
    else:
        cmd_a = ["swift", "run", "Swingft_Encryption", str(root), str(cfg)]


    script_dir = Path(__file__).parent.resolve()
    build_target_py = script_dir / "build_target.py"
    if not build_target_py.exists():
        print(f"[Swingft_String_Encryption] WARN: build_target.py not found next to this script: {build_target_py}")
    cmd_b = ["python3", str(build_target_py if build_target_py.exists() else "build_target.py"), str(root)]

    
    rcA, rcB = run_parallel(cmd_a, "A", cmd_b, "B", cwd=cfg_dir)
    if rcA != 0:
        print(f"[Swingft_String_Encryption] ERROR: failed with code {rcA}")
        sys.exit(3)
    if rcB != 0:
        print(f"[Swingft_String_Encryption] ERROR: failed with code {rcB}")
        sys.exit(3)

  
    strings_json = cfg_dir / "strings.json"
    targets_json = cfg_dir / "targets_swift_paths.json"

    
    if not strings_json.exists():
        cand = newest_matching(root, re.compile(r"^strings.*\.json$", re.I))
        if cand:
            shutil.copy2(cand, strings_json)
            print(f"[Swingft_String_Encryption] Copied strings.json from: {cand}")
        else:
            print("[Swingft_String_Encryption] ERROR: strings.json not found.")
            sys.exit(4)

    
    if not targets_json.exists():
        cand = newest_matching(root, re.compile(r"^targets_swift_paths\.json$", re.I))
        if cand:
            shutil.copy2(cand, targets_json)
            print(f"[Swingft_String_Encryption] Copied targets_swift_paths.json from: {cand}")
        else:
            print("[Swingft_String_Encryption] ERROR: targets_swift_paths.json not found.")
            sys.exit(4)

   
    swingft_enc_py = script_dir / "SwingftEncryption.py"
    if not swingft_enc_py.exists():
        print(f"[Swingft_String_Encryption] WARN: SwingftEncryption.py not found next to this script: {swingft_enc_py}")
    cmd_c = [
        "python3",
        str(swingft_enc_py if swingft_enc_py.exists() else "SwingftEncryption.py"),
        str(root),
        str(strings_json),
        str(cfg),
        str(targets_json),
    ]
    #print("[Swingft_String_Encryption] Running :", " ".join(cmd_c))
    rcC = run_streamed(cmd_c, cwd=cfg_dir, tag="C")
    if rcC != 0:
        print(f"[Swingft_String_Encryption] ERROR: step failed with code {rcC}")
        sys.exit(5)

    #print("[Swingft_String_Encryption] Done.")

if __name__ == "__main__":
    main()
