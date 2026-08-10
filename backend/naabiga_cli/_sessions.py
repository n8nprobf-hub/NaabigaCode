"""Extrait de naabiga_cli/main.py — _sessions.

Généré par extraction AST; main.py importe et ré-exporte ces symboles.
"""

from typing import Optional
from pathlib import Path
import time as _time
from datetime import datetime
from naabiga_cli.config import get_naabiga_home
import json
import os
import shutil
import subprocess
import sys

def _relative_time(ts) -> str:
    """Format a timestamp as relative time (e.g., '2h ago', 'yesterday')."""
    if not ts:
        return "?"
    delta = _time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    if delta < 172800:
        return "yesterday"
    if delta < 604800:
        return f"{int(delta / 86400)}d ago"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

def _has_any_provider_configured() -> bool:
    """Check if at least one inference provider is usable."""
    from naabiga_cli.config import get_env_path, load_config
    from naabiga_cli.auth import get_auth_status

    # Determine whether Naabiga itself has been explicitly configured (model
    # in config that isn't the hardcoded default). Used below to gate external
    # tool credentials (Claude Code, Codex CLI) that shouldn't silently skip
    # the setup wizard on a fresh install.
    from naabiga_cli.config import DEFAULT_CONFIG

    _DEFAULT_MODEL = DEFAULT_CONFIG.get("model", "")
    cfg = load_config()
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        _model_name = (model_cfg.get("default") or "").strip()
    elif isinstance(model_cfg, str):
        _model_name = model_cfg.strip()
    else:
        _model_name = ""
    _has_naabiga_config = _model_name and _model_name != _DEFAULT_MODEL

    # Check env vars (may be set by .env or shell).
    # OPENAI_BASE_URL alone counts — local models (vLLM, llama.cpp, etc.)
    # often don't require an API key.
    from naabiga_cli.auth import PROVIDER_REGISTRY

    # Collect all provider env vars
    provider_env_vars = {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "OPENAI_BASE_URL",
    }
    for pconfig in PROVIDER_REGISTRY.values():
        if pconfig.auth_type == "api_key":
            provider_env_vars.update(pconfig.api_key_env_vars)
    if any(os.getenv(v) for v in provider_env_vars):
        return True

    # Check .env file for keys
    env_file = get_env_path()
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:]
                key, _, val = line.partition("=")
                val = val.strip().strip("'\"")
                if key.strip() in provider_env_vars and val:
                    return True
        except Exception:
            pass

    # Check provider-specific auth fallbacks (for example, Copilot via gh auth).
    try:
        for provider_id, pconfig in PROVIDER_REGISTRY.items():
            if pconfig.auth_type != "api_key":
                continue
            status = get_auth_status(provider_id)
            if status.get("logged_in"):
                return True
    except Exception:
        pass

    # Check for Nous Portal OAuth credentials
    auth_file = get_naabiga_home() / "auth.json"
    if auth_file.exists():
        try:
            import json

            auth = json.loads(auth_file.read_text())
            active = auth.get("active_provider")
            if active:
                status = get_auth_status(active)
                if status.get("logged_in"):
                    return True
        except Exception:
            pass

    # Check config.yaml — if model is a dict with an explicit provider set,
    # the user has gone through setup (fresh installs have model as a plain
    # string).  Also covers custom endpoints that store api_key/base_url in
    # config rather than .env.
    if isinstance(model_cfg, dict):
        cfg_provider = (model_cfg.get("provider") or "").strip()
        cfg_base_url = (model_cfg.get("base_url") or "").strip()
        cfg_api_key = (model_cfg.get("api_key") or "").strip()
        if cfg_provider or cfg_base_url or cfg_api_key:
            return True

    # Check for Claude Code OAuth credentials (~/.claude/.credentials.json)
    # Only count these if Naabiga has been explicitly configured — Claude Code
    # being installed doesn't mean the user wants Naabiga to use their tokens.
    if _has_naabiga_config:
        try:
            from agent.anthropic_adapter import (
                read_claude_code_credentials,
                is_claude_code_token_valid,
            )

            creds = read_claude_code_credentials()
            if creds and (
                is_claude_code_token_valid(creds) or creds.get("refreshToken")
            ):
                return True
        except Exception:
            pass

    return False

