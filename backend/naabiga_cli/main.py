#!/usr/bin/env python3
"""
Naabiga CLI - Main entry point.

Usage:
    naabiga                     # Interactive chat (default)
    naabiga chat                # Interactive chat
    naabiga gateway             # Run gateway in foreground
    naabiga gateway start       # Start gateway as service
    naabiga gateway stop        # Stop gateway service
    naabiga gateway status      # Show gateway status
    naabiga gateway install     # Install gateway service
    naabiga gateway uninstall   # Uninstall gateway service
    naabiga setup               # Interactive setup wizard
    naabiga logout              # Clear stored authentication
    naabiga status              # Show status of all components
    naabiga cron                # Manage cron jobs
    naabiga cron list           # List cron jobs
    naabiga cron status         # Check if cron scheduler is running
    naabiga doctor              # Check configuration and dependencies
    naabiga honcho setup                    # Configure Honcho AI memory integration
    naabiga honcho status                   # Show Honcho config and connection status
    naabiga honcho sessions                 # List directory → session name mappings
    naabiga honcho map <name>               # Map current directory to a session name
    naabiga honcho peer                     # Show peer names and dialectic settings
    naabiga honcho peer --user NAME         # Set user peer name
    naabiga honcho peer --ai NAME           # Set AI peer name
    naabiga honcho peer --reasoning LEVEL   # Set dialectic reasoning level
    naabiga honcho mode                     # Show current memory mode
    naabiga honcho mode [hybrid|honcho|local]  # Set memory mode
    naabiga honcho tokens                   # Show token budget settings
    naabiga honcho tokens --context N       # Set session.context() token cap
    naabiga honcho tokens --dialectic N     # Set dialectic result char cap
    naabiga honcho identity                 # Show AI peer identity representation
    naabiga honcho identity <file>          # Seed AI peer identity from a file (SOUL.md etc.)
    naabiga honcho migrate                  # Step-by-step migration guide: OpenClaw native → Naabiga + Honcho
    naabiga version             Show version
    naabiga update              Update to latest version
    naabiga uninstall           Uninstall Naabiga Agent
    naabiga acp                 Run as an ACP server for editor integration
    naabiga sessions browse     Interactive session picker with search

    naabiga claw migrate --dry-run  # Preview migration without changes
"""

# IMPORTANT: naabiga_bootstrap must be the very first import — it sets up
# UTF-8 stdio on Windows so print()/subprocess children don't hit
# UnicodeEncodeError with non-ASCII characters.  No-op on POSIX.
#
# Guarded against ModuleNotFoundError because ``naabiga_bootstrap`` is a
# top-level module registered via pyproject.toml's ``py-modules`` list.
# When the user upgrades code via ``git pull`` (or ``naabiga update``
# crashes between ``git reset --hard`` and ``uv pip install -e .``), the
# new code references ``naabiga_bootstrap`` but the editable install's
# ``.pth`` file still points at the old set of top-level modules.  Without
# this guard, naabiga crashes on import and the user can't run
# ``naabiga update`` to recover.  Missing the bootstrap means UTF-8 stdio
# setup is skipped on Windows — degraded, not broken.  POSIX is unaffected.
try:
    import naabiga_bootstrap  # noqa: F401
except ModuleNotFoundError:
    pass

import os
import sys


def _set_process_title() -> None:
    """Set the process title to 'naabiga' so tools like 'ps', 'top', and
    'htop' show the app name instead of 'python3.xx'.

    Purely cosmetic — non-fatal on any platform.

    Strategy (try in order):
      1. ``setproctitle`` (opt-in dep — installed via ``naabiga tools`` or
         ``pip install setproctitle``, or bundled in a future release).
      2. ctypes ``prctl(PR_SET_NAME)`` (Linux only, 15-char limit).
      3. ctypes ``pthread_setname_np`` (macOS only, kernel thread name —
         changes lldb/top but not ``ps aux``).
      4. No-op on Windows (the .exe name is already ``naabiga.exe``).
    """
    # Strategy 1: setproctitle (best — works on macOS, Linux, BSD)
    try:
        import setproctitle  # type: ignore[import-untyped]

        setproctitle.setproctitle("naabiga")
        return
    except ImportError:
        pass

    # Strategy 2/3: platform-specific ctypes fallback
    import ctypes
    import platform

    try:
        system = platform.system()
        if system == "Linux":
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.prctl(15, b"naabiga", 0, 0, 0)  # PR_SET_NAME = 15
        elif system == "Darwin":
            libc = ctypes.CDLL("libc.dylib", use_errno=True)
            libc.pthread_setname_np(b"naabiga")
        # Windows: the .exe name is already ``naabiga.exe`` — nothing to do.
    except Exception:
        pass


# Cheap, dependency-free read of `display.interface` from config.yaml for the
# earliest hot-path decisions (mouse-residue suppression, Termux fast launch)
# that run *before* naabiga_cli.config is importable. Mirrors the explicit
# precedence used everywhere else: `--cli` always wins, then `--tui`/env, then
# this config value. Cached so the multiple early callers don't re-parse YAML.
_EARLY_INTERFACE_CACHE: "list | None" = None


def _config_default_interface_early() -> str:
    """Return the configured default interface ("cli"/"tui") via a minimal
    YAML read. Best-effort: any error falls back to "cli" (legacy behavior)."""
    global _EARLY_INTERFACE_CACHE
    if _EARLY_INTERFACE_CACHE is not None:
        return _EARLY_INTERFACE_CACHE[0]
    value = "cli"
    try:
        home = os.environ.get("NAABIGA_HOME")
        if home:
            cfg_path = os.path.join(home, "config.yaml")
        else:
            cfg_path = os.path.join(os.path.expanduser("~"), ".naabiga", "config.yaml")
        if os.path.exists(cfg_path):
            import yaml as _yaml_iface

            with open(cfg_path, encoding="utf-8") as _f:
                raw = _yaml_iface.load(
                    _f, Loader=getattr(_yaml_iface, "CSafeLoader", None) or _yaml_iface.SafeLoader
                ) or {}
            disp = raw.get("display", {})
            if isinstance(disp, dict):
                iface = disp.get("interface")
                if isinstance(iface, str) and iface.strip().lower() == "tui":
                    value = "tui"
    except Exception:
        value = "cli"  # best-effort — default to classic REPL on any error
    _EARLY_INTERFACE_CACHE = [value]
    return value


def _wants_tui_early(argv: "list[str] | None" = None) -> bool:
    """Earliest TUI decision, usable before argparse/config imports.

    Precedence: explicit ``--cli`` wins (forces classic REPL), then
    ``--tui``/``NAABIGA_TUI=1``, then ``display.interface`` in config.
    """
    if argv is None:
        argv = sys.argv[1:]
    if "--cli" in argv:
        return False
    if os.environ.get("NAABIGA_TUI") == "1" or "--tui" in argv:
        return True
    return _config_default_interface_early() == "tui"


# Mouse-tracking residue suppression — runs BEFORE every other import on the
# TUI hot path so the terminal stops emitting SGR/X10 mouse reports while the
# Python launcher is still doing imports (≈100–300ms in cooked + echo mode,
# before the Node TUI takes stdin into raw mode). During that window any
# incoming bytes are echoed straight back to the user's shell scrollback as
# ``^[[<…M`` text. The TUI itself runs `resetTerminalModes()` again in
# `entry.tsx`; this is just the earlier cousin. ``NAABIGA_TUI_NO_EARLY_DISABLE``
# escapes the behaviour for diagnostics.
def _suppress_mouse_residue_early() -> None:
    if os.environ.get("NAABIGA_TUI_NO_EARLY_DISABLE") == "1":
        return
    if not _wants_tui_early():
        return
    try:
        # Skip when stdout is redirected (`naabiga --tui … >log`, CI capture):
        # the bytes can't reach the terminal anyway and would just pollute
        # the log with raw CSI.
        if not os.isatty(1):
            return
        # Disable every mouse-tracking variant we know about. Idempotent and
        # safe to send even when no tracking is currently asserted.
        os.write(
            1,
            b"\x1b[?1003l\x1b[?1002l\x1b[?1001l\x1b[?1000l\x1b[?9l"
            b"\x1b[?1006l\x1b[?1005l\x1b[?1015l\x1b[?1016l\x1b[?2029l",
        )
    except OSError:
        pass


_suppress_mouse_residue_early()


def _is_termux_startup_environment_fast() -> bool:
    """Tiny Termux check for pre-import startup shortcuts."""
    prefix = os.environ.get("PREFIX", "")
    return bool(
        os.environ.get("TERMUX_VERSION")
        or "com.termux/files/usr" in prefix
        or prefix.startswith("/data/data/com.termux/")
    )


def _is_termux_fast_version_argv(argv: list[str]) -> bool:
    return argv in (["--version"], ["-V"], ["version"])


def _read_openai_version_fast() -> str | None:
    """Read OpenAI SDK version without importing ``importlib.metadata``."""
    for base in sys.path:
        if not base:
            base = os.getcwd()
        version_file = os.path.join(base, "openai", "_version.py")
        try:
            with open(version_file, encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped.startswith("__version__"):
                        continue
                    _key, _sep, value = stripped.partition("=")
                    value = value.split("#", 1)[0].strip().strip("\"'")
                    return value or None
        except OSError:
            continue
    return None


def _print_fast_version_info() -> None:
    from naabiga_cli import __release_date__, __version__

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    print(f"Naabiga Agent v{__version__} ({__release_date__})")
    print(f"Project: {project_root}")
    print(f"Python: {sys.version.split()[0]}")

    openai_version = _read_openai_version_fast()
    print(f"OpenAI SDK: {openai_version}" if openai_version else "OpenAI SDK: Not installed")


def _try_termux_ultrafast_version() -> bool:
    """Handle ``naabiga --version`` before config/logging imports on Termux."""
    if os.environ.get("NAABIGA_TERMUX_DISABLE_FAST_CLI") == "1":
        return False
    if not _is_termux_startup_environment_fast():
        return False
    if not _is_termux_fast_version_argv(sys.argv[1:]):
        return False

    _print_fast_version_info()
    return True


if _try_termux_ultrafast_version():
    raise SystemExit(0)

import json
import shutil
import subprocess
from pathlib import Path


from naabiga_cli.subcommands.cron import build_cron_parser
from naabiga_cli.subcommands.gateway import build_gateway_parser
from naabiga_cli.subcommands.profile import build_profile_parser
from naabiga_cli.subcommands.model import build_model_parser
from naabiga_cli.subcommands.setup import build_setup_parser
from naabiga_cli.subcommands.postinstall import build_postinstall_parser
from naabiga_cli.subcommands.whatsapp import build_whatsapp_parser
from naabiga_cli.subcommands.slack import build_slack_parser
from naabiga_cli.subcommands.login import build_login_parser
from naabiga_cli.subcommands.logout import build_logout_parser
from naabiga_cli.subcommands.auth import build_auth_parser
from naabiga_cli.subcommands.status import build_status_parser
from naabiga_cli.subcommands.webhook import build_webhook_parser
from naabiga_cli.subcommands.hooks import build_hooks_parser
from naabiga_cli.subcommands.doctor import build_doctor_parser
from naabiga_cli.subcommands.security import build_security_parser
from naabiga_cli.subcommands.dump import build_dump_parser
from naabiga_cli.subcommands.debug import build_debug_parser
from naabiga_cli.subcommands.backup import build_backup_parser
from naabiga_cli.subcommands.import_cmd import build_import_cmd_parser
from naabiga_cli.subcommands.config import build_config_parser
from naabiga_cli.subcommands.version import build_version_parser
from naabiga_cli.subcommands.update import build_update_parser
from naabiga_cli.subcommands.uninstall import build_uninstall_parser
from naabiga_cli.subcommands.logs import build_logs_parser
from naabiga_cli.subcommands.prompt_size import build_prompt_size_parser
from naabiga_cli.subcommands.memory import build_memory_parser
from naabiga_cli.subcommands.acp import build_acp_parser
from naabiga_cli.subcommands.tools import build_tools_parser
from naabiga_cli.subcommands.insights import build_insights_parser
from naabiga_cli.subcommands.skills import build_skills_parser
from naabiga_cli.subcommands.pairing import build_pairing_parser
from naabiga_cli.subcommands.plugins import build_plugins_parser
from naabiga_cli.subcommands.mcp import build_mcp_parser
from naabiga_cli.subcommands.claw import build_claw_parser


def _require_tty(command_name: str) -> None:
    """Exit with a clear error if stdin is not a terminal.

    Interactive TUI commands (naabiga tools, naabiga setup, naabiga model) use
    curses or input() prompts that spin at 100% CPU when stdin is a pipe.
    This guard prevents accidental non-interactive invocation.
    """
    if not sys.stdin.isatty():
        print(
            f"Error: 'naabiga {command_name}' requires an interactive terminal.\n"
            f"It cannot be run through a pipe or non-interactive subprocess.\n"
            f"Run it directly in your terminal instead.",
            file=sys.stderr,
        )
        sys.exit(1)


# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Profile override — MUST happen before any naabiga module import.
#
# Many modules cache NAABIGA_HOME at import time (module-level constants).
# We intercept --profile/-p from sys.argv here and set the env var so that
# every subsequent ``os.getenv("NAABIGA_HOME", ...)`` resolves correctly.
# The flag is stripped from sys.argv so argparse never sees it.
# Falls back to ~/.naabiga/active_profile for sticky default.
# ---------------------------------------------------------------------------
def _apply_profile_override() -> None:
    """Pre-parse --profile/-p and set NAABIGA_HOME before imports."""
    argv = sys.argv[1:]
    profile_name = None
    consume = 0
    profile_index = None

    def _inside_mcp_add_args(index: int) -> bool:
        """True once argv reaches `naabiga mcp add ... --args <command argv>`.

        ``mcp add --args`` is command-argv passthrough. Flags after that point
        belong to the child MCP command (for example Docker MCP Toolkit's
        ``--profile``), not to Naabiga' own profile selector.
        """
        try:
            mcp_index = argv.index("mcp", 0, index)
            argv.index("add", mcp_index + 1, index)
        except ValueError:
            return False
        return True

    def _resolve_sudo_user_profile_env(name: str) -> str | None:
        """Resolve `sudo naabiga -p <name>` against the invoking user's home.

        `_apply_profile_override()` runs before argparse, so `--run-as-user`
        is not available yet. For sudo invocations, the best available signal
        is SUDO_USER: root is only doing the privileged install/start action,
        while the profile store normally belongs to the user who invoked sudo.
        """
        if name == "default":
            return None
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            return None
        sudo_user = os.environ.get("SUDO_USER", "").strip()
        if not sudo_user or sudo_user == "root":
            return None

        try:
            import pwd

            home = Path(pwd.getpwnam(sudo_user).pw_dir)
        except Exception:
            return None

        candidate = home / ".naabiga" / "profiles" / name
        try:
            if candidate.is_dir():
                return str(candidate)
        except OSError:
            return None
        return None

    # 1. Check for explicit -p / --profile flag. Historically this worked even
    # after the subcommand (`naabiga chat -p coder`), so keep scanning broadly.
    # The exception is command-argv passthrough regions such as `mcp add --args`.
    value_flags = {
        "-z", "--oneshot",
        "-m", "--model",
        "--provider",
        "-t", "--toolsets",
        "-r", "--resume",
        "-s", "--skills",
        "--usage-file",
    }
    optional_value_flags = {"-c", "--continue"}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            break
        if arg == "--args" and _inside_mcp_add_args(i):
            break
        if arg in {"--profile", "-p"} and i + 1 < len(argv):
            profile_name = argv[i + 1]
            consume = 2
            profile_index = i
            break
        if arg.startswith("--profile="):
            profile_name = arg.split("=", 1)[1]
            consume = 1
            profile_index = i
            break
        if "=" not in arg and arg in value_flags and i + 1 < len(argv):
            i += 2
        elif (
            "=" not in arg
            and arg in optional_value_flags
            and i + 1 < len(argv)
            and not argv[i + 1].startswith("-")
        ):
            i += 2
        else:
            i += 1

    # 1b. Reject values that can't be valid profile names (e.g. pytest's
    # "-p no:xdist" would be misread as profile "no:xdist" otherwise).
    # Mirrors naabiga_cli.profiles._PROFILE_ID_RE so we never call
    # resolve_profile_env() with a value it must reject + sys.exit on.
    if profile_name is not None and consume == 2:
        import re as _re

        if not _re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", profile_name):
            profile_name = None
            consume = 0
            profile_index = None

    # 1.5 If NAABIGA_HOME is already set and no explicit flag was given, trust it
    # only when it already points to a specific profile directory.  The
    # distinguishing heuristic: a profile path has "profiles" as its immediate
    # parent directory name (e.g. ~/.naabiga/profiles/coder or
    # /opt/data/profiles/coder).  If NAABIGA_HOME points to the naabiga root
    # instead (e.g. systemd hardcodes NAABIGA_HOME=/root/.naabiga), we must
    # still read active_profile — the user may have switched profiles via
    # `naabiga profile use` and the gateway should honour that choice.
    # See issue #22502.
    naabiga_home_env = os.environ.get("NAABIGA_HOME", "")
    if profile_name is None and naabiga_home_env:
        if Path(naabiga_home_env).parent.name == "profiles":
            return

    # 2. If no flag, check active_profile in the naabiga root.
    #
    # EXCEPTION: a supervised s6 gateway child (exported by the container
    # run-script as NAABIGA_S6_SUPERVISED_CHILD=1) must NOT follow the sticky
    # active_profile. Each supervised slot has a fixed profile identity: named
    # slots pass ``-p <name>`` explicitly (handled in step 1 above), and the
    # reserved ``gateway-default`` slot runs bare ``naabiga gateway run`` to mean
    # "the root NAABIGA_HOME profile". If the reserved default child read
    # active_profile here, switching the active profile (e.g. via the dashboard)
    # would silently redirect the default gateway into that profile — yielding a
    # duplicate gateway for the active profile and no real default gateway. See
    # the "Docker & Profiles & Dashboard" report.
    if profile_name is None and not os.environ.get("NAABIGA_S6_SUPERVISED_CHILD"):
        try:
            from naabiga_constants import get_default_naabiga_root

            active_path = get_default_naabiga_root() / "active_profile"
            if active_path.exists():
                name = active_path.read_text().strip()
                if name and name != "default":
                    profile_name = name
                    consume = 0  # don't strip anything from argv
        except (UnicodeDecodeError, OSError):
            pass  # corrupted file, skip

    # 3. If we found a profile, resolve and set NAABIGA_HOME
    if profile_name is not None:
        try:
            from naabiga_cli.profiles import resolve_profile_env

            naabiga_home = resolve_profile_env(profile_name)
        except FileNotFoundError as exc:
            naabiga_home = _resolve_sudo_user_profile_env(profile_name)
            if not naabiga_home:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            # A bug in profiles.py must NEVER prevent naabiga from starting
            print(
                f"Warning: profile override failed ({exc}), using default",
                file=sys.stderr,
            )
            return
        os.environ["NAABIGA_HOME"] = naabiga_home
        # Strip the flag from argv so argparse doesn't choke
        if consume > 0 and profile_index is not None:
            start = profile_index + 1  # +1 because argv is sys.argv[1:]
            sys.argv = sys.argv[:start] + sys.argv[start + consume :]


_apply_profile_override()

# Load .env from ~/.naabiga/.env first, then project root as dev fallback.
# User-managed env files should override stale shell exports on restart.
from naabiga_cli.config import get_naabiga_home
from naabiga_cli.env_loader import load_naabiga_dotenv

load_naabiga_dotenv(project_env=PROJECT_ROOT / ".env")

# Bridge security.redact_secrets from config.yaml → NAABIGA_REDACT_SECRETS env
# var BEFORE naabiga_logging imports agent.redact (which snapshots the flag at
# module-import time). Without this, config.yaml's toggle is ignored because
# the setup_logging() call below imports agent.redact, which reads the env var
# exactly once. Env var in .env still wins — this is config.yaml fallback only.
#
# We also read network.force_ipv4 from the same yaml load to avoid two
# separate config.yaml reads (saves ~17ms on every CLI startup — the second
# `load_config()` was doing a full deep-merge for one boolean lookup).
_FORCE_IPV4_EARLY = False
try:
    import yaml as _yaml_early

    _cfg_path = get_naabiga_home() / "config.yaml"
    if _cfg_path.exists():
        with open(_cfg_path, encoding="utf-8") as _f:
            _early_cfg_raw = _yaml_early.load(
                _f, Loader=getattr(_yaml_early, "CSafeLoader", None) or _yaml_early.SafeLoader
            ) or {}
        # Managed scope: overlay administrator-pinned values so a managed
        # security.redact_secrets / network.force_ipv4 wins here too. This early
        # bridge reads config.yaml directly (before load_config is usable), so
        # without the overlay a managed redact_secrets toggle would be ignored.
        # Fail-open via the shared helper.
        try:
            from naabiga_cli import managed_scope
            _early_cfg_raw = managed_scope.apply_managed_overlay(_early_cfg_raw)
        except Exception:
            pass
        if "NAABIGA_REDACT_SECRETS" not in os.environ:
            _early_sec_cfg = _early_cfg_raw.get("security", {})
            if isinstance(_early_sec_cfg, dict):
                _early_redact = _early_sec_cfg.get("redact_secrets")
                if _early_redact is not None:
                    os.environ["NAABIGA_REDACT_SECRETS"] = str(_early_redact).lower()
        _early_net_cfg = _early_cfg_raw.get("network", {})
        if isinstance(_early_net_cfg, dict) and _early_net_cfg.get("force_ipv4"):
            _FORCE_IPV4_EARLY = True
        del _early_cfg_raw
    del _cfg_path
except Exception:
    pass  # best-effort — redaction stays at default (enabled) on config errors

# Initialize centralized file logging early — all `naabiga` subcommands
# (chat, setup, gateway, config, etc.) write to agent.log + errors.log.
try:
    from naabiga_logging import setup_logging as _setup_logging

    _setup_logging(mode="cli")
except Exception:
    pass  # best-effort — don't crash the CLI if logging setup fails

# Apply IPv4 preference early, before any HTTP clients are created.
# We already determined whether to force IPv4 from the raw yaml read above —
# this just calls the toggle without a redundant load_config() round trip.
if _FORCE_IPV4_EARLY:
    try:
        from naabiga_constants import apply_ipv4_preference as _apply_ipv4

        _apply_ipv4(force=True)
    except Exception:
        pass  # best-effort — don't crash if naabiga_constants not importable yet

import logging

from naabiga_cli import __version__, __release_date__

# Provider model-selection wizard flows extracted to naabiga_cli/model_setup_flows.py
# (god-file decomposition Phase 2). Re-imported here so select_provider_and_model and
# existing test monkeypatches (naabiga_cli.main._model_flow_*) keep resolving unchanged.
logger = logging.getLogger(__name__)


def _is_termux_startup_environment(env: dict[str, str] | None = None) -> bool:
    """Import-safe Termux check for cold-start-sensitive CLI paths."""
    check = env or os.environ
    prefix = str(check.get("PREFIX", ""))
    return bool(
        check.get("TERMUX_VERSION")
        or "com.termux/files/usr" in prefix
        or prefix.startswith("/data/data/com.termux/")
    )


def _read_packed_ref(common_dir: Path, ref: str) -> str | None:
    """Look up a ref in .git/packed-refs without spawning git.

    packed-refs lines look like ``<sha> <ref>`` with optional ``^<sha>``
    peel lines and ``#``-prefixed comments / ``# pack-refs with:`` header.
    """
    try:
        text = (common_dir / "packed-refs").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].strip() == ref:
            return parts[0].strip()
    return None


