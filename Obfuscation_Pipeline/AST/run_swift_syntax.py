import os
import subprocess
import shutil

def run_command(cmd):
    subprocess.run(cmd, capture_output=True, text=True)

def run_swift_syntax():
    target_project_dir = "./AST/SyntaxAST"
    target_name = "SyntaxAST"
    
    original_dir = os.getcwd()
    swift_list_dir = "./swift_file_list.txt"
    swift_list_dir = os.path.join(original_dir, swift_list_dir)

    external_list_dir = "./AST/output/external_file_list.txt"
    external_list_dir = os.path.join(original_dir, external_list_dir)

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

    run_command(["swift", "run", target_name, swift_list_dir, external_list_dir])
