import os, sys, subprocess, shutil, json
import time
import argparse

from remove_files import remove_files
from AST.run_ast import run_ast
from Mapping.run_mapping import mapping
from ID_Obf.id_dump import make_dump_file_id
from merge_list import merge_llm_and_rule
from Opaquepredicate.run_opaque import run_opaque
from DeadCode.deadcode import deadcode
from remove_debug_symbol import remove_debug_symbol
from swift_comment_remover import strip_comments_in_place

def run_command(cmd, show_logs=False):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"명령어 실행 실패: {' '.join(cmd)}")
        print(f"오류 코드: {result.returncode}")
        print(f"stderr: {result.stderr}")
        print(f"stdout: {result.stdout}")
        raise RuntimeError(f"명령어 실행 실패: {' '.join(cmd)}")
    else:
        # show_logs가 True일 때만 내부 로그 출력
        if show_logs:
            if result.stdout.strip():
                print(result.stdout)
            if result.stderr.strip():
                print(result.stderr)

def ignore_git_and_build(dir, files):
    """Git 폴더와 빌드 아티팩트 제외"""
    ignored = set()
    for file in files:
        if file == '.git' or file.startswith('.') and file in ['.DS_Store', '.build', 'DerivedData']:
            ignored.add(file)
    return ignored

def stage1_ast_analysis(original_project_dir, obf_project_dir):
    """STAGE 1: AST 분석 및 파일 목록 생성"""
    original_dir = os.getcwd()
    
    # decorative separators only in verbose mode
    if os.environ.get("SWINGFT_VERBOSE_STAGE"):
        print("=" * 50)
        print("STAGE 1: AST 분석 및 파일 목록 생성 (AST Analysis)")
        print("=" * 50)
    
    start = time.time()
    
    # 구성 확인: Obfuscation_identifiers=false면 전체 Stage 1 스킵
    try:
        cfg_path = os.environ.get("SWINGFT_WORKING_CONFIG")
        if not cfg_path:
            SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
            cfg_path = os.path.join(SCRIPT_DIR, "Swingft_config.json")
        cfg_json = {}
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_json = json.load(f)
        def _to_bool(v, default=True):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"1","true","yes","y","on"}
            if isinstance(v, (int, float)):
                return bool(v)
            return default
        opt_map = cfg_json.get("options") if isinstance(cfg_json.get("options"), dict) else cfg_json
        if not _to_bool((opt_map or {}).get("Obfuscation_identifiers", True), True):
            print("[INFO] Obfuscation_identifiers=false → Stage 1(AST) 스킵")
            return
    except Exception:
        pass
    
    # 1차 룰베이스 제외 대상 식별 & AST 분석
    run_ast(obf_project_dir)
    
    ast_end = time.time()
    # print("ast: Done")
    
    # Rule & LLM 결과 병합
    merge_llm_and_rule()
    
    if os.environ.get("SWINGFT_VERBOSE_STAGE"):
        print("STAGE 1 완료! (AST 분석)")
        print("=" * 50)
        print()

