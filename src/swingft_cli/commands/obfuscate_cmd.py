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


_BANNER = r"""
__     ____            _              __ _
\ \   / ___|_       _ (_)_ __   __ _ / _| |_
 \ \  \___  \ \ /\ / /| | '_ \ / _` | |_| __|
 / /   ___) |\ V  V / | | | | | (_) |  _| |_
/_/___|____/  \_/\_/  |_|_| |_|\__, |_|  \__|
 |_____|                       |___/
"""

_UI_PORTABLE = (os.environ.get("SWINGFT_TUI_PORTABLE", "") == "1") or (not sys.stdout.isatty())
_UI_ULTRA = (os.environ.get("SWINGFT_TUI_ULTRA", "") == "1")

_ULTRA_LAST_WIDTH = 0

def _term_width(default: int = 80) -> int:
    try:
        import shutil as _shutil
        size = _shutil.get_terminal_size((default, 24))
        return max(20, int(size.columns))
    except Exception:
        return default


def print_banner():
    print(_BANNER)


# --- Minimal UI helpers to keep banner visually fixed and update status ---
def _ui_init():
    if _UI_PORTABLE:
        # no cursor save/restore; nothing to init
        sys.stdout.write("\n\n")
        sys.stdout.flush()
        return
    # reserve a small status area under the banner and save cursor
    sys.stdout.write("\n\n")
    sys.stdout.write("\x1b[s")
    sys.stdout.flush()


def _ui_set_status(lines):
    if not isinstance(lines, (list, tuple)):
        lines = [str(lines)]
    if _UI_ULTRA:
        # compress to max 2 segments (first non-empty lines)
        segments = [ln for ln in lines if str(ln).strip()]
        if len(segments) > 2:
            segments = segments[:2]
        # compress to single line and overwrite using CR + padding
        msg = " | ".join([str(s) for s in segments]).strip()
        width = _term_width()
        out = (msg[:width - 1])
        pad = max(0, max(len(out), _ULTRA_LAST_WIDTH) - len(out))
        sys.stdout.write("\r" + out + (" " * pad))
        sys.stdout.flush()
        globals()["_ULTRA_LAST_WIDTH"] = max(len(out), _ULTRA_LAST_WIDTH)
        return
    if _UI_PORTABLE:
        # full redraw each time for portability
        _ui_redraw_full(lines)
        return
    # restore cursor to status area, clear to end of screen, print new lines
    sys.stdout.write("\x1b[u\x1b[J")
    for ln in lines:
        sys.stdout.write(str(ln) + "\n")
    sys.stdout.flush()


def _ui_redraw_full(lines):
    if not isinstance(lines, (list, tuple)):
        lines = [str(lines)]
    # clear full screen and draw banner + lines
    if _UI_ULTRA:
        # print banner once, then put status on the next line using CR overwrites
        sys.stdout.write("\r\n")
        print_banner()
        if lines:
            sys.stdout.write("\n")
            sys.stdout.flush()
            _ui_set_status([lines[0]])
        return
    sys.stdout.write("\x1b[H\x1b[2J")
    sys.stdout.write(_BANNER)
    sys.stdout.write("\n")
    for ln in lines:
        sys.stdout.write(str(ln) + "\n")
    # reset saved cursor after banner for subsequent _ui_set_status
    if not _UI_PORTABLE:
        sys.stdout.write("\n\n\x1b[s")
    sys.stdout.flush()


def _ui_prompt_line(prompt: str) -> str:
    if _UI_PORTABLE:
        # portable: 일반 입력 후 전체 리드로우로 흔적 제거
        try:
            ans = input(str(prompt))
        except Exception:
            ans = ""
        _ui_redraw_full([""])
        return ans
    if _UI_ULTRA:
        try:
            ans = input("\r" + str(prompt))
        except Exception:
            ans = ""
        # clear prompt line by padding
        width = _term_width()
        sys.stdout.write("\r" + (" " * width) + "\r")
        sys.stdout.flush()
        return ans
    # 상태 영역에 프롬프트 문구를 올리고, 같은 줄에서 입력을 받는다
    sys.stdout.write("\x1b[u\x1b[J")  # 상태 영역 복귀 및 지우기
    sys.stdout.write(str(prompt))
    sys.stdout.flush()
    try:
        ans = input("")
    except Exception:
        ans = ""
    # 입력 직후 프롬프트 라인을 공백으로 덮어써 지운다
    sys.stdout.write("\x1b[u\x1b[J")
    sys.stdout.flush()
    return ans


