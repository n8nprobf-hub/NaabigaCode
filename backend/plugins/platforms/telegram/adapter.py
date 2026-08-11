"""
Telegram platform adapter.

Uses python-telegram-bot library for:
- Receiving messages from users/groups
- Sending responses back
- Handling media and commands
"""

import asyncio
import logging
import os
import re
from typing import Dict, List, Optional, Set, Any

logger = logging.getLogger(__name__)


def _redact_telegram_error_text(error: object) -> str:
    """Redact secrets from Telegram transport errors before logging or returning them."""
    text = "" if error is None else str(error)
    if not text:
        return text
    try:
        from agent.redact import redact_sensitive_text

        return redact_sensitive_text(text, force=True)
    except Exception:
        return "<telegram error redacted>"


try:
    from telegram import Update, Bot, Message, InlineKeyboardButton, InlineKeyboardMarkup
    try:
        from telegram import LinkPreviewOptions
    except ImportError:
        LinkPreviewOptions = None
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        MessageHandler as TelegramMessageHandler,
        ContextTypes,
        filters,
    )
    from telegram.constants import ParseMode, ChatType
    from telegram.request import HTTPXRequest
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Update = Any
    Bot = Any
    Message = Any
    InlineKeyboardButton = Any
    InlineKeyboardMarkup = Any
    LinkPreviewOptions = None
    Application = Any
    CommandHandler = Any
    CallbackQueryHandler = Any
    TelegramMessageHandler = Any
    HTTPXRequest = Any
    filters = None
    ParseMode = None
    ChatType = None

    # Mock ContextTypes so type annotations using ContextTypes.DEFAULT_TYPE
    # don't crash during class definition when the library isn't installed.
    class _MockContextTypes:
        DEFAULT_TYPE = Any
    ContextTypes = _MockContextTypes

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[3]))

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    utf16_len,
)
from utils import env_float

_TELEGRAM_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_TELEGRAM_IMAGE_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_TELEGRAM_IMAGE_EXT_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def check_telegram_requirements() -> bool:
    """Check if Telegram dependencies are available.

    If python-telegram-bot is missing, attempts to lazy-install it via
    ``tools.lazy_deps.ensure("platform.telegram")``. After a successful
    install, re-imports the SDK and flips ``TELEGRAM_AVAILABLE`` to True
    so the adapter's class-level type aliases get rebound.
    """
    global TELEGRAM_AVAILABLE, Update, Bot, Message, InlineKeyboardButton
    global InlineKeyboardMarkup, LinkPreviewOptions, Application
    global CommandHandler, CallbackQueryHandler, TelegramMessageHandler
    global ContextTypes, filters, ParseMode, ChatType, HTTPXRequest
    if TELEGRAM_AVAILABLE:
        return True
    try:
        from tools.lazy_deps import ensure as _lazy_ensure
        _lazy_ensure("platform.telegram", prompt=False)
    except Exception:
        return False
    try:
        from telegram import Update as _Update, Bot as _Bot, Message as _Message
        from telegram import InlineKeyboardButton as _IKB, InlineKeyboardMarkup as _IKM
        try:
            from telegram import LinkPreviewOptions as _LPO
        except ImportError:
            _LPO = None
        from telegram.ext import (
            Application as _App, CommandHandler as _CH,
            CallbackQueryHandler as _CQH,
            MessageHandler as _MH,
            ContextTypes as _CT, filters as _filters,
        )
        from telegram.constants import ParseMode as _PM, ChatType as _CtT
        from telegram.request import HTTPXRequest as _HR
    except ImportError:
        return False
    Update = _Update
    Bot = _Bot
    Message = _Message
    InlineKeyboardButton = _IKB
    InlineKeyboardMarkup = _IKM
    LinkPreviewOptions = _LPO
    Application = _App
    CommandHandler = _CH
    CallbackQueryHandler = _CQH
    TelegramMessageHandler = _MH
    ContextTypes = _CT
    filters = _filters
    ParseMode = _PM
    ChatType = _CtT
    HTTPXRequest = _HR
    TELEGRAM_AVAILABLE = True
    return True


# Matches every character that MarkdownV2 requires to be backslash-escaped
# when it appears outside a code span or fenced code block.
_MDV2_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#\+\-=|{}.!\\])')


