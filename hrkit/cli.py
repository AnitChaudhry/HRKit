"""hrkit CLI: argparse-based orchestrator for serve/scan/init/migrate/status/activity."""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from . import branding
from . import config as cfg
from . import db as dbmod
from . import frontmatter as fm
from .models import Activity


def _safe_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join(c if c not in bad else "_" for c in str(name))
    return cleaned.strip().rstrip(".") or "item"


def _fpath(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def _resolve_root(path_arg: str | None) -> Path | None:
    """Return a workspace root from --path or auto-discovery."""
    if path_arg:
        return Path(path_arg).resolve()
    return cfg.find_workspace()


def _die(msg: str) -> int:
    """Print error to stderr and return exit code 1."""
    print(f"error: {msg}", file=sys.stderr)
    return 1


def _now_iso() -> str:
    """Return current time in IST, ISO-8601, seconds precision."""
    return datetime.now(cfg.IST).isoformat(timespec="seconds")


# ---- command handlers ------------------------------------------------------

def cmd_serve(args: argparse.Namespace) -> int:
    """Start the HTTP server (lazy import of server module)."""
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found; run `hrkit init <dir>` or pass --path")
    try:
        from . import server
    except ImportError as e:
        return _die(f"server module not available: {e}")
    try:
        server.run(args.host, args.port, root, open_browser=not args.no_browser)
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        return _die(f"serve failed: {e}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan the workspace and print summary as JSON (lazy import of scanner)."""
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found; run `hrkit init <dir>` or pass --path")
    try:
        from . import scanner
    except ImportError as e:
        return _die(f"scanner module not available: {e}")
    try:
        conn = dbmod.open_db(cfg.db_path(root))
        summary = scanner.scan(conn, root)
        print(json.dumps(summary, indent=2, default=str))
    except Exception as e:
        return _die(f"scan failed: {e}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a new workspace/department/position/task folder with a getset.md."""
    target = Path(args.path).resolve()
    typ = args.type
    if typ not in cfg.TYPES:
        return _die(f"invalid --type {typ!r}; must be one of {cfg.TYPES}")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _die(f"could not create {target}: {e}")
    marker = target / cfg.MARKER
    if marker.exists():
        return _die(f"{marker} already exists; refusing to overwrite")
    name = args.name or target.name
    fm_dict = _initial_frontmatter(typ, name, args)
    body = _initial_body(typ, name)
    try:
        marker.write_text(fm.dump(fm_dict, body), encoding="utf-8")
    except OSError as e:
        return _die(f"could not write {marker}: {e}")
    print(f"created {typ}: {target}")
    print(f"  marker: {marker}")
    return 0


def _initial_frontmatter(typ: str, name: str, args: argparse.Namespace) -> dict:
    """Build the default frontmatter dict for a given node type."""
    if typ == "workspace":
        return {"type": "workspace", "name": name, "theme": "dark", "port": cfg.DEFAULT_PORT}
    if typ == "department":
        return {"type": "department", "name": name, "description": ""}
    if typ == "position":
        return {
            "type": "position", "name": name, "role": "",
            "columns": list(cfg.DEFAULT_COLUMNS),
            "statuses": list(cfg.DEFAULT_STATUSES),
        }
    # task
    status = getattr(args, "status", None) or "applied"
    return {
        "type": "task", "name": name, "status": status,
        "priority": "medium", "tags": [], "created": _now_iso(),
    }


def _initial_body(typ: str, name: str) -> str:
    """Build a minimal markdown body under the frontmatter."""
    return f"# {name}\n"


def cmd_migrate(args: argparse.Namespace) -> int:
    """Run schema/data migration on the current workspace."""
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found; run `hrkit init <dir>` or pass --path")
    try:
        from . import migrate as migmod
    except ImportError as e:
        return _die(f"migrate module not available: {e}")
    try:
        result = migmod.run(root, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        return _die(f"migrate failed: {e}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print workspace root, DB path, existence, and stats if DB exists."""
    root = _resolve_root(args.path)
    if root is None:
        print("workspace: <none>")
        print("hint: cd into a workspace or run `hrkit init <dir>`")
        return 0
    db_file = cfg.db_path(root)
    print(f"workspace: {root}")
    print(f"db_path:   {db_file}")
    print(f"db_exists: {db_file.exists()}")
    if db_file.exists():
        try:
            conn = dbmod.open_db(db_file)
            s = dbmod.stats(conn)
            print("stats:")
            print(json.dumps(s, indent=2, default=str))
        except Exception as e:
            return _die(f"could not read stats: {e}")
    return 0


def cmd_activity(args: argparse.Namespace) -> int:
    """Print the last 20 activity entries as a compact table."""
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found; run `hrkit init <dir>` or pass --path")
    db_file = cfg.db_path(root)
    if not db_file.exists():
        return _die(f"no database at {db_file}; run `hrkit scan` first")
    try:
        conn = dbmod.open_db(db_file)
        rows = dbmod.recent_activity(conn, 20)
    except Exception as e:
        return _die(f"could not read activity: {e}")
    if not rows:
        print("(no activity yet)")
        return 0
    hdr = ("AT", "ACTION", "FOLDER", "FROM", "TO", "ACTOR")
    table = [hdr] + [(
        str(r.get("at", ""))[:19],
        str(r.get("action", ""))[:12],
        str(r.get("folder_name", ""))[:24],
        str(r.get("from_value", ""))[:12],
        str(r.get("to_value", ""))[:12],
        str(r.get("actor", ""))[:10],
    ) for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(hdr))]
    for i, row in enumerate(table):
        line = "  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row))
        print(line)
        if i == 0:
            print("  ".join("-" * w for w in widths))
    return 0


# ---- hiring helper commands -----------------------------------------------

def _open_db(root: Path):
    return dbmod.open_db(cfg.db_path(root))


def _ensure_scanned(conn, root: Path) -> None:
    from . import scanner
    scanner.scan(conn, root)


def _rescan_and_get(conn, root: Path, folder_path: Path):
    _ensure_scanned(conn, root)
    return dbmod.folder_by_path(conn, _fpath(folder_path))


def cmd_task_new(args: argparse.Namespace) -> int:
    pos_path = Path(args.parent_position).resolve()
    marker = pos_path / cfg.MARKER
    if not marker.exists():
        return _die(f"position marker not found: {marker}")
    pos_fm, _ = fm.parse(marker.read_text(encoding="utf-8"))
    if pos_fm.get("type") != "position":
        return _die(f"{pos_path} is not a position (type={pos_fm.get('type')!r})")
    task_dir = pos_path / _safe_name(args.name)
    task_dir.mkdir(parents=True, exist_ok=True)
    task_marker = task_dir / cfg.MARKER
    if task_marker.exists() and not args.overwrite:
        return _die(f"{task_marker} already exists (use --overwrite)")
    now = _now_iso()
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    task_fm: dict = {
        "type": "task",
        "name": args.name,
        "status": args.status or "applied",
        "priority": args.priority or "medium",
        "tags": tags,
        "created": now,
        "updated": now,
    }
    optional = {
        "email": args.email, "phone": args.phone, "source": args.source,
        "received": args.received, "thread_url": args.thread_url,
        "role": args.role or pos_fm.get("role", ""),
        "department": args.department,
        "next_action": args.next_action,
        "subject": args.subject,
    }
    for k, v in optional.items():
        if v:
            task_fm[k] = v
    body = args.body or ""
    task_marker.write_text(fm.dump(task_fm, body), encoding="utf-8")
    root = cfg.find_workspace(pos_path)
    fid = None
    if root:
        try:
            conn = _open_db(root)
            f = _rescan_and_get(conn, root, task_dir)
            if f:
                fid = f.id
                dbmod.log_activity(conn, Activity(
                    folder_id=f.id, action="created", to_value="task",
                    actor=args.actor or "user",
                    note=args.note or f"task created under {pos_path.name}",
                ))
        except Exception as e:
            print(f"warning: activity log failed: {e}", file=sys.stderr)
    print(json.dumps({
        "ok": True, "path": str(task_dir), "marker": str(task_marker),
        "folder_id": fid,
    }))
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found")
    conn = _open_db(root)
    fid = None
    if args.folder_path:
        fp = Path(args.folder_path).resolve()
        f = dbmod.folder_by_path(conn, _fpath(fp))
        if f is None:
            f = _rescan_and_get(conn, root, fp)
        if f:
            fid = f.id
    dbmod.log_activity(conn, Activity(
        folder_id=fid, action=args.action,
        from_value=args.from_value or "",
        to_value=args.to_value or "",
        actor=args.actor or "ai",
        note=args.note or "",
    ))
    print(json.dumps({"ok": True, "folder_id": fid, "action": args.action}))
    return 0


def cmd_match_position(args: argparse.Namespace) -> int:
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found")
    subject = (args.subject or "").lower()
    dept_filter = (args.department or "").lower()
    ranked = []
    for path in root.rglob(cfg.MARKER):
        rel = path.relative_to(root)
        if len(rel.parts) != 3:
            continue
        try:
            fm_dict, _ = fm.parse(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if fm_dict.get("type") != "position":
            continue
        if dept_filter and dept_filter not in path.parent.parent.name.lower():
            continue
        keywords = fm_dict.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = []
        score = 0
        matched = []
        for kw in keywords:
            kws = str(kw).lower().strip()
            if kws and kws in subject:
                score += len(kws)
                matched.append(kws)
        pos_name = str(fm_dict.get("name") or path.parent.name)
        if not keywords and pos_name.lower() in subject:
            score = len(pos_name)
            matched.append(pos_name.lower())
        ranked.append({
            "score": score,
            "name": pos_name,
            "path": _fpath(path.parent),
            "matched": matched,
        })
    ranked.sort(key=lambda r: -r["score"])
    best = ranked[0] if ranked and ranked[0]["score"] > 0 else None
    print(json.dumps({"match": best, "candidates": ranked[:5]}, indent=2))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    import urllib.request
    dest = Path(args.to)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(args.url)
        with urllib.request.urlopen(req, timeout=args.timeout) as r, open(dest, "wb") as w:
            w.write(r.read())
    except Exception as e:
        return _die(f"download failed: {e}")
    print(json.dumps({"ok": True, "path": str(dest), "size": dest.stat().st_size}))
    return 0


def cmd_position_new(args: argparse.Namespace) -> int:
    dept_path = Path(args.department).resolve()
    dept_marker = dept_path / cfg.MARKER
    if not dept_path.exists():
        dept_path.mkdir(parents=True, exist_ok=True)
    if not dept_marker.exists():
        dept_fm = {"type": "department", "name": dept_path.name, "description": ""}
        dept_marker.write_text(fm.dump(dept_fm, f"# {dept_path.name}\n"), encoding="utf-8")
    pos_dir = dept_path / _safe_name(args.name)
    pos_dir.mkdir(parents=True, exist_ok=True)
    marker = pos_dir / cfg.MARKER
    if marker.exists() and not args.overwrite:
        return _die(f"{marker} already exists (use --overwrite)")
    kw = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]
    pos_fm: dict = {
        "type": "position",
        "name": args.name,
        "role": args.role or args.name,
        "columns": list(cfg.DEFAULT_COLUMNS),
        "statuses": list(cfg.DEFAULT_STATUSES),
        "keywords": kw,
    }
    body = f"# {args.name}\n"
    marker.write_text(fm.dump(pos_fm, body), encoding="utf-8")
    root = cfg.find_workspace(pos_dir)
    fid = None
    if root:
        try:
            conn = _open_db(root)
            f = _rescan_and_get(conn, root, pos_dir)
            if f:
                fid = f.id
                dbmod.log_activity(conn, Activity(
                    folder_id=f.id, action="created", to_value="position",
                    actor=args.actor or "ai",
                    note=f"position '{args.name}' created",
                ))
        except Exception as e:
            print(f"warning: activity log failed: {e}", file=sys.stderr)
    print(json.dumps({"ok": True, "path": str(pos_dir), "folder_id": fid}))
    return 0


def cmd_evaluation(args: argparse.Namespace) -> int:
    task_path = Path(args.task_path).resolve()
    marker = task_path / cfg.MARKER
    if not marker.exists():
        return _die(f"{marker} not found")
    fm_dict, body = fm.parse(marker.read_text(encoding="utf-8"))
    if fm_dict.get("type") != "task":
        return _die(f"{task_path} is not a task (type={fm_dict.get('type')!r})")
    now = _now_iso()
    fm_dict["overall_score"] = args.score
    fm_dict["recommendation"] = args.rec
    fm_dict["evaluated"] = now
    fm_dict["rule_version"] = args.rule_version or 1
    fm_dict["updated"] = now
    if args.next_action:
        fm_dict["next_action"] = args.next_action
    if args.flags:
        flags = [f.strip() for f in args.flags.split("|") if f.strip()]
        fm_dict["flags"] = flags
    marker.write_text(fm.dump(fm_dict, body), encoding="utf-8")
    root = cfg.find_workspace(task_path)
    fid = None
    if root:
        try:
            conn = _open_db(root)
            f = _rescan_and_get(conn, root, task_path)
            if f:
                fid = f.id
                dbmod.log_activity(conn, Activity(
                    folder_id=f.id, action="evaluated",
                    to_value=args.rec, actor="ai",
                    note=f"score {args.score}/10",
                ))
        except Exception as e:
            print(f"warning: activity log failed: {e}", file=sys.stderr)
    print(json.dumps({
        "ok": True, "path": str(task_path),
        "score": args.score, "rec": args.rec,
        "folder_id": fid,
    }))
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """Load canonical sample data into the workspace (idempotent)."""
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found; run `init <dir>` first or pass --path")
    try:
        from . import seeds
    except ImportError as e:
        return _die(f"seeds module not available: {e}")
    try:
        conn = _open_db(root)
        counts = seeds.load_sample_data(conn)
    except Exception as e:
        return _die(f"seed failed: {e}")
    print(json.dumps({"ok": True, "inserted": counts}, indent=2))
    return 0


def cmd_migrate_folders(args: argparse.Namespace) -> int:
    """Migrate legacy .getset/uploads/employee/<id>/ files into employees/<EMP-CODE>/documents/."""
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found; run `init <dir>` first or pass --path")
    try:
        from . import employee_fs
    except ImportError as e:
        return _die(f"employee_fs module not available: {e}")
    conn = _open_db(root)
    plan = employee_fs.plan_migration(conn, root)
    summary = {
        "total_documents": len(plan),
        "to_move": sum(1 for e in plan if not e.get("reason")),
        "skipped": sum(1 for e in plan if e.get("reason")),
    }
    print(json.dumps({"plan": plan, "summary": summary}, indent=2, default=str))
    if args.dry_run:
        print("dry-run only; pass --apply to copy files and update document.file_path",
              file=sys.stderr)
        return 0
    if not args.apply:
        print("refusing to mutate; pass --apply explicitly", file=sys.stderr)
        return 1
    result = employee_fs.apply_migration(conn, root, plan)
    print(json.dumps({"applied": result}, indent=2, default=str))
    if result.get("errors"):
        return 2
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    """Show or set BYOK settings (AI provider, AI key, Composio key, app name)."""
    root = _resolve_root(args.path)
    if root is None:
        return _die("no workspace found; run `init <dir>` first or pass --path")
    conn = _open_db(root)
    updates: dict[str, str] = {}
    for key in cfg.SETTINGS_KEYS:
        cli_attr = key.lower()
        val = getattr(args, cli_attr, None)
        if val:
            updates[key] = val
    if updates:
        branding.set_settings(conn, updates)
        print(json.dumps({"ok": True, "updated": list(updates.keys())}, indent=2))
        return 0
    # No updates — show current effective settings (with secrets masked).
    out = {
        "APP_NAME": branding.app_name(),
        "AI_PROVIDER": branding.ai_provider(conn),
        "AI_MODEL": branding.ai_model(conn),
        "AI_BASE_URL": branding.ai_base_url(conn),
        "AI_API_KEY": branding.masked(branding.ai_api_key(conn)),
        "COMPOSIO_API_KEY": branding.masked(branding.composio_api_key(conn)),
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    task_path = Path(args.task_path).resolve()
    marker = task_path / cfg.MARKER
    if not marker.exists():
        return _die(f"{marker} not found")
    fm_dict, body = fm.parse(marker.read_text(encoding="utf-8"))
    if fm_dict.get("type") != "task":
        return _die(f"{task_path} is not a task")
    old = str(fm_dict.get("status", ""))
    now = _now_iso()
    fm_dict["status"] = args.status
    fm_dict["updated"] = now
    if args.status in ("hired", "rejected"):
        fm_dict["closed"] = now
    marker.write_text(fm.dump(fm_dict, body), encoding="utf-8")
    root = cfg.find_workspace(task_path)
    if root:
        try:
            conn = _open_db(root)
            f = _rescan_and_get(conn, root, task_path)
            if f:
                dbmod.log_activity(conn, Activity(
                    folder_id=f.id, action="status_change",
                    from_value=old, to_value=args.status,
                    actor=args.actor or "user",
                    note=args.note or "",
                ))
        except Exception as e:
            print(f"warning: activity log failed: {e}", file=sys.stderr)
    print(json.dumps({"ok": True, "from": old, "to": args.status}))
    return 0


# ---- parser ----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser and all subparsers."""
    name = branding.app_name()
    slug = branding.app_slug()
    p = argparse.ArgumentParser(prog=slug,
                                description=f"{name} — local HR app. White-label via APP_NAME env var.")
    p.add_argument("--version", action="version", version=f"{slug} {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--host", default=cfg.DEFAULT_HOST)
    s.add_argument("--port", type=int, default=cfg.DEFAULT_PORT)
    s.add_argument("--no-browser", action="store_true", help="do not open a browser")
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("scan", help="rescan the workspace into the DB cache")
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("init", help="scaffold a new workspace/department/position/task")
    s.add_argument("path", help="folder to create / initialize")
    s.add_argument("--type", default="workspace", choices=list(cfg.TYPES))
    s.add_argument("--name", help="display name (defaults to folder name)")
    s.add_argument("--status", help="initial status (tasks only)", default=None)
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("migrate", help="run migrations on the workspace")
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_migrate)

    s = sub.add_parser("status", help="print workspace + DB summary")
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("activity", help="show recent activity")
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.set_defaults(func=cmd_activity)

    s = sub.add_parser("task-new", help="create a new task under a position")
    s.add_argument("--parent-position", required=True, help="path to the position folder")
    s.add_argument("--name", required=True)
    s.add_argument("--status", default=None)
    s.add_argument("--priority", default=None)
    s.add_argument("--tags", default="", help="comma-separated")
    s.add_argument("--email", default=None)
    s.add_argument("--phone", default=None)
    s.add_argument("--source", default=None)
    s.add_argument("--subject", default=None)
    s.add_argument("--received", default=None)
    s.add_argument("--thread-url", default=None)
    s.add_argument("--role", default=None)
    s.add_argument("--department", default=None)
    s.add_argument("--next-action", default=None)
    s.add_argument("--body", default=None)
    s.add_argument("--actor", default="user")
    s.add_argument("--note", default=None)
    s.add_argument("--overwrite", action="store_true")
    s.set_defaults(func=cmd_task_new)

    s = sub.add_parser("log", help="log an activity entry to the DB")
    s.add_argument("--path", help="workspace root")
    s.add_argument("--action", required=True)
    s.add_argument("--folder-path", default=None)
    s.add_argument("--from-value", default=None)
    s.add_argument("--to-value", default=None)
    s.add_argument("--actor", default="ai")
    s.add_argument("--note", default=None)
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("match-position", help="match a subject line against known positions")
    s.add_argument("--path", help="workspace root")
    s.add_argument("--subject", required=True)
    s.add_argument("--department", default=None)
    s.set_defaults(func=cmd_match_position)

    s = sub.add_parser("download", help="download a URL to a local path")
    s.add_argument("--url", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--timeout", type=int, default=60)
    s.set_defaults(func=cmd_download)

    s = sub.add_parser("position-new", help="create a new position under a department")
    s.add_argument("--department", required=True, help="path to the department folder")
    s.add_argument("--name", required=True)
    s.add_argument("--role", default=None)
    s.add_argument("--keywords", default="", help="comma-separated keywords for subject matching")
    s.add_argument("--actor", default="ai")
    s.add_argument("--overwrite", action="store_true")
    s.set_defaults(func=cmd_position_new)

    s = sub.add_parser("evaluation", help="write evaluation result to a task + log activity")
    s.add_argument("--task-path", required=True)
    s.add_argument("--score", type=float, required=True)
    s.add_argument("--rec", required=True, help="Strong hire | Shortlist | Borderline | Reject")
    s.add_argument("--rule-version", type=int, default=1)
    s.add_argument("--next-action", default=None)
    s.add_argument("--flags", default=None, help="pipe-separated list")
    s.set_defaults(func=cmd_evaluation)

    s = sub.add_parser("set-status", help="change a task status and log the transition")
    s.add_argument("--task-path", required=True)
    s.add_argument("--status", required=True)
    s.add_argument("--actor", default="user")
    s.add_argument("--note", default=None)
    s.set_defaults(func=cmd_set_status)

    s = sub.add_parser("seed", help="load canonical sample HR data into the workspace")
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser(
        "migrate-folders",
        help="copy legacy uploads into the per-employee folder layout (Phase 1.7)",
    )
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.add_argument("--dry-run", action="store_true",
                   help="print the plan and exit without copying anything")
    s.add_argument("--apply", action="store_true",
                   help="actually copy files and update document.file_path")
    s.set_defaults(func=cmd_migrate_folders)

    s = sub.add_parser("settings", help="show or set BYOK settings (no args = show)")
    s.add_argument("--path", help="workspace root (defaults to auto-discovery)")
    s.add_argument("--app-name", dest="app_name", help="white-label app name")
    s.add_argument("--ai-provider", dest="ai_provider", choices=["openrouter", "upfyn"])
    s.add_argument("--ai-api-key", dest="ai_api_key")
    s.add_argument("--ai-model", dest="ai_model")
    s.add_argument("--composio-api-key", dest="composio_api_key")
    s.set_defaults(func=cmd_settings)

    # ---- HR module CLI commands -------------------------------------------
    _register_module_commands(sub)

    return p


def _register_module_commands(subparsers) -> None:
    """Discover every module in hrkit.modules and add its CLI subcommands.

    Each module exports MODULE['cli'] = [(name, build_parser_fn, handle_fn)].
    handle_fn is wrapped so it receives (args, conn) instead of just args.
    """
    import importlib
    try:
        from . import modules as mods_pkg
    except ImportError:
        return
    for mod_name in getattr(mods_pkg, "__all__", []):
        try:
            mod = importlib.import_module(f"hrkit.modules.{mod_name}")
        except ImportError:
            continue
        module_dict = getattr(mod, "MODULE", None)
        if not module_dict:
            continue
        for entry in module_dict.get("cli", []) or []:
            cmd_name, build_fn, handle_fn = entry
            sp = subparsers.add_parser(cmd_name, help=f"({mod_name}) {cmd_name}")
            sp.add_argument("--path", help="workspace root (defaults to auto-discovery)")
            try:
                build_fn(sp)
            except Exception as exc:
                print(f"warning: {mod_name}.{cmd_name} parser setup failed: {exc}",
                      file=sys.stderr)
            sp.set_defaults(func=_make_module_runner(handle_fn))


def _make_module_runner(handle_fn):
    """Wrap a module's handle_fn(args, conn) into a CLI command(args)->int."""
    def _runner(args: argparse.Namespace) -> int:
        root = _resolve_root(getattr(args, "path", None))
        if root is None:
            return _die("no workspace found; run `init <dir>` first or pass --path")
        conn = _open_db(root)
        try:
            return int(handle_fn(args, conn) or 0)
        except Exception as exc:
            return _die(str(exc))
    return _runner


def main(argv: list[str] | None = None) -> int:
    """Program entry: build parser, dispatch to handler, return exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
