import os
import sys
import subprocess
import shutil
from swingft_cli.validator import check_permissions
from swingft_cli.config import load_config_or_exit, summarize_risks_and_confirm, extract_rule_patterns

def print_banner():
    print("=" * 50)
    print("Swingft CLI - Swift Obfuscation Tool")
    print("=" * 50)

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
    
    print(f"[CLI] 원본 보호 확인 완료")
    print(f"[CLI] 입력: {input_path}")
    print(f"[CLI] 출력: {output_path}")

    print("Start Swingft ...")
    print_banner()

    # 파이프라인 경로 확인
    pipeline_path = os.path.join(os.getcwd(), "Obfuscation_Pipeline", "obf_pipeline.py")
    if not os.path.exists(pipeline_path):
        print(f"Error: Obfuscation Pipeline not found at {pipeline_path}")
        sys.exit(1)

    # Config 파일 처리
    config_path = None
    if getattr(args, 'config', None) is not None:
        if isinstance(args.config, str) and args.config.strip():
            config_path = args.config.strip()
        else:
            config_path = 'swingft_config.json'
        if not os.path.exists(config_path):
            print(f"Error: {config_path} not found. You can generate a sample file using the --json option.")
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
            print(f"[config] 설정 복사본 생성 실패: {copy_error}")
            sys.exit(1)
        print(f"[config] 원본 설정 유지: {abs_src}")
        print(f"[config] 작업용 설정 복사본 사용: {working_path}")
        working_config_path = working_path

    # 1단계: 전처리 (exception_list.json 생성)
    print(f"[pipeline] 1단계: 전처리 시작")
    try:
        result = subprocess.run([
            "python3", pipeline_path, 
            args.input, 
            args.output,
            "--stage", "preprocessing"
        ], cwd=os.path.join(os.getcwd(), "Obfuscation_Pipeline"), 
           text=True, timeout=600)
        
        if result.returncode != 0:
            print(f"[pipeline] 1단계 실행 실패 (exit code: {result.returncode})")
            if result.stderr:
                print(f"[pipeline] stderr: {result.stderr}")
            sys.exit(1)
        
        print("[pipeline] 1단계 완료: exception_list.json 생성됨")
        if result.stdout:
            print(f"[pipeline] stdout: {result.stdout}")
            
    except subprocess.TimeoutExpired:
        print("[pipeline] 1단계 실행 시간 초과 (10분)")
        sys.exit(1)
    except Exception as e:
        print(f"[pipeline] 1단계 실행 오류: {e}")
        sys.exit(1)

    # Config 검증 및 LLM 분석
    if working_config_path:
        print(f"[config] 설정 검증 시작: {working_config_path}")
        try:
            config = load_config_or_exit(working_config_path)
            patterns = extract_rule_patterns(config)
            
            # LLM 분석 및 사용자 확인
            auto_yes = getattr(args, 'yes', False)
            summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
            
            print("[config] 설정 검증 완료")
        except Exception as e:
            print(f"[config] 설정 검증 실패: {e}")
            sys.exit(1)

    # 2단계: 최종 난독화
    print(f"[pipeline] 2단계: 최종 난독화 시작")
    try:
        # Working config를 환경변수로 전달
        env = os.environ.copy()
        if working_config_path:
            env["SWINGFT_WORKING_CONFIG"] = os.path.abspath(working_config_path)
        
        result = subprocess.run([
            "python3", pipeline_path, 
            args.input, 
            args.output,
            "--stage", "final"
        ], cwd=os.path.join(os.getcwd(), "Obfuscation_Pipeline"), 
           text=True, timeout=1200, env=env)
        
        if result.returncode != 0:
            print(f"[pipeline] 2단계 실행 실패 (exit code: {result.returncode})")
            if result.stderr:
                print(f"[pipeline] stderr: {result.stderr}")
            if result.stdout:
                print(f"[pipeline] stdout: {result.stdout}")
            sys.exit(1)
        
        print("[pipeline] 2단계 완료: 최종 난독화 완료")
        if result.stdout:
            print(f"[pipeline] stdout: {result.stdout}")
            
    except subprocess.TimeoutExpired:
        print("[pipeline] 2단계 실행 시간 초과 (20분)")
        sys.exit(1)
    except Exception as e:
        print(f"[pipeline] 2단계 실행 오류: {e}")
        sys.exit(1)

    print("난독화 완료!")