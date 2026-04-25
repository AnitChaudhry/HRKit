"""One-time migration: flatten current candidates into the 3-level hierarchy."""
from __future__ import annotations
import shutil
from pathlib import Path

from .frontmatter import dump as fm_dump
from .frontmatter import parse as fm_parse


DEPARTMENT_NAME = "Legal-Lawyers"
POSITION_NAME = "Junior Litigation Associate"

_CANDIDATES = [
    "Anushka Singh", "Ashu Jain", "Charly", "Dhruv Jaiswal",
    "Harishmita Singh", "Ismat Chughtai", "Mohit Kumar", "Nirbhay Gupta",
    "Puja Kumari", "Rahul Lakhera", "Rehan Alam", "Sudeep Pandey",
    "Syed Khafiz Zamar", "Yogesh Arora", "Yugant Parihar Bisht",
]


def _say(msg: str, dry: bool) -> None:
    prefix = "[dry-run] " if dry else ""
    print(prefix + msg)


def _write_department(dept: Path, dry: bool) -> None:
    marker = dept / "getset.md"
    if marker.exists():
        _say(f"department marker exists: {marker}", dry)
        return
    fm = {
        "type": "department",
        "name": DEPARTMENT_NAME,
        "description": "Sample department for legal/litigation hiring.",
    }
    body = f"# {DEPARTMENT_NAME}\n\nDepartment for all legal/litigation hiring.\n"
    _say(f"write {marker}", dry)
    if not dry:
        marker.write_text(fm_dump(fm, body), encoding="utf-8")


def _write_position(pos_dir: Path, dry: bool) -> None:
    if pos_dir.exists():
        _say(f"position dir exists: {pos_dir}", dry)
    else:
        _say(f"mkdir {pos_dir}", dry)
        if not dry:
            pos_dir.mkdir(parents=True, exist_ok=True)

    marker = pos_dir / "getset.md"
    if marker.exists():
        _say(f"position marker exists: {marker}", dry)
        return
    fm = {
        "type": "position",
        "name": POSITION_NAME,
        "role": POSITION_NAME,
        "department": DEPARTMENT_NAME,
        "columns": ["applied", "screening", "interview", "offer", "closed"],
        "statuses": ["applied", "screening", "interview", "offer", "hired", "rejected"],
        "source": "Email",
        "rule_file": "../Rule.md",
    }
    body = (
        f"# {POSITION_NAME}\n\n"
        "Sample Junior Litigation Associate role. "
        "See `../Rule.md` for the evaluation rubric.\n"
    )
    _say(f"write {marker}", dry)
    if not dry:
        marker.write_text(fm_dump(fm, body), encoding="utf-8")


def _move_candidate(src: Path, pos_dir: Path, dry: bool) -> tuple[bool, str]:
    dest = pos_dir / src.name
    if dest.exists():
        return False, "already at destination"
    _say(f"move {src} -> {dest}", dry)
    if not dry:
        shutil.move(str(src), str(dest))
    return True, ""


def _convert_candidate_md(folder: Path, dry: bool) -> tuple[bool, str]:
    cand = folder / "candidate.md"
    getset = folder / "getset.md"
    if getset.exists() and not cand.exists():
        return False, "already converted"
    if not cand.exists():
        return False, "no candidate.md"
    if getset.exists() and cand.exists():
        return False, "both candidate.md and getset.md present"

    try:
        text = cand.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"read error: {e}"
    fm, body = fm_parse(text)

    new_fm = {"type": "task"}
    for k, v in fm.items():
        if k == "type":
            continue
        new_fm[k] = v
    if "name" not in new_fm:
        new_fm["name"] = folder.name

    _say(f"write {getset} (converted from candidate.md)", dry)
    _say(f"delete {cand}", dry)
    if not dry:
        getset.write_text(fm_dump(new_fm, body), encoding="utf-8")
        cand.unlink()
    return True, ""


def run(root: Path, *, dry_run: bool = False) -> dict:
    root = Path(root).resolve()
    dept = root / DEPARTMENT_NAME
    pos_dir = dept / POSITION_NAME

    result: dict = {
        "department_created": DEPARTMENT_NAME,
        "position_created": POSITION_NAME,
        "candidates_moved": [],
        "candidate_md_converted": [],
        "skipped": [],
        "dry_run": dry_run,
    }

    if not dept.exists():
        result["skipped"].append((DEPARTMENT_NAME, "department folder missing"))
        return result

    _write_department(dept, dry_run)
    _write_position(pos_dir, dry_run)

    for name in _CANDIDATES:
        legacy = dept / name
        already = pos_dir / name
        if already.exists():
            if legacy.exists() and legacy.resolve() != already.resolve():
                result["skipped"].append((name, "exists at both legacy and new path"))
            converted, reason = _convert_candidate_md(already, dry_run)
            if converted:
                result["candidate_md_converted"].append(name)
            elif reason and reason != "already converted":
                result["skipped"].append((name, reason))
            continue
        if not legacy.exists():
            result["skipped"].append((name, "not found"))
            continue

        moved, reason = _move_candidate(legacy, pos_dir, dry_run)
        if moved:
            result["candidates_moved"].append(name)
        else:
            result["skipped"].append((name, reason or "move failed"))
            continue

        target = pos_dir / name if not dry_run else legacy
        converted, reason = _convert_candidate_md(target, dry_run)
        if converted:
            result["candidate_md_converted"].append(name)
        elif reason and reason not in ("already converted",):
            result["skipped"].append((name, reason))

    return result


if __name__ == "__main__":
    import argparse, json, sys
    ap = argparse.ArgumentParser(description="One-shot legacy data migration to 3-level hierarchy")
    ap.add_argument("--root", default=".", help="workspace root (default: cwd)")
    ap.add_argument("--dry-run", action="store_true", help="print actions without touching disk")
    args = ap.parse_args()
    out = run(Path(args.root), dry_run=args.dry_run)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
