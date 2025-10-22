import os
import sys
import subprocess
import shutil
import io
import time
import threading
import queue
import re
from contextlib import redirect_stdout, redirect_stderr
from collections import deque
import json
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
    # 초기 상태 문자열은 기본 비표시. 필요 시 SWINGFT_TUI_SHOW_INIT=1 로 켭니다.
    try:
        _show_init = str(os.environ.get("SWINGFT_TUI_SHOW_INIT", "0")).strip().lower() in {"1", "true", "yes", "y", "on"}
    except Exception:
        _show_init = False
    if _show_init:
        tui.set_status([
            "원본 보호 확인 완료",
            f"입력:  {input_path}",
            f"출력:  {output_path}",
            "Start Swingft …",
        ])

    # preflight echo stream holder
    class StreamProxy:
        """Proxy file-like object that forwards writes/flushes to the current echo object
        stored in the shared holder dict. This allows redirect_stdout to remain bound to
        a stable proxy while the prompt provider swaps which echo object is the active
        target (include vs exclude) at runtime.
        """
        def __init__(self, holder: dict):
            self._holder = holder
        def write(self, data):
            # forward writes to the currently selected echo target
            try:
                # if the preflight output contains indicators that an exclude phase is
                # starting (e.g. a candidate list or an explicit exclude-detected line),
                # create the exclude echo and switch the current proxy target so the
                # TUI shows the Include header above the Exclude header immediately.
                try:
                    text = data if isinstance(data, str) else str(data)
                    lowered = text.lower()
                    trigger = False
                    # trigger as early as possible, before the candidates list prints
                    if ("exclude candidates overlap" in lowered or
                        "candidates:" in lowered or
                        "exclude candidate detected" in lowered or
                        "exclude this identifier" in lowered):
                        trigger = True
                    if trigger:
                        # guard against repeated creation
                        if self._holder.get("exclude") is None:
                            try:
                                include_header = ""
                                exclude_header = f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List"
                                try:
                                    tui.set_status([include_header, exclude_header, ""])
                                except Exception:
                                    try:
                                        tui.set_status([exclude_header])
                                    except Exception:
                                        pass
                                # create exclude echo then immediately switch current so upcoming lines go to exclude
                                excl = tui.make_stream_echo(header=exclude_header, tail_len=10)
                                self._holder["exclude"] = excl
                                # copy prior include tail for context, but do not duplicate current line to include
                                try:
                                    inc = self._holder.get("include")
                                    if inc is not None and hasattr(inc, "_tail") and hasattr(excl, "_tail"):
                                        for line in list(inc._tail):
                                            try:
                                                excl._tail.append(line)
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                                # switch current before forwarding this write so Candidates go to exclude tail
                                if self._holder.get("proxy") is not None:
                                    self._holder["current"] = "exclude"
                            except Exception:
                                pass
                except Exception:
                    # non-fatal, continue to forward as usual
                    pass

                cur = self._holder.get("current", "include")
                target = self._holder.get(cur)
                if target is not None:
                    target.write(data)
            except Exception:
                pass
        def flush(self):
            try:
                cur = self._holder.get("current", "include")
                target = self._holder.get(cur)
                if target is not None:
                    target.flush()
            except Exception:
                pass

    # preflight echo holder: will contain 'include' and optional 'exclude' echo objects,
    # the current key ('include' or 'exclude'), and a stable 'proxy' used for redirect_stdout
    _preflight_echo = {
        "include": None,
        "exclude": None,
        "current": None,
        "proxy": None,
    }

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
                        include_header = ""
                        exclude_header = f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List"
                        # do not redraw header; keep previous (prefer Preprocessing panel)
                        # create an exclude echo (no header) and switch proxy target if possible
                        try:
                            excl = tui.make_stream_echo(header="", tail_len=10)
                            _preflight_echo["exclude"] = excl
                            # if a proxy exists, switch current to 'exclude'
                            if _preflight_echo.get("proxy") is not None:
                                _preflight_echo["current"] = "exclude"
                        except Exception:
                            # best-effort: keep include echo's header intact
                            try:
                                if _preflight_echo.get("include") is not None:
                                    _preflight_echo["include"]._tail.clear()
                                    _preflight_echo["include"]._header = include_header
                            except Exception:
                                pass
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
    # 진행률 모드: milestones(기본) | files
    preflight_progress_mode = str(os.environ.get("SWINGFT_PREFLIGHT_PROGRESS_MODE", "milestones")).strip().lower()
    preflight_progress_files = (str(os.environ.get("SWINGFT_PREFLIGHT_PROGRESS_FILES", "1")).strip().lower() not in {"0", "false", "no"})

    # 식별자 난독화 옵션에 따라 Preprocessing UI 표시 여부 결정
    show_pre_ui = True
    try:
        if working_config_path and os.path.isfile(working_config_path):
            with open(working_config_path, "r", encoding="utf-8") as _f:
                _cfg = json.load(_f)
            _src = _cfg.get("options") if isinstance(_cfg.get("options"), dict) else _cfg
            val = (_src or {}).get("Obfuscation_identifiers", True)
            if isinstance(val, str):
                show_pre_ui = val.strip().lower() in {"1","true","yes","y","on"}
            else:
                show_pre_ui = bool(val)
    except Exception:
        show_pre_ui = True

    # milestones 정의: ast_node.json 생성까지의 주요 산출물 체크(순서 보장)
    milestones = [
        ("external_file_list.txt", lambda base: os.path.isfile(os.path.join(base, "external_file_list.txt"))),
        ("external_list.json", lambda base: os.path.isfile(os.path.join(base, "external_list.json"))),
        ("external_name.txt", lambda base: os.path.isfile(os.path.join(base, "external_name.txt"))),
        ("import_list.txt", lambda base: os.path.isfile(os.path.join(base, "import_list.txt"))),
        ("keyword_list.txt", lambda base: os.path.isfile(os.path.join(base, "keyword_list.txt"))),
        ("standard_list.json", lambda base: os.path.isfile(os.path.join(base, "standard_list.json"))),
        ("wrapper_list.txt", lambda base: os.path.isfile(os.path.join(base, "wrapper_list.txt"))),
        ("xc_list.txt", lambda base: os.path.isfile(os.path.join(base, "xc_list.txt"))),
        ("inheritance_node.json", lambda base: os.path.isfile(os.path.join(base, "inheritance_node.json"))),
        ("no_inheritance_node.json", lambda base: os.path.isfile(os.path.join(base, "no_inheritance_node.json"))),
        ("internal_exception_list.json", lambda base: os.path.isfile(os.path.join(base, "internal_exception_list.json"))),
        ("external_candidates.json", lambda base: os.path.isfile(os.path.join(base, "external_candidates.json"))),
        ("source_json/", lambda base: (os.path.isdir(os.path.join(base, "source_json")) and any(True for _r,_d,f in os.walk(os.path.join(base, "source_json")) for _ in f))),
        ("typealias_json/", lambda base: (os.path.isdir(os.path.join(base, "typealias_json")) and any(True for _r,_d,f in os.walk(os.path.join(base, "typealias_json")) for _ in f))),
        ("sdk-json/", lambda base: (os.path.isdir(os.path.join(base, "sdk-json")) and any(True for _r,_d,f in os.walk(os.path.join(base, "sdk-json")) for _ in f))),
        ("external_to_ast/", lambda base: (os.path.isdir(os.path.join(base, "external_to_ast")) and any(True for _r,_d,f in os.walk(os.path.join(base, "external_to_ast")) for _ in f))),
        ("exception_list.json", lambda base: os.path.isfile(os.path.join(base, "exception_list.json"))),
        ("ast_node.json", lambda base: os.path.isfile(os.path.join(base, "ast_node.json"))),
    ]

    try:
        if preflight_progress_mode == "files":
            expected_total_files = 0
            for root_dir, _dirs, files in os.walk(input_path):
                for fn in files:
                    if fn.endswith(".swift"):
                        expected_total_files += 1
        else:
            expected_total_files = len(milestones)
    except Exception:
        expected_total_files = len(milestones) if preflight_progress_mode != "files" else 0
    ast_output_dir = os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output")
    last_scan_ts = 0.0
    current_files_count = 0
    if show_pre_ui:
        tui.set_status(["Preprocessing…", _progress_bar(0, max(1, expected_total_files)), "AST analysis"])
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

            # 진행률 업데이트(0.2초 간격 스캔)
            if preflight_progress_files and expected_total_files > 0:
                now_ts = time.time()
                if now_ts - last_scan_ts >= 0.2:
                    last_scan_ts = now_ts
                    try:
                        if preflight_progress_mode == "files":
                            cnt = 0
                            if os.path.isdir(ast_output_dir):
                                for _r, _d, fns in os.walk(ast_output_dir):
                                    for _fn in fns:
                                        cnt += 1
                            current_files_count = max(current_files_count, cnt)
                        else:
                            reached = 0
                            if os.path.isdir(ast_output_dir):
                                for _name, checker in milestones:
                                    try:
                                        if checker(ast_output_dir):
                                            reached += 1
                                    except Exception:
                                        pass
                            current_files_count = max(current_files_count, reached)
                    except Exception:
                        pass
            sp_idx = (sp_idx + 1) % len(spinner)
            if preflight_progress_files and expected_total_files > 0:
                bar = progress_bar(min(current_files_count, expected_total_files), expected_total_files)
            else:
                bar = progress_bar(1 if done_ast else 0, 1)
            if show_pre_ui:
                tui.set_status([ f"Preprocessing: {bar}  {spinner[sp_idx]}", "Current: AST analysis",   "",   *list(tail1) ])

            if eof and line_queue.empty():
                break
            time.sleep(0.05)
        rc1 = proc1.wait()
        if rc1 != 0:
            sys.exit(1)
        # ensure final bar reaches 100%
        try:
            done_ast = True
            if preflight_progress_files and expected_total_files > 0:
                current_files_count = max(current_files_count, expected_total_files)
                bar = progress_bar(expected_total_files, expected_total_files)
            else:
                bar = progress_bar(1, 1)
            # draw one last 100% frame
            try:
                sp_idx = (sp_idx + 1) % len(spinner)
            except Exception:
                sp_idx = 0
            if show_pre_ui:
                try:
                    tui.set_status([ f"Preprocessing: {bar}  {spinner[sp_idx]}", "Current: AST analysis",   "",   *list(tail1) ])
                except Exception:
                    pass
        except Exception:
            pass
        
        # preprocessing finished: clear previous tail logs so next phase starts clean
        try:
            tail1.clear()
        except Exception:
            pass
        # keep previous panel (Preprocessing) without switching to Preflight header
            
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
                # sticky preflight completion screen to ensure visible redraw before final stage
                try:
                    tui.show_exact_screen([
                        "Preflight confirmation received",
                        "Proceeding to obfuscation…",
                    ])
                except Exception:
                    try:
                        tui.set_status(["Preflight confirmation received", "Proceeding to obfuscation…"])  
                    except Exception:
                        pass
                try:
                    time.sleep(0.2)
                except Exception:
                    pass
            else:
                config = load_config_or_exit(working_config_path)
                patterns = extract_rule_patterns(config)
                # route preflight prints into TUI panel tail
                try:
                    include_echo = tui.make_stream_echo(
                        header="",
                        tail_len=10,
                    )
                except Exception:
                    include_echo = None
                _preflight_echo["include"] = include_echo
                _preflight_echo["current"] = "include"
                # create stable proxy used by redirect_stdout so we can switch targets at runtime
                if _preflight_echo.get("proxy") is None:
                    _preflight_echo["proxy"] = StreamProxy(_preflight_echo)

                if _preflight_echo.get("include") is not None:
                    # do not overwrite panel header before prompts
                    # use the proxy for the redirection so writes forward to the current echo object
                    try:
                        with redirect_stdout(_preflight_echo["proxy"]), redirect_stderr(_preflight_echo["proxy"]):
                            ok = summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
                    finally:
                        _preflight_echo["current"] = "include"
                    # sticky preflight result
                    try:
                        if ok is False:
                            tui.show_exact_screen(["Preflight aborted by user"])  
                        else:
                            tui.show_exact_screen([
                                "Preflight confirmation received",
                                "Proceeding to obfuscation…",
                            ])
                    except Exception:
                        try:
                            if ok is False:
                                tui.set_status(["Preflight aborted by user"])  
                            else:
                                tui.set_status(["Preflight confirmation received", "Proceeding to obfuscation…"])  
                        except Exception:
                            pass
                    try:
                        time.sleep(0.2)
                    except Exception:
                        pass
                else:
                    ok = summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
        except Exception as e:
            tui.set_status([f"설정 검증 실패: {e}"])
            sys.exit(1)

    # 2단계: 최종 난독화 (라이브 진행 바)
    try:
        tui.set_status(["Obfuscation in progress…", ""])  # below-banner refresh only
    except Exception:
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
            ("cfg", "Dynamic function"),
            ("debug", "Debug symbol removal"),
        ]
        labels_extra = {}
        detectors = {
            "mapping": re.compile(r"(\\bmapping\\b.*?:|\\[mapping\\]|\\bmapping\\b.*\\bstart\\b|identifier\\s+mapping)", re.I),
            "id-obf": re.compile(r"(id[-_ ]?obf|identifier\\s+obfuscation)", re.I),
            "cff": re.compile(r"(\\bcff\\b|control\\s*flow\\s*flattening|control[- ]?flow)", re.I),
            "opaq": re.compile(r"(\\bopaq\\b|opaque\\s+predicate)", re.I),
            "deadcode": re.compile(r"(dead\\s*code|\\bdeadcode\\b)", re.I),
            "encryption": re.compile(r"(string\\s+encryption|encryption\\s+start|\\[swingft_string_encryption\\])", re.I),
            "cfg": re.compile(r"(\\bcfg\\b|dynamic\\s*function|cfg:)", re.I),
            "debug": re.compile(r"(delete\\s+debug\\s+symbols|debug:|\\bdebug\\b)", re.I),
        }
        step_keys = [k for k, _ in steps]
        total_steps = len(steps)
        seen: set[str] = {"_bootstrap"}
        # track per-step state: start|done|skip
        step_state: dict[str, str] = {}
        # explicit stage2 markers: "key: start|done|skip"
        marker_rx = re.compile(r"^\s*(mapping|id-obf|cff|opaq|deadcode|encryption|cfg|debug)\s*:\s*(start|done|skip)\s*$", re.I)
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
        spinner = ["|", "/", "-", "\\"]
        sp2 = 0
        # queue reader
        q2: "queue.Queue[str|None]" = queue.Queue()
        def _reader2():
            try:
                for raw in proc.stdout:  # type: ignore[arg-type]
                    line = (raw or "").rstrip("\n")
                    q2.put(line)
            finally:
                try:
                    q2.put(None)
                except Exception:
                    pass
        thr2 = threading.Thread(target=_reader2, daemon=True)
        thr2.start()

        eof2 = False
        while True:
            try:
                item = q2.get(timeout=0.1)
            except queue.Empty:
                item = ""
            if item is None:
                eof2 = True
            elif isinstance(item, str) and item:
                line = item
                if line.strip():
                    tail2.append(line)
                    try:
                        if os.environ.get("SWINGFT_TUI_ECHO", "") == "1":
                            print(line)
                    except Exception:
                        pass
                low = line.lower()
                # explicit marker handling has priority
                try:
                    m = marker_rx.match(line.strip())
                except Exception:
                    m = None
                if m is not None:
                    key = m.group(1).lower()
                    action = m.group(2).lower()
                    # set current on start
                    if action == "start":
                        try:
                            idx = step_keys.index(key)
                            last_current = steps[idx][1]
                        except Exception:
                            pass
                        step_state[key] = "start"
                    else:
                        # done or skip => mark seen and advance current to next remaining step
                        if key in step_keys:
                            seen.add(key)
                        step_state[key] = action  # done|skip
                        try:
                            # if all primary steps are completed, show the last completed label
                            primary_keys = [k for k in step_keys if k != "_bootstrap"]
                            if all(k in seen for k in primary_keys):
                                # among completed, prefer the last with state==done; else fallback to current
                                last_done_label = None
                                for k2 in reversed(step_keys):
                                    if k2 in seen and k2 != "_bootstrap" and step_state.get(k2) == "done":
                                        try:
                                            idx2 = step_keys.index(k2)
                                            last_done_label = steps[idx2][1]
                                            break
                                        except Exception:
                                            pass
                                if last_done_label:
                                    last_current = last_done_label
                                else:
                                    idx = step_keys.index(key)
                                    last_current = steps[idx][1]
                            else:
                                # find next step not yet seen
                                for k2, lbl2 in steps:
                                    if k2 not in seen:
                                        last_current = lbl2
                                        break
                        except Exception:
                            pass
                    # handled marker, skip generic detection
                    sp2 = (sp2 + 1) % len(spinner)
                    bar = progress_bar(len([k for k in seen if k in step_keys]), total_steps)
                    try:
                        tui.set_status([
                            f"Obfuscation: {bar}  {spinner[sp2]}",
                            f"Current: {last_current}",
                            "",
                            *list(tail2)
                        ])
                    except Exception:
                        pass
                    if eof2 and q2.empty():
                        break
                    time.sleep(0.05)
                    continue
                if low.startswith("completed:") or low.startswith("skipped:"):
                    try:
                        last_current = "Finalizing"
                    except Exception:
                        pass
                # step detection via regex detectors first
                matched_key = None
                for key, rx in detectors.items():
                    try:
                        if rx.search(line):
                            matched_key = key
                            break
                    except Exception:
                        pass
                if matched_key is not None:
                    for k, lbl in steps:
                        if k == matched_key:
                            seen.add(k)
                            # if this is the last primary step to complete, keep its label as final
                            primary_keys = [kk for kk in step_keys if kk != "_bootstrap"]
                            if all(kk in seen for kk in primary_keys):
                                # prefer last done label if available
                                last_done_label = None
                                for k2 in reversed(step_keys):
                                    if k2 in seen and k2 != "_bootstrap" and step_state.get(k2) == "done":
                                        try:
                                            idx2 = step_keys.index(k2)
                                            last_done_label = steps[idx2][1]
                                            break
                                        except Exception:
                                            pass
                                last_current = last_done_label or lbl
                            else:
                                # otherwise, move to next not-yet-seen step
                                idx = step_keys.index(k)
                                mv = None
                                for j in range(idx + 1, len(steps)):
                                    if steps[j][0] not in seen:
                                        mv = steps[j][1]
                                        break
                                last_current = mv or lbl
                            break
                else:
                    for key, label in steps:
                        if key == "encryption":
                            if "[swingft_string_encryption] encryption_strings is true" in low:
                                last_current = label
                            if (low.startswith("encryption:") or " encryption:" in low or
                                "[swingft_string_encryption] done" in low or
                                low.endswith("[swingft_string_encryption] done.")):
                                seen.add(key)
                                step_state[key] = "done"
                                last_current = label
                        else:
                            # accept common variants like "[key]", "key start"
                            if (low.startswith(f"{key}:") or f" {key}:" in low or
                                f"[{key}]" in low or low.startswith(f"{key} start")):
                                seen.add(key)
                                # same completion rule: keep final label on last step
                                primary_keys = [kk for kk in step_keys if kk != "_bootstrap"]
                                if all(kk in seen for kk in primary_keys):
                                    last_done_label = None
                                    for k2 in reversed(step_keys):
                                        if k2 in seen and k2 != "_bootstrap" and step_state.get(k2) == "done":
                                            try:
                                                idx2 = step_keys.index(k2)
                                                last_done_label = steps[idx2][1]
                                                break
                                            except Exception:
                                                pass
                                    last_current = last_done_label or label
                                else:
                                    idx = step_keys.index(key)
                                    mv = None
                                    for j in range(idx + 1, len(steps)):
                                        if steps[j][0] not in seen:
                                            mv = steps[j][1]
                                            break
                                    last_current = mv or label
                for k, lbl in labels_extra.items():
                    if low.startswith(f"{k}:") or f" {k}:" in low:
                        last_current = lbl
            # periodic redraw
            sp2 = (sp2 + 1) % len(spinner)
            # if 모든 주요 단계가 완료되었다면, 마지막 'done' 단계명을 최종 표시로 유지 (skip은 제외)
            try:
                primary_keys = [k for k in step_keys if k != "_bootstrap"]
                if all(k in seen for k in primary_keys):
                    # 가장 뒤에 위치한 'done' 단계의 라벨 선택
                    last_done_label = None
                    for k in reversed(step_keys):
                        if k in seen and k != "_bootstrap" and step_state.get(k) == "done":
                            try:
                                idx = step_keys.index(k)
                                last_done_label = steps[idx][1]
                                break
                            except Exception:
                                pass
                    if last_done_label:
                        last_current = last_done_label
            except Exception:
                pass
            bar = progress_bar(len(seen), total_steps)
            try:
                tui.set_status([
                    f"Obfuscation: {bar}  {spinner[sp2]}",
                    f"Current: {last_current}",
                    "",
                    *list(tail2)
                ])
            except Exception:
                pass
            if eof2 and q2.empty():
                break
            time.sleep(0.05)

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