def _session_browse_picker(sessions: list) -> Optional[str]:
    """Interactive curses-based session browser with live search filtering.

    Returns the selected session ID, or None if cancelled.
    Uses curses (not simple_term_menu) to avoid the ghost-duplication rendering
    bug in tmux/iTerm when arrow keys are used.
    """
    if not sessions:
        print("No sessions found.")
        return None

    # Try curses-based picker first
    try:
        import curses

        result_holder = [None]

        def _format_row(s, max_x):
            """Format a session row for display."""
            title = (s.get("title") or "").strip()
            preview = (s.get("preview") or "").strip()
            source = s.get("source", "")[:6]
            last_active = _relative_time(s.get("last_active"))
            sid = s["id"][:18]

            # Adaptive column widths based on terminal width
            # Layout: [arrow 3] [title/preview flexible] [active 12] [src 6] [id 18]
            fixed_cols = 3 + 12 + 6 + 18 + 6  # arrow + active + src + id + padding
            name_width = max(20, max_x - fixed_cols)

            if title:
                name = title[:name_width]
            elif preview:
                name = preview[:name_width]
            else:
                name = sid

            return f"{name:<{name_width}}  {last_active:<10}  {source:<5} {sid}"

        def _match(s, query):
            """Check if a session matches the search query (case-insensitive)."""
            q = query.lower()
            return (
                q in (s.get("title") or "").lower()
                or q in (s.get("preview") or "").lower()
                or q in s.get("id", "").lower()
                or q in (s.get("source") or "").lower()
            )

        def _curses_browse(stdscr):
            curses.curs_set(0)
            if curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_GREEN, -1)  # selected
                curses.init_pair(2, curses.COLOR_YELLOW, -1)  # header
                curses.init_pair(3, curses.COLOR_CYAN, -1)  # search
                curses.init_pair(4, 8 if curses.COLORS > 8 else curses.COLOR_WHITE, -1)  # dim

            cursor = 0
            scroll_offset = 0
            search_text = ""
            filtered = list(sessions)

            while True:
                stdscr.clear()
                max_y, max_x = stdscr.getmaxyx()
                if max_y < 5 or max_x < 40:
                    # Terminal too small
                    try:
                        stdscr.addstr(0, 0, "Terminal too small")
                    except curses.error:
                        pass
                    stdscr.refresh()
                    stdscr.getch()
                    return

                # Header line
                if search_text:
                    header = f"  Browse sessions — filter: {search_text}█"
                    header_attr = curses.A_BOLD
                    if curses.has_colors():
                        header_attr |= curses.color_pair(3)
                else:
                    header = "  Browse sessions — ↑↓ navigate  Enter select  Type to filter  Esc quit"
                    header_attr = curses.A_BOLD
                    if curses.has_colors():
                        header_attr |= curses.color_pair(2)
                try:
                    stdscr.addnstr(0, 0, header, max_x - 1, header_attr)
                except curses.error:
                    pass

                # Column header line
                fixed_cols = 3 + 12 + 6 + 18 + 6
                name_width = max(20, max_x - fixed_cols)
                col_header = f"   {'Title / Preview':<{name_width}}  {'Active':<10}  {'Src':<5} {'ID'}"
                try:
                    dim_attr = (
                        curses.color_pair(4) if curses.has_colors() else curses.A_DIM
                    )
                    stdscr.addnstr(1, 0, col_header, max_x - 1, dim_attr)
                except curses.error:
                    pass

                # Compute visible area
                visible_rows = max_y - 4  # header + col header + blank + footer
                visible_rows = max(visible_rows, 1)

                # Clamp cursor and scroll
                if not filtered:
                    try:
                        msg = "  No sessions match the filter."
                        stdscr.addnstr(3, 0, msg, max_x - 1, curses.A_DIM)
                    except curses.error:
                        pass
                else:
                    if cursor >= len(filtered):
                        cursor = len(filtered) - 1
                    cursor = max(cursor, 0)
                    if cursor < scroll_offset:
                        scroll_offset = cursor
                    elif cursor >= scroll_offset + visible_rows:
                        scroll_offset = cursor - visible_rows + 1

                    for draw_i, i in enumerate(
                        range(
                            scroll_offset,
                            min(len(filtered), scroll_offset + visible_rows),
                        )
                    ):
                        y = draw_i + 3
                        if y >= max_y - 1:
                            break
                        s = filtered[i]
                        arrow = " → " if i == cursor else "   "
                        row = arrow + _format_row(s, max_x - 3)
                        attr = curses.A_NORMAL
                        if i == cursor:
                            attr = curses.A_BOLD
                            if curses.has_colors():
                                attr |= curses.color_pair(1)
                        try:
                            stdscr.addnstr(y, 0, row, max_x - 1, attr)
                        except curses.error:
                            pass

                # Footer
                footer_y = max_y - 1
                if filtered:
                    footer = f"  {cursor + 1}/{len(filtered)} sessions"
                    if len(filtered) < len(sessions):
                        footer += f" (filtered from {len(sessions)})"
                else:
                    footer = f"  0/{len(sessions)} sessions"
                try:
                    stdscr.addnstr(
                        footer_y,
                        0,
                        footer,
                        max_x - 1,
                        curses.color_pair(4) if curses.has_colors() else curses.A_DIM,
                    )
                except curses.error:
                    pass

                stdscr.refresh()
                key = stdscr.getch()

                if key in {curses.KEY_UP,}:
                    if filtered:
                        cursor = (cursor - 1) % len(filtered)
                elif key in {curses.KEY_DOWN,}:
                    if filtered:
                        cursor = (cursor + 1) % len(filtered)
                elif key in {curses.KEY_ENTER, 10, 13}:
                    if filtered:
                        result_holder[0] = filtered[cursor]["id"]
                    return
                elif key == 27:  # Esc
                    if search_text:
                        # First Esc clears the search
                        search_text = ""
                        filtered = list(sessions)
                        cursor = 0
                        scroll_offset = 0
                    else:
                        # Second Esc exits
                        return
                elif key in {curses.KEY_BACKSPACE, 127, 8}:
                    if search_text:
                        search_text = search_text[:-1]
                        if search_text:
                            filtered = [s for s in sessions if _match(s, search_text)]
                        else:
                            filtered = list(sessions)
                        cursor = 0
                        scroll_offset = 0
                elif key == ord("q") and not search_text:
                    return
                elif 32 <= key <= 126:
                    # Printable character → add to search filter
                    search_text += chr(key)
                    filtered = [s for s in sessions if _match(s, search_text)]
                    cursor = 0
                    scroll_offset = 0

        curses.wrapper(_curses_browse)
        return result_holder[0]

    except Exception:
        pass

    # Fallback: numbered list (Windows without curses, etc.)
    print("\n  Browse sessions  (enter number to resume, q to cancel)\n")
    for i, s in enumerate(sessions):
        title = (s.get("title") or "").strip()
        preview = (s.get("preview") or "").strip()
        label = title or preview or s["id"]
        if len(label) > 50:
            label = label[:47] + "..."
        last_active = _relative_time(s.get("last_active"))
        src = s.get("source", "")[:6]
        print(f"  {i + 1:>3}. {label:<50}  {last_active:<10}  {src}")

    while True:
        try:
            val = input(f"\n  Select [1-{len(sessions)}]: ").strip()
            if not val or val.lower() in {"q", "quit", "exit"}:
                return None
            idx = int(val) - 1
            if 0 <= idx < len(sessions):
                return sessions[idx]["id"]
            print(f"  Invalid selection. Enter 1-{len(sessions)} or q to cancel.")
        except ValueError:
            print("  Invalid input. Enter a number or q to cancel.")
        except (KeyboardInterrupt, EOFError):
            print()
            return None

