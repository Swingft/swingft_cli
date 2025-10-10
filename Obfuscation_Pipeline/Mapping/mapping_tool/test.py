import json
from pathlib import Path

# 파일 경로
BASE = Path("/Users/lanian/Desktop/S_DEV/identifier_obfuscation")
map_path = BASE / "mapping_result.json"
all_path = BASE / "all_identifier.json"

# 로드
with open(map_path, encoding="utf-8") as f:
    mapping = json.load(f)
with open(all_path, encoding="utf-8") as f:
    all_ids = json.load(f)

# all_identifier가 dict 구조일 때(flatten 필요)
if isinstance(all_ids, dict):
    flat = []
    for v in all_ids.values():
        flat.extend(v)
    all_ids_set = set(flat)
elif isinstance(all_ids, list):
    all_ids_set = set(all_ids)
else:
    raise TypeError("all_identifier.json 형식을 인식하지 못했습니다 (dict 또는 list 여야 함)")

# mapping_result에서 target/replacement 각각 꺼내기
# mapping 형식: { kind: [ {"target": str, "replacement": str}, ... ], ... }
if not isinstance(mapping, dict):
    raise TypeError("mapping_result.json은 kind별 dict 형태여야 합니다")

targets = []  # (kind, name)
repls = []    # (kind, name)
for kind, entries in mapping.items():
    if not isinstance(entries, list):
        continue
    for e in entries:
        if not isinstance(e, dict):
            continue
        t = e.get("target")
        r = e.get("replacement")
        if isinstance(t, str):
            targets.append((kind, t))
        if isinstance(r, str):
            repls.append((kind, r))

# 교차 비교: target vs all_ids, replacement vs all_ids
overlap_targets = [(k, n) for (k, n) in targets if n in all_ids_set]
overlap_repls = [(k, n) for (k, n) in repls if n in all_ids_set]

print(f"[CHECK] all_identifier 총 {len(all_ids_set)}개")
print(f"[CHECK] mapping targets {len(targets)}개, replacements {len(repls)}개")

print(f"\n[타겟 겹침] 총 {len(overlap_targets)}개")
for kind, name in overlap_targets[:50]:
    print(f"- {kind}: {name}")

print(f"\n[대체명 겹침(replacement)] 총 {len(overlap_repls)}개")
for kind, name in overlap_repls[:50]:
    print(f"- {kind}: {name}")

# 결과를 파일로도 저장 (선택)
out = {
    "overlap_targets": [{"kind": k, "name": n} for k, n in overlap_targets],
    "overlap_replacements": [{"kind": k, "name": n} for k, n in overlap_repls],
}
with open(BASE / "overlaps.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n세부 결과 저장: {BASE / 'overlaps.json'}")