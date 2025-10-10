from __future__ import annotations

import os
import shlex
import subprocess
from typing import Dict, Optional
import time
import sys
import threading


def _wait_for_first_existing(path_list: list[str], timeout: Optional[int] = None, interval: float = 1.0) -> str | None:
    parents_and_names = []
    for p in path_list:
        parent = os.path.dirname(p)
        name = os.path.basename(p)
        # Prefer checking the 'output' directory specifically to avoid huge parent listings.
        # If the candidate path's parent is already '.../output', use it. Otherwise, prefer parent/output.
        if os.path.basename(parent).lower() == "output":
            check_parent = parent
        else:
            check_parent = os.path.join(parent, "output")
        parents_and_names.append((p, check_parent, name))
    start_time = time.time()
    try:
        while True:
            # DEBUG: print candidate paths and basic existence status each poll
            try:
                print(f"[DEBUG] poll at {time.strftime('%Y-%m-%d %H:%M:%S')} - candidates: {[p for p, _, _ in parents_and_names]}", flush=True)
                for p, parent, name in parents_and_names:
                    try:
                        print(f"[DEBUG]  - {p} exists={os.path.exists(p)} parent_exists={os.path.isdir(parent)} parent={parent}", flush=True)
                    except Exception:
                        pass
            except Exception:
                # never fail on debug printing
                pass
            for p, parent, name in parents_and_names:
                if os.path.exists(p):
                    return os.path.abspath(p)
                # primary check: the preferred 'parent' (usually .../output)
                try:
                    if os.path.isdir(parent):
                        try:
                            items = os.listdir(parent)
                            if name in items:
                                return os.path.abspath(os.path.join(parent, name))
                        except Exception:
                            pass
                except Exception:
                    pass
                # fallback: check the original parent (in case we substituted parent/output but the file sits in parent)
                try:
                    orig_parent = os.path.dirname(p)
                    if orig_parent and os.path.isdir(orig_parent):
                        try:
                            items2 = os.listdir(orig_parent)
                            if name in items2:
                                return os.path.abspath(os.path.join(orig_parent, name))
                        except Exception:
                            pass
                except Exception:
                    pass
            # DEBUG: print parent directory listings every poll
            for _, parent, _ in parents_and_names:
                if os.path.isdir(parent):
                    try:
                        items = os.listdir(parent)
                        print(f"[DEBUG] output dir listing for '{parent}' (first 50): {items[:50]}", flush=True)
                    except Exception as e:
                        print(f"[DEBUG] could not list {parent}: {e}", flush=True)
            if timeout is not None and (time.time() - start_time) >= timeout:
                return None
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[pipeline] wait cancelled by user", flush=True)
        return None
    return None