def stage2_obfuscation(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg=False):
    """STAGE 2: 매핑 및 난독화"""
    original_dir = os.getcwd()
    
    if os.environ.get("SWINGFT_VERBOSE_STAGE"):
        print("=" * 50)
        print("STAGE 2: 매핑 및 난독화 (Mapping & Obfuscation)")
        print("=" * 50)
    
    start = time.time()
    # minimal TUI markers (default on; set SWINGFT_TUI_MARKERS=0 to disable)
    def _to_bool(v, default=True):
        try:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"1","true","yes","y","on"}
            if isinstance(v, (int, float)):
                return bool(v)
        except Exception:
            pass
        return default
    _markers = _to_bool(os.environ.get("SWINGFT_TUI_MARKERS", "1"), True)
    def _marker(msg: str):
        try:
            if _markers:
                print(msg)
        except Exception:
            pass
    step_status = {}

    # 구성 파일 로드 (암호화와 동일한 기본 경로 정책)
    working_cfg = os.environ.get("SWINGFT_WORKING_CONFIG")
    if working_cfg:
        cfg_path = working_cfg
    else:
        cfg_path = os.path.join(OBFUSCATION_ROOT, "Swingft_config.json")
    cfg_json = {}
    try:
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_json = json.load(f)
    except Exception as e:
        print(f"[WARN] 구성 파일 파싱 실패: {cfg_path} ({e}) → 기본값으로 진행")

    # options 블록 우선
    def get_bool(key: str, default: bool) -> bool:
        try:
            src = cfg_json.get("options") if isinstance(cfg_json.get("options"), dict) else cfg_json
            v = (src or {}).get(key)
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"1","true","yes","y","on"}
            if isinstance(v, (int, float)):
                return bool(v)
        except Exception:
            pass
        return default

    flag_ident = get_bool("Obfuscation_identifiers", True)
    # 0) (앞쪽) 주석 제거: 디버깅 심볼 제거 플래그가 켜진 경우 주석도 먼저 제거
    flag_dbg = get_bool("Delete_debug_symbols", True)
    if flag_dbg:
        try:
            strip_comments_in_place(obf_project_dir)
        except Exception:
            pass

    if flag_ident:
        _marker("mapping: start")
        # 식별자 매핑
        mapping()
        mapping_end = time.time()
        _marker("mapping: done")
        step_status["mapping"] = "Done"

        # 식별자 난독화
        _marker("id-obf: start")
        swift_list_dir = os.path.join(OBFUSCATION_ROOT, "swift_file_list.txt")
        mapping_result_dir = os.path.join(OBFUSCATION_ROOT, "mapping_result_s.json")

        target_project_dir = os.path.join(OBFUSCATION_ROOT, "ID_Obf")
        target_name = "IDOBF"

        os.chdir(target_project_dir)
        build_marker_file = ".build/build_path.txt"
        previous_build_path = ""
        if os.path.exists(build_marker_file):
            with open(build_marker_file, "r") as f:
                previous_build_path = f.read().strip()
        current_build_path = os.path.abspath(".build")
        if previous_build_path != current_build_path or previous_build_path == "":
            run_command(["swift", "package", "clean"])
            shutil.rmtree(".build", ignore_errors=True)
            run_command(["swift", "build"])
            with open(build_marker_file, "w") as f:
                f.write(current_build_path)
        run_command(["swift", "run", target_name, mapping_result_dir, swift_list_dir])

        # 식별자 난독화 덤프파일 생성
        os.chdir(original_dir)
        make_dump_file_id(original_project_dir, obf_project_dir)

        id_end = time.time()
        _marker("id-obf: done")
        step_status["id-obf"] = "Done"
    else:
        _marker("mapping: skip")
        _marker("id-obf: skip")
        step_status["mapping"] = "Skip"
        step_status["id-obf"] = "Skip"
        id_end = start

    # 제어흐름 평탄화
    flag_cff = get_bool("Obfuscation_controlFlow", True)
    if flag_cff:
        _marker("cff: start")
        cff_path = os.path.join(OBFUSCATION_ROOT, "CFF")
        os.chdir(cff_path)
        build_marker_file = ".build/build_path.txt"
        previous_build_path = ""
        if os.path.exists(build_marker_file):
            with open(build_marker_file, "r") as f:
                previous_build_path = f.read().strip()
        current_build_path = os.path.abspath(".build")
        if previous_build_path != current_build_path or previous_build_path == "":
            run_command(["swift", "package", "clean"])
            shutil.rmtree(".build", ignore_errors=True)
            run_command(["swift", "build"])
            with open(build_marker_file, "w") as f:
                f.write(current_build_path)
        cmd = ["swift", "run", "Swingft_CFF", obf_project_dir]
        run_command(cmd)
        os.chdir(original_dir)

        cff_end = time.time()
        _marker("cff: done")
        step_status["cff"] = "Done"
    else:
        _marker("cff: skip")
        step_status["cff"] = "Skip"
        cff_end = id_end

    # 불투명한 술어 + 데드코드 (Obfuscation_controlFlow와 동일 플래그로 제어)
    if flag_cff:
        # 불투명한 술어
        _marker("opaq: start")
        run_opaque(obf_project_dir)
        opaq_end = time.time()
        _marker("opaq: done")
        step_status["opaq"] = "Done"

        # 데드코드
        _marker("deadcode: start")
        deadcode()
        deadcode_end = time.time()
        _marker("deadcode: done")
        step_status["deadcode"] = "Done"
    else:
        _marker("opaq: skip")
        _marker("deadcode: skip")
        step_status["opaq"] = "Skip"
        step_status["deadcode"] = "Skip"
        deadcode_end = cff_end

    # 문자열 암호화
    # 문자열 암호화: 구성으로 제어
    flag_enc = get_bool("Encryption_strings", True)
    if flag_enc:
        _marker("encryption: start")
        enc_path = os.path.join(OBFUSCATION_ROOT, "String_Encryption")
        os.chdir(enc_path)
        working_cfg = os.environ.get("SWINGFT_WORKING_CONFIG")
        if working_cfg:
            cfg_arg = working_cfg
        else:
            cfg_arg = os.path.join(OBFUSCATION_ROOT, "Swingft_config.json")
        cmd = ["python3", "run_Swingft_Encryption.py", obf_project_dir, cfg_arg]
        run_command(cmd, show_logs=True)
        os.chdir(original_dir)
        enc_end = time.time()
        _marker("encryption: done")
        step_status["encryption"] = "Done"
    else:
        enc_end = deadcode_end
        _marker("encryption: skip")
        step_status["encryption"] = "Skip"

    # 동적 함수 호출 (인플레이스 실행)
    if not skip_cfg:
        if not flag_cff:
            #print("[INFO] Obfuscation_controlFlow=false → CFG 단계 건너뜀")
            cfg_end = enc_end
        else:
            _marker("cfg: start")
            cfg_path = os.path.join(OBFUSCATION_ROOT, "CFG")
            os.chdir(cfg_path)
            # src와 dst 모두 obf_project_dir로 동일 설정하여 인플레이스 적용
            # 구성 파일 경로 추출 (Stage 2에서 사용하던 정책과 동일)
            working_cfg = os.environ.get("SWINGFT_WORKING_CONFIG")
            cfg_arg = working_cfg if working_cfg else os.path.join(OBFUSCATION_ROOT, "Swingft_config.json")
            cmd = ["python3", "run_pipeline.py", "--src", obf_project_dir, "--dst", obf_project_dir, 
                   "--perfile-inject", "--overwrite", "--debug", "--include-packages", "--no-skip-ui", "--config", cfg_arg]
            run_command(cmd)
            os.chdir(original_dir)

            cfg_end = time.time()
            _marker("cfg: done")
            step_status["cfg"] = "Done"
    else:
        _marker("cfg: skip")
        step_status["cfg"] = "Skip"
        cfg_end = enc_end

    # 디버깅용 코드 제거 (원래 자리에서 실행)
    if flag_dbg:
        _marker("debug: start")
        start_dbg = time.time()
        remove_debug_symbol(obf_project_dir)
        debug_end = time.time()
        _marker("debug: done")
        step_status["debug"] = "Done"
    else:
        debug_end = cfg_end

    # total은 유지하되 시간은 분 단위만 로그로 남김(원하면 지울 수 있음)
    # print("total: Done")

    # Summary block (grouped labels)
    def _group_status(keys):
        vals = [step_status.get(k) for k in keys]
        return "Done" if any(v == "Done" for v in vals) else "Skip"

    summary_map = {
        "Identifiers obfuscation": _group_status(["mapping", "id-obf"]),
        "Control flow obfuscation": _group_status(["cff", "opaq", "deadcode", "cfg"]),
        "String encryption": step_status.get("encryption", "Skip"),
        "Delete debug symbols": step_status.get("debug", "Skip"),
    }

    done_labels = [name for name, st in summary_map.items() if st == "Done"]
    skip_labels = [name for name, st in summary_map.items() if st == "Skip"]
    if done_labels:
        print("completed:", ", ".join(done_labels))
    if skip_labels:
        print("skipped:", ", ".join(skip_labels))
    
    if os.environ.get("SWINGFT_VERBOSE_STAGE"):
        print("STAGE 2 완료!")
        print("=" * 50)
        print()

