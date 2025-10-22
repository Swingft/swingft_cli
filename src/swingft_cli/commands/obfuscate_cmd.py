import os
import sys
import subprocess
import shutil
import io
import time
import threading
import queue
from contextlib import redirect_stdout, redirect_stderr
from collections import deque
from swingft_cli.validator import check_permissions
from swingft_cli.config import load_config_or_exit, summarize_risks_and_confirm, extract_rule_patterns
from swingft_cli.core.config import set_prompt_provider

from swingft_cli.core.tui import TUI, progress_bar

# Ensure interactive redraw is visible even under partial buffering
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

_BANNER = r"""
__     ____            _              __ _
\ \   / ___|_       _ (_)_ __   __ _ / _| |_
 \ \  \___  \ \ /\ / /| | '_ \ / _` | |_| __|
 / /   ___) |\ V  V / | | | | | (_) |  _| |_
/_/___|____/  \_/\_/  |_|_| |_|\__, |_|  \__|
 |_____|                       |___/
"""

# shared TUI instance
tui = TUI(banner=_BANNER)


def _progress_bar(completed: int, total: int, width: int = 30) -> str:
    # kept only for local call-sites compatibility if any leftover imports expect function
    return progress_bar(completed, total, width)


def handle_obfuscate(args):
    check_permissions(args.input, args.output)

    # 원본 보호: 입력과 출력 경로 검증
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)

    if input_path == output_path:
        print(f"[ERROR] Input and output paths are the same!")
        print(f"[ERROR] Input: {input_path}")
        print(f"[ERROR] Output: {output_path}")
        print(f"[ERROR] The original file may be damaged. Use a different output path.")
        sys.exit(1)

    if output_path.startswith(input_path + os.sep) or output_path.startswith(input_path + "/"):
        print(f"[ERROR] Output path is a subdirectory of the input!")
        print(f"[ERROR] Input: {input_path}")
        print(f"[ERROR] Output: {output_path}")
        print(f"[ERROR] The original file may be damaged. Use a different output path.")
        sys.exit(1)

    tui.print_banner()
    tui.init()
    tui.set_status([
        "원본 보호 확인 완료",
        f"입력:  {input_path}",
        f"출력:  {output_path}",
        "Start Swingft …",
    ])

    # preflight echo stream holder
    _preflight_echo = {"obj": None}

    # install prompt provider to render interactive y/n inside status area
    _preflight_phase = {"phase": "init"}  # init | include | exclude

    def _prompt_provider(msg: str) -> str:
        try:
            text = str(msg)
            # detect include confirmation prompt
            if "Do you really want to include" in text:
                _preflight_phase["phase"] = "include"
            # detect transition to exclude prompts
            elif text.startswith("Exclude this identifier") or "Exclude this identifier" in text:
                if _preflight_phase.get("phase") != "exclude":
                    # transition: include -> exclude (or init -> exclude)
                    try:
                        # clear panel and retitle header for exclude phase
                        tui.show_exact_screen([
                            f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List",
                            "",
                        ])
                    except Exception:
                        try:
                            tui.set_status([f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List"])  # fallback
                        except Exception:
                            pass
                    # if echo is active, reset its tail and header
                    try:
                        if _preflight_echo["obj"] is not None:
                            _preflight_echo["obj"]._tail.clear()
                            _preflight_echo["obj"]._header = f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List"
                    except Exception:
                        pass
                _preflight_phase["phase"] = "exclude"
        except Exception:
            pass
        return tui.prompt_line(msg)

    set_prompt_provider(_prompt_provider)

    # 파이프라인 경로 확인
    pipeline_path = os.path.join(os.getcwd(), "Obfuscation_Pipeline", "obf_pipeline.py")
    if not os.path.exists(pipeline_path):
        sys.exit(1)

    # Config 파일 처리
    config_path = None
    if getattr(args, 'config', None) is not None:
        if isinstance(args.config, str) and args.config.strip():
            config_path = args.config.strip()
        else:
            config_path = 'swingft_config.json'
        if not os.path.exists(config_path):
            sys.exit(1)

    # Working config 생성
    working_config_path = None
    if config_path:
        abs_src = os.path.abspath(config_path)
        base_dir = os.path.dirname(abs_src)
        filename = os.path.basename(abs_src)
        root, ext = os.path.splitext(filename)
        if not ext:
            ext = ".json"
        working_name = f"{root}__working{ext}"
        working_path = os.path.join(base_dir, working_name)
        try:
            shutil.copy2(abs_src, working_path)
        except Exception as copy_error:
            sys.exit(1)
        working_config_path = working_path

    # 1단계: 전처리 (exception_list.json 생성)
    tui.set_status(["Preprocessing…", _progress_bar(0, 1), "AST analysis"])
    try:
        # Stage 1에도 작업용 설정을 환경변수로 전달
        env1 = os.environ.copy()
        if working_config_path:
            env1["SWINGFT_WORKING_CONFIG"] = os.path.abspath(working_config_path)
        env1.setdefault("PYTHONUNBUFFERED", "1")

        spinner = ["|", "/", "-", "\\"]
        sp_idx = 0
        done_ast = False
        tail1 = deque(maxlen=10)
        proc1 = subprocess.Popen([
            "python3", pipeline_path,
            args.input,
            args.output,
            "--stage", "preprocessing"
        ], cwd=os.path.join(os.getcwd(), "Obfuscation_Pipeline"),
           text=True, env=env1, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        assert proc1.stdout is not None

        # 비동기 리더 + 주기적 틱으로, 출력이 잠시 없어도 진행 UI가 갱신되도록 함
        line_queue: "queue.Queue[str|None]" = queue.Queue()

        def _reader():
            try:
                for raw_line in proc1.stdout:  # type: ignore[arg-type]
                    line = (raw_line or "").rstrip("\n")
                    line_queue.put(line)
            finally:
                try:
                    line_queue.put(None)
                except Exception:
                    pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        eof = False
        while True:
            try:
                item = line_queue.get(timeout=0.1)
            except queue.Empty:
                item = ""
            if item is None:
                eof = True
            elif isinstance(item, str) and item:
                if item.strip():
                    tail1.append(item)
                # Optional: echo raw logs for visibility when requested
                try:
                    if os.environ.get("SWINGFT_TUI_ECHO", "") == "1":
                        print(item)
                except Exception:
                    pass
                low = item.lower()
                if low.startswith("ast:") or " ast:" in low:
                    done_ast = True

            sp_idx = (sp_idx + 1) % len(spinner)
            bar = progress_bar(1 if done_ast else 0, 1)
            tui.set_status([ f"Preprocessing: {bar}  {spinner[sp_idx]}", "Current: AST analysis",   "",   *list(tail1) ])

            if eof and line_queue.empty():
                break
            time.sleep(0.05)
        rc1 = proc1.wait()
        if rc1 != 0:
            sys.exit(1)

        # preprocessing finished: clear previous tail logs so next phase starts clean
        try:
            tail1.clear()
        except Exception:
            pass
        # refresh status to preflight screen for next phase
        try:
            tui.set_status([f"Preflight: {progress_bar(0,1)}  - | Current: Checking Include List"]) 
        except Exception:
            pass

    except subprocess.TimeoutExpired:
        sys.exit(1)
    except Exception as e:
        sys.exit(1)

    # Config 검증 및 LLM 분석
    if working_config_path:
        try:
            analyzer_root = os.environ.get("SWINGFT_ANALYZER_ROOT", os.path.join(os.getcwd(), "externals", "obfuscation-analyzer")).strip()
            proj_in = input_path
            ast_path = os.environ.get("SWINGFT_AST_NODE_PATH", "")
            from swingft_cli.core.config.loader import _apply_analyzer_exclusions_to_ast_and_config as _apply_anl
            _apply_anl(analyzer_root, proj_in, ast_path, working_config_path, {})
        except Exception:
            pass
        try:
            auto_yes = getattr(args, 'yes', False)
            if auto_yes:
                buf_out1, buf_err1 = io.StringIO(), io.StringIO()
                with redirect_stdout(buf_out1), redirect_stderr(buf_err1):
                    config = load_config_or_exit(working_config_path)
                patterns = extract_rule_patterns(config)
                buf_out2, buf_err2 = io.StringIO(), io.StringIO()
                with redirect_stdout(buf_out2), redirect_stderr(buf_err2):
                    ok = summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
                if ok is False:
                    sys.stdout.write(buf_out1.getvalue() + buf_err1.getvalue() + buf_out2.getvalue() + buf_err2.getvalue())
                    sys.stdout.flush()
                    raise RuntimeError("사용자 취소")
                tui.set_status(["설정 검증 완료"])
            else:
                config = load_config_or_exit(working_config_path)
                patterns = extract_rule_patterns(config)
                # route preflight prints into TUI panel tail
                try:
                    _preflight_echo["obj"] = tui.make_stream_echo(
                        header=f"Preflight: {progress_bar(0,1)}  - | Current: Checking Include List",
                        tail_len=10,
                    )
                except Exception:
                    _preflight_echo["obj"] = None
                if _preflight_echo["obj"] is not None:
                    with redirect_stdout(_preflight_echo["obj"]), redirect_stderr(_preflight_echo["obj"]):
                        ok = summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
                else:
                    ok = summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
            if ok is False:
                raise RuntimeError("사용자 취소")
            tui.set_status(["설정 검증 완료"])
        except Exception as e:
            tui.set_status([f"설정 검증 실패: {e}"])
            sys.exit(1)

    # 2단계: 최종 난독화 (라이브 진행 바)
    tui.set_status(["Obfuscation in progress…"])
    try:
        env = os.environ.copy()
        if working_config_path:
            env["SWINGFT_WORKING_CONFIG"] = os.path.abspath(working_config_path)
        env.setdefault("PYTHONUNBUFFERED", "1")

        steps = [
            ("_bootstrap", "Bootstrap"),
            ("mapping", "Identifier mapping"),
            ("id-obf", "Identifier obfuscation"),
            ("cff", "Control flow flattening"),
            ("opaq", "Opaque predicate"),
            ("deadcode", "Dead code"),
            ("encryption", "String encryption"),
        ]
        labels_extra = {
            "cfg": "Dynamic function",
            "debug": "Debug symbol removal",
        }
        step_keys = [k for k, _ in steps]
        total_steps = len(steps)
        seen = {"_bootstrap"}
        tail2 = deque(maxlen=10)

        proc = subprocess.Popen([
            "python3", pipeline_path,
            args.input,
            args.output,
            "--stage", "final"
        ], cwd=os.path.join(os.getcwd(), "Obfuscation_Pipeline"),
           text=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)

        assert proc.stdout is not None
        last_current = "준비 중"
        for raw in proc.stdout:
            line = (raw or "").rstrip("\n")
            if line.strip():
                tail2.append(line)
                try:
                    if os.environ.get("SWINGFT_TUI_ECHO", "") == "1":
                        print(line)
                except Exception:
                    pass
            low = line.lower()
            if low.startswith("completed:") or low.startswith("skipped:"):
                try:
                    summary = low.split(":", 1)[1]
                    items = [s.strip() for s in summary.split(",") if s.strip()]
                    for item in items:
                        if "identifiers obfuscation" in item:
                            seen.update(["mapping", "id-obf"])
                        if "control flow obfuscation" in item:
                            seen.update(["cff", "opaq", "deadcode"])
                        if "string encryption" in item:
                            seen.add("encryption")
                        if "delete debug symbols" in item:
                            last_current = "Debug symbol removal"
                except Exception:
                    pass
            for key, label in steps:
                if key == "encryption":
                    if "[swingft_string_encryption] encryption_strings is true" in low:
                        last_current = label
                    if low.startswith("encryption:") or " encryption:" in low or "[swingft_string_encryption] done" in low or low.endswith("[swingft_string_Encryption] Done.".lower()):
                        seen.add(key)
                        last_current = label
                else:
                    if low.startswith(f"{key}:") or f" {key}:" in low:
                        seen.add(key)
                        idx = step_keys.index(key)
                        if idx + 1 < total_steps:
                            last_current = steps[idx + 1][1]
                        else:
                            last_current = label
            for k, lbl in labels_extra.items():
                if low.startswith(f"{k}:") or f" {k}:" in low:
                    last_current = lbl
            bar = progress_bar(len(seen), total_steps)
            tui.set_status([
                f"2단계 진행: {bar}",
                f"현재: {last_current}",
                "",
                *list(tail2)
            ])
        rc = proc.wait()
        if rc != 0:
            tui.set_status(["Obfuscation failed", f"exit code: {rc}"])
            sys.exit(1)

    except Exception as e:
        tui.set_status([f"Obfuscation failed: {e}"])
        sys.exit(1)

    # 종료 시 전체 리로드 방지: 상태영역 갱신 대신 한 줄만 추가
    try:
        sys.stdout.write("\nObfuscation completed\n")
        sys.stdout.flush()
    except Exception:
        tui.set_status(["Obfuscation completed"])