def _read_git_revision_fingerprint(repo_root: Path) -> str | None:
    """Return a cheap checkout fingerprint without spawning git."""
    git_dir = repo_root / ".git"
    try:
        if git_dir.is_file():
            for line in git_dir.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "gitdir" and value.strip():
                    git_dir = (repo_root / value.strip()).resolve()
                    break
        # Worktrees point HEAD at a per-worktree gitdir but pack their refs
        # in the main repo's gitdir (referenced via ``commondir``). Resolve
        # that up front so packed-refs lookups hit the right file.
        common_dir = git_dir
        commondir_file = git_dir / "commondir"
        if commondir_file.exists():
            try:
                rel = commondir_file.read_text(encoding="utf-8", errors="replace").strip()
                if rel:
                    common_dir = (git_dir / rel).resolve()
            except OSError:
                pass
        head_file = git_dir / "HEAD"
        head = head_file.read_text(encoding="utf-8", errors="replace").strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            # Loose refs may live in the worktree gitdir OR the common dir
            # (branches created via `git worktree add` typically live in the
            # common dir's refs/heads/).
            for candidate in (git_dir, common_dir):
                ref_file = candidate / ref
                if ref_file.exists():
                    return f"git:{ref}:{ref_file.read_text(encoding='utf-8', errors='replace').strip()}"
            packed_sha = _read_packed_ref(common_dir, ref)
            if packed_sha:
                return f"git:{ref}:{packed_sha}"
            # Ref name is known but unresolved — still stable across launches,
            # and the version/release fallback in the caller will invalidate
            # after `naabiga update`.
            return f"git:{ref}:unresolved"
        return f"git:HEAD:{head}"
    except OSError:
        return None


def _termux_bundled_skills_fingerprint() -> str:
    """Cheap invalidation key for Termux bundled-skill startup sync."""
    git_fp = _read_git_revision_fingerprint(PROJECT_ROOT)
    if git_fp:
        return git_fp
    skills_dir = PROJECT_ROOT / "skills"
    try:
        stat = skills_dir.stat()
        return f"skills:{__version__}:{__release_date__}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return f"skills:{__version__}:{__release_date__}:missing"


def _termux_bundled_skills_stamp_path() -> Path:
    return get_naabiga_home() / "skills" / ".termux_bundled_sync_stamp"


def _termux_bundled_skills_sync_needed() -> bool:
    if not _is_termux_startup_environment():
        return True
    if os.environ.get("NAABIGA_TERMUX_FORCE_SKILLS_SYNC") == "1":
        return True
    try:
        stamp = _termux_bundled_skills_stamp_path()
        return stamp.read_text(encoding="utf-8").strip() != _termux_bundled_skills_fingerprint()
    except OSError:
        return True


def _mark_termux_bundled_skills_synced() -> None:
    if not _is_termux_startup_environment():
        return
    try:
        stamp = _termux_bundled_skills_stamp_path()
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(_termux_bundled_skills_fingerprint() + "\n", encoding="utf-8")
    except OSError:
        pass


def _sync_bundled_skills_for_startup() -> bool:
    """Sync bundled skills, but skip unchanged Termux checkouts cheaply.

    Hashing every bundled skill is safe but expensive on older Android
    storage. The git/ref stamp keeps post-update correctness: a changed
    checkout revision forces one real sync, then later starts skip it.
    """
    if _is_termux_startup_environment() and not _termux_bundled_skills_sync_needed():
        return False

    from tools.skills_sync import sync_skills

    sync_skills(quiet=True)
    _mark_termux_bundled_skills_synced()
    return True


def _termux_should_prefetch_update_check() -> bool:
    if not _is_termux_startup_environment():
        return True
    return os.environ.get("NAABIGA_TERMUX_PREFETCH_UPDATES") == "1"


# Session helpers — extraits dans _sessions.py (cluster autonome).
from naabiga_cli._sessions import (  # noqa: E402
    _exec_in_container,
    _has_any_provider_configured,
    _relative_time,
    _resolve_last_session,
    _resolve_session_by_name_or_id,
    _session_browse_picker,
)


_NPM_LOCK_RUNTIME_KEYS = frozenset({"ideallyInert", "peer"})
"""Lockfile fields npm writes non-deterministically at install time.

``ideallyInert`` is npm's runtime annotation for packages it skipped installing
(per-platform opt-outs).  ``peer`` is dropped from the hidden ``.package-lock.json``
on dev-dependencies that are *also* declared as peers — the canonical
``package-lock.json`` records the dual role, but npm 9's actualized tree strips
it.  Neither key represents a real skew between what was declared and what was
installed, so we exclude them from the comparison in :func:`_tui_need_npm_install`
to avoid false-positive reinstalls on every launch.
"""
_TUI_BUILD_INPUT_DIRS = (
    "src",
    "packages/naabiga-ink/src",
)

_TUI_BUILD_INPUT_FILES = (
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "tsconfig.build.json",
    "babel.compiler.config.cjs",
    "scripts/build.mjs",
    "packages/naabiga-ink/package.json",
    "packages/naabiga-ink/index.js",
    "packages/naabiga-ink/text-input.js",
)

_TUI_BUILD_INPUT_SUFFIXES = frozenset(
    {".cjs", ".js", ".jsx", ".json", ".mjs", ".ts", ".tsx"}
)


# TUI launch machinery — extrait dans _tui_launch.py.
from naabiga_cli._tui_launch import (  # noqa: E402
    _launch_tui,
    _pin_kanban_board_env,
    _resolve_use_tui,
    _sync_bundled_skills_quietly,
)