def stage3_cleanup(obf_project_dir, obf_project_dir_cfg):
    """STAGE 3: 정리 및 삭제"""
    
    # quiet logger (default: quiet on unless SWINGFT_QUIET=0/false)
    def _p(*args, **kwargs):
        try:
            q = str(os.environ.get("SWINGFT_QUIET", "1")).strip().lower() in {"1", "true", "yes", "y"}
        except Exception:
            q = True
        if not q:
            print(*args, **kwargs)

    if os.environ.get("SWINGFT_VERBOSE_STAGE"):
        _p("=" * 50)
        _p("STAGE 3: 정리 및 삭제 (Cleanup)")
        _p("=" * 50)
    
    # 기준 루트(Obfuscation_Pipeline 디렉토리)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # AST/output 폴더 정리 (루트 기준)
    ast_output_dir = os.path.join(script_dir, "AST", "output")
    _p(f"AST/output 폴더 경로: {ast_output_dir}")
    _p(f"AST/output 폴더 존재 여부: {os.path.exists(ast_output_dir)}")
    
    if os.path.exists(ast_output_dir):
        try:
            _p(f"AST/output 폴더 정리 시작: {ast_output_dir}")
            shutil.rmtree(ast_output_dir)
            _p("AST/output 폴더 정리 완료")
        except Exception as e:
            _p(f"AST/output 폴더 정리 실패: {e}")
    else:
        _p("AST/output 폴더가 존재하지 않습니다")
    
    # 파일 삭제
    _p("임시 파일들을 삭제합니다...")
    remove_files(obf_project_dir, obf_project_dir_cfg)

    # String_Encryption 디렉토리의 JSON 파일들 정리 (루트 기준)
    se_dir = os.path.join(script_dir, "String_Encryption")
    se_jsons = [
        os.path.join(se_dir, "strings.json"),
        os.path.join(se_dir, "targets_swift_paths.json"),
    ]
    for p in se_jsons:
        try:
            if os.path.exists(p):
                os.remove(p)
                _p(f"삭제 완료: {p}")
        except Exception as e:
            _p(f"삭제 실패: {p} ({e})")

    # 루트(Obfuscation_Pipeline) 레벨 매핑 산출물 정리
    root_side_artifacts = [
        os.path.join(script_dir, "mapping_result.json"),
        os.path.join(script_dir, "mapping_result_s.json"),
        os.path.join(script_dir, "type_info.json"),
    ]
    for p in root_side_artifacts:
        try:
            if os.path.exists(p):
                os.remove(p)
                print(f"삭제 완료: {p}")
        except Exception as e:
            print(f"삭제 실패: {p} ({e})")

    # Mapping/output 디렉토리 정리 (루트 기준)
    mapping_output_dir = os.path.join(script_dir, "Mapping", "output")
    if os.path.exists(mapping_output_dir):
        try:
            shutil.rmtree(mapping_output_dir)
            _p(f"삭제 완료: {mapping_output_dir}")
        except Exception as e:
            _p(f"삭제 실패: {mapping_output_dir} ({e})")

    # 혹시 현재 작업 디렉토리(cwd)에 동일 이름의 파일이 있는 경우도 정리 (실행 위치가 달랐던 경우 대응)
    cwd = os.getcwd()
    cwd_side_artifacts = [
        os.path.join(cwd, "mapping_result.json"),
        os.path.join(cwd, "mapping_result_s.json"),
        os.path.join(cwd, "type_info.json"),
    ]
    for p in cwd_side_artifacts:
        try:
            if os.path.exists(p):
                os.remove(p)
                _p(f"삭제 완료(cwd): {p}")
        except Exception as e:
            _p(f"삭제 실패(cwd): {p} ({e})")
    
    _p("STAGE 3 완료!")
    _p("=" * 50)
    _p("전체 난독화 파이프라인 완료!")
    _p("=" * 50)

