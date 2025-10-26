#!/usr/bin/env python3
"""Migrate existing timelapse video files into per-set directories.

Rules:
  - Videos currently in BASE_DIR root (e.g. /mnt/legotimelapse) are scanned.
  - Filenames expected format: "<set_number> - <set_name> - <phase>.mp4" or with "-temp.mp4" suffix.
  - Destination: BASE_DIR/media/<set_number>/timelapse/<filename>.mp4
  - If source ends with -temp.mp4 and target filename WITHOUT -temp does NOT exist, remove -temp.
  - If removing -temp would conflict (target exists), keep -temp when moving. If that also conflicts, append unique numeric suffix.
  - Non -temp files moved as-is; if conflict, append unique numeric suffix.

Extras:
  - Dry-run mode (default) prints actions without performing them. Use --apply to execute.
  - Uses sets.yml to validate known set ids; unknown set ids are still migrated but flagged.
  - Provides summary at end.

Usage:
  python migrate_timelapse_videos.py --base /mnt/legotimelapse --apply
"""
from __future__ import annotations
import os
import re
import argparse
import shutil
import yaml
from typing import List, Tuple, Dict

FILENAME_PATTERN = re.compile(r"^(?P<set>[^\-]+?) - (?P<name>.+?) - (?P<phase>[^\-]+?)(-temp)?\.mp4$")
PHASES = {"build","build1","build2","build3","install_lights","disassemble","sort"}

def load_sets(sets_path: str) -> Dict[str, str]:
    if not os.path.exists(sets_path):
        print(f"[WARN] sets.yml not found at {sets_path}; proceeding without validation.")
        return {}
    try:
        with open(sets_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        sets_list = data.get('sets', [])
        mapping = {}
        for entry in sets_list:
            sid = str(entry.get('id')).strip()
            name = str(entry.get('name','')).strip()
            if sid and name:
                mapping[sid] = name
        return mapping
    except Exception as e:
        print(f"[WARN] Failed to parse sets.yml: {e}; continuing without validation.")
        return {}

def find_root_videos(base_dir: str) -> List[str]:
    entries = []
    try:
        for fn in os.listdir(base_dir):
            if fn.lower().endswith('.mp4'):
                full = os.path.join(base_dir, fn)
                if os.path.isfile(full):
                    entries.append(full)
    except FileNotFoundError:
        print(f"[ERROR] Base directory {base_dir} not found.")
    return entries

def parse_filename(path: str) -> Tuple[str,str,str,bool]:
    name = os.path.basename(path)
    m = FILENAME_PATTERN.match(name)
    if not m:
        raise ValueError(f"Unrecognized filename pattern: {name}")
    set_id = m.group('set').strip()
    set_name = m.group('name').strip()
    phase = m.group('phase').strip()
    has_temp = name.endswith('-temp.mp4')
    return set_id, set_name, phase, has_temp

def ensure_dir(path: str, apply: bool):
    if apply:
        os.makedirs(path, exist_ok=True)

def unique_path(dest: str) -> str:
    if not os.path.exists(dest):
        return dest
    root, ext = os.path.splitext(dest)
    i = 1
    while True:
        candidate = f"{root}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1

def plan_move(src: str, set_id: str, phase: str, has_temp: bool, base_dir: str) -> Tuple[str,str,bool]:
    dest_dir = os.path.join(base_dir, 'media', set_id, 'timelapse')
    # Proposed canonical filename (without -temp)
    basename = os.path.basename(src)
    if has_temp:
        cleaned = basename.replace('-temp.mp4', '.mp4')
    else:
        cleaned = basename
    cleaned_path = os.path.join(dest_dir, cleaned)
    # If source had -temp and cleaned target does not exist, drop -temp.
    if has_temp and not os.path.exists(cleaned_path):
        return dest_dir, cleaned, True  # rename (drop -temp)
    # Otherwise keep original basename.
    final_name = basename
    final_path = os.path.join(dest_dir, final_name)
    if os.path.exists(final_path):
        # conflict - generate unique
        unique = os.path.basename(unique_path(final_path))
        return dest_dir, unique, True  # rename to unique
    return dest_dir, final_name, has_temp and '-temp' in final_name  # rename only if we kept -temp? treat as False

def migrate(base_dir: str, sets_map: Dict[str,str], apply: bool) -> Dict[str,int]:
    stats = {"moved":0,"skipped":0,"errors":0,"renamed":0}
    videos = find_root_videos(base_dir)
    if not videos:
        print("[INFO] No .mp4 files found in base directory.")
        return stats
    print(f"[INFO] Found {len(videos)} candidate video files in {base_dir}")
    for src in videos:
        try:
            set_id, set_name_in_file, phase, has_temp = parse_filename(src)
        except ValueError as e:
            print(f"[SKIP] {src}: {e}")
            stats["skipped"] += 1
            continue
        known = set_id in sets_map
        if not known:
            print(f"[WARN] Set id {set_id} from filename not found in sets.yml")
        dest_dir, dest_name, renamed = plan_move(src, set_id, phase, has_temp, base_dir)
        dest_path = os.path.join(dest_dir, dest_name)
        action = "MOVE" if apply else "DRY-RUN" 
        print(f"[{action}] {os.path.basename(src)} -> {dest_path}{' (renamed)' if renamed and dest_name != os.path.basename(src) else ''}")
        if apply:
            try:
                ensure_dir(dest_dir, apply=True)
                shutil.move(src, dest_path)
                stats["moved"] += 1
                if renamed and dest_name != os.path.basename(src):
                    stats["renamed"] += 1
            except Exception as e:
                print(f"[ERROR] Failed moving {src} -> {dest_path}: {e}")
                stats["errors"] += 1
    return stats

def main():
    parser = argparse.ArgumentParser(description="Migrate legacy timelapse videos to per-set directories.")
    parser.add_argument('--base', default='/mnt/legotimelapse', help='Base directory hosting captures and videos')
    parser.add_argument('--sets', default='sets.yml', help='Path to sets.yml')
    parser.add_argument('--apply', action='store_true', help='Perform moves (omit for dry-run)')
    args = parser.parse_args()
    sets_map = load_sets(args.sets)
    if sets_map:
        print(f"[INFO] Loaded {len(sets_map)} sets from {args.sets}")
    stats = migrate(args.base, sets_map, apply=args.apply)
    print("\n=== SUMMARY ===")
    for k,v in stats.items():
        print(f"{k}: {v}")
    if not args.apply:
        print("\nRun again with --apply to execute the moves.")

if __name__ == '__main__':
    main()
