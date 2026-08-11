"""Compatibility shim — ``hermes_cli.config`` for vendored gateway code.

Re-exports the Naabiga config layer under the upstream Hermes names,
plus the handful of symbols the gateway needs that Naabiga renamed
(``get_hermes_home``) or that live upstream only (``_is_ssh_remote_tilde_cwd``).

⚠️ Les ré-exports portent ``# noqa: F401`` — ils sont utilisés par le
gateway vendu (gateway/*), pas par ce fichier lui-même. Ne pas laisser
``ruff --fix`` les supprimer.
"""

from naabiga_cli.config import (  # noqa: F401 — ré-exports pour gateway vendu
    DEFAULT_CONFIG,
    atomic_config_write,
    cfg_get,
    clear_model_endpoint_credentials,
    get_compatible_custom_providers,
    get_custom_provider_context_length,
    get_config_path,
    get_env_value,
    get_naabiga_home,
    load_config,
    save_config,
)
from utils import fast_safe_load

from hermes_constants import get_hermes_home  # noqa: F401 — ré-export pour gateway vendu


def read_user_config_raw(config_path=None) -> dict:
    """Read a user ``config.yaml`` EXACTLY as written on disk.

    No DEFAULT_CONFIG merge, no env expansion, no migration. Only legal
    for write-back round-trips and raw-file diagnostics.
    """
    if config_path is None:
        config_path = get_config_path()
    try:
        with open(config_path, encoding="utf-8") as f:
            data = fast_safe_load(f) or {}
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_ssh_remote_tilde_cwd(backend: str, cwd: str) -> bool:
    """Whether the remote SSH shell must expand *cwd* itself.

    Expanding ``~`` on the Naabiga host rewrites it to the host home
    before SSH sees it. Preserve ``~`` and ``~/...`` so they follow the
    user selected by the SSH connection.
    """
    if (backend or "").strip().lower() != "ssh":
        return False
    return cwd == "~" or cwd.startswith("~/")
