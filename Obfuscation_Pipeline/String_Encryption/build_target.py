
import sys
import re
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import Optional, List, Dict, Set, Union


HEX_ID_RE = re.compile(r'\b[0-9A-Fa-f]{24}\b')

def read_text(p: Path) -> str:
    return p.read_text(encoding='utf-8', errors='ignore')

def find_section(text: str, isa_name: str) -> str:
    
    pat = re.compile(
        r'/\*\s*Begin\s+' + re.escape(isa_name) + r'\s+section\s*\*/(.*?)/\*\s*End\s+' + re.escape(isa_name) + r'\s+section\s*\*/',
        re.DOTALL
    )
    m = pat.search(text)
    return m.group(1) if m else ''

def parse_blocks(section_text: str) -> List[str]:
   
    i, n = 0, len(section_text)
    blocks: List[str] = []
    while i < n:
        m = HEX_ID_RE.search(section_text, i)
        if not m:
            break
        eq = section_text.find('=', m.end())
        if eq == -1:
            break
        brace = section_text.find('{', eq)
        if brace == -1:
            break
        depth, j = 1, brace + 1
        while j < n and depth > 0:
            c = section_text[j]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            j += 1
        blocks.append(section_text[m.start():j])
        i = j
    return blocks

def kv(block_text: str, key: str) -> Optional[str]:
    m = re.search(r'\b' + re.escape(key) + r'\s*=\s*(.*?);', block_text, re.DOTALL)
    return m.group(1).strip() if m else None

def parse_list(field_text: Optional[str]) -> List[str]:
    if not field_text:
        return []
    m = re.search(r'\((.*?)\)', field_text, re.DOTALL)
    if not m:
        return []
    return HEX_ID_RE.findall(m.group(1))

