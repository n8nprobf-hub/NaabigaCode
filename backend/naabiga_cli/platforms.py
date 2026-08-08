"""
Shared platform registry for Naabiga Agent.

Single source of truth for platform metadata consumed by both
skills_config (label display) and tools_config (default toolset
resolution).  Import ``PLATFORMS`` from here instead of maintaining
duplicate dicts in each module.
"""

from collections import OrderedDict
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    """Metadata for a single platform entry."""
    label: str
    default_toolset: str


# Ordered so that TUI menus are deterministic.
PLATFORMS: OrderedDict[str, PlatformInfo] = OrderedDict([
    ("cli",            PlatformInfo(label="🖥️  CLI",            default_toolset="naabiga-cli")),
    ("telegram",       PlatformInfo(label="📱 Telegram",        default_toolset="naabiga-telegram")),
    ("discord",        PlatformInfo(label="💬 Discord",         default_toolset="naabiga-discord")),
    ("slack",          PlatformInfo(label="💼 Slack",           default_toolset="naabiga-slack")),
    ("whatsapp",       PlatformInfo(label="📱 WhatsApp",        default_toolset="naabiga-whatsapp")),
    ("whatsapp_cloud", PlatformInfo(label="📱 WhatsApp Business (Cloud)", default_toolset="naabiga-whatsapp")),
    ("signal",         PlatformInfo(label="📡 Signal",          default_toolset="naabiga-signal")),
    ("bluebubbles",    PlatformInfo(label="💙 BlueBubbles",     default_toolset="naabiga-bluebubbles")),
    ("email",          PlatformInfo(label="📧 Email",           default_toolset="naabiga-email")),
    ("homeassistant",  PlatformInfo(label="🏠 Home Assistant",  default_toolset="naabiga-homeassistant")),
    ("mattermost",     PlatformInfo(label="💬 Mattermost",      default_toolset="naabiga-mattermost")),
    ("matrix",         PlatformInfo(label="💬 Matrix",          default_toolset="naabiga-matrix")),
    ("dingtalk",       PlatformInfo(label="💬 DingTalk",        default_toolset="naabiga-dingtalk")),
    ("feishu",         PlatformInfo(label="🪽 Feishu",          default_toolset="naabiga-feishu")),
    ("wecom",          PlatformInfo(label="💬 WeCom",           default_toolset="naabiga-wecom")),
    ("wecom_callback", PlatformInfo(label="💬 WeCom Callback",  default_toolset="naabiga-wecom-callback")),
    ("weixin",         PlatformInfo(label="💬 Weixin",          default_toolset="naabiga-weixin")),
    ("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="naabiga-qqbot")),
    ("yuanbao",        PlatformInfo(label="🤖 Yuanbao",         default_toolset="naabiga-yuanbao")),
    ("webhook",        PlatformInfo(label="🔗 Webhook",         default_toolset="naabiga-webhook")),
    ("api_server",     PlatformInfo(label="🌐 API Server",      default_toolset="naabiga-api-server")),
    ("cron",           PlatformInfo(label="⏰ Cron",            default_toolset="naabiga-cron")),
])


def platform_label(key: str, default: str = "") -> str:
    """Return the display label for a platform key, or *default*.

    Checks the static PLATFORMS dict first, then the plugin platform
    registry for dynamically registered platforms.
    """
    info = PLATFORMS.get(key)
    if info is not None:
        return info.label
    # Check plugin registry
    try:
        from gateway.platform_registry import platform_registry
        entry = platform_registry.get(key)
        if entry:
            return f"{entry.emoji}  {entry.label}" if entry.emoji else entry.label
    except Exception:
        pass
    return default


def get_all_platforms() -> "OrderedDict[str, PlatformInfo]":
    """Return PLATFORMS merged with any plugin-registered platforms.

    Plugin platforms are appended after builtins.  This is the function
    that tools_config and skills_config should use for platform menus.
    """
    merged = OrderedDict(PLATFORMS)
    try:
        from gateway.platform_registry import platform_registry
        for entry in platform_registry.plugin_entries():
            if entry.name not in merged:
                merged[entry.name] = PlatformInfo(
                    label=f"{entry.emoji}  {entry.label}" if entry.emoji else entry.label,
                    default_toolset=f"naabiga-{entry.name}",
                )
    except Exception:
        pass
    return merged