def cmd_chat(args):
    """Run interactive chat CLI."""
    use_tui = _resolve_use_tui(args)

    _apply_safe_mode(args)

    # Resolve --continue into --resume with the latest session or by name
    continue_val = getattr(args, "continue_last", None)
    if continue_val and not getattr(args, "resume", None):
        if isinstance(continue_val, str):
            # -c "session name" — resolve by title or ID
            resolved = _resolve_session_by_name_or_id(continue_val)
            if resolved:
                args.resume = resolved
            else:
                print(f"No session found matching '{continue_val}'.")
                print("Use 'naabiga sessions list' to see available sessions.")
                sys.exit(1)
        else:
            # -c with no argument — continue the most recent session
            source = "tui" if use_tui else "cli"
            last_id = _resolve_last_session(source=source)
            if not last_id and source == "tui":
                last_id = _resolve_last_session(source="cli")
            if last_id:
                args.resume = last_id
            else:
                kind = "TUI" if use_tui else "CLI"
                print(f"No previous {kind} session found to continue.")
                sys.exit(1)

    # Resolve --resume by title if it's not a direct session ID
    resume_val = getattr(args, "resume", None)
    if resume_val:
        resolved = _resolve_session_by_name_or_id(resume_val)
        if resolved:
            args.resume = resolved
        # If resolution fails, keep the original value — _init_agent will
        # report "Session not found" with the original input

    # xAI retirement warning — one-shot, non-blocking, never fails startup
    try:
        from naabiga_cli.xai_retirement import (
            MIGRATION_GUIDE_URL,
            RETIREMENT_DATE,
            find_retired_xai_refs,
            format_issue,
        )
        from naabiga_cli.config import load_config as _load_config_for_xai_check

        _retired_xai_refs = find_retired_xai_refs(_load_config_for_xai_check())
        if _retired_xai_refs:
            sys.stderr.write(
                f"\033[33m⚠ xAI retires {len(_retired_xai_refs)} model(s) "
                f"in your config on {RETIREMENT_DATE}:\033[0m\n"
            )
            for _ref in _retired_xai_refs:
                sys.stderr.write(f"  \033[33m⚠\033[0m {format_issue(_ref)}\n")
            sys.stderr.write(f"  \033[2mMigration guide: {MIGRATION_GUIDE_URL}\033[0m\n")
            sys.stderr.write("  \033[2mRun 'naabiga doctor' for details.\033[0m\n\n")
    except Exception:
        pass

    # First-run guard: check if any provider is configured before launching
    if not _has_any_provider_configured():
        print()
        print(
            "It looks like Naabiga isn't configured yet -- no API keys or providers found."
        )
        print()
        print("  Run:  naabiga setup")
        print()

        from naabiga_cli.setup import (
            is_interactive_stdin,
            print_noninteractive_setup_guidance,
        )

        if not is_interactive_stdin():
            print_noninteractive_setup_guidance(
                "No interactive TTY detected for the first-run setup prompt."
            )
            sys.exit(1)

        try:
            reply = input("Run setup now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            reply = "n"
        if reply in {"", "y", "yes"}:
            cmd_setup(args)
            return
        print()
        print("You can run 'naabiga setup' at any time to configure.")
        sys.exit(1)

    # Start update check in background (runs while other init happens).
    # On Termux this imports rich/prompt_toolkit in the foreground and then
    # competes for CPU on single-core devices, so keep it opt-in there.
    if _termux_should_prefetch_update_check():
        try:
            from naabiga_cli.banner import prefetch_update_check

            prefetch_update_check()
        except Exception:
            pass

    # Sync bundled skills on every CLI launch (fast -- skips unchanged skills)
    try:
        _sync_bundled_skills_for_startup()
    except Exception:
        pass

    # --yolo: bypass all dangerous command approvals
    if getattr(args, "yolo", False):
        os.environ["NAABIGA_YOLO_MODE"] = "1"

    # --ignore-user-config: make load_cli_config() / load_config() skip the
    # user's ~/.naabiga/config.yaml and return built-in defaults. Set BEFORE
    # importing cli (which runs `CLI_CONFIG = load_cli_config()` at module
    # import time). Credentials in .env are still loaded — this flag only
    # ignores behavioral/config settings.
    if getattr(args, "ignore_user_config", False):
        os.environ["NAABIGA_IGNORE_USER_CONFIG"] = "1"

    # --ignore-rules: skip auto-injection of AGENTS.md/SOUL.md/.cursorrules
    # (rules), memory entries, and any preloaded skills coming from user config.
    # Maps to AIAgent(skip_context_files=True, skip_memory=True).
    if getattr(args, "ignore_rules", False):
        os.environ["NAABIGA_IGNORE_RULES"] = "1"

    # --source: tag session source for filtering (e.g. 'tool' for third-party integrations)
    if getattr(args, "source", None):
        os.environ["NAABIGA_SESSION_SOURCE"] = args.source

    _pin_kanban_board_env()

    if use_tui:
        _launch_tui(
            getattr(args, "resume", None),
            tui_dev=getattr(args, "tui_dev", False),
            model=getattr(args, "model", None),
            provider=getattr(args, "provider", None),
            toolsets=getattr(args, "toolsets", None),
            skills=getattr(args, "skills", None),
            verbose=getattr(args, "verbose", None),
            quiet=getattr(args, "quiet", False),
            query=getattr(args, "query", None),
            image=getattr(args, "image", None),
            worktree=getattr(args, "worktree", False),
            checkpoints=getattr(args, "checkpoints", False),
            pass_session_id=getattr(args, "pass_session_id", False),
            max_turns=getattr(args, "max_turns", None),
            accept_hooks=getattr(args, "accept_hooks", False),
        )

    # Import and run the CLI
    from cli import main as cli_main

    # Build kwargs from args
    kwargs = {
        "model": args.model,
        "provider": getattr(args, "provider", None),
        "toolsets": args.toolsets,
        "skills": getattr(args, "skills", None),
        "verbose": getattr(args, "verbose", None),
        "quiet": getattr(args, "quiet", False),
        "query": args.query,
        "image": getattr(args, "image", None),
        "resume": getattr(args, "resume", None),
        "worktree": getattr(args, "worktree", False),
        "checkpoints": getattr(args, "checkpoints", False),
        "pass_session_id": getattr(args, "pass_session_id", False),
        "max_turns": getattr(args, "max_turns", None),
        "ignore_rules": getattr(args, "ignore_rules", False) or getattr(args, "safe_mode", False),
        "ignore_user_config": getattr(args, "ignore_user_config", False) or getattr(args, "safe_mode", False),
        "compact": getattr(args, "compact", False),
    }
    # Filter out None values
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    try:
        cli_main(**kwargs)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_gateway(args):
    """Gateway management commands."""
    _sync_bundled_skills_quietly()

    from naabiga_cli.gateway import gateway_command

    gateway_command(args)


def cmd_proxy(args):
    """Local OpenAI-compatible proxy to OAuth providers."""
    # Lazy import — pulls in aiohttp, which is gated behind an extras install
    # for users who don't run the proxy or the messaging gateway.
    from naabiga_cli.proxy.cli import cmd_proxy as _cmd_proxy

    rc = _cmd_proxy(args)
    if isinstance(rc, int) and rc != 0:
        raise SystemExit(rc)


def cmd_whatsapp(args):
    """Set up WhatsApp: choose mode, configure, install bridge, pair via QR."""
    _require_tty("whatsapp")
    from naabiga_cli.config import get_env_value, save_env_value
    from naabiga_constants import find_node_executable, with_naabiga_node_path

    print()
    print("⚕ WhatsApp Setup")
    print("=" * 50)

    # ── Step 1: Choose mode ──────────────────────────────────────────────
    current_mode = get_env_value("WHATSAPP_MODE") or ""
    if not current_mode:
        print()
        print("How will you use WhatsApp with Naabiga?")
        print()
        print("  1. Separate bot number (recommended)")
        print("     People message the bot's number directly — cleanest experience.")
        print(
            "     Requires a second phone number with WhatsApp installed on a device."
        )
        print()
        print("  2. Personal number (self-chat)")
        print("     You message yourself to talk to the agent.")
        print("     Quick to set up, but the UX is less intuitive.")
        print()
        try:
            choice = input("  Choose [1/2]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled.")
            return

        if choice == "1":
            save_env_value("WHATSAPP_MODE", "bot")
            wa_mode = "bot"
            print("  ✓ Mode: separate bot number")
            print()
            print("  ┌─────────────────────────────────────────────────┐")
            print("  │  Getting a second number for the bot:           │")
            print("  │                                                 │")
            print("  │  Easiest: Install WhatsApp Business (free app)  │")
            print("  │  on your phone with a second number:            │")
            print("  │    • Dual-SIM: use your 2nd SIM slot            │")
            print("  │    • Google Voice: free US number (voice.google) │")
            print("  │    • Prepaid SIM: $3-10, verify once            │")
            print("  │                                                 │")
            print("  │  WhatsApp Business runs alongside your personal │")
            print("  │  WhatsApp — no second phone needed.             │")
            print("  └─────────────────────────────────────────────────┘")
        else:
            save_env_value("WHATSAPP_MODE", "self-chat")
            wa_mode = "self-chat"
            print("  ✓ Mode: personal number (self-chat)")
    else:
        wa_mode = current_mode
        mode_label = (
            "separate bot number" if wa_mode == "bot" else "personal number (self-chat)"
        )
        print(f"\n✓ Mode: {mode_label}")

    # ── Step 2: Mode is selected, will enable WhatsApp only after pairing ──
    # We intentionally don't write WHATSAPP_ENABLED=true here.  If the user
    # aborts the wizard later (Ctrl+C, failed npm install, missed QR scan),
    # we'd otherwise leave .env claiming WhatsApp is ready when the bridge
    # has no creds.json.  Every subsequent `naabiga gateway` then paid a 30s
    # bridge-bootstrap timeout and queued WhatsApp for indefinite retries.
    # Now: aborted setup leaves WHATSAPP_ENABLED unset → gateway skips it.
    # Re-runs that already have WHATSAPP_ENABLED=true (from a prior
    # successful pairing) stay enabled — we just don't write it pre-emptively.
    print()
    if (get_env_value("WHATSAPP_ENABLED") or "").lower() == "true":
        print("✓ WhatsApp is already enabled")

    # ── Step 3: Allowed users ────────────────────────────────────────────
    current_users = get_env_value("WHATSAPP_ALLOWED_USERS") or ""
    if current_users:
        print(f"✓ Allowed users: {current_users}")
        try:
            response = input("\n  Update allowed users? [y/N] ").strip()
        except (EOFError, KeyboardInterrupt):
            response = "n"
        if response.lower() in {"y", "yes"}:
            if wa_mode == "bot":
                phone = input(
                    "  Phone numbers that can message the bot (comma-separated): "
                ).strip()
            else:
                phone = input("  Your phone number (e.g. 15551234567): ").strip()
            if phone:
                save_env_value("WHATSAPP_ALLOWED_USERS", phone.replace(" ", ""))
                print(f"  ✓ Updated to: {phone}")
    else:
        print()
        if wa_mode == "bot":
            print("  Who should be allowed to message the bot?")
            phone = input(
                "  Phone numbers (comma-separated, or * for anyone): "
            ).strip()
        else:
            phone = input("  Your phone number (e.g. 15551234567): ").strip()
        if phone:
            save_env_value("WHATSAPP_ALLOWED_USERS", phone.replace(" ", ""))
            print(f"  ✓ Allowed users set: {phone}")
        else:
            print("  ⚠ No allowlist — the agent will respond to ALL incoming messages")

    # ── Step 4: Install bridge dependencies ──────────────────────────────
    from gateway.platforms.whatsapp_common import resolve_whatsapp_bridge_dir
    bridge_dir = resolve_whatsapp_bridge_dir()
    bridge_script = bridge_dir / "bridge.js"

    if not bridge_script.exists():
        print(f"\n✗ Bridge script not found at {bridge_script}")
        return

    if not (bridge_dir / "node_modules").exists():
        print(
            "\n→ Installing WhatsApp bridge dependencies (this can take a few minutes)..."
        )
        npm = find_node_executable("npm")
        if not npm:
            print("  ✗ npm not found on PATH — install Node.js first")
            return
        try:
            result = subprocess.run(
                [npm, "install", "--no-fund", "--no-audit", "--progress=false"],
                cwd=str(bridge_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=with_naabiga_node_path(),
            )
        except KeyboardInterrupt:
            print("\n  ✗ Install cancelled")
            return
        if result.returncode != 0:
            err = (result.stderr or "").strip()
            preview = "\n".join(err.splitlines()[-30:]) if err else "(no output)"
            print("  ✗ npm install failed:")
            print(preview)
            return
        print("  ✓ Dependencies installed")
    else:
        print("✓ Bridge dependencies already installed")

    # ── Step 5: Check for existing session ───────────────────────────────
    session_dir = get_naabiga_home() / "whatsapp" / "session"
    session_dir.mkdir(parents=True, exist_ok=True)

    if (session_dir / "creds.json").exists():
        print("✓ Existing WhatsApp session found")
        try:
            response = input(
                "\n  Re-pair? This will clear the existing session. [y/N] "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            response = "n"
        if response.lower() in {"y", "yes"}:
            shutil.rmtree(session_dir, ignore_errors=True)
            session_dir.mkdir(parents=True, exist_ok=True)
            print("  ✓ Session cleared")
        else:
            # Existing pairing — ensure WHATSAPP_ENABLED reflects that.
            # (Older installs may have lost the env var; covers re-runs
            # where the user picked "no, keep my session" but the var
            # was never set or got removed.)
            if (get_env_value("WHATSAPP_ENABLED") or "").lower() != "true":
                save_env_value("WHATSAPP_ENABLED", "true")
            print("\n✓ WhatsApp is configured and paired!")
            print("  Start the gateway with: naabiga gateway")
            return

    # ── Step 6: QR code pairing ──────────────────────────────────────────
    print()
    print("─" * 50)
    if wa_mode == "bot":
        print("📱 Open WhatsApp (or WhatsApp Business) on the")
        print("   phone with the BOT's number, then scan:")
    else:
        print("📱 Open WhatsApp on your phone, then scan:")
    print()
    print("   Settings → Linked Devices → Link a Device")
    print("─" * 50)
    print()

    try:
        subprocess.run(
            [
                find_node_executable("node") or "node",
                str(bridge_script),
                "--pair-only",
                "--session",
                str(session_dir),
            ],
            cwd=str(bridge_dir),
            env=with_naabiga_node_path(),
        )
    except KeyboardInterrupt:
        pass

    # ── Step 7: Post-pairing ─────────────────────────────────────────────
    print()
    if (session_dir / "creds.json").exists():
        # Only enable WhatsApp now that pairing actually succeeded.  If the
        # user Ctrl+C'd at any earlier step, WHATSAPP_ENABLED stays unset
        # and `naabiga gateway` skips it cleanly instead of paying a 30s
        # bridge timeout + queueing the platform for indefinite retries.
        save_env_value("WHATSAPP_ENABLED", "true")
        print("✓ WhatsApp paired successfully!")
        print()
        if wa_mode == "bot":
            print("  Next steps:")
            print("    1. Start the gateway:  naabiga gateway")
            print("    2. Send a message to the bot's WhatsApp number")
            print("    3. The agent will reply automatically")
            print()
            print("  Tip: Agent responses are prefixed with '⚕ Naabiga Agent'")
        else:
            print("  Next steps:")
            print("    1. Start the gateway:  naabiga gateway")
            print("    2. Open WhatsApp → Message Yourself")
            print("    3. Type a message — the agent will reply")
            print()
            print("  Tip: Agent responses are prefixed with '⚕ Naabiga Agent'")
            print("  so you can tell them apart from your own messages.")
        print()
        print("  Or install as a service: naabiga gateway install")
    else:
        print("⚠ Pairing may not have completed. Run 'naabiga whatsapp' to try again.")


def cmd_whatsapp_cloud(args):
    """Set up WhatsApp Business Cloud API (official Meta integration).

    Walks the user through the Meta-side credentials (Phone Number ID,
    Access Token, App Secret, optional App/WABA IDs) plus webhook
    configuration. Includes field-shape validators that catch the most
    common setup mistakes (e.g. pasting a phone number into the Phone
    Number ID field).

    Distinct from ``naabiga whatsapp`` (the Baileys bridge wizard) — the
    two adapters are complementary, not alternatives. See
    ``naabiga_cli/setup_whatsapp_cloud.py``.
    """
    _require_tty("whatsapp-cloud")
    from naabiga_cli.setup_whatsapp_cloud import run_whatsapp_cloud_setup

    return run_whatsapp_cloud_setup()


def cmd_setup(args):
    """Interactive setup wizard."""
    from naabiga_cli.setup import run_setup_wizard

    run_setup_wizard(args)


def cmd_postinstall(args):
    """One-shot bootstrap for pip users: install non-Python deps + run setup."""
    from naabiga_cli.config import stamp_install_method
    from naabiga_cli.dep_ensure import ensure_dependency

    stamp_install_method("pip")

    print("⚕ Naabiga post-install bootstrap")
    print()

    for dep in ("node", "browser", "ripgrep", "ffmpeg"):
        ensure_dependency(dep)

    if not _has_any_provider_configured():
        print()
        cmd_setup(args)
    else:
        print()
        print("✓ Post-install complete.")


def cmd_model(args):
    """Select default model — starts with provider selection, then model picker."""
    _require_tty("model")
    if getattr(args, "refresh", False):
        try:
            from naabiga_cli.models import clear_provider_models_cache
            clear_provider_models_cache()
            print("  Cleared model picker cache.")
        except Exception:
            pass
    select_provider_and_model(args=args)


def _is_profile_api_key_provider(provider_id: str) -> bool:
    """Return True when provider_id maps to a profile with auth_type='api_key'.

    Used as a catch-all in select_provider_and_model() so that new providers
    declared in plugins/model-providers/<name>/ automatically dispatch to _model_flow_api_key_provider
    without requiring an explicit elif branch here.
    """
    try:
        from providers import get_provider_profile
        _p = get_provider_profile(provider_id)
        return _p is not None and _p.auth_type == "api_key"
    except Exception:
        return False
# ─────────────────────────────────────────────────────────────────────────────
# Auxiliary model configuration
#
# Naabiga uses lightweight "auxiliary" models for side tasks (vision analysis,
# context compression, web extraction, session search, etc.). Each task has
# its own provider+model pair in config.yaml under `auxiliary.<task>`.
#
# The UI lives behind "Configure auxiliary models..." at the bottom of the
# `naabiga model` provider picker. It does NOT re-run credential setup — it
# only routes already-authenticated providers to specific aux tasks. Users
# configure new providers through the normal `naabiga model` flow first.
# ─────────────────────────────────────────────────────────────────────────────

# (task_key, display_name, short_description)
_AUX_TASKS: list[tuple[str, str, str]] = [
    ("vision", "Vision", "image/screenshot analysis"),
    ("compression", "Compression", "context summarization"),
    ("web_extract", "Web extract", "web page summarization"),
    ("approval", "Approval", "smart command approval"),
    ("mcp", "MCP", "MCP tool reasoning"),
    ("title_generation", "Title generation", "session titles"),
    ("tts_audio_tags", "TTS audio tags", "Gemini TTS tag insertion"),
    ("skills_hub", "Skills hub", "skills search/install"),
    ("triage_specifier", "Triage specifier", "kanban spec fleshing"),
    ("kanban_decomposer", "Kanban decomposer", "task decomposition"),
    ("profile_describer", "Profile describer", "auto profile descriptions"),
    ("curator", "Curator", "skill-usage review pass"),
]
_DEFAULT_QWEN_PORTAL_MODELS = [
    "qwen3-coder-plus",
    "qwen3-coder",
]
# Lazy-export the model catalog at module level. Tests and a handful of
# downstream call sites read `naabiga_cli.main._PROVIDER_MODELS` directly,
# so the symbol needs to be reachable as a module attribute. But importing
# the catalog eagerly costs ~55ms on every `naabiga` invocation — including
# fast paths like `naabiga --version` and slash-command dispatch that never
# touch the catalog. PEP 562 module-level __getattr__ defers the import
# until first attribute access, so the cost is only paid by callers that
# actually look up the catalog. Termux already defers via the same
# mechanism (its model-selection handlers do their own function-local
# imports), so the explicit termux branch from before is no longer needed.
_LAZY_MODEL_EXPORTS = ("_PROVIDER_MODELS",)


def __getattr__(name):
    """Defer the model-catalog import until something actually reads it."""
    if name in _LAZY_MODEL_EXPORTS:
        from naabiga_cli._model_flows import _PROVIDER_MODELS

        # Cache on the module so subsequent accesses skip the import machinery.
        globals()[name] = _PROVIDER_MODELS
        return _PROVIDER_MODELS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Model/provider flows — extraits dans _model_flows.py.
from naabiga_cli._model_flows import (  # noqa: E402
    cmd_auth,
    cmd_cron,
    cmd_login,
    cmd_logout,
    cmd_slack,
    cmd_status,
    cmd_webhook,
    select_provider_and_model,
)


def cmd_kanban(args):
    """Multi-profile collaboration board."""
    from naabiga_cli.kanban import kanban_command

    return kanban_command(args)


def cmd_project(args):
    """Manage projects (named, multi-folder workspaces)."""
    from naabiga_cli.projects_cmd import projects_command

    return projects_command(args)


def cmd_hooks(args):
    """Shell-hook inspection and management."""
    from naabiga_cli.hooks import hooks_command

    hooks_command(args)


def cmd_doctor(args):
    """Check configuration and dependencies."""
    from naabiga_cli.doctor import run_doctor

    run_doctor(args)


def cmd_security(args):
    """Dispatch `naabiga security <subcmd>`."""
    sub = getattr(args, "security_command", None)
    if sub in ("audit", None):
        from naabiga_cli.security_audit import cmd_security_audit

        # Default subcommand is `audit` when no subcmd is given.
        code = cmd_security_audit(args)
        sys.exit(int(code or 0))
    print(f"unknown security subcommand: {sub}", file=sys.stderr)
    sys.exit(2)


def cmd_dump(args):
    """Dump setup summary for support/debugging."""
    from naabiga_cli.dump import run_dump

    run_dump(args)


def cmd_debug(args):
    """Debug tools (share report, etc.)."""
    from naabiga_cli.debug import run_debug

    run_debug(args)


def cmd_config(args):
    """Configuration management."""
    from naabiga_cli.config import config_command

    config_command(args)


def cmd_backup(args):
    """Back up Naabiga home directory to a zip file."""
    if getattr(args, "quick", False):
        from naabiga_cli.backup import run_quick_backup

        run_quick_backup(args)
    else:
        from naabiga_cli.backup import run_backup

        run_backup(args)


def cmd_import(args):
    """Restore a Naabiga backup from a zip file."""
    from naabiga_cli.backup import run_import

    run_import(args)


def _print_version_info(*, check_updates: bool = True) -> None:
    from naabiga_cli.banner import format_banner_version_label

    print(format_banner_version_label())
    print(f"Project: {PROJECT_ROOT}")

    # Show Python version
    print(f"Python: {sys.version.split()[0]}")

    # Check for key dependencies.  Use importlib.metadata rather than
    # ``import openai`` — the SDK drags in ~800ms of pydantic-backed type
    # modules just to expose ``__version__``.  Metadata lookup is ~2ms.
    try:
        from importlib.metadata import version as _pkg_version, PackageNotFoundError

        try:
            print(f"OpenAI SDK: {_pkg_version('openai')}")
        except PackageNotFoundError:
            print("OpenAI SDK: Not installed")
    except ImportError:
        print("OpenAI SDK: Not installed")

    if not check_updates:
        return

    # Show update status (synchronous — acceptable since user asked for version info)
    try:
        from naabiga_cli.banner import check_for_updates
        from naabiga_cli.config import recommended_update_command

        behind = check_for_updates()
        if behind and behind > 0:
            commits_word = "commit" if behind == 1 else "commits"
            print(
                f"Update available: {behind} {commits_word} behind — "
                f"run '{recommended_update_command()}'"
            )
        elif behind == 0:
            print("Up to date")
    except Exception:
        pass


def cmd_version(args):
    """Show version."""
    _print_version_info(check_updates=True)


# Build/desktop/update machinery — extrait dans _update_build.py.
from naabiga_cli._update_build import (  # noqa: E402
    _cleanup_quarantined_exes,
    _kill_stale_dashboard_processes,
    _recover_from_interrupted_install,
    cmd_update,
)


def cmd_uninstall(args):
    """Uninstall Naabiga Agent (or just the Chat GUI with --gui)."""
    # Machine-readable install snapshot for the desktop app's uninstall UI.
    # Must run before any TTY gate — it's called from a non-interactive child.
    if getattr(args, "gui_summary", False):
        from naabiga_cli.gui_uninstall import gui_install_summary

        print(json.dumps(gui_install_summary()))
        return

    # GUI-only uninstall. The desktop app shells out to this non-interactively
    # with --yes, so only gate on a TTY when we actually need to prompt.
    if getattr(args, "gui", False):
        if not getattr(args, "yes", False):
            _require_tty("uninstall --gui")
        from naabiga_cli.uninstall import run_gui_uninstall

        run_gui_uninstall(args)
        return

    # Full/keep-data uninstall. ``--yes`` runs non-interactively (the desktop
    # app's lite/full modes drive this from a detached cleanup script), so only
    # gate on a TTY when we actually need to prompt for the option + confirm.
    if not getattr(args, "yes", False):
        _require_tty("uninstall")
    from naabiga_cli.uninstall import run_uninstall

    run_uninstall(args)
# Critical files that Naabiga must be able to import immediately after an
# update/install. Most are imported on every CLI startup; ``web_server.py``
# is the desktop/dashboard backend path that a fresh Windows install launches
# right away. If any of these fail to parse after a pull, the user can be
# left with a bricked CLI or desktop backend. The post-pull syntax guard
# validates these and auto-rolls-back on failure.
_UPDATE_CRITICAL_FILES = (
    "naabiga_cli/main.py",
    "naabiga_cli/config.py",
    "naabiga_cli/__init__.py",
    "naabiga_cli/web_server.py",
    "cli.py",
    "run_agent.py",
    "model_tools.py",
    "toolsets.py",
    "naabiga_constants.py",
)
# ---------------------------------------------------------------------------
# Desktop build stamp — content-hash based skip logic
# ---------------------------------------------------------------------------
# The desktop Electron build is expensive.
# Unlike the web UI (which uses mtime comparison), the desktop uses a
# SHA-256 content hash of the source tree so that:
#   - ``git checkout`` / ``git pull`` that touch mtimes but not content
#     don't trigger a rebuild
#   - ``naabiga update`` can unconditionally call ``naabiga desktop --build-only``
#     and it will skip if nothing actually changed
#   - ``naabiga desktop`` (interactive launch) skips the build when the
#     stamp matches, making repeated launches fast
#
# Stamp file: $NAABIGA_HOME/desktop-build-stamp.json
# Schema:
#   {
#     "contentHash": "<sha256 hex of source files>",
#     "sourceMode": true | false,
#     "builtAt": "<ISO 8601>"
#   }
# Last-resort Electron mirror after GitHub download fails (#47266). Only used
# when the user hasn't pinned ELECTRON_MIRROR.
_ELECTRON_FALLBACK_MIRROR = "https://npmmirror.com/mirrors/electron/"
# Back-compat alias: some tests and any external callers may import the old
# warn-only name.  The new behaviour (kill stale processes) replaces it.
_warn_stale_dashboard_processes = _kill_stale_dashboard_processes
# =========================================================================
# Fork detection and upstream management for `naabiga update`
# =========================================================================

OFFICIAL_REPO_URLS = {
    "https://github.com/NousResearch/hermes-agent.git",
    "git@github.com:NousResearch/hermes-agent.git",
    "https://github.com/NousResearch/hermes-agent",
    "git@github.com:NousResearch/hermes-agent",
}
OFFICIAL_REPO_URL = "https://github.com/NousResearch/hermes-agent.git"
SKIP_UPSTREAM_PROMPT_FILE = ".skip_upstream_prompt"
# Install-scoped breadcrumb dropped right before ``naabiga update`` mutates the
# venv and cleared only after the dependency install verifies clean.  If a user
# kills the update mid-install (Ctrl-C, terminal close, WSL OOM), the marker
# survives and the next ``naabiga`` launch finishes the install instead of
# limping along on a half-built venv (e.g. pip wiped, a core dep like Pillow
# never landed).  Lives next to the venv (not under $NAABIGA_HOME) because the
# venv is shared across all profiles, so a single marker covers every profile.
def _coalesce_session_name_args(argv: list) -> list:
    """Join unquoted multi-word session names after -c/--continue and -r/--resume.

    When a user types ``naabiga -c Pokemon Agent Dev`` without quoting the
    session name, argparse sees three separate tokens.  This function merges
    them into a single argument so argparse receives
    ``['-c', 'Pokemon Agent Dev']`` instead.

    Tokens are collected after the flag until we hit another flag (``-*``)
    or a known top-level subcommand.
    """
    _SUBCOMMANDS = {
        "chat",
        "model",
        "gateway",
        "setup",
        "whatsapp",
        "whatsapp-cloud",
        "login",
        "logout",
        "auth",
        "status",
        "cron",
        "doctor",
        "config",
        "pairing",
        "skills",
        "tools",
        "mcp",
        "sessions",
        "insights",
        "version",
        "update",
        "uninstall",
        "profile",
        "dashboard",
        "serve",
        "desktop",
        "gui",
        "honcho",
        "claw",
        "plugins",
        "security",
        "acp",
        "webhook",
        "memory",
        "dump",
        "debug",
        "backup",
        "import",
        "completion",
        "logs",
    }
    _SESSION_FLAGS = {"-c", "--continue", "-r", "--resume"}

    result = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in _SESSION_FLAGS:
            result.append(token)
            i += 1
            # Collect subsequent non-flag, non-subcommand tokens as one name
            parts: list = []
            while (
                i < len(argv)
                and not argv[i].startswith("-")
                and argv[i] not in _SUBCOMMANDS
            ):
                parts.append(argv[i])
                i += 1
            if parts:
                result.append(" ".join(parts))
        else:
            result.append(token)
            i += 1
    return result
def _dashboard_listening(host: str, port: int) -> bool:
    """True when something is accepting TCP connections at host:port.

    Any listener counts — even a 401 response proves a dashboard is up.
    Used by the unified profile-launch routing to decide attach-vs-start.
    """
    import socket

    try:
        with socket.create_connection((host or "127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def cmd_dashboard(args):
    """Naabiga: the web dashboard was removed — Naabiga is CLI-only."""
    print("✗ Naabiga is CLI-only: the web dashboard (naabiga dashboard / serve) has been removed.")
    print("  Use `naabiga chat`, `naabiga -q \"...\"`, or `naabiga` to interact with the agent.")
    sys.exit(1)


def cmd_dashboard_register(args):
    """Naabiga: dashboard OAuth registration was removed with the dashboard."""
    print("✗ Naabiga is CLI-only: the dashboard OAuth client (naabiga dashboard register) has been removed.")
    sys.exit(1)


def cmd_gateway_enroll(args):
    """Enroll a self-hosted gateway with a relay connector."""
    from naabiga_cli.gateway_enroll import cmd_gateway_enroll as _impl

    _impl(args)


def cmd_completion(args, parser=None):
    """Print shell completion script."""
    from naabiga_cli.completion import generate_bash, generate_zsh, generate_fish

    shell = getattr(args, "shell", "bash")
    if shell == "zsh":
        print(generate_zsh(parser))
    elif shell == "fish":
        print(generate_fish(parser))
    else:
        print(generate_bash(parser))


def cmd_prompt_size(args):
    """Show a byte/char breakdown of the system prompt + tool schemas."""
    from naabiga_cli.prompt_size import cmd_prompt_size as _impl

    _impl(args)


def cmd_logs(args):
    """View and filter Naabiga log files."""
    from naabiga_cli.logs import tail_log, list_logs

    log_name = getattr(args, "log_name", "agent") or "agent"

    if log_name == "list":
        list_logs()
        return

    tail_log(
        log_name,
        num_lines=getattr(args, "lines", 50),
        follow=getattr(args, "follow", False),
        level=getattr(args, "level", None),
        session=getattr(args, "session", None),
        since=getattr(args, "since", None),
        component=getattr(args, "component", None),
    )


def cmd_console(args):
    """Naabiga: the GUI command console was removed — Naabiga is CLI-only."""
    print("✗ Naabiga is CLI-only: the command console (naabiga console) has been removed.")
    print("  Use `naabiga chat`, `naabiga -q \"...\"`, or `naabiga` to interact with the agent.")
    sys.exit(1)


def _build_provider_choices() -> list[str]:
    """Build the --provider choices list from CANONICAL_PROVIDERS + 'auto'."""
    try:
        from naabiga_cli.models import CANONICAL_PROVIDERS as _cp
        return ["auto"] + [p.slug for p in _cp]
    except Exception:
        # Fallback: static list guarantees the CLI always works
        return [
            "auto", "openrouter", "nous", "openai-codex", "xai-oauth", "copilot-acp", "copilot",
            "anthropic", "gemini", "vertex", "xai", "bedrock", "azure-foundry",
            "ollama-cloud", "huggingface", "zai", "kimi-coding", "kimi-coding-cn",
            "stepfun", "minimax", "minimax-cn", "kilocode", "novita", "xiaomi", "arcee",
            "nvidia", "deepseek", "alibaba", "qwen-oauth", "opencode-zen", "opencode-go",
        ]


# Top-level subcommands that argparse knows about WITHOUT running plugin
# discovery.  Used to short-circuit eager plugin imports (which can take
# 500ms+ pulling in google.cloud.pubsub_v1, aiohttp, grpc, etc.) when the
# user's invocation clearly doesn't need any plugin-registered subcommand.
#
# Keep this in sync with the ``subparsers.add_parser("NAME", ...)`` calls
# below in ``main()``. Missing an entry here only costs a one-time
# discovery; extra entries here would let a plugin command silently fail
# to parse.
_BUILTIN_SUBCOMMANDS = frozenset(
    {
        "acp", "auth", "backup", "bundles", "checkpoints", "claw", "completion",
        "computer-use",
        "config", "console", "cron", "curator", "dashboard", "serve", "debug", "doctor",
        "dump", "fallback", "gateway", "hooks", "import", "insights",
        "gui", "desktop", "kanban", "login", "logout", "logs", "lsp", "mcp", "memory", "migrate", "moa",
        "journey", "memory-graph", "learning",
        "model", "pairing", "pets", "plugins", "portal", "postinstall", "profile",
        "project", "proxy",
        "prompt-size",
        "send", "sessions", "setup",
        "skills", "slack", "status", "tools", "uninstall", "update",
        "version", "webhook", "whatsapp", "whatsapp-cloud", "chat", "secrets", "security",
        # Help-ish invocations — plugin commands not being listed in
        # top-level --help is an acceptable trade-off for skipping an
        # expensive eager import of every bundled plugin module.
        "help",
    }
)


# Top-level flags that take a value. Needed by ``_first_positional_argv``
# so that in ``naabiga -m gpt5 chat``, ``gpt5`` is correctly skipped as a
# flag value rather than misclassified as a subcommand. Kept in sync with
# the top-level flags declared in ``naabiga_cli/_parser.py``.
#
# Correctness-safe either way: missing an entry here only makes the
# fast-path bail out too eagerly (we run plugin discovery when we didn't
# need to); extra entries would make us skip a real positional.
_TOP_LEVEL_VALUE_FLAGS = frozenset(
    {
        "-z", "--oneshot",
        "-m", "--model",
        "--provider",
        "-t", "--toolsets",
        "-r", "--resume",
        "-s", "--skills",
        "--usage-file",
        # ``-c / --continue`` is nargs='?' (optional value). Treat it as
        # value-taking: if the next token is a subcommand-looking word
        # the user almost certainly meant it as the session name, and
        # either interpretation keeps us on the safe side.
        "-c", "--continue",
    }
)


def _first_positional_argv() -> str | None:
    """Return the first non-flag, non-flag-value token in ``sys.argv[1:]``.

    Used by ``main()`` to decide whether plugin discovery has to run at
    argparse-setup time. Handles common invocations like
    ``naabiga -m gpt5 --provider openai chat "msg"`` by skipping the
    values attached to known top-level flags.

    Does NOT fully simulate argparse — unknown ``--foo=bar`` / ``--foo
    bar`` flags degrade gracefully (``bar`` may be wrongly classified as
    a positional, which at worst forces a one-time plugin discovery).
    """
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            # Everything after ``--`` is positional.
            if i + 1 < len(argv):
                return argv[i + 1]
            return None
        if tok.startswith("-"):
            # ``--flag=value`` carries its value inline — single token.
            if "=" in tok:
                i += 1
                continue
            if tok in _TOP_LEVEL_VALUE_FLAGS and i + 1 < len(argv):
                i += 2
                continue
            i += 1
            continue
        return tok
    return None


def _plugin_cli_discovery_needed() -> bool:
    """True when the CLI might be invoking a plugin-registered subcommand.

    Returning False lets ``main()`` skip plugin discovery entirely during
    argparse setup, saving ~500-650ms per invocation for users whose
    enabled plugins don't contribute any CLI command.
    """
    first = _first_positional_argv()
    if first is None:
        # Bare ``naabiga`` or only flags → defaults to ``chat``.
        return False
    if first in _BUILTIN_SUBCOMMANDS:
        return False
    # Unknown token — could be a plugin subcommand, OR a chat prompt
    # starting with a non-flag word. Either way we need discovery: if it
    # IS a plugin command, argparse needs the subparser; if it's a chat
    # prompt, argparse will route it via positional handling and the
    # extra discovery cost is amortized over a full agent run anyway.
    return True


_AGENT_COMMANDS = {None, "chat", "acp", "rl"}
_AGENT_SUBCOMMANDS = {
    "cron": ("cron_command", {"run", "tick"}),
    "gateway": ("gateway_command", {"run"}),
    "mcp": ("mcp_action", {"serve"}),
}


def _is_tui_chat_launch(args) -> bool:
    return bool(getattr(args, "tui", False) or os.environ.get("NAABIGA_TUI") == "1")


def _command_has_dedicated_mcp_startup(args) -> bool:
    if args.command == "acp":
        return True
    if args.command == "gateway" and getattr(args, "gateway_command", None) == "run":
        return True
    if args.command == "cron" and getattr(args, "cron_command", None) in {"run", "tick"}:
        return True
    return False


def _should_background_mcp_startup(args) -> bool:
    if _is_tui_chat_launch(args):
        return False
    return args.command in {None, "chat", "rl"}


def _prepare_agent_startup(args) -> None:
    """Discover plugins/MCP/hooks for commands that can run an agent turn."""
    _apply_safe_mode(args)

    _sub_attr, _sub_set = _AGENT_SUBCOMMANDS.get(args.command, (None, None))
    if not (
        args.command in _AGENT_COMMANDS
        or (_sub_attr and getattr(args, _sub_attr, None) in _sub_set)
    ):
        return

    _accept_hooks = bool(getattr(args, "accept_hooks", False))
    try:
        from naabiga_cli.plugins import discover_plugins

        discover_plugins()
    except Exception:
        logger.warning(
            "plugin discovery failed at CLI startup",
            exc_info=True,
        )
    _run_inline_mcp_discovery = True
    if _is_tui_chat_launch(args):
        # The TUI launcher hands off to a dedicated startup path that already
        # backgrounds MCP discovery with a bounded join before the first tool
        # snapshot.
        _run_inline_mcp_discovery = False
    elif _command_has_dedicated_mcp_startup(args):
        # These entrypoints already do their own MCP startup later on the real
        # runtime path (gateway executor, ACP launcher, cron job runner).
        _run_inline_mcp_discovery = False
    elif _should_background_mcp_startup(args):
        try:
            from naabiga_cli.mcp_startup import start_background_mcp_discovery

            start_background_mcp_discovery(
                logger=logger,
                thread_name="cli-mcp-discovery",
            )
        except Exception:
            logger.debug(
                "Background MCP tool discovery failed at CLI startup",
                exc_info=True,
            )
        _run_inline_mcp_discovery = False
    if _run_inline_mcp_discovery:
        try:
            # MCP tool discovery remains synchronous for entrypoints that do
            # not own a later bounded/executor startup path.
            from tools.mcp_tool import discover_mcp_tools

            discover_mcp_tools()
        except Exception:
            logger.debug(
                "MCP tool discovery failed at CLI startup",
                exc_info=True,
            )
    try:
        from naabiga_cli.config import load_config
        from agent.shell_hooks import register_from_config

        register_from_config(load_config(), accept_hooks=_accept_hooks)
    except Exception:
        logger.debug(
            "shell-hook registration failed at CLI startup",
            exc_info=True,
        )


def _apply_safe_mode(args) -> None:
    if not getattr(args, "safe_mode", False):
        return
    os.environ["NAABIGA_SAFE_MODE"] = "1"
    os.environ["NAABIGA_IGNORE_USER_CONFIG"] = "1"
    os.environ["NAABIGA_IGNORE_RULES"] = "1"


def _set_chat_arg_defaults(args) -> None:
    for attr, default in [
        ("query", None),
        ("model", None),
        ("provider", None),
        ("toolsets", None),
        ("verbose", False),
        ("resume", None),
        ("continue_last", None),
        ("worktree", False),
    ]:
        if not hasattr(args, attr):
            setattr(args, attr, default)


def _try_termux_fast_cli_launch() -> bool:
    """Run obvious Termux non-TUI chat/oneshot/version paths on a light parser."""
    if not _is_termux_startup_environment():
        return False
    if os.environ.get("NAABIGA_TERMUX_DISABLE_FAST_CLI") == "1":
        return False

    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        return False
    # Let the TUI fast path (or full dispatch) handle anything that resolves to
    # the TUI — explicit --tui/env or display.interface=tui. `--cli` forces this
    # to stay False so the classic fast path still runs.
    if _wants_tui_early(argv):
        return False

    if _is_termux_fast_version_argv(argv):
        _print_version_info(check_updates=False)
        return True

    first = _first_positional_argv()
    has_oneshot = any(
        arg == "-z" or arg == "--oneshot" or arg.startswith("--oneshot=")
        for arg in argv
    )
    if not has_oneshot and first not in {None, "chat"}:
        return False

    from naabiga_cli._parser import build_top_level_parser

    parser, _subparsers, chat_parser = build_top_level_parser()
    chat_parser.set_defaults(func=cmd_chat)
    args = parser.parse_args(_coalesce_session_name_args(argv))

    if getattr(args, "version", False):
        _print_version_info(check_updates=False)
        return True

    if getattr(args, "oneshot", None):
        _prepare_agent_startup(args)
        from naabiga_cli.oneshot import run_oneshot

        sys.exit(
            run_oneshot(
                args.oneshot,
                model=getattr(args, "model", None),
                provider=getattr(args, "provider", None),
                toolsets=getattr(args, "toolsets", None),
                usage_file=getattr(args, "usage_file", None),
            )
        )

    if (args.resume or args.continue_last) and args.command is None:
        args.command = "chat"

    if args.command in {None, "chat"}:
        _set_chat_arg_defaults(args)
        interactive_prompt = not getattr(args, "query", None) and not getattr(args, "image", None)
        if interactive_prompt:
            # Bare Termux CLI should reach the prompt first and do agent-only
            # discovery on the first submitted turn instead of before input.
            args.compact = True
            os.environ["NAABIGA_DEFER_AGENT_STARTUP"] = "1"
            os.environ["NAABIGA_FAST_STARTUP_BANNER"] = "1"
            if getattr(args, "accept_hooks", False):
                os.environ["NAABIGA_ACCEPT_HOOKS"] = "1"
        else:
            _prepare_agent_startup(args)
        cmd_chat(args)
        return True

    return False


def _try_termux_fast_tui_launch() -> bool:
    """Launch obvious Termux TUI invocations before building every subparser.

    `naabiga --tui` is the hot path on phones. The full parser setup imports
    command modules for model, fallback, migrate, kanban, bundles, plugins,
    etc. even though the TUI immediately execs Node. On Termux only, parse the
    lightweight top-level/chat parser and hand off to ``cmd_chat`` when the
    invocation is unambiguously the built-in TUI/chat path.
    """
    if not _is_termux_startup_environment():
        return False

    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        return False

    wants_tui = _wants_tui_early(sys.argv[1:])
    if not wants_tui:
        return False

    first = _first_positional_argv()
    if first not in {None, "chat"}:
        return False

    from naabiga_cli._parser import build_top_level_parser

    parser, _subparsers, chat_parser = build_top_level_parser()
    chat_parser.set_defaults(func=cmd_chat)
    args = parser.parse_args(_coalesce_session_name_args(sys.argv[1:]))

    # Preserve top-level behaviours whose semantics are not "launch chat/TUI".
    if getattr(args, "version", False) or getattr(args, "oneshot", None):
        return False
    if getattr(args, "command", None) not in {None, "chat"}:
        return False
    if not _resolve_use_tui(args):
        return False

    cmd_chat(args)
    return True


def cmd_memory(args):
    sub = getattr(args, "memory_command", None)
    if sub == "off":
        from naabiga_cli.config import load_config, save_config

        config = load_config()
        if not isinstance(config.get("memory"), dict):
            config["memory"] = {}
        config["memory"]["provider"] = ""
        save_config(config)
        print("\n  ✓ Memory provider: built-in only")
        print("  Saved to config.yaml\n")
    elif sub == "reset":
        from naabiga_constants import get_naabiga_home, display_naabiga_home

        mem_dir = get_naabiga_home() / "memories"
        target = getattr(args, "target", "all")
        files_to_reset = []
        if target in {"all", "memory"}:
            files_to_reset.append(("MEMORY.md", "agent notes"))
        if target in {"all", "user"}:
            files_to_reset.append(("USER.md", "user profile"))

        # Check what exists
        existing = [
            (f, desc) for f, desc in files_to_reset if (mem_dir / f).exists()
        ]
        if not existing:
            print(
                f"\n  Nothing to reset — no memory files found in {display_naabiga_home()}/memories/\n"
            )
            return

        print("\n  This will permanently erase the following memory files:")
        for f, desc in existing:
            path = mem_dir / f
            size = path.stat().st_size
            print(f"    ◆ {f} ({desc}) — {size:,} bytes")

        if not getattr(args, "yes", False):
            try:
                answer = input("\n  Type 'yes' to confirm: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled.\n")
                return
            if answer != "yes":
                print("  Cancelled.\n")
                return

        for f, desc in existing:
            (mem_dir / f).unlink()
            print(f"  ✓ Deleted {f} ({desc})")

        print(
            "\n  Memory reset complete. New sessions will start with a blank slate."
        )
        print(f"  Files were in: {display_naabiga_home()}/memories/\n")
    else:
        from naabiga_cli.memory_setup import memory_command

        memory_command(args)


def cmd_acp(args):
    """Launch Naabiga Agent as an ACP server."""
    try:
        from acp_adapter.entry import main as acp_main

        acp_argv = []
        if getattr(args, "acp_version", False):
            acp_argv.append("--version")
        if getattr(args, "check", False):
            acp_argv.append("--check")
        if getattr(args, "setup", False):
            acp_argv.append("--setup")
        if getattr(args, "setup_browser", False):
            acp_argv.append("--setup-browser")
        if getattr(args, "assume_yes", False):
            acp_argv.append("--yes")
        acp_main(acp_argv)
    except ImportError:
        print("ACP dependencies not installed.", file=sys.stderr)
        print("Install them with:  pip install -e '.[acp]'", file=sys.stderr)
        sys.exit(1)


def cmd_tools(args):
    action = getattr(args, "tools_action", None)
    if action in {"list", "disable", "enable"}:
        from naabiga_cli.tools_config import tools_disable_enable_command

        tools_disable_enable_command(args)
    elif action == "post-setup":
        from naabiga_cli.tools_config import run_post_setup_command

        sys.exit(run_post_setup_command(args))
    else:
        _require_tty("tools")
        from naabiga_cli.tools_config import tools_command

        tools_command(args)


def cmd_insights(args):
    try:
        from naabiga_state import SessionDB
        from agent.insights import InsightsEngine

        db = SessionDB()
        engine = InsightsEngine(db)
        report = engine.generate(days=args.days, source=args.source)
        print(engine.format_terminal(report))
        db.close()
    except Exception as e:
        print(f"Error generating insights: {e}")


def cmd_skills(args):
    # Route 'config' action to skills_config module
    if getattr(args, "skills_action", None) == "config":
        _require_tty("skills config")
        from naabiga_cli.skills_config import skills_command as skills_config_command

        skills_config_command(args)
    else:
        from naabiga_cli.skills_hub import skills_command

        skills_command(args)


def cmd_pairing(args):
    from naabiga_cli.pairing import pairing_command

    pairing_command(args)


def cmd_plugins(args):
    from naabiga_cli.plugins_cmd import plugins_command

    plugins_command(args)


def cmd_mcp(args):
    from naabiga_cli.mcp_config import mcp_command

    mcp_command(args)


def cmd_claw(args):
    from naabiga_cli.claw import claw_command

    claw_command(args)


# Profile & dashboard — extrait dans _profile_cmd.py.
from naabiga_cli._profile_cmd import (  # noqa: E402
    cmd_profile,
)


def main():
    """Main entry point for naabiga CLI."""
    # Cosmetic: make the process show up as 'naabiga' instead of 'python3.11'
    # in ps/top/htop.  Non-fatal — just a nicer UX.
    _set_process_title()

    # Force UTF-8 stdio on Windows before anything prints.  No-op elsewhere.
    try:
        from naabiga_cli.stdio import configure_windows_stdio
        configure_windows_stdio()
    except Exception:
        pass

    # Sweep stale ``naabiga.exe.old.*`` quarantine files left by previous
    # ``naabiga update`` runs on Windows. Silent no-op on non-Windows or when
    # there's nothing to clean. See ``_quarantine_running_naabiga_exe``.
    try:
        _cleanup_quarantined_exes()
    except Exception:
        pass

    # Self-heal a venv left half-built by an interrupted ``naabiga update``
    # (Ctrl-C, terminal close, WSL OOM mid-install). Skip when the user is
    # *running* update — that flow writes and clears its own marker, and we
    # don't want a recovery install racing the real one. Never raises.
    #
    # The substring match is deliberately loose: argv isn't parsed yet at this
    # point, and the failure modes are asymmetric. Over-matching (e.g.
    # ``naabiga skills install update``) merely defers recovery one launch;
    # under-matching (missing ``naabiga -p work update``) would race a recovery
    # install against the real one. Loose wins.
    try:
        if "update" not in sys.argv[1:]:
            _recover_from_interrupted_install()
    except Exception:
        pass

    if _try_termux_fast_tui_launch():
        return
    if _try_termux_fast_cli_launch():
        return

    from naabiga_cli._parser import build_top_level_parser

    parser, subparsers, chat_parser = build_top_level_parser()
    chat_parser.set_defaults(func=cmd_chat)

    # =========================================================================
    # model command  (parser built in naabiga_cli/subcommands/model.py)
    # =========================================================================
    build_model_parser(subparsers, cmd_model=cmd_model)

    from naabiga_cli.moa_cmd import cmd_moa

    moa_parser = subparsers.add_parser(
        "moa",
        help="Configure Mixture of Agents provider/model slots",
        description="Configure the provider/model set used by /moa <prompt>.",
    )
    moa_subparsers = moa_parser.add_subparsers(dest="moa_command")
    moa_subparsers.add_parser("list", aliases=["ls"], help="Show current MoA model slots")
    moa_configure = moa_subparsers.add_parser("configure", aliases=["config"], help="Interactively pick MoA models")
    moa_configure.add_argument("name", nargs="?", help="Preset name to create or update")
    moa_delete = moa_subparsers.add_parser("delete", aliases=["rm"], help="Delete a MoA preset")
    moa_delete.add_argument("name", help="Preset name to delete")
    moa_parser.set_defaults(func=cmd_moa)

    # =========================================================================
    # fallback command — manage the fallback provider chain
    # =========================================================================
    from naabiga_cli.fallback_cmd import cmd_fallback

    fallback_parser = subparsers.add_parser(
        "fallback",
        help="Manage fallback providers (tried when the primary model fails)",
        description=(
            "Manage the fallback provider chain.  Fallback providers are tried "
            "in order when the primary model fails with rate-limit, overload, or "
            "connection errors.  See: "
            "https://github.com/n8nprobf-hub/Naabiga#readme"
        ),
    )
    fallback_subparsers = fallback_parser.add_subparsers(dest="fallback_command")
    fallback_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="Show the current fallback chain (default when no subcommand)",
    )
    fallback_subparsers.add_parser(
        "add",
        help="Pick a provider + model (same picker as `naabiga model`) and append to the chain",
    )
    fallback_subparsers.add_parser(
        "remove",
        aliases=["rm"],
        help="Pick an entry to delete from the chain",
    )
    fallback_subparsers.add_parser(
        "clear",
        help="Remove all fallback entries",
    )
    fallback_parser.set_defaults(func=cmd_fallback)

    # =========================================================================
    # secrets command — external secret managers (Bitwarden, 1Password)
    # =========================================================================
    secrets_parser = subparsers.add_parser(
        "secrets",
        help="Manage external secret sources (Bitwarden, 1Password)",
        description=(
            "Pull API keys from an external secret manager at process startup "
            "instead of storing them in ~/.naabiga/.env.  Supports Bitwarden "
            "Secrets Manager and 1Password.  See: "
            "https://github.com/n8nprobf-hub/Naabiga#readme"
        ),
    )
    secrets_subparsers = secrets_parser.add_subparsers(dest="secrets_command")

    secrets_bw = secrets_subparsers.add_parser(
        "bitwarden",
        aliases=["bw"],
        help="Bitwarden Secrets Manager integration",
    )

    secrets_op = secrets_subparsers.add_parser(
        "onepassword",
        aliases=["op", "1password"],
        help="1Password (op:// references) integration",
    )

    # Lazy import — only pays for itself when this subcommand is actually used.
    from naabiga_cli import secrets_cli as _secrets_cli
    from naabiga_cli import onepassword_secrets_cli as _op_secrets_cli

    _secrets_cli.register_cli(secrets_bw)
    _op_secrets_cli.register_cli(secrets_op)

    def _dispatch_secrets(args):  # noqa: ANN001
        sub = getattr(args, "secrets_command", None)
        bw_sub = getattr(args, "secrets_bw_command", None)
        op_sub = getattr(args, "secrets_op_command", None)
        if sub in ("bitwarden", "bw") and bw_sub is not None:
            return args.func(args)
        if sub in ("onepassword", "op", "1password") and op_sub is not None:
            return args.func(args)
        secrets_parser.print_help()
        return 0

    secrets_parser.set_defaults(func=_dispatch_secrets)

    # =========================================================================
    # migrate command
    # =========================================================================
    from naabiga_cli.migrate import cmd_migrate, cmd_migrate_xai

    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate configuration for retired models or deprecated settings",
        description=(
            "Diagnose and (optionally) rewrite the active config.yaml to "
            "replace references to retired models or deprecated settings."
        ),
    )
    migrate_subparsers = migrate_parser.add_subparsers(dest="migrate_type")

    migrate_xai = migrate_subparsers.add_parser(
        "xai",
        help="Migrate xAI models scheduled for retirement on May 15, 2026",
        description=(
            "Scan config.yaml for references to xAI models retiring on "
            "May 15, 2026 and, with --apply, rewrite them in-place to the "
            "official replacements per the xAI migration guide. The original "
            "config.yaml is backed up before any rewrite."
        ),
    )
    migrate_xai.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite config.yaml in-place (default: dry-run, no writes)",
    )
    migrate_xai.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the timestamped backup of config.yaml when applying",
    )
    migrate_xai.set_defaults(func=cmd_migrate_xai)
    migrate_parser.set_defaults(func=cmd_migrate)

    # =========================================================================
    # gateway + proxy commands  (parsers built in naabiga_cli/subcommands/gateway.py)
    # =========================================================================
    build_gateway_parser(
        subparsers, cmd_gateway=cmd_gateway, cmd_proxy=cmd_proxy, cmd_gateway_enroll=cmd_gateway_enroll
    )

    # =========================================================================
    # lsp command
    # =========================================================================
    try:
        from agent.lsp.cli import register_subparser as _lsp_register
        _lsp_register(subparsers)
    except Exception as _lsp_err:  # noqa: BLE001
        # LSP is optional infrastructure — never let a registration
        # failure break the CLI overall.
        logger.debug("LSP CLI registration failed: %s", _lsp_err)

    # =========================================================================
    # setup command  (parser built in naabiga_cli/subcommands/setup.py)
    # =========================================================================
    build_setup_parser(subparsers, cmd_setup=cmd_setup)

    # =========================================================================
    # postinstall command  (parser built in naabiga_cli/subcommands/postinstall.py)
    # =========================================================================
    build_postinstall_parser(subparsers, cmd_postinstall=cmd_postinstall)

    # =========================================================================
    # whatsapp command  (parser built in naabiga_cli/subcommands/whatsapp.py)
    # =========================================================================
    build_whatsapp_parser(subparsers, cmd_whatsapp=cmd_whatsapp)

    # =========================================================================
    # whatsapp-cloud command (official Meta Cloud API; complement to Baileys)
    # =========================================================================
    whatsapp_cloud_parser = subparsers.add_parser(
        "whatsapp-cloud",
        help="Set up WhatsApp Business Cloud API integration",
        description=(
            "Configure the official Meta WhatsApp Business Cloud API "
            "adapter (Business account required, public webhook URL "
            "required). Distinct from `naabiga whatsapp` which sets up "
            "the Baileys bridge for personal accounts."
        ),
    )
    whatsapp_cloud_parser.set_defaults(func=cmd_whatsapp_cloud)

    # =========================================================================
    # slack command  (parser built in naabiga_cli/subcommands/slack.py)
    # =========================================================================
    build_slack_parser(subparsers, cmd_slack=cmd_slack)

    # =========================================================================
    # send command — pipe shell-script output to any configured platform
    # =========================================================================
    from naabiga_cli.send_cmd import register_send_subparser
    register_send_subparser(subparsers)

    # =========================================================================
    # login command  (parser built in naabiga_cli/subcommands/login.py)
    # =========================================================================
    build_login_parser(subparsers, cmd_login=cmd_login)

    # =========================================================================
    # logout command  (parser built in naabiga_cli/subcommands/logout.py)
    # =========================================================================
    build_logout_parser(subparsers, cmd_logout=cmd_logout)

    # =========================================================================
    # auth command  (parser built in naabiga_cli/subcommands/auth.py)
    # =========================================================================
    build_auth_parser(subparsers, cmd_auth=cmd_auth)

    # =========================================================================
    # status command  (parser built in naabiga_cli/subcommands/status.py)
    # =========================================================================
    build_status_parser(subparsers, cmd_status=cmd_status)

    # =========================================================================
    # cron command  (parser built in naabiga_cli/subcommands/cron.py)
    # =========================================================================
    build_cron_parser(subparsers, cmd_cron=cmd_cron)

    # =========================================================================
    # webhook command  (parser built in naabiga_cli/subcommands/webhook.py)
    # =========================================================================
    build_webhook_parser(subparsers, cmd_webhook=cmd_webhook)

    # =========================================================================
    # kanban command — multi-profile collaboration board
    # =========================================================================
    from naabiga_cli.kanban import build_parser as _build_kanban_parser

    kanban_parser = _build_kanban_parser(subparsers)
    kanban_parser.set_defaults(func=cmd_kanban)

    # =========================================================================
    # project command — named, multi-folder workspaces
    # =========================================================================
    from naabiga_cli.projects_cmd import build_parser as _build_project_parser

    project_parser = _build_project_parser(subparsers)
    project_parser.set_defaults(func=cmd_project)

    # =========================================================================
    # hooks command — shell-hook inspection and management
    # =========================================================================
    # hooks command  (parser built in naabiga_cli/subcommands/hooks.py)
    # =========================================================================
    build_hooks_parser(subparsers, cmd_hooks=cmd_hooks)

    # =========================================================================
    # doctor command  (parser built in naabiga_cli/subcommands/doctor.py)
    # =========================================================================
    build_doctor_parser(subparsers, cmd_doctor=cmd_doctor)

    # =========================================================================
    # security command — on-demand supply-chain audit
    # =========================================================================
    # security command  (parser built in naabiga_cli/subcommands/security.py)
    # =========================================================================
    build_security_parser(subparsers, cmd_security=cmd_security)

    # =========================================================================
    # dump command  (parser built in naabiga_cli/subcommands/dump.py)
    # =========================================================================
    build_dump_parser(subparsers, cmd_dump=cmd_dump)

    # =========================================================================
    # debug command  (parser built in naabiga_cli/subcommands/debug.py)
    # =========================================================================
    build_debug_parser(subparsers, cmd_debug=cmd_debug)

    # =========================================================================
    # backup command  (parser built in naabiga_cli/subcommands/backup.py)
    # =========================================================================
    build_backup_parser(subparsers, cmd_backup=cmd_backup)

    # =========================================================================
    # checkpoints command
    # =========================================================================
    checkpoints_parser = subparsers.add_parser(
        "checkpoints",
        help="Inspect / prune / clear ~/.naabiga/checkpoints/",
        description="Manage the filesystem checkpoint store — the shadow git "
        "repo naabiga uses to snapshot working directories before "
        "write_file/patch/terminal calls. Lets you see how much "
        "space checkpoints occupy, force a prune, or wipe the base.",
    )
    from naabiga_cli.checkpoints import register_cli as _register_checkpoints_cli
    _register_checkpoints_cli(checkpoints_parser)

    # =========================================================================
    # import command  (parser built in naabiga_cli/subcommands/import_cmd.py)
    # =========================================================================
    build_import_cmd_parser(subparsers, cmd_import=cmd_import)

    # =========================================================================
    # config command  (parser built in naabiga_cli/subcommands/config.py)
    # =========================================================================
    build_config_parser(subparsers, cmd_config=cmd_config)

    # =========================================================================
    # console command  (REMOVED in Naabiga — CLI-only fork)
    # =========================================================================

    # =========================================================================
    # pairing command  (parser built in naabiga_cli/subcommands/pairing.py)
    # =========================================================================
    build_pairing_parser(subparsers, cmd_pairing=cmd_pairing)

    # =========================================================================
    # skills command  (parser built in naabiga_cli/subcommands/skills.py)
    # =========================================================================
    build_skills_parser(subparsers, cmd_skills=cmd_skills)

    # =========================================================================
    # bundles command — skill bundles (alias /<name> for multiple skills)
    # =========================================================================
    bundles_parser = subparsers.add_parser(
        "bundles",
        help="Create, list, and manage skill bundles (aliases for multiple skills)",
        description=(
            "Skill bundles let you load several skills under one slash "
            "command. `/<bundle>` from the CLI or gateway loads every "
            "referenced skill at once."
        ),
    )
    from naabiga_cli.bundles import register_cli as _bundles_register, bundles_command
    _bundles_register(bundles_parser)
    bundles_parser.set_defaults(func=bundles_command)

    # =========================================================================
    # plugins command  (parser built in naabiga_cli/subcommands/plugins.py)
    # =========================================================================
    build_plugins_parser(subparsers, cmd_plugins=cmd_plugins)

    # =========================================================================
    # Plugin CLI commands — dynamically registered by memory/general plugins.
    # Plugins provide a register_cli(subparser) function that builds their
    # own argparse tree.  No hardcoded plugin commands in main.py.
    #
    # Skipped when the invocation is already targeting a known built-in
    # subcommand — ``naabiga --help``, ``naabiga version``, ``naabiga logs``,
    # etc.  This avoids eagerly importing every bundled plugin module
    # (google.cloud.pubsub_v1, aiohttp, grpc, PIL …) which costs
    # 500-650ms on typical installs.
    # =========================================================================
    if _plugin_cli_discovery_needed():
        try:
            from plugins.memory import discover_plugin_cli_commands
            from naabiga_cli.plugins import discover_plugins, get_plugin_manager

            seen_plugin_commands = set()
            for cmd_info in discover_plugin_cli_commands():
                plugin_parser = subparsers.add_parser(
                    cmd_info["name"],
                    help=cmd_info["help"],
                    description=cmd_info.get("description", ""),
                    formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
                )
                cmd_info["setup_fn"](plugin_parser)
                if cmd_info.get("handler_fn") is not None:
                    plugin_parser.set_defaults(func=cmd_info["handler_fn"])
                seen_plugin_commands.add(cmd_info["name"])

            discover_plugins()
            for cmd_info in get_plugin_manager()._cli_commands.values():
                if cmd_info["name"] in seen_plugin_commands:
                    continue
                plugin_parser = subparsers.add_parser(
                    cmd_info["name"],
                    help=cmd_info["help"],
                    description=cmd_info.get("description", ""),
                    formatter_class=__import__("argparse").RawDescriptionHelpFormatter,
                )
                cmd_info["setup_fn"](plugin_parser)
                if cmd_info.get("handler_fn") is not None:
                    plugin_parser.set_defaults(func=cmd_info["handler_fn"])
        except Exception as _exc:
            logging.getLogger(__name__).debug("Plugin CLI discovery failed: %s", _exc)

    # =========================================================================
    # curator command — background skill maintenance
    # =========================================================================
    curator_parser = subparsers.add_parser(
        "curator",
        help="Background skill maintenance (curator) — status, run, pause, pin",
        description=(
            "The curator is an auxiliary-model background task that "
            "periodically reviews agent-created skills, prunes stale ones, "
            "consolidates overlaps, and archives obsolete skills. "
            "Bundled and hub-installed skills are never touched. "
            "Archives are recoverable; auto-deletion never happens."
        ),
    )
    try:
        from naabiga_cli.curator import register_cli as _register_curator_cli

        _register_curator_cli(curator_parser)
    except Exception as _exc:
        logging.getLogger(__name__).debug("curator CLI wiring failed: %s", _exc)

    # =========================================================================
    # pets command — petdex animated mascots (CLI / TUI / desktop display)
    # =========================================================================
    pets_parser = subparsers.add_parser(
        "pets",
        help="Browse, install, and select petdex animated pets",
        description=(
            "Petdex (https://github.com/crafter-station/petdex) is a public "
            "gallery of animated sprite pets for coding agents. Install one "
            "and Naabiga shows it reacting to agent activity across the CLI, "
            "TUI, and desktop app."
        ),
    )
    try:
        from naabiga_cli.pets import register_cli as _register_pets_cli

        _register_pets_cli(pets_parser)
    except Exception as _exc:
        logging.getLogger(__name__).debug("pets CLI wiring failed: %s", _exc)

    # =========================================================================
    # journey command — learned skills + memories over time, in the terminal
    # =========================================================================
    journey_parser = subparsers.add_parser(
        "journey",
        aliases=["learning", "memory-graph"],
        help="Timeline of learned skills + memories over time",
        description=(
            "A terminal rendition of the desktop Star Map / Memory Graph: a "
            "timeline bar chart of learned skills and memories over time "
            "(oldest at top, newest at bottom) plus a playable constellation "
            "scrubber. Mirrors the TUI `/journey` overlay and the desktop panel."
        ),
    )
    try:
        from naabiga_cli.journey import register_cli as _register_journey_cli

        _register_journey_cli(journey_parser)
    except Exception as _exc:
        logging.getLogger(__name__).debug("journey CLI wiring failed: %s", _exc)

    # =========================================================================
    # memory command  (parser built in naabiga_cli/subcommands/memory.py)
    # =========================================================================
    build_memory_parser(subparsers, cmd_memory=cmd_memory)

    # =========================================================================
    # tools command  (parser built in naabiga_cli/subcommands/tools.py)
    # =========================================================================
    build_tools_parser(subparsers, cmd_tools=cmd_tools)

    # =========================================================================
    # computer-use command — manage Computer Use (cua-driver) on macOS
    # =========================================================================
    computer_use_parser = subparsers.add_parser(
        "computer-use",
        help="Manage the Computer Use (cua-driver) backend (macOS/Windows/Linux)",
        description=(
            "Install or check the cua-driver binary used by the\n"
            "`computer_use` toolset. Supported on macOS, Windows, and\n"
            "Linux.\n\n"
            "Use `naabiga computer-use install` to fetch and run the\n"
            "upstream cua-driver installer. This is equivalent to the\n"
            "post-setup hook that `naabiga tools` runs when you first\n"
            "enable the Computer Use toolset, and is a stable target\n"
            "for re-running the install if it didn't fire (e.g. when\n"
            "toggling the toolset on a returning-user setup).\n\n"
            "Use `naabiga computer-use doctor` to run cua-driver's\n"
            "`health_report` MCP tool and surface its check matrix\n"
            "(TCC, bundle identity, version, platform support, ...)\n"
            "in human-readable form."
        ),
    )
    computer_use_sub = computer_use_parser.add_subparsers(dest="computer_use_action")

    computer_use_install = computer_use_sub.add_parser(
        "install",
        help="Install or repair the cua-driver binary (macOS/Windows/Linux)",
    )
    computer_use_install.add_argument(
        "--upgrade",
        action="store_true",
        help=(
            "Re-run the upstream installer even if cua-driver is already on "
            "PATH. The upstream install.sh always pulls the latest release, "
            "so this performs an in-place upgrade."
        ),
    )
    computer_use_sub.add_parser(
        "status",
        help="Print whether cua-driver is installed and on PATH",
    )
    computer_use_doctor = computer_use_sub.add_parser(
        "doctor",
        help="Run cua-driver `health_report` and surface the check matrix",
        description=(
            "Drive cua-driver's stable `health_report` MCP tool and render\n"
            "its check matrix (TCC permissions, bundle identity, version,\n"
            "platform support, screenshot probe, …) as human-readable\n"
            "output. cua-driver owns the health model; this command stays\n"
            "thin so new checks added upstream surface here without code\n"
            "changes. Exits 0 when overall=ok, 1 when degraded/failed, 2\n"
            "when the binary is missing or unreachable."
        ),
    )
    computer_use_doctor.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="CHECK",
        help=(
            "Run only the listed checks. Repeat for multiple "
            "(e.g. --include tcc_accessibility --include bundle_identity). "
            "Unknown names are reported by cua-driver."
        ),
    )
    computer_use_doctor.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="CHECK",
        help="Skip the listed checks. Repeat for multiple. Wins over --include.",
    )
    computer_use_doctor.add_argument(
        "--json",
        action="store_true",
        help="Emit the raw structured payload as JSON (same shape as `tools/call`).",
    )
    computer_use_perms = computer_use_sub.add_parser(
        "permissions",
        help="Check or grant macOS Accessibility + Screen Recording (macOS)",
        description=(
            "Computer Use drives the Mac through cua-driver, whose TCC grants\n"
            "attach to cua-driver's own identity (com.trycua.driver) — not the\n"
            "terminal or the Naabiga app. `status` reports the driver's grant\n"
            "state; `grant` launches CuaDriver via LaunchServices so the macOS\n"
            "permission dialog is attributed to the process that does the work."
        ),
    )
    computer_use_perms_sub = computer_use_perms.add_subparsers(
        dest="computer_use_perms_action"
    )
    computer_use_perms_status = computer_use_perms_sub.add_parser(
        "status",
        help="Report Accessibility + Screen Recording grant state (read-only)",
    )
    computer_use_perms_status.add_argument(
        "--json",
        action="store_true",
        help="Emit the normalized permission payload as JSON.",
    )
    computer_use_perms_sub.add_parser(
        "grant",
        help="Request the grants (opens the dialog attributed to CuaDriver)",
    )

    def cmd_computer_use(args):
        action = getattr(args, "computer_use_action", None)
        if action == "install":
            from naabiga_cli.tools_config import install_cua_driver
            install_cua_driver(upgrade=bool(getattr(args, "upgrade", False)))
            return
        if action == "status":
            import shutil
            import subprocess
            from naabiga_cli.tools_config import _cua_driver_cmd
            # Honor NAABIGA_CUA_DRIVER_CMD for local-build testing — same
            # resolver `install_cua_driver` and the runtime backend use,
            # so `status` reports what `computer_use` will actually invoke.
            driver_cmd = _cua_driver_cmd()
            path = shutil.which(driver_cmd)
            if path:
                version = ""
                try:
                    from naabiga_cli.tools_config import _cua_driver_env
                    version = subprocess.run(
                        [path, "--version"],
                        capture_output=True, text=True, timeout=5,
                        env=_cua_driver_env(),
                    ).stdout.strip()
                except Exception:
                    pass
                if version:
                    print(f"cua-driver: installed at {path} ({version})")
                else:
                    print(f"cua-driver: installed at {path}")
                try:
                    from tools.computer_use.cua_backend import cua_driver_update_check
                    st = cua_driver_update_check()
                    if st and st.get("update_available"):
                        latest = st.get("latest_version") or "?"
                        print(f"  ⬆ Update available: cua-driver {latest}.")
                        print("    Run: naabiga computer-use install --upgrade")
                    elif st:
                        print("  ✓ Up to date.")
                    else:
                        # Older driver (no check-update verb) or offline.
                        print("  Refresh to latest: naabiga computer-use install --upgrade")
                except Exception:
                    print("  Refresh to latest: naabiga computer-use install --upgrade")
                return
            print("cua-driver: not installed")
            print("  Run: naabiga computer-use install")
            return
        if action == "doctor":
            from tools.computer_use.doctor import run_doctor
            code = run_doctor(
                include=list(getattr(args, "include", []) or []),
                skip=list(getattr(args, "skip", []) or []),
                json_output=bool(getattr(args, "json", False)),
            )
            sys.exit(code)
        if action == "permissions":
            perms_action = getattr(args, "computer_use_perms_action", None)
            if perms_action == "grant":
                from tools.computer_use.permissions import request_permissions_grant
                sys.exit(request_permissions_grant())
            if perms_action == "status":
                import json as _json
                from tools.computer_use.permissions import computer_use_status
                st = computer_use_status()
                if bool(getattr(args, "json", False)):
                    print(_json.dumps(st, indent=2, sort_keys=True))
                    sys.exit(0 if st["ready"] else 1)
                if not st["platform_supported"]:
                    print(f"Computer Use is not supported on {st['platform']}.")
                    sys.exit(1)
                if not st["installed"]:
                    print("cua-driver: not installed. Run: naabiga computer-use install")
                    sys.exit(1)
                glyph = lambda v: "✅" if v is True else ("❌" if v is False else "•")  # noqa: E731
                print(f"cua-driver: {st['version'] or 'installed'} ({st['platform']})")
                if st["can_grant"]:  # macOS TCC permissions
                    print(f"  {glyph(st['accessibility'])} Accessibility")
                    print(f"  {glyph(st['screen_recording'])} Screen Recording")
                    if not st["ready"]:
                        print("  Grant: naabiga computer-use permissions grant")
                else:  # no TCC model — readiness is driver health
                    print(f"  {glyph(st['ready'])} driver health (no permission toggles on {st['platform']})")
                for c in st["checks"]:
                    if c["status"] != "ok":
                        print(f"  ⚠ {c['label']}: {c['message']}")
                if st["error"]:
                    print(f"  ⚠ {st['error']}")
                sys.exit(0 if st["ready"] else 1)
            computer_use_perms.print_help()
            return
        # No subcommand → show help
        computer_use_parser.print_help()

    computer_use_parser.set_defaults(func=cmd_computer_use)
    # =========================================================================
    # mcp command  (parser built in naabiga_cli/subcommands/mcp.py)
    # =========================================================================
    build_mcp_parser(subparsers, cmd_mcp=cmd_mcp)

    # =========================================================================
    # sessions command
    # =========================================================================
    sessions_parser = subparsers.add_parser(
        "sessions",
        help="Manage session history (list, rename, export, prune, delete)",
        description="View and manage the SQLite session store",
    )
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_action")

    sessions_list = sessions_subparsers.add_parser("list", help="List recent sessions")
    sessions_list.add_argument(
        "--source", help="Filter by source (cli, telegram, discord, etc.)"
    )
    sessions_list.add_argument(
        "--limit", type=int, default=20, help="Max sessions to show"
    )

    def _add_session_filter_args(p, default_older_help):
        p.add_argument(
            "--older-than",
            metavar="AGE",
            help=default_older_help,
        )
        p.add_argument(
            "--newer-than",
            metavar="AGE",
            help="Only match sessions started within the last AGE "
            "(e.g. '5h', '2d') or after an ISO timestamp",
        )
        p.add_argument(
            "--before",
            metavar="TIME",
            help="Only match sessions started before TIME "
            "(duration ago like '5h', or ISO timestamp like '2026-07-05 14:30')",
        )
        p.add_argument(
            "--after",
            metavar="TIME",
            help="Only match sessions started at/after TIME "
            "(duration ago like '5h', or ISO timestamp)",
        )
        p.add_argument("--source", help="Only match sessions from this source")
        p.add_argument(
            "--title", help="Only match sessions whose title contains this substring"
        )
        p.add_argument(
            "--end-reason", help="Only match sessions with this end reason"
        )
        p.add_argument(
            "--cwd", help="Only match sessions whose working directory is under this path"
        )
        p.add_argument(
            "--min-messages", type=int, help="Only match sessions with >= N messages"
        )
        p.add_argument(
            "--max-messages", type=int, help="Only match sessions with <= N messages"
        )
        p.add_argument(
            "--model",
            help="Only match sessions whose model name contains this substring "
            "(e.g. 'sonnet', 'gpt-5', 'naabiga')",
        )
        p.add_argument(
            "--provider",
            help="Only match sessions billed through this provider "
            "(e.g. openrouter, anthropic, nous)",
        )
        p.add_argument(
            "--user", help="Only match sessions from this user ID"
        )
        p.add_argument(
            "--chat-id", help="Only match sessions from this chat/channel ID"
        )
        p.add_argument(
            "--chat-type",
            help="Only match sessions with this chat type (e.g. dm, group)",
        )
        p.add_argument(
            "--branch",
            help="Only match sessions whose git branch contains this substring",
        )
        p.add_argument(
            "--min-tokens", type=int,
            help="Only match sessions with >= N total tokens (input+output)",
        )
        p.add_argument(
            "--max-tokens", type=int,
            help="Only match sessions with <= N total tokens (input+output)",
        )
        p.add_argument(
            "--min-cost", type=float,
            help="Only match sessions costing >= N USD (actual or estimated)",
        )
        p.add_argument(
            "--max-cost", type=float,
            help="Only match sessions costing <= N USD (actual or estimated)",
        )
        p.add_argument(
            "--min-tool-calls", type=int,
            help="Only match sessions with >= N tool calls",
        )
        p.add_argument(
            "--max-tool-calls", type=int,
            help="Only match sessions with <= N tool calls",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="List matching sessions without changing anything",
        )
        p.add_argument(
            "--yes", "-y", action="store_true", help="Skip confirmation"
        )

    sessions_export = sessions_subparsers.add_parser(
        "export", help="Export sessions to JSONL, Markdown, or QMD"
    )
    sessions_export.add_argument(
        "output",
        nargs="?",
        help=(
            "Output path. JSONL: file path (use - for stdout, required). "
            "md/qmd: output directory (default: <naabiga home>/session-exports)"
        ),
    )
    sessions_export.add_argument(
        "--format",
        choices=["jsonl", "md", "qmd", "html", "trace"],
        default="jsonl",
        help=(
            "Export format (default: jsonl). 'trace' emits Claude Code JSONL "
            "for the Hugging Face Agent Trace Viewer"
        ),
    )
    sessions_export.add_argument(
        "--upload",
        action="store_true",
        help=(
            "trace only: upload to your Hugging Face traces dataset instead "
            "of writing a local file (needs HF_TOKEN)"
        ),
    )
    sessions_export.add_argument(
        "--public",
        action="store_true",
        help="trace --upload only: create/update a public dataset instead of private",
    )
    sessions_export.add_argument(
        "--no-redact",
        action="store_true",
        help=(
            "trace only: skip the forced secret redaction; "
            "only use after manual review"
        ),
    )
    sessions_export.add_argument(
        "--only",
        choices=["user-prompts"],
        help=(
            "Export only a filtered view (user-prompts: one prompt record "
            "per line for jsonl, headed sections for md)"
        ),
    )
    sessions_export.add_argument(
        "--session-id", help="Session ID or unique prefix to export"
    )
    _add_session_filter_args(
        sessions_export,
        "Only export sessions older than AGE (duration like '5h'/'2d', "
        "bare number of days, or an ISO timestamp)",
    )
    sessions_export.add_argument(
        "--redact",
        action="store_true",
        help="Redact secrets (API keys, tokens, credentials) from exported content",
    )
    sessions_export.add_argument(
        "--lineage",
        choices=["single", "logical"],
        default="single",
        help="md/qmd only: export one row or its compression lineage",
    )
    sessions_export.add_argument(
        "--delete-after-verified",
        action="store_true",
        help="md/qmd only: after verified single-session export, delete that session (needs --yes)",
    )
    sessions_export.add_argument(
        "--force",
        action="store_true",
        help="md/qmd only: overwrite an existing export file",
    )

    sessions_delete = sessions_subparsers.add_parser(
        "delete", help="Delete a specific session"
    )
    sessions_delete.add_argument("session_id", help="Session ID to delete")
    sessions_delete.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation"
    )

    sessions_prune = sessions_subparsers.add_parser(
        "prune",
        help="Delete old sessions (filterable by time window, source, title, ...)",
    )
    _add_session_filter_args(
        sessions_prune,
        "Delete sessions older than AGE — days if bare number, or a duration "
        "like '5h'/'2d'/'1w', or an ISO timestamp (bare prune with no filters "
        "defaults to 90 days; any filter matches all ages)",
    )
    sessions_prune.add_argument(
        "--include-archived",
        action="store_true",
        help="Also delete archived sessions (excluded by default)",
    )

    sessions_archive = sessions_subparsers.add_parser(
        "archive",
        help="Bulk-archive (soft-hide) sessions matching filters — no deletion",
    )
    _add_session_filter_args(
        sessions_archive,
        "Only archive sessions older than AGE (duration like '5h'/'2d', "
        "bare number of days, or ISO timestamp)",
    )

    sessions_subparsers.add_parser(
        "optimize",
        help="Reclaim disk space: merge FTS5 segments + VACUUM (no data change)",
    )

    sessions_repair = sessions_subparsers.add_parser(
        "repair",
        help="Repair a malformed state.db schema so hidden sessions reappear",
        description=(
            "Recover a state.db whose schema is malformed (e.g. 'table "
            "messages_fts already exists'), which makes Desktop/Dashboard show "
            "no sessions. A backup is made first; sessions and messages are "
            "preserved and the FTS search index is rebuilt if needed."
        ),
    )
    sessions_repair.add_argument(
        "--check-only",
        action="store_true",
        help="Only report whether the database opens cleanly; do not modify it",
    )
    sessions_repair.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the timestamped backup copy (not recommended)",
    )

    sessions_subparsers.add_parser("stats", help="Show session store statistics")

    sessions_rename = sessions_subparsers.add_parser(
        "rename", help="Set or change a session's title"
    )
    sessions_rename.add_argument("session_id", help="Session ID to rename")
    sessions_rename.add_argument("title", nargs="+", help="New title for the session")

    sessions_browse = sessions_subparsers.add_parser(
        "browse",
        help="Interactive session picker — browse, search, and resume sessions",
    )
    sessions_browse.add_argument(
        "--source", help="Filter by source (cli, telegram, discord, etc.)"
    )
    sessions_browse.add_argument(
        "--limit", type=int, default=500, help="Max sessions to load (default: 500)"
    )

    def _confirm_prompt(prompt: str) -> bool:
        """Prompt for y/N confirmation, safe against non-TTY environments."""
        try:
            return input(prompt).strip().lower() in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False

    def cmd_sessions(args):
        import json as _json

        action = args.sessions_action

        # 'repair' must run BEFORE opening SessionDB(): a malformed schema is
        # exactly the case where SessionDB() can't open, so it operates on the
        # raw file path instead.
        if action == "repair":
            from naabiga_state import (
                DEFAULT_DB_PATH,
                _db_opens_cleanly,
                repair_state_db_schema,
            )

            db_path = DEFAULT_DB_PATH
            if not db_path.exists():
                print(f"No session database at {db_path} (nothing to repair).")
                return
            reason = _db_opens_cleanly(db_path)
            if reason is None:
                print(f"✓ {db_path} opens cleanly — no repair needed.")
                return
            print(f"✗ {db_path} does not open cleanly: {reason}")
            if getattr(args, "check_only", False):
                return
            print("Repairing (a backup copy is made first)…")
            report = repair_state_db_schema(
                db_path, backup=not getattr(args, "no_backup", False)
            )
            if report.get("repaired"):
                if report.get("backup_path"):
                    print(f"  backup: {report['backup_path']}")
                print(f"  strategy: {report.get('strategy')}")
                try:
                    from naabiga_state import SessionDB

                    n = SessionDB()._conn.execute(
                        "SELECT COUNT(*) FROM sessions"
                    ).fetchone()[0]
                    print(f"✓ Repaired — {n} sessions recovered.")
                except Exception:
                    print("✓ Repaired.")
            else:
                print(f"✗ Repair failed: {report.get('error')}")
                if report.get("backup_path"):
                    print(f"  A backup is preserved at: {report['backup_path']}")
                print("  Keep state.db and the backup; do not delete them.")
            return

        try:
            from naabiga_state import SessionDB

            db = SessionDB()
        except Exception as e:
            print(f"Error: Could not open session database: {e}")
            return

        # Hide third-party tool sessions by default, but honour explicit --source
        _source = getattr(args, "source", None)
        _exclude = None if _source else ["tool"]

        if action == "list":
            sessions = db.list_sessions_rich(
                source=args.source, exclude_sources=_exclude, limit=args.limit
            )
            if not sessions:
                print("No sessions found.")
                return
            has_titles = any(s.get("title") for s in sessions)
            if has_titles:
                print(f"{'Title':<32} {'Preview':<40} {'Last Active':<13} {'ID'}")
                print("─" * 110)
            else:
                print(f"{'Preview':<50} {'Last Active':<13} {'Src':<6} {'ID'}")
                print("─" * 95)
            for s in sessions:
                last_active = _relative_time(s.get("last_active"))
                preview = (
                    s.get("preview", "")[:38]
                    if has_titles
                    else s.get("preview", "")[:48]
                )
                if has_titles:
                    title = (s.get("title") or "—")[:30]
                    sid = s["id"]
                    print(f"{title:<32} {preview:<40} {last_active:<13} {sid}")
                else:
                    sid = s["id"]
                    print(f"{preview:<50} {last_active:<13} {s['source']:<6} {sid}")

        elif action == "export":
            from naabiga_cli.session_filters import (
                build_prune_filters,
                describe_filters,
            )

            _filter_arg_names = (
                "older_than", "newer_than", "before", "after",
                "source", "title", "end_reason", "cwd",
                "min_messages", "max_messages", "model", "provider",
                "user", "chat_id", "chat_type", "branch",
                "min_tokens", "max_tokens", "min_cost", "max_cost",
                "min_tool_calls", "max_tool_calls",
            )
            _any_filters = any(
                getattr(args, a, None) is not None for a in _filter_arg_names
            )
            filters = None
            if _any_filters:
                try:
                    filters = build_prune_filters(args)
                except ValueError as e:
                    print(f"Error: {e}")
                    return
                # Unlike prune/archive, export includes archived sessions.
                filters["archived"] = None

            def _redact(data):
                if not args.redact or data is None:
                    return data
                from naabiga_cli.session_export_md import redact_session_data

                return redact_session_data(data)

            def _collect_sessions():
                """Resolve --session-id / filters / bare export into a list
                of redacted session dicts, or None after printing an error."""
                if args.session_id:
                    resolved = db.resolve_session_id(args.session_id)
                    data = _redact(db.export_session(resolved)) if resolved else None
                    if not data:
                        print(f"Session '{args.session_id}' not found.")
                        return None
                    return [data]
                if filters:
                    candidates = db.list_prune_candidates(**filters)
                    if args.dry_run:
                        print(
                            f"Would export {len(candidates)} session(s) "
                            f"({describe_filters(filters)})."
                        )
                        for row in candidates[:100]:
                            print(f"  {row.get('id')}  {row.get('source', '')}")
                        if len(candidates) > 100:
                            print(f"  ... {len(candidates) - 100} more")
                        return None
                    return [
                        s
                        for s in (
                            _redact(db.export_session(row["id"])) for row in candidates
                        )
                        if s
                    ]
                if args.dry_run:
                    print("--dry-run requires at least one filter.")
                    return None
                return [_redact(s) for s in db.export_all(source=None)]

            # Prompt-only export (--only user-prompts): one prompt record per
            # line (jsonl) or headed sections (md). Delegates rendering to
            # naabiga_cli.session_export.
            if getattr(args, "only", None):
                if args.format not in ("jsonl", "md"):
                    print("--only user-prompts supports --format jsonl or md.")
                    return
                from naabiga_cli.session_export import (
                    export_record_count,
                    render_sessions_export,
                )

                sessions = _collect_sessions()
                if sessions is None:
                    db.close()
                    return
                rendered = render_sessions_export(
                    sessions,
                    fmt="markdown" if args.format == "md" else "jsonl",
                    only=args.only,
                )
                if not args.output or args.output == "-":
                    sys.stdout.write(rendered)
                    db.close()
                    return
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(rendered)
                count, noun = export_record_count(sessions, only=args.only)
                suffix = "" if count == 1 else "s"
                print(f"Exported {count} {noun}{suffix} to {args.output}")
                db.close()
                return

            # Standalone HTML export: one self-contained file (single session
            # or multi-session with sidebar navigation).
            if args.format == "html":
                if not args.output or args.output == "-":
                    print("HTML export requires an output file path.")
                    return
                from naabiga_cli.session_export_html import (
                    generate_html_export,
                    generate_multi_session_html_export,
                )

                sessions = _collect_sessions()
                if sessions is None:
                    db.close()
                    return
                if len(sessions) == 1:
                    content = generate_html_export(sessions[0])
                else:
                    content = generate_multi_session_html_export(sessions)
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(content)
                suffix = "" if len(sessions) == 1 else "s"
                print(f"Exported {len(sessions)} session{suffix} to {args.output} (HTML)")
                db.close()
                return

            # Claude Code JSONL trace export — local file or HF upload.
            # Redaction is ON by default for traces (they leave the machine
            # when --upload is used); --no-redact opts out after review.
            if args.format == "trace":
                if getattr(args, "only", None):
                    print("--only user-prompts supports --format jsonl or md.")
                    db.close()
                    return
                session_id = args.session_id
                if not session_id and not filters:
                    # Match the shell's common intent: "the last thing I did".
                    rows = db.list_sessions_rich(limit=1, order_by_last_active=True)
                    session_id = rows[0].get("id") if rows else None
                    if not session_id:
                        print("No session found to export. Pass --session-id.")
                        db.close()
                        return
                if session_id and not db.resolve_session_id(session_id):
                    print(f"Session '{session_id}' not found.")
                    db.close()
                    return

                from agent.trace_upload import (
                    TraceRedactionError,
                    build_trace_jsonl,
                    upload_session_trace,
                )

                redact_trace = not getattr(args, "no_redact", False)

                if getattr(args, "upload", False):
                    if not session_id:
                        print("--upload exports one session: pass --session-id (or drop filters to use the most recent).")
                        db.close()
                        return
                    resolved = db.resolve_session_id(session_id)
                    db.close()
                    status = upload_session_trace(
                        resolved,
                        cwd="",
                        redact=redact_trace,
                        private=not getattr(args, "public", False),
                    )
                    print(status)
                    return

                # Local trace file(s)
                def _trace_ids():
                    if session_id:
                        return [db.resolve_session_id(session_id)]
                    candidates = db.list_prune_candidates(**filters)
                    if args.dry_run:
                        print(
                            f"Would export {len(candidates)} session(s) "
                            f"({describe_filters(filters)})."
                        )
                        for row in candidates[:100]:
                            print(f"  {row.get('id')}  {row.get('source', '')}")
                        if len(candidates) > 100:
                            print(f"  ... {len(candidates) - 100} more")
                        return None
                    return [row["id"] for row in candidates]

                ids = _trace_ids()
                if ids is None:
                    db.close()
                    return

                def _render_trace(sid):
                    meta = db.get_session(sid) or {}
                    messages = db.get_messages_as_conversation(sid)
                    if not messages:
                        return None
                    return build_trace_jsonl(
                        messages,
                        session_id=sid,
                        model=meta.get("model") or "",
                        cwd="",
                        redact=redact_trace,
                    )

                try:
                    if len(ids) == 1:
                        jsonl = _render_trace(ids[0])
                        if not jsonl:
                            print(f"No transcript to export for session '{ids[0]}'.")
                            db.close()
                            return
                        if not args.output or args.output == "-":
                            sys.stdout.write(jsonl)
                        else:
                            with open(args.output, "w", encoding="utf-8") as f:
                                f.write(jsonl)
                            print(f"Exported 1 session trace to {args.output}")
                    else:
                        out_dir = (
                            Path(args.output).expanduser()
                            if args.output and args.output != "-"
                            else get_naabiga_home() / "session-exports"
                        )
                        out_dir.mkdir(parents=True, exist_ok=True)
                        exported = 0
                        for sid in ids:
                            jsonl = _render_trace(sid)
                            if not jsonl:
                                continue
                            (out_dir / f"{sid}.trace.jsonl").write_text(
                                jsonl, encoding="utf-8"
                            )
                            exported += 1
                        print(f"Exported {exported} session trace(s) to {out_dir}")
                except TraceRedactionError:
                    print("Redaction failed; refusing to export unredacted trace content.")
                db.close()
                return

            if args.format == "jsonl":
                if not args.output:
                    print("JSONL export requires an output path (use - for stdout).")
                    return
                if args.session_id:
                    resolved_session_id = db.resolve_session_id(args.session_id)
                    if not resolved_session_id:
                        print(f"Session '{args.session_id}' not found.")
                        return
                    data = _redact(db.export_session(resolved_session_id))
                    if not data:
                        print(f"Session '{args.session_id}' not found.")
                        return
                    line = _json.dumps(data, ensure_ascii=False) + "\n"
                    if args.output == "-":

                        sys.stdout.write(line)
                    else:
                        with open(args.output, "w", encoding="utf-8") as f:
                            f.write(line)
                        print(f"Exported 1 session to {args.output}")
                else:
                    if filters:
                        candidates = db.list_prune_candidates(**filters)
                        if args.dry_run:
                            print(
                                f"Would export {len(candidates)} session(s) "
                                f"({describe_filters(filters)})."
                            )
                            for row in candidates[:100]:
                                print(f"  {row.get('id')}  {row.get('source', '')}")
                            if len(candidates) > 100:
                                print(f"  ... {len(candidates) - 100} more")
                            return
                        sessions = [
                            s
                            for s in (
                                db.export_session(row["id"]) for row in candidates
                            )
                            if s
                        ]
                    else:
                        if args.dry_run:
                            print("--dry-run requires at least one filter.")
                            return
                        sessions = db.export_all(source=None)
                    if args.output == "-":

                        for s in sessions:
                            sys.stdout.write(
                                _json.dumps(_redact(s), ensure_ascii=False) + "\n"
                            )
                    else:
                        with open(args.output, "w", encoding="utf-8") as f:
                            for s in sessions:
                                f.write(
                                    _json.dumps(_redact(s), ensure_ascii=False) + "\n"
                                )
                        print(f"Exported {len(sessions)} sessions to {args.output}")
                return

            # Markdown / QMD export
            from naabiga_cli.session_export_md import (
                append_manifest_entry,
                verify_export_file,
                write_session_markdown,
            )

            if args.output == "-":
                print("Markdown/QMD export writes files; stdout (-) is only supported with --format jsonl.")
                db.close()
                return
            output_dir = Path(args.output).expanduser() if args.output else get_naabiga_home() / "session-exports"

            def _export_one(session_id: str):
                data = (
                    db.export_session_lineage(session_id)
                    if getattr(args, "lineage", "single") == "logical"
                    else db.export_session(session_id)
                )
                if not data:
                    return None, None
                data = _redact(data)
                path = write_session_markdown(
                    data,
                    output_dir,
                    fmt=args.format,
                    force=args.force,
                )
                append_manifest_entry(output_dir, data, path, fmt=args.format)
                return data, path

            if args.delete_after_verified and not args.yes:
                print("--delete-after-verified requires --yes.")
                db.close()
                return
            if args.delete_after_verified and not args.session_id:
                print("--delete-after-verified is only supported with --session-id.")
                db.close()
                return

            if args.session_id:
                resolved_session_id = db.resolve_session_id(args.session_id)
                if not resolved_session_id:
                    print(f"Session '{args.session_id}' not found.")
                    db.close()
                    return
                try:
                    data, exported_path = _export_one(resolved_session_id)
                except FileExistsError as e:
                    print(f"Export already exists: {e}. Pass --force to overwrite.")
                    db.close()
                    return
                if not data or not exported_path:
                    print(f"Session '{args.session_id}' not found.")
                    db.close()
                    return
                message_count = len(data.get("messages") or [])
                suffix = "" if message_count == 1 else "s"
                print(f"Exported 1 session ({message_count} message{suffix}) to {exported_path}")
                if args.delete_after_verified:
                    ok, reason = verify_export_file(exported_path, data)
                    if not ok:
                        print(f"Export verification failed; not deleting: {reason}")
                        db.close()
                        return
                    sessions_dir = get_naabiga_home() / "sessions"
                    if db.delete_session(resolved_session_id, sessions_dir=sessions_dir):
                        print(f"Deleted exported session '{resolved_session_id}'.")
                    else:
                        print(f"Exported, but session '{resolved_session_id}' was not deleted because it was not found.")
                db.close()
                return

            if not filters:
                print(
                    "Refusing bulk export without a filter. Pass --session-id or "
                    "at least one filter (e.g. --older-than 90, --source telegram)."
                )
                db.close()
                return
            candidates = db.list_prune_candidates(**filters)
            if args.dry_run:
                print(
                    f"Would export {len(candidates)} session(s) "
                    f"({describe_filters(filters)})."
                )
                for row in candidates[:100]:
                    print(f"  {row.get('id')}  {row.get('source', '')}")
                if len(candidates) > 100:
                    print(f"  ... {len(candidates) - 100} more")
                db.close()
                return
            exported = 0
            for row in candidates:
                try:
                    data, exported_path = _export_one(row["id"])
                except FileExistsError as e:
                    print(f"Skipping existing export: {e}. Pass --force to overwrite.")
                    continue
                if data and exported_path:
                    exported += 1
            print(f"Exported {exported} session(s) to {output_dir}")

        elif action == "delete":
            resolved_session_id = db.resolve_session_id(args.session_id)
            if not resolved_session_id:
                print(f"Session '{args.session_id}' not found.")
                return
            if not args.yes:
                if not _confirm_prompt(
                    f"Delete session '{resolved_session_id}' and all its messages? [y/N] "
                ):
                    print("Cancelled.")
                    return
            sessions_dir = get_naabiga_home() / "sessions"
            if db.delete_session(resolved_session_id, sessions_dir=sessions_dir):
                print(f"Deleted session '{resolved_session_id}'.")
            else:
                print(f"Session '{args.session_id}' not found.")

        elif action in ("prune", "archive"):
            from naabiga_cli.session_filters import (
                build_prune_filters,
                describe_filters,
                format_epoch,
            )

            # Preserve the historical default ONLY for a truly bare
            # `naabiga sessions prune`: no time window and no filters at all
            # means "older than 90 days". ANY filter — including --source —
            # suppresses the implicit cutoff, so `prune --source cron`
            # matches ALL cron sessions regardless of age. The preview +
            # confirmation below (count, oldest/newest) is the safety net.
            _non_time_filters = any(
                getattr(args, a, None) is not None
                for a in (
                    "source", "title", "end_reason", "cwd",
                    "min_messages", "max_messages", "model", "provider",
                    "user", "chat_id", "chat_type", "branch",
                    "min_tokens", "max_tokens", "min_cost", "max_cost",
                    "min_tool_calls", "max_tool_calls",
                )
            )
            if (
                action == "prune"
                and args.older_than is None
                and args.newer_than is None
                and args.before is None
                and args.after is None
                and not _non_time_filters
            ):
                args.older_than = "90"

            try:
                filters = build_prune_filters(args)
            except ValueError as e:
                print(f"Error: {e}")
                return

            if action == "archive" and not any(
                v for k, v in filters.items() if k != "older_than_days"
            ):
                print(
                    "Refusing to archive every ended session: pass at least one "
                    "filter (e.g. --newer-than 5h, --source cli, --title codex)."
                )
                return

            # Prune skips archived sessions unless --include-archived;
            # archive only targets not-yet-archived rows (idempotent).
            if action == "prune":
                filters["archived"] = (
                    None if getattr(args, "include_archived", False) else False
                )
            else:
                filters["archived"] = False

            candidates = db.list_prune_candidates(**filters)
            verb = "Delete" if action == "prune" else "Archive"
            if not candidates:
                print(f"No sessions match ({describe_filters(filters)}).")
                return

            # Candidates are ordered oldest-first — surface the age span so
            # the confirmation makes the blast radius obvious.
            _oldest = candidates[0].get("started_at")
            _newest = candidates[-1].get("started_at")
            _span = (
                f"oldest {format_epoch(_oldest)}, newest {format_epoch(_newest)}"
            )

            if args.dry_run or not args.yes:
                shown = candidates if args.dry_run else candidates[:15]
                print(
                    f"{len(candidates)} session(s) match "
                    f"({describe_filters(filters)}; {_span}):"
                )
                for s in shown:
                    title = (s.get("title") or "")[:36]
                    model = (s.get("model") or "-").split("/")[-1][:24]
                    print(
                        f"  {s['id']}  {format_epoch(s['started_at']):<17} "
                        f"{s['source']:<10} {model:<24} "
                        f"{s['message_count']:>4} msgs  {title}"
                    )
                if len(candidates) > len(shown):
                    print(f"  … and {len(candidates) - len(shown)} more")
                if args.dry_run:
                    print(f"Dry run — nothing {'deleted' if action == 'prune' else 'archived'}.")
                    return

            if not args.yes:
                if not _confirm_prompt(
                    f"{verb} these {len(candidates)} session(s) ({_span})? [y/N] "
                ):
                    print("Cancelled.")
                    return

            if action == "prune":
                sessions_dir = get_naabiga_home() / "sessions"
                count = db.prune_sessions(sessions_dir=sessions_dir, **filters)
                print(f"Pruned {count} session(s).")
            else:
                count = db.archive_sessions(**filters)
                print(
                    f"Archived {count} session(s). They're hidden from listings "
                    "but fully recoverable (nothing was deleted)."
                )

        elif action == "rename":
            resolved_session_id = db.resolve_session_id(args.session_id)
            if not resolved_session_id:
                print(f"Session '{args.session_id}' not found.")
                return
            title = " ".join(args.title)
            try:
                if db.set_session_title(resolved_session_id, title):
                    print(f"Session '{resolved_session_id}' renamed to: {title}")
                else:
                    print(f"Session '{args.session_id}' not found.")
            except ValueError as e:
                print(f"Error: {e}")

        elif action == "browse":
            limit = getattr(args, "limit", 500) or 500
            source = getattr(args, "source", None)
            _browse_exclude = None if source else ["tool"]
            sessions = db.list_sessions_rich(
                source=source, exclude_sources=_browse_exclude, limit=limit
            )
            db.close()
            if not sessions:
                print("No sessions found.")
                return

            selected_id = _session_browse_picker(sessions)
            if not selected_id:
                print("Cancelled.")
                return

            # Launch naabiga --resume <id> by replacing the current process
            print(f"Resuming session: {selected_id}")
            from naabiga_cli.relaunch import relaunch

            relaunch(["--resume", selected_id])
            return  # won't reach here after execvp

        elif action == "optimize":
            db_path = db.db_path
            before_mb = (
                os.path.getsize(db_path) / (1024 * 1024)
                if db_path.exists()
                else 0.0
            )
            print("Optimizing session store (FTS merge + VACUUM)…")
            try:
                # vacuum() merges FTS5 segments (optimize_fts) then VACUUMs,
                # and returns the number of indexes it merged.
                n = db.vacuum()
            except Exception as e:
                print(f"Error: optimization failed: {e}")
                db.close()
                return
            after_mb = (
                os.path.getsize(db_path) / (1024 * 1024)
                if db_path.exists()
                else 0.0
            )
            saved = before_mb - after_mb
            print(f"Optimized {n} FTS index(es).")
            print(
                f"Database size: {before_mb:.1f} MB -> {after_mb:.1f} MB "
                f"(reclaimed {saved:.1f} MB)"
            )

        elif action == "stats":
            total = db.session_count()
            msgs = db.message_count()
            print(f"Total sessions: {total}")
            print(f"Total messages: {msgs}")
            for src in ["cli", "telegram", "discord", "whatsapp", "slack"]:
                c = db.session_count(source=src)
                if c > 0:
                    print(f"  {src}: {c} sessions")
            db_path = db.db_path
            if db_path.exists():
                size_mb = os.path.getsize(db_path) / (1024 * 1024)
                print(f"Database size: {size_mb:.1f} MB")

        else:
            sessions_parser.print_help()

        db.close()

    sessions_parser.set_defaults(func=cmd_sessions)

    # =========================================================================
    # insights command  (parser built in naabiga_cli/subcommands/insights.py)
    # =========================================================================
    build_insights_parser(subparsers, cmd_insights=cmd_insights)

    # =========================================================================
    # claw command  (parser built in naabiga_cli/subcommands/claw.py)
    # =========================================================================
    build_claw_parser(subparsers, cmd_claw=cmd_claw)

    # =========================================================================
    # version command  (parser built in naabiga_cli/subcommands/version.py)
    # =========================================================================
    build_version_parser(subparsers, cmd_version=cmd_version)

    # =========================================================================
    # update command  (parser built in naabiga_cli/subcommands/update.py)
    # =========================================================================
    build_update_parser(subparsers, cmd_update=cmd_update)

    # =========================================================================
    # uninstall command  (parser built in naabiga_cli/subcommands/uninstall.py)
    # =========================================================================
    build_uninstall_parser(subparsers, cmd_uninstall=cmd_uninstall)

    # =========================================================================
    # acp command  (parser built in naabiga_cli/subcommands/acp.py)
    # =========================================================================
    build_acp_parser(subparsers, cmd_acp=cmd_acp)

    # =========================================================================
    # profile command  (parser built in naabiga_cli/subcommands/profile.py)
    # =========================================================================
    build_profile_parser(subparsers, cmd_profile=cmd_profile)

    # =========================================================================
    # completion command
    # =========================================================================
    completion_parser = subparsers.add_parser(
        "completion",
        help="Print shell completion script (bash, zsh, or fish)",
    )
    completion_parser.add_argument(
        "shell",
        nargs="?",
        default="bash",
        choices=["bash", "zsh", "fish"],
        help="Shell type (default: bash)",
    )
    completion_parser.set_defaults(func=lambda args: cmd_completion(args, parser))

    # =========================================================================
    # dashboard command  (REMOVED in Naabiga — CLI-only fork)
    # =========================================================================

    # =========================================================================
    # desktop (a.k.a. gui) command  (REMOVED in Naabiga — CLI-only fork)
    # =========================================================================

    # =========================================================================
    # logs command  (parser built in naabiga_cli/subcommands/logs.py)
    # =========================================================================
    build_logs_parser(subparsers, cmd_logs=cmd_logs)

    # =========================================================================
    # prompt-size command  (parser built in naabiga_cli/subcommands/prompt_size.py)
    # =========================================================================
    build_prompt_size_parser(subparsers, cmd_prompt_size=cmd_prompt_size)

    # =========================================================================
    # Parse and execute
    # =========================================================================
    # Pre-process argv so unquoted multi-word session names after -c / -r
    # are merged into a single token before argparse sees them.
    # e.g. ``naabiga -c Pokemon Agent Dev`` → ``naabiga -c 'Pokemon Agent Dev'``
    # ── Container-aware routing ────────────────────────────────────────
    # When NixOS container mode is active, route ALL subcommands into
    # the managed container.  This MUST run before parse_args() so that
    # --help, unrecognised flags, and every subcommand are forwarded
    # transparently instead of being intercepted by argparse on the host.
    from naabiga_cli.config import get_container_exec_info

    container_info = get_container_exec_info()
    if container_info:
        _exec_in_container(container_info, sys.argv[1:])
        # Unreachable: os.execvp never returns on success (process is replaced)
        # and raises OSError on failure (which propagates as a traceback).
        sys.exit(1)

    _processed_argv = _coalesce_session_name_args(sys.argv[1:])

    # ── Defensive subparser routing (bpo-9338 workaround) ───────────
    # On some Python versions (notably <3.11), argparse fails to route
    # subcommand tokens when the parent parser has nargs='?' optional
    # arguments (--continue).  The symptom: "unrecognized arguments: model"
    # even though 'model' is a registered subcommand.
    #
    # Fix: when argv contains a token matching a known subcommand, set
    # subparsers.required=True to force deterministic routing.  If that
    # fails (e.g. 'naabiga -c model' where 'model' is consumed as the
    # session name for --continue), fall back to the default behaviour.
    import io as _io

    _known_cmds = (
        set(subparsers.choices.keys()) if hasattr(subparsers, "choices") else set()
    )
    _has_cmd_token = any(
        t in _known_cmds for t in _processed_argv if not t.startswith("-")
    )

    if _has_cmd_token:
        subparsers.required = True
        _saved_stderr = sys.stderr
        try:
            sys.stderr = _io.StringIO()
            args = parser.parse_args(_processed_argv)
            sys.stderr = _saved_stderr
        except SystemExit as exc:
            sys.stderr = _saved_stderr
            # Help/version flags (exit code 0) already printed output —
            # re-raise immediately to avoid a second parse_args printing
            # the same help text again (#10230).
            if exc.code == 0:
                raise
            # Subcommand name was consumed as a flag value (e.g. -c model).
            # Fall back to optional subparsers so argparse handles it normally.
            subparsers.required = False
            args = parser.parse_args(_processed_argv)
    else:
        subparsers.required = False
        args = parser.parse_args(_processed_argv)

    # Handle --version flag
    if args.version:
        cmd_version(args)
        return

    # Discover Python plugins and register shell hooks once, before any
    # command that can fire lifecycle hooks.  Both are idempotent; gated
    # so introspection/management commands (naabiga hooks list, cron
    # list, gateway status, mcp add, ...) don't pay discovery cost or
    # trigger consent prompts for hooks the user is still inspecting.
    _prepare_agent_startup(args)

    # Handle top-level --oneshot / -z: single-shot mode, stdout = final
    # response only, nothing else. Bypasses cli.py entirely.
    if getattr(args, "oneshot", None):
        from naabiga_cli.oneshot import run_oneshot

        sys.exit(
            run_oneshot(
                args.oneshot,
                model=getattr(args, "model", None),
                provider=getattr(args, "provider", None),
                toolsets=getattr(args, "toolsets", None),
                usage_file=getattr(args, "usage_file", None),
            )
        )

    # Handle top-level --resume / --continue as shortcut to chat
    if (args.resume or args.continue_last) and args.command is None:
        args.command = "chat"
        for attr, default in [
            ("query", None),
            ("model", None),
            ("provider", None),
            ("toolsets", None),
            ("verbose", None),
            ("worktree", False),
        ]:
            if not hasattr(args, attr):
                setattr(args, attr, default)
        cmd_chat(args)
        return

    # Default to chat if no command specified
    if args.command is None:
        for attr, default in [
            ("query", None),
            ("model", None),
            ("provider", None),
            ("toolsets", None),
            ("verbose", None),
            ("resume", None),
            ("continue_last", None),
            ("worktree", False),
        ]:
            if not hasattr(args, attr):
                setattr(args, attr, default)
        cmd_chat(args)
        return

    # Execute the command
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