def _escape_mdv2(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters with a preceding backslash."""
    return _MDV2_ESCAPE_RE.sub(r'\\\1', text)


def _strip_mdv2(text: str) -> str:
    """Strip MarkdownV2 escape backslashes to produce clean plain text.

    Also removes MarkdownV2 formatting markers so the fallback
    doesn't show stray syntax characters from format_message conversion.
    """
    # Remove escape backslashes before special characters
    cleaned = re.sub(r'\\([_*\[\]()~`>#\+\-=|{}.!\\])', r'\1', text)
    # Remove standard markdown bold (**text** → text) BEFORE MarkdownV2 bold
    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
    # Remove MarkdownV2 bold markers that format_message converted from **bold**
    cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
    # Remove MarkdownV2 italic markers that format_message converted from *italic*
    # Use word boundary (\b) to avoid breaking snake_case like my_variable_name
    cleaned = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', cleaned)
    # Remove MarkdownV2 strikethrough markers (~text~ → text)
    cleaned = re.sub(r'~([^~]+)~', r'\1', cleaned)
    # Remove MarkdownV2 spoiler markers (||text|| → text)
    cleaned = re.sub(r'\|\|([^|]+)\|\|', r'\1', cleaned)
    return cleaned


_CHUNK_INDICATOR_ON_FENCE_RE = re.compile(
    r'(?m)^``` (?P<indicator>(?:\\)?\(\d+/\d+(?:\\)?\))$'
)


def _separate_chunk_indicator_from_fence(text: str) -> str:
    """Move ``(N/M)`` chunk markers off Telegram code-fence lines.

    ``truncate_message()`` appends chunk indicators to the end of a chunk. When
    the chunk had to close an in-progress fenced code block, that creates a
    line like ````` \\(1/2\\)`` after MarkdownV2 escaping. Telegram does not
    treat that as a clean closing fence, so it can reject MarkdownV2 and fall
    back to plain text. Put the indicator on its own line immediately after the
    closing fence.
    """
    return _CHUNK_INDICATOR_ON_FENCE_RE.sub(r'```\n\g<indicator>', text)


# ---------------------------------------------------------------------------
# Markdown table → Telegram-friendly row groups
# ---------------------------------------------------------------------------
# Telegram's MarkdownV2 has no table syntax — '|' is just an escaped literal,
# so pipe tables render as noisy backslash-pipe text with no alignment.
# The shared convert_table_to_bullets() in gateway.platforms.helpers handles
# the full conversion (detection + rendering); Telegram just calls it.



# ---------------------------------------------------------------------------
# Rich-message newline normalization
# ---------------------------------------------------------------------------

# Matches a protected region whose internal newlines must stay bare in the
# rich-message path: a fenced code block (```...```) OR a GFM pipe-table block
# (a header row, a delimiter row of dashes/pipes, then any pipe data rows).
# Telegram renders both natively, so injecting Markdown hard breaks inside them
# would corrupt the code block / table.
_RICH_PROTECTED_REGION_RE = re.compile(
    r'(?:```[^\n]*\n[\s\S]*?```)'                       # fenced code block
    r'|(?:^[^\n]*\|[^\n]*\n'                            # table header row (has a pipe)
    r'[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)+\|?[ \t]*'  # delimiter
    r'(?:\n[^\n]*\|[^\n]*)*)',                          # data rows (newline-led, trailing \n left for prose)
    re.MULTILINE,
)


def _rich_normalize_linebreaks(text: str) -> str:
    """Convert single ``\\n`` to Markdown hard breaks for the rich-message path.

    Standard Markdown treats a lone ``\\n`` as whitespace (soft break), so
    Bot API 10.1 ``sendRichMessage`` collapses multi-line content — e.g.
    slash-command lists joined with ``"\\n".join(lines)`` — into a single
    paragraph.  Adding two trailing spaces before each single newline
    forces a hard line break (``<br>``) in the rendered output.

    Paragraph breaks (``\\n\\n``), fenced code blocks, and GFM pipe-table
    blocks are left untouched: tables render natively in the rich path and a
    hard break injected into a row separator would corrupt the table.
    """
    if not text or '\n' not in text:
        return text

    out: list[str] = []
    # Split off protected regions (fenced code OR table blocks) and only inject
    # hard breaks in the prose between them. Boundary newlines are handled by
    # the original single-\n regex, which sees each prose run as a whole string.
    pos = 0
    for m in _RICH_PROTECTED_REGION_RE.finditer(text):
        prose = text[pos:m.start()]
        out.append(re.sub(r'(?<!\n)\n(?!\n)', '  \n', prose))
        out.append(m.group(0))  # protected region kept verbatim
        pos = m.end()
    tail = text[pos:]
    out.append(re.sub(r'(?<!\n)\n(?!\n)', '  \n', tail))
    return ''.join(out)


# Watchdog bound for `await updater.stop()`. When the underlying TCP socket is
# in CLOSE-WAIT the PTB polling task is blocked on epoll on the dead socket and
# never wakes, so an unguarded stop() hangs indefinitely and wedges the whole
# reconnect/teardown ladder. This is an internal safety bound (not a user knob),
# applied identically at every stop() site so no path can hang on a dead socket.
_UPDATER_STOP_TIMEOUT = 15.0
# start_polling() can also hang when the connection pool is in a degraded state
# after _drain_polling_connections(), particularly when both primary and fallback
# Telegram endpoints are unreachable. Bounding start_polling() prevents the
# reconnect ladder from stalling indefinitely and allows the heartbeat loop to
# trigger its own recovery path. Refs: NousResearch/naabiga-agent#59614
_UPDATER_START_TIMEOUT = 30.0


# TelegramAdapter is split across thematic mixins (extracted from this
# module) — see _telegram_mixins.py. Import BEFORE the class so the
# inheritance list below resolves; the mixins import nothing from
# adapter.py, so no cycle.
from plugins.platforms.telegram._telegram_mixins import (
    _TelegramAuthMixin,
    _TelegramCallbackMixin,
    _TelegramDraftMixin,
    _TelegramEventsMixin,
    _TelegramMediaMixin,
    _TelegramMentionsMixin,
    _TelegramObserveMixin,
    _TelegramPollingMixin,
    _TelegramSendMixin,
    _TelegramTopicsMixin,
)


class TelegramAdapter(
    _TelegramAuthMixin,
    _TelegramPollingMixin,
    _TelegramTopicsMixin,
    _TelegramSendMixin,
    _TelegramDraftMixin,
    _TelegramCallbackMixin,
    _TelegramMediaMixin,
    _TelegramMentionsMixin,
    _TelegramObserveMixin,
    _TelegramEventsMixin,
    BasePlatformAdapter,
):
    """
    Telegram bot adapter.

    Handles:
    - Receiving messages from users and groups
    - Sending responses with Telegram markdown
    - Forum topics (thread_id support)
    - Media messages
    """

    # Telegram message limits
    MAX_MESSAGE_LENGTH = 4096
    supports_code_blocks = True  # Telegram MarkdownV2 renders fenced code blocks
    splits_long_messages = True  # send() chunks via truncate_message(MAX_MESSAGE_LENGTH)
    # Bot API 10.1 Rich Messages cap the raw markdown/html text at 32,768
    # UTF-8 characters. Content above this is sent via the legacy chunking path.
    RICH_MESSAGE_MAX_CHARS = 32768
    # Backwards-compatible alias for tests/external callers that referenced the
    # initial implementation name. The API limit is character-based, not bytes.
    RICH_MESSAGE_MAX_BYTES = RICH_MESSAGE_MAX_CHARS
    # Threshold for detecting Telegram client-side message splits.
    # When a chunk is near this limit, a continuation is almost certain.
    _SPLIT_THRESHOLD = 4000
    MEDIA_GROUP_WAIT_SECONDS = 0.8
    _GENERAL_TOPIC_THREAD_ID = "1"

    # Telegram's edit_message applies MarkdownV2 formatting only on the
    # finalize=True path.  Without this flag, stream_consumer._send_or_edit
    # short-circuits when the raw text is unchanged between the last streamed
    # edit and the final edit, skipping the plain-text → MarkdownV2 conversion.
    # Fixes #25710.
    REQUIRES_EDIT_FINALIZE: bool = True

    # Adaptive text-batch ingress: short messages need a tighter delay so the
    # first token reaches the agent fast.  Numbers tuned for "feels instant":
    # ≤320 codepoints (one short paragraph) settles in ~180ms; ≤1024
    # (a normal paragraph) in ~240ms; longer waits the configured cap.
    # Always clamped to ``_text_batch_delay_seconds`` so an operator can lower
    # the cap further via env var.
    _TEXT_BATCH_FAST_LEN = 320
    _TEXT_BATCH_FAST_DELAY_S = 0.18
    _TEXT_BATCH_SHORT_LEN = 1024
    _TEXT_BATCH_SHORT_DELAY_S = 0.24

    @staticmethod
    def _env_float_clamped(
        name: str,
        default: float,
        *,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> float:
        """Read a float env var, reject non-finite values, and clamp to bounds.

        Guarantees the returned value is a finite number usable directly in
        ``asyncio.sleep()`` and similar APIs that reject NaN / Inf.
        """
        import math

        raw = os.getenv(name)
        try:
            value = float(raw) if raw is not None else float(default)
        except (TypeError, ValueError):
            value = float(default)
        if not math.isfinite(value):
            value = float(default)
        if min_value is not None:
            value = max(value, min_value)
        if max_value is not None:
            value = min(value, max_value)
        return value

    @property
    def message_len_fn(self):
        """Telegram measures message length in UTF-16 code units."""
        return utf16_len

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.TELEGRAM)
        self._app: Optional[Application] = None
        self._bot: Optional[Bot] = None
        self._webhook_mode: bool = False
        self._mention_patterns = self._compile_mention_patterns()
        self._reply_to_mode: str = getattr(config, 'reply_to_mode', 'first') or 'first'
        self._disable_link_previews: bool = self._coerce_bool_extra("disable_link_previews", False)
        # Bot API 10.1 Rich Messages: render constructs the legacy MarkdownV2
        # path degrades (tables → bullet lists, task lists, <details>, block
        # math) via sendRichMessage / editMessageText's rich_message param using
        # the raw agent markdown. Disabled by default so Telegram messages stay
        # easy to copy as plain text; users can opt in for richer rendering on
        # clients that accept but render rich messages poorly via
        # platforms.telegram.extra.rich_messages: true.  Keep this opt-in:
        # current Telegram clients can make rich messages difficult to copy
        # as plain text, which is worse than degraded table/task-list rendering
        # for command snippets and mobile handoffs.
        self._rich_messages_enabled: bool = self._coerce_bool_extra("rich_messages", False)
        # Rich draft previews use a separate opt-in. Telegram macOS / Desktop
        # can leave Bot API 10.1 rich draft frames visually overlaid until the
        # chat is redrawn, while final rich messages remain useful.
        self._rich_drafts_enabled: bool = self._coerce_bool_extra("rich_drafts", False)
        # Latched off after a capability failure on sendRichMessage /
        # sendRichMessageDraft (e.g. older python-telegram-bot without the
        # endpoint) so later sends skip the doomed rich attempt entirely.
        self._rich_send_disabled: bool = False
        self._rich_draft_disabled: bool = False
        # Transient Telegram sendChatAction failures (network blips, 429/5xx)
        # can happen on every keep-typing tick while the agent is waiting on a
        # long model call. Back off per chat so a short Telegram-side outage
        # does not spam the API/logs or burn the keep-typing budget.
        self._telegram_typing_cooldown_until: Dict[str, float] = {}
        self._telegram_typing_cooldown_seconds: float = self._coerce_float_extra(
            "typing_cooldown_seconds",
            30.0,
            min_value=1.0,
            max_value=300.0,
        )
        # Buffer rapid/album photo updates so Telegram image bursts are handled
        # as a single MessageEvent instead of self-interrupting multiple turns.
        self._media_batch_delay_seconds = env_float("NAABIGA_TELEGRAM_MEDIA_BATCH_DELAY_SECONDS", 0.8)
        self._pending_photo_batches: Dict[str, MessageEvent] = {}
        self._pending_photo_batch_tasks: Dict[str, asyncio.Task] = {}
        self._media_group_events: Dict[str, MessageEvent] = {}
        self._media_group_tasks: Dict[str, asyncio.Task] = {}
        # Buffer rapid text messages so Telegram client-side splits of long
        # messages are aggregated into a single MessageEvent.  Lower defaults
        # (0.3s / 1.0s instead of 0.6s / 2.0s) let short replies stream
        # without a noticeable wait — combined with the adaptive fast-path
        # in ``_calc_text_batch_delay`` below, ≤320-codepoint replies settle
        # in ~180ms.  All bounds are conservative for Telegram's
        # ~1 edit/s flood envelope.
        self._text_batch_delay_seconds = self._env_float_clamped(
            "NAABIGA_TELEGRAM_TEXT_BATCH_DELAY_SECONDS",
            0.3,
            min_value=0.08,
            max_value=2.0,
        )
        self._text_batch_split_delay_seconds = self._env_float_clamped(
            "NAABIGA_TELEGRAM_TEXT_BATCH_SPLIT_DELAY_SECONDS",
            1.0,
            min_value=self._text_batch_delay_seconds,
            max_value=4.0,
        )
        self._pending_text_batches: Dict[str, MessageEvent] = {}
        self._pending_text_batch_tasks: Dict[str, asyncio.Task] = {}
        self._drop_delayed_deliveries = False
        self._polling_error_task: Optional[asyncio.Task] = None
        self._polling_conflict_count: int = 0
        self._polling_network_error_count: int = 0
        self._polling_error_callback_ref = None
        self._polling_heartbeat_task: Optional[asyncio.Task] = None
        # Consecutive heartbeat probes that saw queued updates the running
        # poller is not consuming. get_me() can't see this — the send path is
        # healthy while the getUpdates consumer is wedged — so the heartbeat
        # also probes get_webhook_info().pending_update_count and escalates to
        # recovery after two consecutive stuck probes (#42909).
        self._polling_pending_stuck_count: int = 0
        # Consecutive heartbeat probes that found the updater stopped entirely
        # (running=False) while we are in polling mode with no reconnect in
        # flight. Distinct from the wedged-but-running case above: the long-poll
        # task is simply gone, so neither the connectivity probe nor PTB's
        # error_callback ever fires and the gateway silently stops receiving
        # messages with the process still alive (#55769).
        self._polling_not_running_count: int = 0
        # After sustained reconnect storms the PTB httpx pool can return
        # SendResult(success=True) for sends that never actually transmit.
        # _handle_polling_network_error sets this; _verify_polling_after_reconnect
        # clears it once getMe() confirms the Bot client is healthy.
        # While True, send() short-circuits to a failure so callers
        # (cron live-adapter branch) fall through to standalone delivery.
        self._send_path_degraded: bool = False
        self._general_request_drain_lock = asyncio.Lock()
        # DM Topics: map of topic_name -> message_thread_id (populated at startup)
        self._dm_topics: Dict[str, int] = {}
        # Track forum chats where we've already registered bot commands
        self._forum_command_registered: set[int] = set()
        # Lock per la registrazione sicura dei comandi nei forum supergroup
        self._forum_lock = asyncio.Lock()
        # Status indicator: when enabled, the bot's short description (the line
        # shown under its name in the profile) is set to "Online" on connect and
        # "Offline" on clean disconnect, so users can tell whether the gateway is
        # up. Telegram bots have no real presence/online dot (that's a user-account
        # feature), so the short description is the closest available surface.
        # Off by default — this mutates the bot's GLOBAL profile, visible to all
        # users. Opt in via gateway config: extra.status_indicator: true, or set
        # custom strings via extra.status_online / extra.status_offline.
        self._status_indicator_enabled: bool = bool(
            self.config.extra.get("status_indicator", False)
        )
        self._status_online_text: str = str(
            self.config.extra.get("status_online", "Online")
        )
        self._status_offline_text: str = str(
            self.config.extra.get("status_offline", "Offline")
        )
        # DM Topics config from extra.dm_topics
        self._dm_topics_config: List[Dict[str, Any]] = self.config.extra.get("dm_topics", [])
        # Precomputed chat_ids that have DM topics configured (for O(1) root-DM ignore check)
        self._dm_topic_chat_ids: Set[str] = {
            str(e["chat_id"]) for e in self._dm_topics_config if "chat_id" in e
        }
        # Document size cap. Telegram's public Bot API caps getFile at 20MB; a
        # locally-hosted telegram-bot-api server (configured via extra.base_url)
        # raises that to 2GB, so the presence of base_url is the opt-in.
        self._max_doc_bytes: int = (
            2 * 1024 * 1024 * 1024
            if self.config.extra.get("base_url")
            else 20 * 1024 * 1024
        )
        # Interactive model picker state per chat
        self._model_picker_state: Dict[str, dict] = {}
        # Approval button state: message_id → session_key
        self._approval_state: Dict[int, str] = {}
        # Slash-confirm button state: confirm_id → session_key (for /reload-mcp
        # and any other slash-confirm prompts; see GatewayRunner._request_slash_confirm).
        self._slash_confirm_state: Dict[str, str] = {}
        # Clarify button state: clarify_id → session_key (for the clarify tool's
        # multiple-choice prompts; see GatewayRunner clarify_callback wiring).
        self._clarify_state: Dict[str, str] = {}
        # Notification mode for message sends.
        # "important" — only final responses, approvals, and slash confirmations
        #               trigger notifications; tool progress, streaming, status
        #               messages are delivered silently via disable_notification.
        #               This is the default — Telegram users found per-tool-call
        #               push notifications too noisy.
        # "all"       — every message triggers a push notification (legacy
        #               behavior; opt-in via display.platforms.telegram.notifications).
        self._notifications_mode: str = "important"
        # send_or_update_status() bookkeeping: {(chat_id, status_key) -> bot message_id}
        # Tracks status bubbles owned by this adapter so subsequent calls with the
        # same key edit the same message instead of appending new ones (#30045).
        self._status_message_ids: Dict[tuple, str] = {}
        # Last truncated mid-stream preview delivered per (chat_id, message_id).
        # Once an oversized streaming edit saturates at the 4096 preview cap,
        # every subsequent progressive edit truncates to the SAME text; sending
        # it again is a no-op that still burns Telegram's flood budget (~1
        # edit/0.8s × the rest of the stream ⇒ flood control with 200s+
        # penalties, hanging final delivery). Dedup here so a saturated preview
        # goes quiet until finalize. Bounded: entries are dropped on finalize.
        self._last_overflow_preview: Dict[tuple, str] = {}
        # Background task that runs post-connect housekeeping (command-menu
        # registration + DM-topic setup) off the connect path so a slow Bot
        # API call (e.g. a set_my_commands stall for certain tokens) cannot
        # blow the gateway's connect timeout (#46298).
        self._post_connect_task: Optional[asyncio.Task] = None
    # ------------------------------------------------------------------
    # Bot API 10.1 Rich Messages (sendRichMessage)
    #
    # Final / new-message replies opportunistically use sendRichMessage with
    # the RAW agent markdown so richer constructs (tables, task lists,
    # collapsible details, math, ...) render natively. The legacy MarkdownV2
    # send() path stays as the fallback for unsupported/oversized content and
    # older PTB/clients. Streaming edits stay on Naabiga' existing MarkdownV2
    # edit path for now; finalization can re-send as rich and delete the stale
    # preview until rich_message edit support is wired directly.
    # ------------------------------------------------------------------
    _RICH_DETAILS_RE = re.compile(r"<details\b[^>]*>.*?</details>", re.IGNORECASE | re.DOTALL)
    _RICH_MATH_IN_DETAILS_RE = re.compile(
        r"(\$\$.*?\$\$|"
        r"\\\[.*?\\\]|"
        r"\\\(.*?\\\)|"
        r"\\(?:sum|frac|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|"
        r"int|prod|sqrt|lim|infty|begin\{(?:equation|align|matrix|cases)\}))",
        re.IGNORECASE | re.DOTALL,
    )
    _RICH_CJK_RE = re.compile(
        "["
        "\u3040-\u30ff"  # Hiragana, Katakana
        "\u3400-\u4dbf"  # CJK Extension A
        "\u4e00-\u9fff"  # CJK Unified Ideographs
        "\uac00-\ud7af"  # Hangul syllables
        "\uf900-\ufaff"  # CJK Compatibility Ideographs
        "\U00020000-\U000323af"  # CJK extensions and compatibility supplement
        "]"
    )
    _PROVIDER_PAGE_SIZE = 10
    _MODEL_PAGE_SIZE = 8
    # Maps `gt:<verb>` -> (script-name, extra-args, success-label, is_state).
    # Scripts live in ~/.naabiga/scripts/gmail-triage/. `arg` from the callback
    # data is always passed as the first positional arg.
    # is_state=True means the verb is a sticky sender-rule change (mute, trust,
    # vip) that should leave the keyboard tappable for follow-on actions.
    # is_state=False is a per-email one-shot (send, archive, draft, spam) that
    # strips the keyboard on success.
    _GT_VERB_DISPATCH = {
        "send":         ("send-draft.sh",      [],         "✓ sent draft",         False),
        "archive":      ("archive.sh",         [],         "✓ archived",           False),
        "draft":        ("draft-blank.sh",     [],         "✓ drafted reply",      False),
        "spam":         ("spam.sh",            [],         "✓ marked spam",        False),
        "mute":         ("mute-add.sh",        ["email"],  "✓ muted",              True),
        "mute-domain":  ("mute-add.sh",        ["domain"], "✓ muted domain",       True),
        "trust":        ("trusted-ops-add.sh", ["email"],  "✓ trusted",            True),
        "trust-domain": ("trusted-ops-add.sh", ["domain"], "✓ trusted domain",     True),
        "vip":          ("vip-add.sh",         ["email"],  "✓ marked VIP",         True),
        "vip-domain":   ("vip-add.sh",         ["domain"], "✓ marked VIP domain",  True),
    }
    # ── Group mention gating ──────────────────────────────────────────────
    # ------------------------------------------------------------------
    # Text message aggregation (handles Telegram client-side splits)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Photo batching
    # ------------------------------------------------------------------
    # ── Message reactions (processing lifecycle) ──────────────────────────
# ──────────────────────────────────────────────────────────────────────────
# Plugin migration glue (#41112 / #3823)
#
# Added when the Telegram adapter (+ its telegram_network satellite) moved from
# gateway/platforms/ into this bundled plugin. Mirrors the Discord (#24356) /
# Slack migrations: a register(ctx) entry point plus hook implementations that
# replace the per-platform core touchpoints (the Platform.TELEGRAM branch in
# gateway/run.py, the telegram_cfg YAML→env/extra block in gateway/config.py,
# the _setup_telegram wizard + _PLATFORMS["telegram"] static dict in
# naabiga_cli/{setup,gateway}.py, and the _send_telegram dispatch in
# tools/send_message_tool.py).  Telegram uses the generic token connected
# check, so no is_connected override is needed.
# ──────────────────────────────────────────────────────────────────────────


def _resolve_notifications_mode() -> str:
    """Resolve the Telegram notification mode (all/important) from env or
    config.yaml display.platforms.telegram.notifications, defaulting to
    'important'.  Mirrors the post-construction logic that used to live in
    gateway/run.py::_create_adapter()."""
    mode = os.getenv("NAABIGA_TELEGRAM_NOTIFICATIONS", "")
    if not mode:
        try:
            from gateway.config import load_gateway_config
            from gateway.run import cfg_get
            _gw_cfg = load_gateway_config()
            _raw = cfg_get(_gw_cfg, "display", "platforms", "telegram", "notifications")
            if _raw not in {None, ""}:
                mode = str(_raw).strip().lower()
        except Exception:
            pass
    mode = mode or "important"
    if mode not in {"all", "important"}:
        logger.warning(
            "Unknown telegram notifications mode '%s', defaulting to 'important' "
            "(valid: all, important)", mode,
        )
        mode = "important"
    return mode


def _build_adapter(config):
    """Factory wrapper that constructs TelegramAdapter and applies the
    notification mode (preserving the gateway/run.py post-construction step)."""
    adapter = TelegramAdapter(config)
    try:
        adapter._notifications_mode = _resolve_notifications_mode()
    except Exception:
        adapter._notifications_mode = "important"
    return adapter


def _is_connected(config) -> bool:
    """Telegram is connected when a bot token is configured.

    check_telegram_requirements() only verifies the python-telegram-bot SDK is
    importable, NOT that a token is set — so without this is_connected the
    registry-driven plugin-enable pass in gateway/config.py would enable
    Telegram on any machine that merely has the SDK installed. Gate on the
    token (env or PlatformConfig.token), matching the generic token check
    Telegram had as a built-in.
    """
    token = getattr(config, "token", None)
    if not token:
        import naabiga_cli.gateway as gateway_mod
        token = gateway_mod.get_env_value("TELEGRAM_BOT_TOKEN") or ""
    return bool(str(token).strip())


async def _standalone_send(
    pconfig,
    chat_id,
    message,
    *,
    thread_id=None,
    media_files=None,
    force_document=False,
):
    """Out-of-process Telegram delivery. Delegates to the standalone
    ``_send_telegram`` REST sender in tools/send_message_tool.py (which already
    handles chunking-agnostic single sends, threads, media, retries, and
    parse-mode fallback). Implements the standalone_sender_fn contract so
    deliver=telegram cron jobs succeed when cron runs separately from the
    gateway."""
    token = getattr(pconfig, "token", None) or os.getenv("TELEGRAM_BOT_TOKEN", "")
    disable_link_previews = bool(
        getattr(pconfig, "extra", {}) and pconfig.extra.get("disable_link_previews")
    )
    from tools.send_message_tool import _send_telegram
    return await _send_telegram(
        token,
        chat_id,
        message,
        media_files=media_files,
        thread_id=thread_id,
        disable_link_previews=disable_link_previews,
        force_document=force_document,
    )


def interactive_setup() -> None:
    """Configure Telegram bot credentials and allowlist.

    Delegates to the existing CLI setup helper (manual @BotFather token
    validation, allowlist capture) via lazy import so the full wizard
    behavior is preserved without duplicating ~150 lines. Replaces the
    _PLATFORMS["telegram"] static dict dispatch in naabiga_cli/gateway.py.
    """
    from naabiga_cli import setup as _setup_mod
    _setup_mod._setup_telegram()


def _apply_yaml_config(yaml_cfg: dict, telegram_cfg: dict) -> dict | None:
    """Translate config.yaml telegram: keys into TELEGRAM_* env vars and
    PlatformConfig.extra entries.

    Implements the apply_yaml_config_fn contract (#24849). Mirrors the legacy
    telegram_cfg block from gateway/config.py::load_gateway_config(). Env vars
    take precedence over YAML. Returns a dict of extras to merge into
    PlatformConfig.extra (disable_topic_auto_rename + runtime flags), or None.
    """
    import json as _json
    extras: dict = {}

    if "disable_topic_auto_rename" in telegram_cfg:
        extras.setdefault("disable_topic_auto_rename", telegram_cfg["disable_topic_auto_rename"])

    _effective_rm = telegram_cfg.get("require_mention", yaml_cfg.get("require_mention"))
    if _effective_rm is not None and not os.getenv("TELEGRAM_REQUIRE_MENTION"):
        os.environ["TELEGRAM_REQUIRE_MENTION"] = str(_effective_rm).lower()
    if "mention_patterns" in telegram_cfg and not os.getenv("TELEGRAM_MENTION_PATTERNS"):
        os.environ["TELEGRAM_MENTION_PATTERNS"] = _json.dumps(telegram_cfg["mention_patterns"])
    if "exclusive_bot_mentions" in telegram_cfg and not os.getenv("TELEGRAM_EXCLUSIVE_BOT_MENTIONS"):
        os.environ["TELEGRAM_EXCLUSIVE_BOT_MENTIONS"] = str(telegram_cfg["exclusive_bot_mentions"]).lower()
    if "allow_bots" in telegram_cfg and not os.getenv("TELEGRAM_ALLOW_BOTS"):
        os.environ["TELEGRAM_ALLOW_BOTS"] = str(telegram_cfg["allow_bots"]).lower()
    if "guest_mode" in telegram_cfg and not os.getenv("TELEGRAM_GUEST_MODE"):
        os.environ["TELEGRAM_GUEST_MODE"] = str(telegram_cfg["guest_mode"]).lower()
    if "observe_unmentioned_group_messages" in telegram_cfg and not os.getenv("TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES"):
        os.environ["TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES"] = str(telegram_cfg["observe_unmentioned_group_messages"]).lower()
    frc = telegram_cfg.get("free_response_chats")
    if frc is not None and not os.getenv("TELEGRAM_FREE_RESPONSE_CHATS"):
        if isinstance(frc, list):
            frc = ",".join(str(v) for v in frc)
        os.environ["TELEGRAM_FREE_RESPONSE_CHATS"] = str(frc)
    ac = telegram_cfg.get("allowed_chats")
    if ac is not None and not os.getenv("TELEGRAM_ALLOWED_CHATS"):
        if isinstance(ac, list):
            ac = ",".join(str(v) for v in ac)
        os.environ["TELEGRAM_ALLOWED_CHATS"] = str(ac)
    allowed_topics = telegram_cfg.get("allowed_topics")
    if allowed_topics is not None and not os.getenv("TELEGRAM_ALLOWED_TOPICS"):
        if isinstance(allowed_topics, list):
            allowed_topics = ",".join(str(v) for v in allowed_topics)
        os.environ["TELEGRAM_ALLOWED_TOPICS"] = str(allowed_topics)
    ignored_threads = telegram_cfg.get("ignored_threads")
    if ignored_threads is not None and not os.getenv("TELEGRAM_IGNORED_THREADS"):
        if isinstance(ignored_threads, list):
            ignored_threads = ",".join(str(v) for v in ignored_threads)
        os.environ["TELEGRAM_IGNORED_THREADS"] = str(ignored_threads)
    if "reactions" in telegram_cfg and not os.getenv("TELEGRAM_REACTIONS"):
        os.environ["TELEGRAM_REACTIONS"] = str(telegram_cfg["reactions"]).lower()
    if "proxy_url" in telegram_cfg and not os.getenv("TELEGRAM_PROXY"):
        os.environ["TELEGRAM_PROXY"] = str(telegram_cfg["proxy_url"]).strip()
    _telegram_extra = telegram_cfg.get("extra") if isinstance(telegram_cfg.get("extra"), dict) else {}
    _telegram_rtm = (
        telegram_cfg["reply_to_mode"] if "reply_to_mode" in telegram_cfg
        else _telegram_extra.get("reply_to_mode")
    )
    if _telegram_rtm is not None and not os.getenv("TELEGRAM_REPLY_TO_MODE"):
        _rtm_str = "off" if _telegram_rtm is False else str(_telegram_rtm).lower()
        os.environ["TELEGRAM_REPLY_TO_MODE"] = _rtm_str
    allowed_users = telegram_cfg.get("allow_from")
    if allowed_users is not None and not os.getenv("TELEGRAM_ALLOWED_USERS"):
        if isinstance(allowed_users, list):
            allowed_users = ",".join(str(v) for v in allowed_users)
        os.environ["TELEGRAM_ALLOWED_USERS"] = str(allowed_users)
    group_allowed_users = telegram_cfg.get("group_allow_from")
    if group_allowed_users is not None and not os.getenv("TELEGRAM_GROUP_ALLOWED_USERS"):
        if isinstance(group_allowed_users, list):
            group_allowed_users = ",".join(str(v) for v in group_allowed_users)
        os.environ["TELEGRAM_GROUP_ALLOWED_USERS"] = str(group_allowed_users)
    group_allowed_chats = telegram_cfg.get("group_allowed_chats")
    if group_allowed_chats is not None and not os.getenv("TELEGRAM_GROUP_ALLOWED_CHATS"):
        if isinstance(group_allowed_chats, list):
            group_allowed_chats = ",".join(str(v) for v in group_allowed_chats)
        os.environ["TELEGRAM_GROUP_ALLOWED_CHATS"] = str(group_allowed_chats)
    for _key in ("guest_mode", "disable_link_previews", "observe_unmentioned_group_messages"):
        if _key in telegram_cfg:
            extras.setdefault(_key, telegram_cfg[_key])
    # Pass through telegram-specific extra keys (e.g. base_url proxy override),
    # but EXCLUDE the generic shared-config keys that _merge_platform_map in
    # gateway/config.py already merges with correct top-level-over-nested
    # precedence. The apply_yaml_config_fn dispatch merges our return via
    # dict.update() (clobber), so re-emitting those generic keys here would
    # undo that precedence (top-level losing to a nested-fallback block).
    _GENERIC_MERGE_KEYS = {
        "reply_prefix", "reply_in_thread", "reply_to_mode",
        "unauthorized_dm_behavior", "notice_delivery", "require_mention",
        "channel_skill_bindings", "channel_prompts", "gateway_restart_notification",
        "allow_from", "allow_admin_from", "dm_policy", "group_policy",
    }
    for _k, _v in _telegram_extra.items():
        if _k not in _GENERIC_MERGE_KEYS:
            extras.setdefault(_k, _v)

    return extras or None


def register(ctx) -> None:
    """Plugin entry point — called by the Naabiga plugin system."""
    ctx.register_platform(
        name="telegram",
        label="Telegram",
        adapter_factory=_build_adapter,
        check_fn=check_telegram_requirements,
        is_connected=_is_connected,
        required_env=["TELEGRAM_BOT_TOKEN"],
        install_hint="pip install 'naabiga-agent[telegram]'",
        setup_fn=interactive_setup,
        apply_yaml_config_fn=_apply_yaml_config,
        allowed_users_env="TELEGRAM_ALLOWED_USERS",
        allow_all_env="TELEGRAM_ALLOW_ALL_USERS",
        cron_deliver_env_var="TELEGRAM_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        max_message_length=4096,
        emoji="✈️",
        allow_update_command=True,
    )