def _progress_bar(completed: int, total: int, width: int = 30) -> str:
    completed = max(0, min(completed, total))
    if total <= 0:
        total = 1
    filled = int(width * completed / total)
    bar = "#" * filled + "-" * (width - filled)
    pct = int(100 * completed / total)
    return f"[{bar}] {completed}/{total} ({pct}%)"


def handle_obfuscate(args):
    check_permissions(args.input, args.output)

    # 원본 보호: 입력과 출력 경로 검증
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    
    if input_path == output_path:
        print(f"[ERROR] 입력과 출력 경로가 동일합니다!")
        print(f"[ERROR] 입력: {input_path}")
        print(f"[ERROR] 출력: {output_path}")
        print(f"[ERROR] 원본 파일이 손상될 수 있습니다. 다른 출력 경로를 사용하세요.")
        sys.exit(1)
    
    if output_path.startswith(input_path + os.sep) or output_path.startswith(input_path + "/"):
        print(f"[ERROR] 출력 경로가 입력의 하위 디렉토리입니다!")
        print(f"[ERROR] 입력: {input_path}")
        print(f"[ERROR] 출력: {output_path}")
        print(f"[ERROR] 원본 파일이 손상될 수 있습니다. 다른 출력 경로를 사용하세요.")
        sys.exit(1)
    
    print_banner()
    _ui_init()
    _ui_set_status([
        #"원본 보호 확인 완료",
        #f"입력:  {input_path}",
        #f"출력:  {output_path}",
        #"Start Swingft …",
    ])

    # install prompt provider to render interactive y/n inside status area
    def _prompt_provider(msg: str) -> str:
        return _ui_prompt_line(msg)
    set_prompt_provider(_prompt_provider)

    # 파이프라인 경로 확인
    pipeline_path = os.path.join(os.getcwd(), "Obfuscation_Pipeline", "obf_pipeline.py")
    if not os.path.exists(pipeline_path):
        _ui_set_status([f"Pipeline not found: {pipeline_path}"])
        sys.exit(1)

    # Config 파일 처리
    config_path = None
    if getattr(args, 'config', None) is not None:
        if isinstance(args.config, str) and args.config.strip():
            config_path = args.config.strip()
        else:
            config_path = 'swingft_config.json'
        if not os.path.exists(config_path):
            _ui_set_status([f"Config not found: {config_path}"])
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
            _ui_set_status([f"[config] 설정 복사본 생성 실패: {copy_error}"])
            sys.exit(1)
        _ui_set_status([
            "설정 준비 완료",
            f"원본:   {abs_src}",
            f"작업용: {working_path}",
        ])
        working_config_path = working_path

    # 1단계: 전처리 (exception_list.json 생성)
    _ui_set_status(["Preprocessing…", _progress_bar(0, 1), "AST analysis"])
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
                low = item.lower()
                if low.startswith("ast:") or " ast:" in low:
                    done_ast = True

            sp_idx = (sp_idx + 1) % len(spinner)
            bar = _progress_bar(1 if done_ast else 0, 1)
            _ui_set_status([
                f"Preprocessing: {bar}  {spinner[sp_idx]}",
                "Current: AST analysis",
                "",
                *list(tail1)
            ])

            if eof and line_queue.empty():
                break
            time.sleep(0.05)
        rc1 = proc1.wait()
        if rc1 != 0:
            _ui_set_status(["Preprocessing failed", f"exit code: {rc1}"])
            sys.exit(1)
        _ui_set_status(["Preprocessing completed: exception_list.json created"])
            
    except subprocess.TimeoutExpired:
        _ui_set_status(["Preprocessing timed out"])
        sys.exit(1)
    except Exception as e:
        _ui_set_status([f"Preprocessing failed: {e}"])
        sys.exit(1)

    # Config 검증 및 LLM 분석
    if working_config_path:
        #_ui_set_status([f"설정 검증 시작: {working_config_path}"])
        try:
            auto_yes = getattr(args, 'yes', False)
            if auto_yes:
                # 비대화형: 캡처하여 상태만 갱신
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
                _ui_set_status(["설정 검증 완료"])  # 상태 영역만 정리
            else:
                # 대화형: 프롬프트/로그를 그대로 표시 (캡처하지 않음)
                config = load_config_or_exit(working_config_path)
                patterns = extract_rule_patterns(config)
                ok = summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
                if ok is False:
                    raise RuntimeError("사용자 취소")
                _ui_set_status(["설정 검증 완료"])  # 상태 영역만 정리
        except Exception as e:
            _ui_set_status([f"설정 검증 실패: {e}"])
            sys.exit(1)

    # 2단계: 최종 난독화 (라이브 진행 바)
    _ui_set_status(["Obfuscation in progress…"])
    try:
        env = os.environ.copy()
        if working_config_path:
            env["SWINGFT_WORKING_CONFIG"] = os.path.abspath(working_config_path)
        # ensure unbuffered output from child python
        env.setdefault("PYTHONUNBUFFERED", "1")

        # known sub-steps for coarse progress
        steps = [
            ("_bootstrap", "Bootstrap"),  # dummy step to align with end-of-step logs
            ("mapping", "Identifier mapping"),
            ("id-obf", "Identifier obfuscation"),
            ("cff", "Control flow flattening"),
            ("opaq", "Opaque predicate"),
            ("deadcode", "Dead code"),
            ("encryption", "String encryption"),
        ]
        # non-progress labels we still want to show
        labels_extra = {
            "cfg": "Dynamic function",
            "debug": "Debug symbol removal",
        }
        step_keys = [k for k, _ in steps]
        total_steps = len(steps)
        # count bootstrap as immediately completed so bar can reach 100%
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
            low = line.lower()
            # handle final summary lines to update progress when steps were skipped (no per-step logs)
            if low.startswith("completed:") or low.startswith("skipped:"):
                try:
                    summary = low.split(":", 1)[1]
                    items = [s.strip() for s in summary.split(",") if s.strip()]
                    for item in items:
                        if "identifiers obfuscation" in item:
                            seen.update(["mapping", "id-obf"])  # treat skipped as completed for bar
                        if "control flow obfuscation" in item:
                            seen.update(["cff", "opaq", "deadcode"])  # cfg is extra label
                        if "string encryption" in item:
                            seen.add("encryption")
                        if "delete debug symbols" in item:
                            last_current = "Debug symbol removal"
                except Exception:
                    pass
            # mark completion on duration lines like "mapping:" etc.
            for key, label in steps:
                # encryption: detect both start and end
                if key == "encryption":
                    if "[swingft_string_encryption] encryption_strings is true" in low:
                        last_current = label
                    if low.startswith("encryption:") or " encryption:" in low or "[swingft_string_encryption] done" in low or low.endswith("[swingft_string_Encryption] Done.".lower()):
                        seen.add(key)
                        last_current = label
                else:
                    if low.startswith(f"{key}:") or f" {key}:" in low:
                        seen.add(key)
                        # show NEXT step as current upon completion of this step
                        idx = step_keys.index(key)
                        if idx + 1 < total_steps:
                            last_current = steps[idx + 1][1]
                        else:
                            last_current = label
            # show extra labels (do not affect progress)
            for k, lbl in labels_extra.items():
                if low.startswith(f"{k}:") or f" {k}:" in low:
                    last_current = lbl
            bar = _progress_bar(len(seen), total_steps)
            _ui_set_status([
                f"2단계 진행: {bar}",
                f"현재: {last_current}",
                "",
                *list(tail2)
            ])
        rc = proc.wait()
        if rc != 0:
            _ui_set_status(["Obfuscation failed", f"exit code: {rc}"])
            sys.exit(1)
        # 화면 리로드 없이 아래 한 줄만 추가
        # 완료 라인 출력은 종료 시 한 번만 담당 (아래 공통 블록에서 처리)

    except Exception as e:
        _ui_set_status([f"Obfuscation failed: {e}"])
        sys.exit(1)

    # 종료 시 전체 리로드 방지: 상태영역 갱신 대신 한 줄만 추가
    try:
        sys.stdout.write("\nObfuscation completed\n")
        sys.stdout.flush()
    except Exception:
        _ui_set_status(["Obfuscation completed"])  # 폴백