import os, sys, subprocess, shutil
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
    
    print("=" * 50)
    print("STAGE 1: AST 분석 및 파일 목록 생성 (AST Analysis)")
    print("=" * 50)
    
    start = time.time()
    
    # 1차 룰베이스 제외 대상 식별 & AST 분석
    run_ast(obf_project_dir)
    
    ast_end = time.time()
    print("ast: ", ast_end - start)
    
    # Rule & LLM 결과 병합
    merge_llm_and_rule()
    
    print("STAGE 1 완료! (AST 분석)")
    print("=" * 50)
    print()

def stage2_obfuscation(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg=False):
    """STAGE 2: 매핑 및 난독화"""
    original_dir = os.getcwd()
    
    print("=" * 50)
    print("STAGE 2: 매핑 및 난독화 (Mapping & Obfuscation)")
    print("=" * 50)
    
    start = time.time()

    # 식별자 매핑
    mapping()
    
    mapping_end = time.time()
    print("mapping: ", mapping_end - start)

    # 식별자 난독화
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
    print("id-obf: ", id_end - mapping_end)

    # 제어흐름 평탄화
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
    print("cff: ", cff_end - id_end)

    # 불투명한 술어 삽입
    run_opaque(obf_project_dir)

    opaq_end = time.time()
    print("opaq: ", opaq_end - cff_end)

    # 데드코드 삽입
    deadcode()
    
    deadcode_end = time.time()
    print("deadcode: ", deadcode_end - opaq_end)

    # 문자열 암호화
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
    print("encryption: ", enc_end - deadcode_end)

    # 동적 함수 호출
    if not skip_cfg:
        obf_project_dir_cfg = os.path.join(os.path.dirname(obf_project_dir), "cfg")
        shutil.copytree(obf_project_dir, obf_project_dir_cfg)

        cfg_path = os.path.join(OBFUSCATION_ROOT, "CFG")
        os.chdir(cfg_path)
        cmd = ["python3", "run_pipeline.py", "--src", obf_project_dir_cfg, "--dst", obf_project_dir, 
               "--perfile-inject", "--overwrite", "--debug", "--include-packages", "--no-skip-ui"]
        run_command(cmd)
        os.chdir(original_dir)

        # CFG 작업 완료 후 cfg 폴더 정리
        if os.path.exists(obf_project_dir_cfg):
            print(f"CFG 작업용 복사본 정리: {obf_project_dir_cfg}")
            shutil.rmtree(obf_project_dir_cfg)
            print("CFG 작업용 복사본 정리 완료")

        cfg_end = time.time()
        print("cfg: ", cfg_end - enc_end)
    else:
        print("CFG (동적 함수) 단계가 건너뜀")
        cfg_end = enc_end

    # 디버깅용 코드 제거
    remove_debug_symbol(obf_project_dir)

    debug_end = time.time()
    print("debug: ", debug_end - cfg_end)

    print("total: ", debug_end - start)
    print((debug_end - start) / 60)
    
    print("STAGE 2 완료!")
    print("=" * 50)
    print()

def stage3_cleanup(obf_project_dir, obf_project_dir_cfg):
    """STAGE 3: 정리 및 삭제"""
    
    print("=" * 50)
    print("STAGE 3: 정리 및 삭제 (Cleanup)")
    print("=" * 50)
    
    # AST/output 폴더 정리
    ast_output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AST", "output")
    print(f"AST/output 폴더 경로: {ast_output_dir}")
    print(f"AST/output 폴더 존재 여부: {os.path.exists(ast_output_dir)}")
    
    if os.path.exists(ast_output_dir):
        try:
            print(f"AST/output 폴더 정리 시작: {ast_output_dir}")
            shutil.rmtree(ast_output_dir)
            print("AST/output 폴더 정리 완료")
        except Exception as e:
            print(f"AST/output 폴더 정리 실패: {e}")
    else:
        print("AST/output 폴더가 존재하지 않습니다")
    
    # 파일 삭제
    print("임시 파일들을 삭제합니다...")
    remove_files(obf_project_dir, obf_project_dir_cfg)
    
    print("STAGE 3 완료!")
    print("=" * 50)
    print("전체 난독화 파이프라인 완료!")
    print("=" * 50)

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
            print(f"새로운 output 디렉토리를 생성합니다: {obf_project_dir}")
            os.makedirs(obf_project_dir, exist_ok=True)
        else:
            print(f"기존 output 디렉토리가 존재합니다: {obf_project_dir}")

        # 프로젝트 복사 (항상 새로 복사, 기존 파일 위에 덮어쓰기)
        print(f"프로젝트를 복사합니다: {original_project_dir} -> {obf_project_dir}")
        shutil.copytree(original_project_dir, obf_project_dir, dirs_exist_ok=True, ignore=ignore_git_and_build)
    else:
        print("[INFO] Stage 2/3 실행: 원본→출력 복사 건너뜀 (이전 결과 유지)")

    if args.stage == 'preprocessing':
        print("STAGE 1만 실행합니다... (AST 분석)")
        stage1_ast_analysis(original_project_dir, obf_project_dir)
    elif args.stage == 'final':
        print("STAGE 2만 실행합니다... (매핑&난독화)")
        stage2_obfuscation(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg)
    elif args.stage == 'full':
        print("전체 파이프라인을 실행합니다...")
        obf_pipeline(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg)

if __name__ == "__main__":
    main()
