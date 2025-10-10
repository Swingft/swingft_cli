import os  
import json
import subprocess
from Mapping.collect_identifiers import collect_identifiers

SWIFT_FILE_PATH = []

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)

def mapping():
    os.makedirs("./Mapping/output/", exist_ok=True)
    identifier_info, all_identifier_info = collect_identifiers()
    identifier_path = "./Mapping/output/identifier.json"
    with open(identifier_path, "w", encoding="utf-8") as f:
        json.dump(identifier_info, f, indent=2, ensure_ascii=False, default=list)
    
    external_name_path = "/AST/output/external_name.txt"
    if os.path.exists(external_name_path):
        with open(external_name_path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name not in all_identifier_info:
                    all_identifier_info.append(name)

    all_identifier_path = "./Mapping/output/all_identifier.json"
    with open(all_identifier_path, "w", encoding="utf-8") as f:
        json.dump(all_identifier_info, f, indent=2, ensure_ascii=False, default=list)
    
    cmd = ["python3", "./Mapping/mapping_tool/service_mapping.py", 
           "--targets", "./Mapping/output/identifier.json", 
           "--exclude", "./Mapping/output/all_identifier.json",
           "--output", "./mapping_result.json", 
           "--pool-dir", "./Mapping/mapping_tool/name_clusters_opt", 
           "--index-dir", "./Mapping/mapping_tool/name_clusters_opt",
           "--seed", "42",
           "--cluster-threshold", "0.2"]
    run_command(cmd)

    # 식별자 매핑 정보 가공
    mapping_file_path = "./mapping_result.json"
    if os.path.exists(mapping_file_path):
        with open(mapping_file_path, "r", encoding="utf-8") as f:
            mapping_data = json.load(f)
        
        result = []
        for _, items in mapping_data.items():
            for item in items:
                result.append(item)

        save_file_path = "./mapping_result_s.json"
        with open(save_file_path, "w", encoding="utf-8") as f:  
            json.dump(result, f, indent=2, ensure_ascii=False)