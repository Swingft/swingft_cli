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

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"명령어 실행 실패: {' '.join(cmd)}")
        print(f"오류 코드: {result.returncode}")
        print(f"stderr: {result.stderr}")
        print(f"stdout: {result.stdout}")
        raise RuntimeError(f"명령어 실행 실패: {' '.join(cmd)}")
    else:
        print(f"명령어 실행 성공: {' '.join(cmd)}")
        if result.stdout.strip():
            print(f"stdout: {result.stdout}")


def stage1_ast_analysis(original_project_dir, obf_project_dir):
    """STAGE 1: AST 분석 및 파일 목록 생성"""
    original_dir = os.getcwd()

    if not getattr(sys.modules[__name__], '_encryption_only', False):
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

    ast_end = time.time()
    print("ast: ", ast_end - start)

    print("STAGE 1 완료! (AST 분석)")
    print("=" * 50)
    print()

def stage2_obfuscation(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg=False):
    """STAGE 2: 매핑 및 난독화"""
    original_dir = os.getcwd()

    if not getattr(sys.modules[__name__], '_encryption_only', False):
        print("=" * 50)
        print("STAGE 2: 매핑 및 난독화 (Mapping & Obfuscation)")
        print("=" * 50)

    start = time.time()

    # 식별자 매핑
    if not getattr(sys.modules[__name__], '_encryption_only', False):
        print("=== 식별자 매핑 시작 ===")
    mapping()

    mapping_end = time.time()
    if not getattr(sys.modules[__name__], '_encryption_only', False):
        print("mapping: ", mapping_end - start)
        print("=== 식별자 매핑 완료 ===\n")

    # 식별자 난독화
    if not getattr(sys.modules[__name__], '_encryption_only', False):
        print("=== 식별자 난독화 시작 ===")
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
    print("id-obf: ", id_end - start)
    print("=== 식별자 난독화 완료 ===\n")

    # 제어흐름 평탄화
    print("=== CFF (Control Flow Flattening) 시작 ===")
    print(f"CFF 대상 프로젝트: {obf_project_dir}")
    
    cff_path = os.path.join(OBFUSCATION_ROOT, "CFF")
    print(f"CFF 도구 경로: {cff_path}")
    os.chdir(cff_path)

    build_marker_file = ".build/build_path.txt"
    previous_build_path = ""
    if os.path.exists(build_marker_file):
        with open(build_marker_file, "r") as f:
            previous_build_path = f.read().strip()
    
    current_build_path = os.path.abspath(".build")
    if previous_build_path != current_build_path or previous_build_path == "":
        print("CFF 도구 빌드 중...")
        run_command(["swift", "package", "clean"])
        shutil.rmtree(".build", ignore_errors=True)
        result = subprocess.run(["swift", "build"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"CFF 빌드 실패: {result.stderr}")
        else:
            print("CFF 빌드 완료")
        with open(build_marker_file, "w") as f:
            f.write(current_build_path)
    else:
        print("CFF 도구 이미 빌드됨 (캐시 사용)")
    
    print("CFF 적용 중...")
    cmd = ["swift", "run", "Swingft_CFF", obf_project_dir]
    print(f"실행 명령: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("CFF 적용 완료!")
        if result.stdout.strip():
            print(f"CFF 출력: {result.stdout}")
    else:
        print(f"CFF 적용 실패: {result.stderr}")
        if result.stdout.strip():
            print(f"CFF 출력: {result.stdout}")
    
    os.chdir(original_dir)
    print("=== CFF 완료 ===\n")

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
    print("=== String Encryption 시작 ===")
    print(f"암호화 대상 프로젝트: {obf_project_dir}")
    
    enc_path = os.path.join(OBFUSCATION_ROOT, "String_Encryption")
    print(f"암호화 도구 경로: {enc_path}")
    
    # 사용자가 입력한 config 파일 경로 사용
    user_config_path = os.environ.get("SWINGFT_WORKING_CONFIG")
    if user_config_path and os.path.exists(user_config_path):
        config_path = user_config_path
        print(f"사용자 설정 파일 경로: {config_path}")
    else:
        config_path = os.path.join(OBFUSCATION_ROOT, "Swingft_config.json")
        print(f"기본 설정 파일 경로: {config_path}")
    
    os.chdir(enc_path)
    cmd = ["python3", "run_Swingft_Encryption.py", obf_project_dir, config_path]
    print(f"실행 명령: {' '.join(cmd)}")
    
    print("문자열 암호화 적용 중...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("문자열 암호화 적용 완료!")
        if result.stdout.strip():
            print(f"암호화 출력:\n{result.stdout}")
    else:
        print(f"문자열 암호화 적용 실패: {result.stderr}")
        if result.stdout.strip():
            print(f"암호화 출력:\n{result.stdout}")
    
    os.chdir(original_dir)
    print("=== String Encryption 완료 ===\n")

    enc_end = time.time()
    print("encryption: ", enc_end - deadcode_end)

    # 동적 함수 호출
    if not skip_cfg:
        print("=== CFG (Control Flow Graph) 래핑 시작 ===")
        print(f"CFG 대상 디렉토리: {obf_project_dir}")
        print(f"CFG 대상 디렉토리 존재 여부: {os.path.exists(obf_project_dir)}")
        
        # CFG 처리를 위한 안전한 복사본 생성
        obf_project_dir_cfg = os.path.join(os.path.dirname(obf_project_dir), "cfg")
        print(f"CFG 작업용 복사본 생성: {obf_project_dir} -> {obf_project_dir_cfg}")
        shutil.copytree(obf_project_dir, obf_project_dir_cfg)
        
        cfg_path = os.path.join(OBFUSCATION_ROOT, "CFG")
        print(f"CFG 도구 경로: {cfg_path}")
        print(f"CFG 도구 경로 존재 여부: {os.path.exists(cfg_path)}")
        os.chdir(cfg_path)
        
        # run_pipeline.py 사용 (과거 방식)
        cmd = ["python3", "run_pipeline.py", "--src", obf_project_dir_cfg, "--dst", obf_project_dir, 
               "--perfile-inject", "--overwrite", "--debug", "--include-packages", "--no-skip-ui"]
        print(f"CFG 명령어 실행: {' '.join(cmd)}")
        print(f"현재 작업 디렉토리: {os.getcwd()}")
        run_command(cmd)
        
        # CFG 작업 완료 후 cfg 폴더 정리
        if os.path.exists(obf_project_dir_cfg):
            print(f"CFG 작업용 복사본 정리: {obf_project_dir_cfg}")
            shutil.rmtree(obf_project_dir_cfg)
            print("CFG 작업용 복사본 정리 완료")
        
        os.chdir(original_dir)
        print("=== CFG 래핑 완료 ===")
    else:
        print("CFG (동적 함수) 단계가 건너뜀")

    cfg_end = time.time()
    print("cfg: ", cfg_end - enc_end)

    # 디버깅용 코드 제거
    print("=== 디버그 심볼 삭제 시작 ===")
    remove_debug_symbol(obf_project_dir)
    print("=== 디버그 심볼 삭제 완료 ===")

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
    
    # 파일 삭제
    print("임시 파일들을 삭제합니다...")
    remove_files(obf_project_dir, obf_project_dir_cfg)
    
    print("STAGE 3 완료!")
    print("=" * 50)
    print("전체 난독화 파이프라인 완료!")
    print("=" * 50)

def obf_pipeline(original_project_dir, obf_project_dir, skip_cfg=False): 
    """전체 난독화 파이프라인 실행"""
    # 스크립트 파일의 디렉토리를 기준으로 경로 설정
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    OBFUSCATION_ROOT = SCRIPT_DIR

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
    parser.add_argument("--stage", type=int, choices=[1, 2, 3], help="실행할 스테이지 (1: AST 분석, 2: 매핑&난독화, 3: 정리)")
    parser.add_argument("--encryption-only", action="store_true", help="암호화 관련 로그만 출력")
    parser.add_argument("--skip-cfg", action="store_true", help="CFG (동적 함수) 로그를 건너뜀")

    args = parser.parse_args()
    
    original_project_dir = args.input
    obf_project_dir = args.output

    # 스크립트 파일의 디렉토리를 기준으로 경로 설정
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    OBFUSCATION_ROOT = SCRIPT_DIR

    # 로그 제어 옵션 체크
    encryption_only = getattr(sys.modules[__name__], '_encryption_only', False)
    skip_cfg = getattr(args, 'skip_cfg', False)

    # Stage별 복사 정책
    # - 전체 실행(or stage 미지정) 또는 Stage 1에서만 원본을 출력으로 복사
    # - Stage 2/3에서는 절대 복사하지 않음 (이전 단계 결과를 유지)
    is_full_run = args.stage is None
    should_copy = is_full_run or args.stage == 1

    if should_copy:
        # output 디렉토리 준비 (없으면 생성)
        if not os.path.exists(obf_project_dir):
            if not encryption_only or "encryption" in str(args.stage):
                print(f"새로운 output 디렉토리를 생성합니다: {obf_project_dir}")
            os.makedirs(obf_project_dir, exist_ok=True)
        else:
            if not encryption_only or "encryption" in str(args.stage):
                print(f"기존 output 디렉토리가 존재합니다: {obf_project_dir}")

        # 프로젝트 복사 (항상 새로 복사, 기존 파일 위에 덮어쓰기)
        if not encryption_only or "encryption" in str(args.stage):
            print(f"프로젝트를 복사합니다: {original_project_dir} -> {obf_project_dir}")
        shutil.copytree(original_project_dir, obf_project_dir, dirs_exist_ok=True, ignore=ignore_git_and_build)
    else:
        print("[INFO] Stage 2/3 실행: 원본→출력 복사 건너뜀 (이전 결과 유지)")

    if args.stage == 1:
        if not encryption_only:
            print("STAGE 1만 실행합니다... (AST 분석)")
        stage1_ast_analysis(original_project_dir, obf_project_dir)
    elif args.stage == 2:
        if not encryption_only:
            print("STAGE 2만 실행합니다... (매핑&난독화)")
        stage2_obfuscation(original_project_dir, obf_project_dir, OBFUSCATION_ROOT, skip_cfg)
    elif args.stage == 3:
        if not encryption_only:
            print("STAGE 3만 실행합니다... (정리)")
        obf_project_dir_cfg = os.path.join(os.path.dirname(obf_project_dir), "cfg")
        stage3_cleanup(obf_project_dir, obf_project_dir_cfg)
    else:
        if not encryption_only:
            print("전체 파이프라인을 실행합니다...")
        obf_pipeline(original_project_dir, obf_project_dir, skip_cfg)

def ignore_git_and_build(dir, files):
    """Git 폴더와 빌드 아티팩트 제외"""
    ignored = set()
    for file in files:
        if file == '.git' or file.startswith('.') and file in ['.DS_Store', '.build', 'DerivedData']:
            ignored.add(file)
    return ignored


if __name__ == "__main__":
    main()