def sstr(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    return v

class PBXProj:
    def __init__(self, proj_dir: Path):
      
        self.proj_dir = proj_dir
        self.source_root = proj_dir.parent.resolve()
        self.pbxproj_path = proj_dir / "project.pbxproj"
        text = read_text(self.pbxproj_path)

        
        self.sec_native_target = find_section(text, "PBXNativeTarget")
        self.sec_sources_phase = find_section(text, "PBXSourcesBuildPhase")
        self.sec_build_file    = find_section(text, "PBXBuildFile")
        self.sec_file_ref      = find_section(text, "PBXFileReference")
        self.sec_group         = find_section(text, "PBXGroup")
        self.sec_proj          = find_section(text, "PBXProject")

       
        self.native_targets = self._parse_native_targets()
        self.sources_phases = self._parse_sources_phases()
        self.build_files    = self._parse_build_files()
        self.file_refs      = self._parse_file_refs()
        self.groups, self.main_group = self._parse_groups_and_main()

       
        self.parent_of: Dict[str, str] = {}
        for gid, g in self.groups.items():
            for cid in g.get("children", []):
                self.parent_of[cid] = gid

    def _parse_native_targets(self) -> Dict[str, Dict[str, object]]:
        out: Dict[str, Dict[str, object]] = {}
        for blk in parse_blocks(self.sec_native_target):
            ids = HEX_ID_RE.findall(blk)
            if not ids:
                continue
            oid = ids[0]
            out[oid] = {
                "name": sstr(kv(blk, 'name')),
                "buildPhases": parse_list(kv(blk, 'buildPhases')),
            }
        return out

    def _parse_sources_phases(self) -> Dict[str, Dict[str, List[str]]]:
        out: Dict[str, Dict[str, List[str]]] = {}
        for blk in parse_blocks(self.sec_sources_phase):
            ids = HEX_ID_RE.findall(blk)
            if not ids:
                continue
            oid = ids[0]
            out[oid] = {"files": parse_list(kv(blk, 'files'))}
        return out

    def _parse_build_files(self) -> Dict[str, Dict[str, Optional[str]]]:
        out: Dict[str, Dict[str, Optional[str]]] = {}
        for blk in parse_blocks(self.sec_build_file):
            ids = HEX_ID_RE.findall(blk)
            if not ids:
                continue
            oid = ids[0]
            m = re.search(r'\bfileRef\s*=\s*([0-9A-Fa-f]{24})\b', blk)
            out[oid] = {"fileRef": m.group(1) if m else None}
        return out

    def _parse_file_refs(self) -> Dict[str, Dict[str, Optional[str]]]:
        out: Dict[str, Dict[str, Optional[str]]] = {}
        for blk in parse_blocks(self.sec_file_ref):
            ids = HEX_ID_RE.findall(blk)
            if not ids:
                continue
            oid = ids[0]
            out[oid] = {
                "id": oid, 
                "name": sstr(kv(blk, 'name')),
                "path": sstr(kv(blk, 'path')),
                "sourceTree": sstr(kv(blk, 'sourceTree')),
                "lastKnownFileType": sstr(kv(blk, 'lastKnownFileType')),
                "explicitFileType": sstr(kv(blk, 'explicitFileType')),
            }
        return out

    def _parse_groups_and_main(self):
        main_group: Optional[str] = None
        m = re.search(r'\bmainGroup\s*=\s*([0-9A-Fa-f]{24})\b', self.sec_proj)
        if m:
            main_group = m.group(1)

        groups: Dict[str, Dict[str, object]] = {}
        for blk in parse_blocks(self.sec_group):
            ids = HEX_ID_RE.findall(blk)
            if not ids:
                continue
            oid = ids[0]
            groups[oid] = {
                "id": oid,
                "name": sstr(kv(blk, 'name')),
                "path": sstr(kv(blk, 'path')),
                "sourceTree": sstr(kv(blk, 'sourceTree')),
                "children": parse_list(kv(blk, 'children')),
            }
        return groups, main_group

   
    def _group_chain_to_root(self, start_id: str) -> List[str]:
        parts: List[str] = []
        gid = self.parent_of.get(start_id)
        seen: Set[str] = set()
        while gid and gid not in seen:
            seen.add(gid)
            g = self.groups.get(gid)
            if not g:
                break
            gp = g.get("path")
            if gp:
                parts.append(gp)  
            gid = self.parent_of.get(gid)
        parts.reverse()
        return parts

    def resolve_file_path(self, file_ref_id: str) -> Optional[Path]:
        fr = self.file_refs.get(file_ref_id)
        if not fr:
            return None
        path = fr.get("path") or fr.get("name")
        if not path:
            return None
        p = Path(path)
        if p.is_absolute():
            return p.resolve()

        st = (fr.get("sourceTree") or "").strip()
        if st in ("<group>", "GROUP", ""):
            chain = self._group_chain_to_root(file_ref_id)
            rel = (Path(*chain) / p) if chain else p
            return (self.source_root / rel).resolve()
        elif st in ("SOURCE_ROOT",):
            return (self.source_root / p).resolve()
        else:
            
            return None

 
    def list_target_to_swift_paths(self) -> Dict[str, List[str]]:
        result: Dict[str, Set[str]] = {}
        for _, tgt in self.native_targets.items():
            tname = (tgt.get("name") or "").strip()  
            if not tname:
                continue
            acc = result.setdefault(tname, set())
            for phase_id in (tgt.get("buildPhases") or []):  
                sp = self.sources_phases.get(phase_id)
                if not sp:
                    continue
                for bfid in sp.get("files", []):
                    bf = self.build_files.get(bfid)
                    if not bf or not bf.get("fileRef"):
                        continue
                    fr_id = bf["fileRef"]  
                    fr = self.file_refs.get(fr_id)
                    if not fr:
                        continue
                    
                    ftype = (fr.get("lastKnownFileType") or fr.get("explicitFileType") or "")
                    fname = (fr.get("name") or fr.get("path") or "")
                    if not fname:
                        continue
                    if not (fname.endswith(".swift") or ftype == "sourcecode.swift"):
                        continue
                    resolved = self.resolve_file_path(fr_id)  
                    if resolved:
                        acc.add(str(resolved))
        return {k: sorted(v) for k, v in result.items()}

def find_projects_in_workspace(xcworkspace: Path) -> List[Path]:
    wsdata = xcworkspace / "contents.xcworkspacedata"
    if not wsdata.exists():
        return []
    try:
        root = ET.fromstring(read_text(wsdata))
    except Exception:
        return []
    projects: List[Path] = []
    for fr in root.findall(".//FileRef"):
        loc = fr.get("location") or ""
        p = loc.split(":", 1)[1] if ":" in loc else loc
        p = p.strip()
        if p.endswith(".xcodeproj"):
            proj_path = (xcworkspace.parent / p).resolve()
            if proj_path.exists():
                projects.append(proj_path)
    return projects



def _expand_and_dedupe(candidates: List[Path]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    for c in candidates:
        c = Path(c)
        if c.suffix == ".xcworkspace":
            try:
                for pj in find_projects_in_workspace(c):
                    pj = Path(pj).resolve()
                    if pj not in seen:
                        seen.add(pj)
                        out.append(pj)
            except Exception:
               
                continue
        elif c.suffix == ".xcodeproj":
            pj = c.resolve()
            if pj not in seen:
                seen.add(pj)
                out.append(pj)
    return out

def _recursive_project_search(root: Path) -> List[Path]:
    workspaces = list(root.rglob("*.xcworkspace"))
    projects   = list(root.rglob("*.xcodeproj"))
    return _expand_and_dedupe([*(Path(p) for p in workspaces),
                               *(Path(p) for p in projects)])

def find_projects(input_path: Union[str, Path]) -> List[Path]:
    p = Path(input_path).resolve()

    candidates: List[Path] = []
    if p.is_file() and p.suffix in (".xcworkspace", ".xcodeproj"):
        candidates = [p]
    elif p.is_dir():
        candidates = list(p.glob("*.xcworkspace")) + list(p.glob("*.xcodeproj"))

    expanded = _expand_and_dedupe([Path(c) for c in candidates])
    if expanded:
        return expanded

    deep = _recursive_project_search(p)
    if deep:
        return deep

    raise FileNotFoundError(f"No .xcworkspace or .xcodeproj found under: {p}")

def main():
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    projects = find_projects(root)

    merged: Dict[str, Set[str]] = {}
    for proj in projects:
        pbx = PBXProj(proj)
        m = pbx.list_target_to_swift_paths()
        for tname, paths in m.items():
            merged.setdefault(tname, set()).update(paths)

    out: Dict[str, List[str]] = {k: sorted(v) for k, v in merged.items()}
    Path("targets_swift_paths.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    #print("[ok] targets_swift_paths.json 작성 완료")

if __name__ == "__main__":
    main()