def run_obfuscation_pipeline(
    project_input: str,
    project_output: str,
    config_path: Optional[str] = None,
    *,
    pipeline_cmd_path: Optional[str] = None,
    extra_env: Optional[Dict[str, str]] = None,
    stage: str = "full",
) -> Dict[str, str]:
    """Run external Obfuscation_Pipeline with stage control.

    Args:
        stage: "preprocessing" (1단계만), "final" (최종 단계만), "full" (전체)

    Fixed template (positional only, as requested):
        <cmd> <project_input> <project_output> [--stage <stage>]
    """

    cmd_str = (pipeline_cmd_path or os.getenv("SWINGFT_PIPELINE_CMD", "")).strip()
    if not cmd_str:
        raise RuntimeError(
            "SWINGFT_PIPELINE_CMD 가 설정되지 않았습니다. 외부 난독화 파이프라인 실행 파일 경로를 지정하세요."
        )

    base = shlex.split(cmd_str)
    tokens = base + [project_input, project_output]
    
    # 단계별 실행을 위한 옵션 추가
    if stage != "full":
        tokens += ["--stage", stage]

    env = os.environ.copy()
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})

    if config_path:
        abs_cfg = os.path.abspath(config_path)
        env["SWINGFT_WORKING_CONFIG"] = abs_cfg

    # 파이프라인 실행 시 작업 디렉터리를 파이프라인 폴더로 변경
    pipeline_dir = None
    if cmd_str.startswith("python3 ") and "Obfuscation_Pipeline" in cmd_str:
        # 하드코딩된 파이프라인의 경우 작업 디렉터리를 Obfuscation_Pipeline로 설정
        pipeline_dir = os.path.join(os.getcwd(), "Obfuscation_Pipeline")
        if os.path.isdir(pipeline_dir):
            # 절대경로로 변환해서 전달
            tokens = ["python3", "obf_pipeline.py", os.path.abspath(project_input), os.path.abspath(project_output)]
            if stage != "full":
                tokens += ["--stage", stage]
    
    print(f"[pipeline] 실행 명령: {' '.join(tokens)}", flush=True)
    print(f"[pipeline] 작업 디렉터리: {pipeline_dir}", flush=True)
    print(f"[DEBUG] stage 파라미터: {stage}", flush=True)
    
    exception_list_paths = [
        os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "exception_list.json"),
    ]
    if pipeline_dir:
        exception_list_paths.append(os.path.join(pipeline_dir, "AST", "output", "exception_list.json"))

    candidates = {
        "exception_list": exception_list_paths,
        "rename_map": [
            os.path.join(project_output, "rename_map.json"),
            os.path.join(project_output, "output", "rename_map.json"),
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "output", "rename_map.json"),
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "rename_map.json"),
        ],
        "report": [
            os.path.join(project_output, "report.json"),
            os.path.join(project_output, "output", "report.json"),
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "output", "report.json"),
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "report.json"),
        ],
    }

    proc = subprocess.Popen(tokens, env=env, cwd=pipeline_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    found_artifacts: Dict[str, str] = {}
    stop_event = threading.Event()

    def _poll_artifacts():
        try:
            while not stop_event.is_set():
                for key, paths in candidates.items():
                    if stop_event.is_set():
                        return
                    # direct existence check for each path (no helper)
                    for p in paths:
                        ap = os.path.abspath(p)
                        if os.path.exists(ap):
                            if key not in found_artifacts:
                                found_artifacts[key] = ap
                                print(f"[pipeline] {key} 발견: {ap}", flush=True)
                time.sleep(1.0)
        except Exception as e:
            print(f"[pipeline] artifact poller error: {e}", flush=True)

    poll_thread = threading.Thread(target=_poll_artifacts, daemon=True)
    poll_thread.start()

    try:
        retcode = proc.wait()
    except KeyboardInterrupt:
        print("[pipeline] external pipeline interrupted by user; terminating child", flush=True)
        try:
            proc.terminate()
        except Exception:
            pass
        stop_event.set()
        poll_thread.join(timeout=1.0)
        raise

    # ensure poller stops after process ends
    stop_event.set()
    poll_thread.join(timeout=0.5)

    # Capture stdout and stderr for debugging
    stdout, stderr = proc.communicate()
    if stdout:
        print(f"[pipeline stdout]: {stdout[:1000]}...", flush=True)
    if stderr:
        print(f"[pipeline stderr]: {stderr[:1000]}...", flush=True)

    if retcode != 0:
        raise RuntimeError(f"외부 난독화 파이프라인 실패 (exit={retcode})")

    artifacts: Dict[str, str] = {}
    for key, paths in candidates.items():
        if key in found_artifacts:
            artifacts[key] = found_artifacts[key]
        else:
            p = _wait_for_first_existing(paths, timeout=0, interval=1.0)
            if p:
                artifacts[key] = p
                print(f"[pipeline] {key} 발견: {p}", flush=True)
            else:
                if key == "exception_list":
                    print(f"[pipeline] {key} 미발견. 확인 경로들: {paths}", flush=True)

    return artifacts