def _resolve_last_session(source: str = "cli") -> Optional[str]:
    """Look up the most recently-used session ID for a source."""
    db = None
    try:
        from naabiga_state import SessionDB

        db = SessionDB()
        sessions = db.search_sessions(source=source, limit=1)
        return sessions[0]["id"] if sessions else None
    except Exception:
        pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    return None

def _probe_container(cmd: list, backend: str, via_sudo: bool = False):
    """Run a container inspect probe, returning the CompletedProcess.

    Catches TimeoutExpired specifically for a human-readable message;
    all other exceptions propagate naturally.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        label = f"sudo {backend}" if via_sudo else backend
        print(
            f"Error: timed out waiting for {label} to respond.\n"
            f"The {backend} daemon may be unresponsive or starting up.",
            file=sys.stderr,
        )
        sys.exit(1)

def _exec_in_container(container_info: dict, cli_args: list):
    """Replace the current process with a command inside the managed container.

    Probes whether sudo is needed (rootful containers), then os.execvp
    into the container. On success the Python process is replaced entirely
    and the container's exit code becomes the process exit code (OS semantics).
    On failure, OSError propagates naturally.

    Args:
        container_info: dict with backend, container_name, exec_user, naabiga_bin
        cli_args: the original CLI arguments (everything after 'naabiga')
    """

    backend = container_info["backend"]
    container_name = container_info["container_name"]
    exec_user = container_info["exec_user"]
    naabiga_bin = container_info["naabiga_bin"]

    runtime = shutil.which(backend)
    if not runtime:
        print(
            f"Error: {backend} not found on PATH. Cannot route to container.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rootful containers (NixOS systemd service) are invisible to unprivileged
    # users — Podman uses per-user namespaces, Docker needs group access.
    # Probe whether the runtime can see the container; if not, try via sudo.
    sudo_path = None
    probe = _probe_container(
        [runtime, "inspect", "--format", "ok", container_name],
        backend,
    )
    if probe.returncode != 0:
        sudo_path = shutil.which("sudo")
        if sudo_path:
            probe2 = _probe_container(
                [sudo_path, "-n", runtime, "inspect", "--format", "ok", container_name],
                backend,
                via_sudo=True,
            )
            if probe2.returncode != 0:
                print(
                    f"Error: container '{container_name}' not found via {backend}.\n"
                    f"\n"
                    f"The container is likely running as root. Your user cannot see it\n"
                    f"because {backend} uses per-user namespaces. Grant passwordless\n"
                    f"sudo for {backend} — the -n (non-interactive) flag is required\n"
                    f"because a password prompt would hang or break piped commands.\n"
                    f"\n"
                    f"On NixOS:\n"
                    f"\n"
                    f"  security.sudo.extraRules = [{{\n"
                    f'    users = [ "{os.getenv("USER", "your-user")}" ];\n'
                    f'    commands = [{{ command = "{runtime}"; options = [ "NOPASSWD" ]; }}];\n'
                    f"  }}];\n"
                    f"\n"
                    f"Or run: sudo naabiga {' '.join(cli_args)}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            print(
                f"Error: container '{container_name}' not found via {backend}.\n"
                f"The container may be running under root. Try: sudo naabiga {' '.join(cli_args)}",
                file=sys.stderr,
            )
            sys.exit(1)

    is_tty = sys.stdin.isatty()
    tty_flags = ["-it"] if is_tty else ["-i"]

    env_flags = []
    for var in ("TERM", "COLORTERM", "LANG", "LC_ALL"):
        val = os.environ.get(var)
        if val:
            env_flags.extend(["-e", f"{var}={val}"])

    cmd_prefix = [sudo_path, "-n", runtime] if sudo_path else [runtime]
    exec_cmd = (
        cmd_prefix
        + ["exec"]
        + tty_flags
        + ["-u", exec_user]
        + env_flags
        + [container_name, naabiga_bin]
        + cli_args
    )

    os.execvp(exec_cmd[0], exec_cmd)

def _resolve_session_by_name_or_id(name_or_id: str) -> Optional[str]:
    """Resolve a session name (title) or ID to a session ID.

    - If it looks like a session ID (contains underscore + hex), try direct lookup first.
    - Otherwise, treat it as a title and use resolve_session_by_title (auto-latest).
    - Falls back to the other method if the first doesn't match.
    - If the resolved session is a compression root, follow the chain forward
      to the latest continuation. Users who remember the old root ID (e.g.
      from an exit summary printed before the bug fix, or from notes) get
      resumed at the live tip instead of a stale parent with no messages.
    """
    try:
        from naabiga_state import SessionDB

        db = SessionDB()

        # Try as exact session ID first
        session = db.get_session(name_or_id)
        resolved_id: Optional[str] = None
        if session:
            resolved_id = session["id"]
        else:
            # Try as title (with auto-latest for lineage)
            resolved_id = db.resolve_session_by_title(name_or_id)

        if resolved_id:
            # Project forward through compression chain so resumes land on
            # the live tip instead of a dead compressed parent.
            try:
                resolved_id = db.get_compression_tip(resolved_id) or resolved_id
            except Exception:
                pass

        db.close()
        return resolved_id
    except Exception:
        pass
    return None

def _read_tui_active_session_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        sid = str(data.get("session_id") or "").strip()
        return sid or None
    except Exception:
        return None

def _print_tui_exit_summary(
    session_id: Optional[str], active_session_file: Optional[str] = None
) -> None:
    """Print a shell-visible epilogue after TUI exits."""
    target = (
        _read_tui_active_session_file(active_session_file)
        or session_id
        or _resolve_last_session(source="tui")
    )
    if not target:
        return

    db = None
    try:
        from naabiga_state import SessionDB

        db = SessionDB()
        session = db.get_session(target)
        if not session:
            return

        title = db.get_session_title(target)
        message_count = int(session.get("message_count") or 0)
        if message_count == 0:
            return  # No real conversation — don't show resume info
        input_tokens = int(session.get("input_tokens") or 0)
        output_tokens = int(session.get("output_tokens") or 0)
        cache_read_tokens = int(session.get("cache_read_tokens") or 0)
        cache_write_tokens = int(session.get("cache_write_tokens") or 0)
        reasoning_tokens = int(session.get("reasoning_tokens") or 0)
        total_tokens = (
            input_tokens
            + output_tokens
            + cache_read_tokens
            + cache_write_tokens
            + reasoning_tokens
        )
    except Exception:
        return
    finally:
        if db is not None:
            db.close()

    print()
    print("Resume this session with:")
    print(f"  naabiga --tui --resume {target}")
    if title:
        print(f'  naabiga --tui -c "{title}"')
    print()
    print(f"Session:        {target}")
    if title:
        print(f"Title:          {title}")
    print(f"Messages:       {message_count}")
    print(
        "Tokens:         "
        f"{total_tokens} (in {input_tokens}, out {output_tokens}, "
        f"cache {cache_read_tokens + cache_write_tokens}, reasoning {reasoning_tokens})"
    )