def obf_pipeline(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg=False):
    """전체 난독화 파이프라인 실행"""
    # STAGE 1 실행
    stage1_ast_analysis(original_project_dir, obf_project_dir)
    
    # STAGE 2 실행
    stage2_obfuscation(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg)
    
    # STAGE 3 실행
    obf_project_dir_cfg = os.path.join(os.path.dirname(obf_project_dir), "cfg")
    stage3_cleanup(obf_project_dir, obf_project_dir_cfg)

def main():
    parser = argparse.ArgumentParser(description="Swingft 난독화 파이프라인")
    parser.add_argument("input", help="입력 프로젝트 경로")
    parser.add_argument("output", help="출력 프로젝트 경로")
    parser.add_argument("--stage", choices=['preprocessing', 'final', 'full'], 
                       default='full', help="실행할 스테이지")
    parser.add_argument("--skip-cfg", action="store_true", help="CFG 단계 건너뛰기")
    
    args = parser.parse_args()
    
    original_project_dir = args.input
    obf_project_dir = args.output
    skip_cfg = getattr(args, 'skip_cfg', False)

    # 스크립트 파일의 디렉토리를 기준으로 경로 설정
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    OBFUSCATION_ROOT = SCRIPT_DIR

    # Stage별 복사 정책
    # - 전체 실행(or stage 미지정) 또는 Stage 1에서만 원본을 출력으로 복사
    # - Stage 2/3에서는 절대 복사하지 않음 (이전 단계 결과를 유지)
    is_full_run = args.stage == 'full'
    should_copy = is_full_run or args.stage == 'preprocessing'

    if should_copy:
        # output 디렉토리 준비 (없으면 생성)
        if not os.path.exists(obf_project_dir):
            if not os.environ.get("SWINGFT_VERBOSE_COPY"):
                pass
            else:
                print(f"새로운 output 디렉토리를 생성합니다: {obf_project_dir}")
            os.makedirs(obf_project_dir, exist_ok=True)
        else:
            if os.environ.get("SWINGFT_VERBOSE_COPY"):
                print(f"기존 output 디렉토리가 존재합니다: {obf_project_dir}")

        # 프로젝트 복사 (항상 새로 복사, 기존 파일 위에 덮어쓰기)
        if os.environ.get("SWINGFT_VERBOSE_COPY"):
            print(f"프로젝트를 복사합니다: {original_project_dir} -> {obf_project_dir}")
        shutil.copytree(original_project_dir, obf_project_dir, dirs_exist_ok=True, ignore=ignore_git_and_build)
    else:
        if os.environ.get("SWINGFT_VERBOSE_COPY"):
            print("[INFO] Stage 2/3 실행: 원본→출력 복사 건너뜀 (이전 결과 유지)")

    if args.stage == 'preprocessing':
        #print("STAGE 1만 실행합니다... (AST 분석)")
        stage1_ast_analysis(original_project_dir, obf_project_dir)
    elif args.stage == 'final':
        #print("STAGE 2만 실행합니다... (매핑&난독화)")
        stage2_obfuscation(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg)
        # Stage 2 이후에도 정리(Stage 3) 실행되도록 추가
        obf_project_dir_cfg = os.path.join(os.path.dirname(obf_project_dir), "cfg")
        stage3_cleanup(obf_project_dir, obf_project_dir_cfg)
    elif args.stage == 'full':
        print("전체 파이프라인을 실행합니다...")
        obf_pipeline(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg)

if __name__ == "__main__":
    main()
