import concurrent.futures
from collections import Counter
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

QUERIES_FILE = "queries_small.txt"
OUTPUT_FILE = "youtube_videos_small.txt"
DATABASE_FILE = "youtube_videos_small.json"
CHANNEL_CACHE_FILE = "youtube_channels_small.json"

# Internal scalable candidate/progress database.
CANDIDATE_DB_FILE = "youtube_candidates_small.sqlite3"
SEARCH_STATE_FILE = "youtube_search_state_small.json"

# Maximum search results requested for EACH query.
RESULTS_PER_QUERY = 500

# Keep these conservative. More workers can make throttling worse, not better.
SEARCH_WORKERS = 1
PROCESS_WORKERS = 12
CHANNEL_PREFETCH_WORKERS = 6

MIN_SUBSCRIBERS = 10_000

# ------------------------------------------------------------
# OPTIONAL YOUTUBE AUTHENTICATION
# ------------------------------------------------------------
#
# yt-dlp does not need your Google username/password.
# The preferred approach is to reuse an existing browser session
# or a Netscape-format cookies file.
#
# Leave False for anonymous behaviour.
USE_YOUTUBE_AUTH = True

# "browser" or "cookie_file"
YOUTUBE_AUTH_MODE = "browser"

# "fallback"
#     Try anonymously first.
#     Only use cookies when YouTube specifically requires sign-in.
#
# "always"
#     Use cookies for all video/channel metadata requests.
#
# "fallback" is recommended for large runs.
YOUTUBE_AUTH_STRATEGY = "fallback"

# Supported examples:
# firefox
# chrome
# edge
# brave
# chromium
# opera
# safari
# vivaldi
# whale
YOUTUBE_COOKIE_BROWSER = "edge"

# Usually leave these as None.
#
# Example Windows Chrome profile:
#
# YOUTUBE_COOKIE_BROWSER_PROFILE = (
#     r"C:\Users\YOUR_NAME\AppData\Local\Google\Chrome\User Data\Default"
# )
#
YOUTUBE_COOKIE_BROWSER_PROFILE = None
YOUTUBE_COOKIE_BROWSER_KEYRING = None
YOUTUBE_COOKIE_BROWSER_CONTAINER = None

# Used only when YOUTUBE_AUTH_MODE == "cookie_file".
#
# IMPORTANT:
# Cookie files contain sensitive login-session information.
# Never commit one to Git.
YOUTUBE_COOKIE_FILE = "youtube_cookies.txt"

# Keep search requests anonymous by default, even when authentication
# is enabled. This avoids attaching thousands of discovery requests
# to your logged-in YouTube account.
USE_AUTH_FOR_SEARCH = False

# Validate the configured cookies when the program starts.
# This checks cookie loading only and does not perform a YouTube request.
VALIDATE_AUTH_AT_STARTUP = True

# ------------------------------------------------------------
# REQUEST PACING / ADAPTIVE RATE-LIMIT RECOVERY
# ------------------------------------------------------------

# Small global spacing between metadata request starts.
#
# With 12 workers this mainly smooths request bursts rather than
# limiting normal throughput.
METADATA_REQUEST_INTERVAL = 0.08

# If YouTube explicitly reports that the current session has been
# rate-limited, ALL metadata workers pause together.
#
# Repeated rate-limit bursts escalate the cooldown.
RATE_LIMIT_COOLDOWN_SCHEDULE = (
    90,
    180,
    300,
)

RATE_LIMIT_MAX_RETRIES = 3

# If no new rate limit appears for this long, the adaptive throttle
# can eventually return to normal.
RATE_LIMIT_RESET_SECONDS = 20 * 60

# After this many successful lookups, reduce the throttle penalty
# by one level.
RATE_LIMIT_RECOVERY_SUCCESSES = 250

# Slightly increase request spacing after rate limiting.
RATE_LIMIT_PENALTY_INTERVALS = (
    0.15,
    0.30,
    0.60,
)

# If all automatic rate-limit retries fail, mark the video as
# "deferred" rather than permanently failed.
RATE_LIMIT_DEFERRED_RETRY_SECONDS = 15 * 60

# ------------------------------------------------------------
# SEARCH / NETWORK SETTINGS
# ------------------------------------------------------------

SEARCH_DELAY = 1.0

MAX_RETRIES = 3
RETRY_DELAY = 5.0
SOCKET_TIMEOUT = 20

# Shared search backoff.
FORBIDDEN_COOLDOWN_THRESHOLD = 10
FORBIDDEN_COOLDOWN_SECONDS = 30.0

# ------------------------------------------------------------
# CHANNEL CACHE
# ------------------------------------------------------------

CHANNEL_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
FAILED_CHANNEL_CACHE_TTL_SECONDS = 15 * 60
CHANNEL_SINGLEFLIGHT_WAIT_SECONDS = 120

# If the same channel occurs at least this many times, resolve the
# channel once before processing the individual videos.
CHANNEL_PREFETCH_MIN_CANDIDATES = 2

# ------------------------------------------------------------
# SAVE SETTINGS
# ------------------------------------------------------------

SAVE_EVERY = 1000
SAVE_INTERVAL_SECONDS = 120
SEARCH_STATE_SAVE_EVERY = 25

# ------------------------------------------------------------
# SQLITE
# ------------------------------------------------------------

SQLITE_TIMEOUT = 30
SQLITE_BATCH_SIZE = 500
SQLITE_STATUS_BATCH_SIZE = 100

MAX_CANDIDATE_ATTEMPTS = 3
FAILED_RETRY_DELAY_SECONDS = 6 * 60 * 60

# ------------------------------------------------------------
# DISPLAY / QUEUE
# ------------------------------------------------------------

PROCESS_PRINT_EVERY = 25

PROCESS_BATCH_MULTIPLIER = 8
SEARCH_QUEUE_MULTIPLIER = 2

# ------------------------------------------------------------
# VALIDATION
# ------------------------------------------------------------

VIDEO_ID_RE = re.compile(
    r"^[A-Za-z0-9_-]{11}$"
)

SUPPORTED_COOKIE_BROWSERS = {
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
}


# ============================================================
# GLOBAL LOCKS / THREAD-LOCAL STATE
# ============================================================

database_lock = threading.Lock()
channel_cache_lock = threading.Lock()
save_lock = threading.Lock()
print_lock = threading.Lock()
channel_inflight_lock = threading.Lock()

thread_local = threading.local()

# channel_id -> threading.Event
channel_inflight = {}


# ============================================================
# AUTH STATE
# ============================================================


class AuthState:
    def __init__(self):
        self.lock = threading.Lock()
        self.disabled_reason = None
        self.fallback_notice_printed = False

    def disable(self, reason):
        with self.lock:
            if self.disabled_reason is None:
                self.disabled_reason = str(reason)

    def mark_fallback_notice(self):
        with self.lock:
            if self.fallback_notice_printed:
                return False

            self.fallback_notice_printed = True
            return True


auth_state = AuthState()


# ============================================================
# ADAPTIVE METADATA THROTTLE
# ============================================================


class AdaptiveMetadataThrottle:
    """
    Global request pacer plus shared rate-limit cooldown.

    Every metadata worker uses this object.

    If one worker receives an explicit YouTube session rate-limit
    message, all workers pause rather than the remaining threads
    continuing to hammer the same session.
    """

    def __init__(self):
        self.lock = threading.Lock()

        self.blocked_until = 0.0
        self.next_request_at = 0.0

        self.penalty_level = 0
        self.last_rate_limit = 0.0

        self.successes_since_limit = 0

    def _current_interval_locked(self):
        if self.penalty_level <= 0:
            return METADATA_REQUEST_INTERVAL

        index = min(
            self.penalty_level - 1,
            len(RATE_LIMIT_PENALTY_INTERVALS) - 1,
        )

        return max(
            METADATA_REQUEST_INTERVAL,
            RATE_LIMIT_PENALTY_INTERVALS[index],
        )

    def wait_for_turn(self):
        while True:
            with self.lock:
                now = time.monotonic()

                target = max(
                    self.blocked_until,
                    self.next_request_at,
                )

                remaining = target - now

                if remaining <= 0:
                    interval = (
                        self._current_interval_locked()
                    )

                    self.next_request_at = (
                        now + interval
                    )

                    return

            time.sleep(
                min(
                    remaining,
                    1.0,
                )
            )

    def record_rate_limit(self):
        """
        Return:

        (
            cooldown_seconds,
            started_new_cooldown,
            penalty_level,
        )
        """

        with self.lock:
            now = time.monotonic()

            if (
                now - self.last_rate_limit
                > RATE_LIMIT_RESET_SECONDS
            ):
                self.penalty_level = 0

            # Multiple workers can receive the same rate-limit
            # response at almost the same time.
            #
            # Only the first worker starts the shared cooldown.
            if now < self.blocked_until:
                return (
                    self.blocked_until - now,
                    False,
                    self.penalty_level,
                )

            index = min(
                self.penalty_level,
                len(
                    RATE_LIMIT_COOLDOWN_SCHEDULE
                ) - 1,
            )

            cooldown = float(
                RATE_LIMIT_COOLDOWN_SCHEDULE[
                    index
                ]
            )

            self.penalty_level = min(
                self.penalty_level + 1,
                max(
                    len(
                        RATE_LIMIT_PENALTY_INTERVALS
                    ),
                    1,
                ),
            )

            self.blocked_until = (
                now + cooldown
            )

            self.last_rate_limit = now
            self.successes_since_limit = 0

            return (
                cooldown,
                True,
                self.penalty_level,
            )

    def record_success(self):
        with self.lock:
            if self.penalty_level <= 0:
                return

            self.successes_since_limit += 1

            if (
                self.successes_since_limit
                >= RATE_LIMIT_RECOVERY_SUCCESSES
            ):
                self.penalty_level -= 1
                self.successes_since_limit = 0

    def status(self):
        with self.lock:
            return {
                "penalty_level":
                    self.penalty_level,

                "blocked_for":
                    max(
                        0.0,
                        self.blocked_until
                        - time.monotonic(),
                    ),

                "interval":
                    self._current_interval_locked(),
            }


metadata_throttle = (
    AdaptiveMetadataThrottle()
)


# ============================================================
# SAFE OUTPUT
# ============================================================


def safe_print(
    *args,
    **kwargs,
):
    with print_lock:
        print(
            *args,
            **kwargs,
        )


# ============================================================
# SMALL HELPERS
# ============================================================


def utc_timestamp():
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(),
    )


def stable_jitter(value):
    """
    Deterministic jitter.

    Unlike Python's hash(), this is stable between runs.
    """

    digest = hashlib.blake2s(
        str(value).encode(
            "utf-8"
        ),
        digest_size=2,
    ).digest()

    integer = int.from_bytes(
        digest,
        "big",
    )

    return (
        0.25
        +
        (
            integer
            /
            65535.0
        )
        *
        0.25
    )


def format_duration(seconds):
    if seconds <= 0:
        return "--"

    seconds = int(seconds)

    days, seconds = divmod(
        seconds,
        86400,
    )

    hours, seconds = divmod(
        seconds,
        3600,
    )

    minutes, seconds = divmod(
        seconds,
        60,
    )

    if days:
        return (
            f"{days}d {hours}h"
        )

    if hours:
        return (
            f"{hours}h {minutes}m"
        )

    if minutes:
        return (
            f"{minutes}m {seconds}s"
        )

    return f"{seconds}s"


def is_valid_video_id(value):
    return bool(
        VIDEO_ID_RE.fullmatch(
            str(
                value or ""
            )
        )
    )


def error_text(error):
    return str(
        error
    ).lower()


# ============================================================
# ERROR CLASSIFICATION
# ============================================================


def is_rate_limit_error(error):
    message = error_text(
        error
    )

    markers = (
        "current session has been rate-limited",
        "rate-limited by youtube",
        "http error 429",
        "429 too many requests",
        "too many requests",
    )

    return any(
        marker in message
        for marker in markers
    )


def is_auth_required_error(error):
    message = error_text(
        error
    )

    markers = (
        "sign in to confirm your age",
        "please sign in",
        "login required",
        "sign in to confirm you're not a bot",
        "sign in to confirm you’re not a bot",
        "authentication required",
        "members-only content",
    )

    return any(
        marker in message
        for marker in markers
    )


def is_unavailable_error(error):
    # These have special handling and should not
    # become permanent "unavailable" results.
    if (
        is_rate_limit_error(
            error
        )
        or
        is_auth_required_error(
            error
        )
    ):
        return False

    message = error_text(
        error
    )

    markers = (
        "video unavailable",
        "this video is unavailable",
        "this video is not available",
        "private video",
        "video has been removed",
        "video removed",
        "deleted video",
        "removed by the uploader",
        "copyright grounds",
        "account associated with this video has been terminated",
    )

    return any(
        marker in message
        for marker in markers
    )


def is_forbidden_error(error):
    message = error_text(
        error
    )

    return (
        "http error 403"
        in message

        or
        "403 forbidden"
        in message

        or
        "status code: 403"
        in message
    )


def is_retryable_error(error):
    message = error_text(
        error
    )

    retry_markers = (
        "http error 403",
        "403 forbidden",
        "http error 429",
        "too many requests",
        "http error 500",
        "http error 502",
        "http error 503",
        "http error 504",
        "timed out",
        "timeout",
        "temporary failure",
        "connection reset",
        "connection aborted",
        "remote end closed",
        "network is unreachable",
    )

    return any(
        marker in message
        for marker
        in retry_markers
    )


# ============================================================
# AUTH HELPERS
# ============================================================


def auth_enabled():
    return bool(
        USE_YOUTUBE_AUTH
        and
        not auth_state.disabled_reason
    )


def auth_description():
    if not USE_YOUTUBE_AUTH:
        return "Disabled"

    if auth_state.disabled_reason:
        return (
            "Disabled after configuration error: "
            f"{auth_state.disabled_reason}"
        )

    if (
        YOUTUBE_AUTH_MODE
        == "browser"
    ):
        detail = (
            YOUTUBE_COOKIE_BROWSER
        )

        if (
            YOUTUBE_COOKIE_BROWSER_PROFILE
        ):
            detail += (
                ":"
                +
                str(
                    YOUTUBE_COOKIE_BROWSER_PROFILE
                )
            )

        return (
            "Browser cookies "
            f"({detail}, "
            f"strategy="
            f"{YOUTUBE_AUTH_STRATEGY})"
        )

    if (
        YOUTUBE_AUTH_MODE
        == "cookie_file"
    ):
        return (
            "Cookie file "
            f"({YOUTUBE_COOKIE_FILE}, "
            f"strategy="
            f"{YOUTUBE_AUTH_STRATEGY})"
        )

    return (
        "Invalid mode: "
        f"{YOUTUBE_AUTH_MODE}"
    )


# ============================================================
# JSON STORAGE
# ============================================================


def load_json(
    filename,
    default,
):
    if not os.path.exists(
        filename
    ):
        return default

    try:
        with open(
            filename,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(
                f
            )

    except Exception as error:
        safe_print(
            f"[!] Failed to load "
            f"{filename}: "
            f"{error}"
        )

        return default


def atomic_save_json(
    filename,
    data,
):
    """
    Write JSON beside the destination,
    fsync it, then atomically replace.
    """

    destination = Path(
        filename
    )

    temp_path = (
        destination.with_name(
            destination.name
            +
            ".tmp"
        )
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

        f.flush()
        os.fsync(
            f.fileno()
        )

    os.replace(
        temp_path,
        destination,
    )


def save_all(
    database,
    channel_cache,
):
    """
    Safely snapshot and save both
    public JSON databases.
    """

    with save_lock:
        with database_lock:
            database_copy = dict(
                database
            )

        with channel_cache_lock:
            cache_copy = dict(
                channel_cache
            )

        atomic_save_json(
            DATABASE_FILE,
            database_copy,
        )

        atomic_save_json(
            CHANNEL_CACHE_FILE,
            cache_copy,
        )


# ============================================================
# SEARCH STATE
# ============================================================


def load_search_state(
    valid_queries,
):
    """
    Return completed query strings.

    Version 1 stored list indexes.

    Index-based state is unsafe if the
    queries file is reordered or edited,
    so old index state is deliberately
    ignored.
    """

    state = load_json(
        SEARCH_STATE_FILE,
        {},
    )

    completed = state.get(
        "completed_queries",
        [],
    )

    if (
        completed
        and
        all(
            isinstance(
                item,
                int,
            )
            for item
            in completed
        )
    ):
        safe_print(
            "[*] Legacy index-based "
            "search state detected; "
            "ignoring it once to avoid "
            "skipping the wrong queries."
        )

        return set()

    valid_set = set(
        valid_queries
    )

    return {
        item
        for item
        in completed
        if (
            isinstance(
                item,
                str,
            )
            and
            item in valid_set
        )
    }


def save_search_state(
    completed_queries,
):
    payload = {
        "version": 2,

        "completed_queries":
            sorted(
                completed_queries
            ),

        "updated_at":
            utc_timestamp(),
    }

    atomic_save_json(
        SEARCH_STATE_FILE,
        payload,
    )


# ============================================================
# QUERIES
# ============================================================


def load_queries():
    if not os.path.exists(
        QUERIES_FILE
    ):
        safe_print(
            f"[!] {QUERIES_FILE} "
            "does not exist."
        )

        safe_print()

        safe_print(
            "Create "
            f"{QUERIES_FILE} "
            "with one search per line."
        )

        safe_print()

        safe_print(
            "minecraft ARG"
        )

        safe_print(
            "minecraft mystery"
        )

        safe_print(
            "minecraft hidden message"
        )

        safe_print()

        sys.exit(
            1
        )

    queries = []
    seen = set()
    duplicates = 0

    with open(
        QUERIES_FILE,
        "r",
        encoding="utf-8",
    ) as f:

        for line in f:
            query = (
                line.strip()
            )

            if (
                not query
                or
                query.startswith(
                    "#"
                )
            ):
                continue

            if query in seen:
                duplicates += 1
                continue

            seen.add(
                query
            )

            queries.append(
                query
            )

    if duplicates:
        safe_print(
            f"[*] Ignored "
            f"{duplicates:,} "
            "duplicate queries."
        )

    if not queries:
        safe_print(
            f"[!] {QUERIES_FILE} "
            "contains no usable "
            "queries."
        )

        sys.exit(
            1
        )

    return queries


# ============================================================
# SQLITE CANDIDATE STORE
# ============================================================


class CandidateStore:
    """
    Thread-safe SQLite candidate/progress
    store with batched writes.
    """

    def __init__(
        self,
        filename,
    ):
        self.filename = filename
        self.lock = (
            threading.Lock()
        )

        self.conn = (
            self._connect()
        )

        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(
            self.filename,
            timeout=SQLITE_TIMEOUT,
            check_same_thread=False,
        )

        conn.execute(
            "PRAGMA journal_mode=WAL"
        )

        conn.execute(
            "PRAGMA synchronous=NORMAL"
        )

        conn.execute(
            "PRAGMA busy_timeout="
            f"{SQLITE_TIMEOUT * 1000}"
        )

        return conn

    def _init_schema(self):
        with self.lock:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    video_id TEXT PRIMARY KEY,
                    channel_id TEXT,
                    uploader TEXT,
                    status TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL
                )
                """
            )

            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS "
                "idx_candidates_status "
                "ON candidates(status)"
            )

            self.conn.commit()

    def add_candidates(
        self,
        rows,
    ):
        if not rows:
            return

        now = time.time()

        payload = [
            (
                row["id"],
                row.get(
                    "channel_id"
                ),
                row.get(
                    "uploader",
                    "",
                ),
                now,
            )

            for row
            in rows

            if is_valid_video_id(
                row.get(
                    "id"
                )
            )
        ]

        if not payload:
            return

        with self.lock:
            self.conn.executemany(
                """
                INSERT INTO candidates(
                    video_id,
                    channel_id,
                    uploader,
                    updated_at
                )
                VALUES (?, ?, ?, ?)

                ON CONFLICT(video_id)
                DO UPDATE SET

                    channel_id =
                        COALESCE(
                            candidates.channel_id,
                            excluded.channel_id
                        ),

                    uploader =
                        CASE
                            WHEN
                                candidates.uploader
                                IS NULL
                                OR
                                candidates.uploader = ''
                            THEN
                                excluded.uploader
                            ELSE
                                candidates.uploader
                        END
                """,
                payload,
            )

            self.conn.commit()

    def set_status_many(
        self,
        results,
        increment_attempt=False,
    ):
        results = list(
            results
        )

        if not results:
            return

        now = time.time()

        payload = [
            (
                status,
                now,
                video_id,
            )

            for video_id, status
            in results
        ]

        if increment_attempt:
            sql = """
                UPDATE candidates

                SET
                    status = ?,
                    attempts = attempts + 1,
                    updated_at = ?

                WHERE
                    video_id = ?
            """

        else:
            sql = """
                UPDATE candidates

                SET
                    status = ?,
                    updated_at = ?

                WHERE
                    video_id = ?
            """

        with self.lock:
            self.conn.executemany(
                sql,
                payload,
            )

            self.conn.commit()

    def finish(
        self,
        video_id,
        status,
    ):
        self.set_status_many(
            [
                (
                    video_id,
                    status,
                )
            ],
            increment_attempt=True,
        )

    def finish_many(
        self,
        results,
    ):
        self.set_status_many(
            results,
            increment_attempt=True,
        )

    def set_status_without_attempt(
        self,
        video_id,
        status,
    ):
        self.set_status_many(
            [
                (
                    video_id,
                    status,
                )
            ],
            increment_attempt=False,
        )

    def set_status_many_without_attempt(
        self,
        results,
    ):
        self.set_status_many(
            results,
            increment_attempt=False,
        )

    def count(self):
        with self.lock:
            row = (
                self.conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM candidates
                    """
                )
                .fetchone()
            )

        return int(
            row[0]
        )

    def status_counts(self):
        with self.lock:
            rows = (
                self.conn.execute(
                    """
                    SELECT
                        COALESCE(
                            status,
                            'pending'
                        ) AS status,
                        COUNT(*)

                    FROM candidates

                    GROUP BY
                        COALESCE(
                            status,
                            'pending'
                        )
                    """
                )
                .fetchall()
            )

        result = {
            "pending": 0,
            "new": 0,
            "filtered": 0,
            "failed": 0,
            "unavailable": 0,
            "auth_required": 0,
            "deferred": 0,
            "invalid": 0,
        }

        for status, count in rows:
            result[
                status
            ] = int(
                count
            )

        return result

    def iter_pending(
        self,
        include_auth_required=False,
    ):
        """
        Stream candidates eligible for
        processing.

        Includes:

        - New candidates
        - Generic failures after cooldown
        - Deferred rate-limited items
        - Auth-required items if auth is now
          enabled
        """

        conn = self._connect()

        failed_retry_before = (
            time.time()
            -
            FAILED_RETRY_DELAY_SECONDS
        )

        deferred_retry_before = (
            time.time()
            -
            RATE_LIMIT_DEFERRED_RETRY_SECONDS
        )

        if include_auth_required:
            auth_clause = (
                "OR status = 'auth_required'"
            )

        else:
            auth_clause = ""

        try:
            cursor = conn.execute(
                f"""
                SELECT
                    video_id,
                    channel_id,
                    uploader

                FROM candidates

                WHERE

                    status IS NULL

                    OR (
                        status = 'failed'
                        AND attempts < ?
                        AND (
                            updated_at IS NULL
                            OR updated_at <= ?
                        )
                    )

                    OR (
                        status = 'deferred'
                        AND (
                            updated_at IS NULL
                            OR updated_at <= ?
                        )
                    )

                    {auth_clause}

                ORDER BY rowid
                """,
                (
                    MAX_CANDIDATE_ATTEMPTS,
                    failed_retry_before,
                    deferred_retry_before,
                ),
            )

            while True:
                rows = cursor.fetchmany(
                    SQLITE_BATCH_SIZE
                )

                if not rows:
                    break

                for (
                    video_id,
                    channel_id,
                    uploader,
                ) in rows:

                    yield {
                        "id":
                            video_id,

                        "channel_id":
                            channel_id,

                        "uploader":
                            uploader
                            or "",
                    }

        finally:
            conn.close()

    def close(self):
        with self.lock:
            self.conn.close()


# ============================================================
# SHARED SEARCH THROTTLE
# ============================================================


class SearchThrottle:
    def __init__(self):
        self.lock = (
            threading.Lock()
        )

        self.forbidden_count = 0
        self.blocked_until = 0.0

    def wait_if_blocked(self):
        while True:
            with self.lock:
                remaining = (
                    self.blocked_until
                    -
                    time.monotonic()
                )

            if remaining <= 0:
                return

            time.sleep(
                min(
                    remaining,
                    1.0,
                )
            )

    def record_success(self):
        with self.lock:
            if self.forbidden_count:
                self.forbidden_count -= 1

    def record_forbidden(self):
        with self.lock:
            self.forbidden_count += 1

            current = (
                self.forbidden_count
            )

            triggered = (
                current
                >=
                FORBIDDEN_COOLDOWN_THRESHOLD
            )

            if triggered:
                self.blocked_until = max(
                    self.blocked_until,
                    time.monotonic()
                    +
                    FORBIDDEN_COOLDOWN_SECONDS,
                )

                self.forbidden_count = 0

        safe_print(
            "[403] Search blocked | "
            "Shared 403 count: "
            f"{current}"
        )

        if triggered:
            safe_print(
                "[THROTTLE] Pausing "
                "new search requests for "
                f"{FORBIDDEN_COOLDOWN_SECONDS:.0f}s."
            )


search_throttle = (
    SearchThrottle()
)


# ============================================================
# YT-DLP INSTANCES / OPTIONAL AUTH
# ============================================================


class QuietYDLLogger:
    """
    Suppress duplicate yt-dlp console errors.

    Exceptions are still returned to the
    script and printed in a cleaner form.
    """

    def debug(
        self,
        _message,
    ):
        pass

    def info(
        self,
        _message,
    ):
        pass

    def warning(
        self,
        _message,
    ):
        pass

    def error(
        self,
        _message,
    ):
        pass


quiet_ydl_logger = (
    QuietYDLLogger()
)


def auth_ydl_options():
    if not USE_YOUTUBE_AUTH:
        return {}

    mode = (
        str(
            YOUTUBE_AUTH_MODE
        )
        .strip()
        .lower()
    )

    if mode == "browser":
        browser = (
            str(
                YOUTUBE_COOKIE_BROWSER
            )
            .strip()
            .lower()
        )

        if (
            browser
            not in
            SUPPORTED_COOKIE_BROWSERS
        ):
            raise ValueError(
                "Unsupported cookie browser "
                f"{browser!r}. Supported: "
                +
                ", ".join(
                    sorted(
                        SUPPORTED_COOKIE_BROWSERS
                    )
                )
            )

        keyring = (
            YOUTUBE_COOKIE_BROWSER_KEYRING
        )

        if (
            isinstance(
                keyring,
                str,
            )
            and
            keyring
        ):
            keyring = (
                keyring.upper()
            )

        # Current yt-dlp Python API shape:
        #
        # (
        #     browser,
        #     profile,
        #     keyring,
        #     container,
        # )
        #
        return {
            "cookiesfrombrowser": (
                browser,
                YOUTUBE_COOKIE_BROWSER_PROFILE,
                keyring,
                YOUTUBE_COOKIE_BROWSER_CONTAINER,
            )
        }

    if mode == "cookie_file":
        cookie_path = (
            Path(
                YOUTUBE_COOKIE_FILE
            )
            .expanduser()
        )

        if not cookie_path.exists():
            raise FileNotFoundError(
                "Cookie file does not exist: "
                f"{cookie_path}"
            )

        return {
            "cookiefile":
                str(
                    cookie_path
                )
        }

    raise ValueError(
        "YOUTUBE_AUTH_MODE must be "
        "'browser' or 'cookie_file'. "
        "Got "
        f"{YOUTUBE_AUTH_MODE!r}"
    )


def validate_auth_configuration():
    if (
        not USE_YOUTUBE_AUTH
        or
        not VALIDATE_AUTH_AT_STARTUP
    ):
        return True

    try:
        import yt_dlp

        options = {
            "quiet": True,
            "no_warnings": True,
            "logger":
                quiet_ydl_logger,

            **auth_ydl_options(),
        }

        ydl = yt_dlp.YoutubeDL(
            options
        )

        try:
            # Force cookie loading.
            _ = ydl.cookiejar

        finally:
            close = getattr(
                ydl,
                "close",
                None,
            )

            if callable(
                close
            ):
                close()

        safe_print(
            "[+] Authentication "
            "cookies loaded: "
            f"{auth_description()}"
        )

        safe_print(
            "[!] Authenticated "
            "requests are tied to "
            "that YouTube account/session. "
            "Keep cookies private."
        )

        return True

    except Exception as error:
        auth_state.disable(
            error
        )

        safe_print(
            "[!] Optional YouTube "
            "authentication disabled: "
            f"{error}"
        )

        safe_print(
            "[*] Continuing anonymously."
        )

        return False


def get_ydl(
    kind,
    authenticated=False,
):
    """
    Create one YoutubeDL instance per
    worker thread and auth state.
    """

    import yt_dlp

    authenticated = bool(
        authenticated
        and
        auth_enabled()
    )

    suffix = (
        "auth"
        if authenticated
        else
        "anon"
    )

    attr = (
        f"ydl_{kind}_{suffix}"
    )

    existing = getattr(
        thread_local,
        attr,
        None,
    )

    if existing is not None:
        return existing

    common = {
        "quiet": True,
        "no_warnings": True,
        "logger":
            quiet_ydl_logger,

        "ignoreerrors": False,
        "skip_download": True,
        "noplaylist": True,

        "socket_timeout":
            SOCKET_TIMEOUT,

        # This script owns retries.
        "retries": 0,
        "fragment_retries": 0,
    }

    if authenticated:
        try:
            common.update(
                auth_ydl_options()
            )

        except Exception as error:
            auth_state.disable(
                error
            )

            raise

    if kind == "search":
        options = {
            **common,
            "extract_flat": True,
        }

    elif kind == "channel":
        # We only want channel header
        # metadata.
        #
        # Do not walk through uploaded
        # videos because one private or
        # unavailable upload can otherwise
        # cause a valid channel lookup to
        # fail.
        options = {
            **common,
            "extract_flat": True,
            "playlist_items": "0",
        }

    elif kind == "video":
        options = common

    else:
        raise ValueError(
            "Unknown yt-dlp kind: "
            f"{kind}"
        )

    try:
        ydl = yt_dlp.YoutubeDL(
            options
        )

    except Exception as error:
        if authenticated:
            auth_state.disable(
                error
            )

        raise

    setattr(
        thread_local,
        attr,
        ydl,
    )

    return ydl


# ============================================================
# YOUTUBE SEARCH
# ============================================================


def enforce_per_worker_search_delay():
    last_search = getattr(
        thread_local,
        "last_search_time",
        0.0,
    )

    elapsed = (
        time.monotonic()
        -
        last_search
    )

    if elapsed < SEARCH_DELAY:
        time.sleep(
            SEARCH_DELAY
            -
            elapsed
        )

    thread_local.last_search_time = (
        time.monotonic()
    )


def search_youtube(query):
    """
    Return:

    (
        videos,
        complete,
        forbidden_seen,
    )
    """

    search_term = (
        f"ytsearch"
        f"{RESULTS_PER_QUERY}:"
        f"{query}"
    )

    last_error = None
    forbidden_seen = False

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        search_throttle.wait_if_blocked()
        enforce_per_worker_search_delay()

        try:
            result = get_ydl(
                "search",
                authenticated=bool(
                    USE_AUTH_FOR_SEARCH
                    and
                    auth_enabled()
                ),
            ).extract_info(
                search_term,
                download=False,
            )

            if not result:
                search_throttle.record_success()

                return (
                    [],
                    True,
                    forbidden_seen,
                )

            videos = []

            for entry in (
                result.get(
                    "entries"
                )
                or
                []
            ):
                if not entry:
                    continue

                video_id = entry.get(
                    "id"
                )

                # Prevent channel IDs, shelves,
                # playlist IDs etc. from entering
                # the video candidate database.
                if not is_valid_video_id(
                    video_id
                ):
                    continue

                videos.append(
                    {
                        "id":
                            video_id,

                        "channel_id":
                            entry.get(
                                "channel_id"
                            ),

                        "uploader":
                            entry.get(
                                "uploader"
                            )
                            or
                            entry.get(
                                "channel"
                            )
                            or
                            "",
                    }
                )

            search_throttle.record_success()

            return (
                videos,
                True,
                forbidden_seen,
            )

        except Exception as error:
            last_error = error

            forbidden = (
                is_forbidden_error(
                    error
                )
            )

            forbidden_seen = (
                forbidden_seen
                or
                forbidden
            )

            if forbidden:
                search_throttle.record_forbidden()

            if (
                attempt >= MAX_RETRIES
                or
                not is_retryable_error(
                    error
                )
            ):
                break

            delay = (
                RETRY_DELAY
                *
                (
                    2
                    **
                    (
                        attempt - 1
                    )
                )
                +
                stable_jitter(
                    query
                )
            )

            time.sleep(
                delay
            )

    label = (
        "PARTIAL"
        if forbidden_seen
        else
        "FAILED"
    )

    safe_print(
        f"[{label}] Search "
        f"{query!r} failed after "
        f"{attempt} attempt(s): "
        f"{last_error}"
    )

    return (
        [],
        False,
        forbidden_seen,
    )


# ============================================================
# VIDEO / CHANNEL METADATA
# ============================================================


def extract_with_retries(
    kind,
    url,
    identity,
    allow_auth_fallback=True,
):
    """
    Return:

    (
        info,
        outcome,
    )

    outcome:

        ok
        unavailable
        auth_required
        deferred
        failed

    Explicit YouTube rate limits trigger
    the shared adaptive cooldown and do
    not consume the video's permanent
    retry attempts.
    """

    last_error = None

    generic_attempt = 0
    rate_limit_attempt = 0

    authenticated = bool(
        auth_enabled()
        and
        str(
            YOUTUBE_AUTH_STRATEGY
        )
        .strip()
        .lower()
        ==
        "always"
    )

    while True:
        metadata_throttle.wait_for_turn()

        try:
            info = get_ydl(
                kind,
                authenticated=authenticated,
            ).extract_info(
                url,
                download=False,
            )

            metadata_throttle.record_success()

            return (
                info,
                "ok",
            )

        except Exception as error:
            last_error = error

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if is_rate_limit_error(
                error
            ):
                rate_limit_attempt += 1

                if (
                    rate_limit_attempt
                    >
                    RATE_LIMIT_MAX_RETRIES
                ):
                    safe_print(
                        "[DEFER] "
                        f"{kind.title()} "
                        f"{identity}: "
                        "YouTube rate limit "
                        "persisted after shared "
                        "cooldown retries."
                    )

                    return (
                        None,
                        "deferred",
                    )

                (
                    cooldown,
                    started,
                    level,
                ) = (
                    metadata_throttle
                    .record_rate_limit()
                )

                if started:
                    safe_print()

                    safe_print(
                        "[RATE LIMIT] "
                        "YouTube throttled the "
                        "metadata session. "
                        "Pausing ALL metadata "
                        "workers for "
                        f"{format_duration(cooldown)} "
                        f"(level {level})."
                    )

                    safe_print(
                        "[*] Rate-limited "
                        "candidates are retried "
                        "and are not counted as "
                        "permanent failures."
                    )

                metadata_throttle.wait_for_turn()
                continue

            # ------------------------------------------------
            # AUTH REQUIRED
            # ------------------------------------------------

            if is_auth_required_error(
                error
            ):
                if (
                    allow_auth_fallback
                    and
                    auth_enabled()
                    and
                    not authenticated
                ):
                    authenticated = True

                    if (
                        auth_state
                        .mark_fallback_notice()
                    ):
                        safe_print(
                            "[AUTH] YouTube "
                            "requested sign-in. "
                            "Retrying affected "
                            "videos with the "
                            "configured cookies."
                        )

                    continue

                safe_print(
                    "[AUTH REQUIRED] "
                    f"{kind.title()} "
                    f"{identity}: "
                    f"{error}"
                )

                return (
                    None,
                    "auth_required",
                )

            # ------------------------------------------------
            # PERMANENTLY UNAVAILABLE
            # ------------------------------------------------

            if is_unavailable_error(
                error
            ):
                safe_print(
                    "[UNAVAILABLE] "
                    f"{kind.title()} "
                    f"{identity}: "
                    f"{error}"
                )

                return (
                    None,
                    "unavailable",
                )

            # ------------------------------------------------
            # ORDINARY RETRYABLE FAILURE
            # ------------------------------------------------

            generic_attempt += 1

            if (
                generic_attempt
                <
                MAX_RETRIES
                and
                is_retryable_error(
                    error
                )
            ):
                delay = (
                    RETRY_DELAY
                    *
                    (
                        2
                        **
                        (
                            generic_attempt
                            -
                            1
                        )
                    )
                    +
                    stable_jitter(
                        identity
                    )
                )

                time.sleep(
                    delay
                )

                continue

            safe_print(
                "[!] "
                f"{kind.title()} "
                "lookup failed for "
                f"{identity}: "
                f"{last_error}"
            )

            return (
                None,
                "failed",
            )


def fetch_channel_info(
    channel_id,
):
    if not channel_id:
        return (
            None,
            "failed",
        )

    url = (
        "https://www.youtube.com/"
        "channel/"
        f"{channel_id}"
    )

    (
        info,
        outcome,
    ) = extract_with_retries(
        "channel",
        url,
        channel_id,
        allow_auth_fallback=True,
    )

    if not info:
        return (
            None,
            outcome,
        )

    subscribers = info.get(
        "channel_follower_count"
    )

    return (
        {
            "channel_id":
                channel_id,

            "uploader":
                info.get(
                    "uploader"
                )
                or
                info.get(
                    "title"
                )
                or
                "",

            "subscribers":
                subscribers,

            "qualified":
                (
                    subscribers
                    is not None
                    and
                    subscribers
                    >=
                    MIN_SUBSCRIBERS
                ),

            "lookup_failed":
                False,

            "fetched_at":
                time.time(),
        },
        "ok",
    )


def fetch_video_info(
    video_id,
):
    if not is_valid_video_id(
        video_id
    ):
        return (
            None,
            "invalid",
        )

    url = (
        "https://www.youtube.com/"
        "watch?v="
        f"{video_id}"
    )

    return extract_with_retries(
        "video",
        url,
        video_id,
        allow_auth_fallback=True,
    )


# ============================================================
# CHANNEL CACHE / SINGLE-FLIGHT RESOLUTION
# ============================================================


def channel_cache_ttl(
    entry,
):
    if entry.get(
        "lookup_failed"
    ):
        return (
            FAILED_CHANNEL_CACHE_TTL_SECONDS
        )

    return (
        CHANNEL_CACHE_TTL_SECONDS
    )


def cache_entry_is_fresh(
    entry,
):
    fetched_at = entry.get(
        "fetched_at"
    )

    if not isinstance(
        fetched_at,
        (
            int,
            float,
        ),
    ):
        return False

    return (
        time.time()
        -
        fetched_at
        <
        channel_cache_ttl(
            entry
        )
    )


def get_cached_channel(
    channel_id,
    channel_cache,
    fresh_only=True,
):
    with channel_cache_lock:
        cached = channel_cache.get(
            channel_id
        )

        if cached is None:
            return None

        cached = dict(
            cached
        )

    if (
        fresh_only
        and
        not cache_entry_is_fresh(
            cached
        )
    ):
        return None

    return cached


def put_channel_cache(
    channel_id,
    entry,
    channel_cache,
):
    if not channel_id:
        return

    with channel_cache_lock:
        channel_cache[
            channel_id
        ] = entry


def resolve_channel(
    channel_id,
    channel_cache,
):
    """
    Resolve a channel once.

    Other workers requesting the same
    channel wait for the first worker and
    reuse its result.
    """

    if not channel_id:
        return None

    cached = get_cached_channel(
        channel_id,
        channel_cache,
        fresh_only=True,
    )

    if cached is not None:
        return cached

    with channel_inflight_lock:
        event = channel_inflight.get(
            channel_id
        )

        if event is None:
            event = (
                threading.Event()
            )

            channel_inflight[
                channel_id
            ] = event

            owner = True

        else:
            owner = False

    if not owner:
        if event.wait(
            timeout=
                CHANNEL_SINGLEFLIGHT_WAIT_SECONDS
        ):
            return get_cached_channel(
                channel_id,
                channel_cache,
                fresh_only=False,
            )

        return get_cached_channel(
            channel_id,
            channel_cache,
            fresh_only=False,
        )

    try:
        (
            info,
            outcome,
        ) = fetch_channel_info(
            channel_id
        )

        if info is None:
            # Do NOT cache temporary auth
            # or rate-limit failures.
            if outcome in {
                "deferred",
                "auth_required",
            }:
                return None

            info = {
                "channel_id":
                    channel_id,

                "uploader":
                    "",

                "subscribers":
                    None,

                "qualified":
                    False,

                "lookup_failed":
                    True,

                "fetched_at":
                    time.time(),
            }

        put_channel_cache(
            channel_id,
            info,
            channel_cache,
        )

        return info

    finally:
        with channel_inflight_lock:
            channel_inflight.pop(
                channel_id,
                None,
            )

            event.set()


def cache_channel_from_video(
    info,
    fallback_channel_id,
    fallback_uploader,
    channel_cache,
):
    channel_id = (
        info.get(
            "channel_id"
        )
        or
        info.get(
            "uploader_id"
        )
        or
        fallback_channel_id
    )

    subscribers = info.get(
        "channel_follower_count"
    )

    if not channel_id:
        return (
            None,
            subscribers,
        )

    # Don't replace a good channel cache
    # entry with an unknown subscriber count.
    if subscribers is not None:
        entry = {
            "channel_id":
                channel_id,

            "uploader":
                info.get(
                    "uploader"
                )
                or
                fallback_uploader
                or
                "",

            "subscribers":
                subscribers,

            "qualified":
                (
                    subscribers
                    >=
                    MIN_SUBSCRIBERS
                ),

            "lookup_failed":
                False,

            "fetched_at":
                time.time(),
        }

        put_channel_cache(
            channel_id,
            entry,
            channel_cache,
        )

    return (
        channel_id,
        subscribers,
    )


# ============================================================
# VIDEO METADATA CONVERSION
# ============================================================


def build_video_metadata(
    info,
    fallback_id,
):
    if not info:
        return None

    return {
        "id":
            info.get(
                "id"
            )
            or
            fallback_id,

        "name":
            info.get(
                "title"
            )
            or
            "",

        "uploader":
            info.get(
                "uploader"
            )
            or
            "",

        "date_uploaded":
            info.get(
                "upload_date"
            )
            or
            "",

        "description":
            info.get(
                "description"
            )
            or
            "",
    }


# ============================================================
# VIDEO WORKER
# ============================================================


def process_video(
    candidate,
    database,
    channel_cache,
    prefetched_channels,
):
    """
    Process one candidate.

    SQLite persistence is handled by the
    coordinator in batches.
    """

    video_id = candidate[
        "id"
    ]

    channel_id = candidate.get(
        "channel_id"
    )

    if not is_valid_video_id(
        video_id
    ):
        return (
            "invalid",
            video_id,
            None,
        )

    with database_lock:
        if video_id in database:
            return (
                "existing",
                video_id,
                None,
            )

    info = None
    subscribers = None

    # --------------------------------------------------------
    # USE PREFETCHED CHANNEL DATA
    # --------------------------------------------------------

    if (
        channel_id
        and
        channel_id
        in prefetched_channels
    ):
        channel_info = (
            prefetched_channels.get(
                channel_id
            )
        )

        if (
            channel_info
            and
            not channel_info.get(
                "lookup_failed"
            )
        ):
            subscribers = (
                channel_info.get(
                    "subscribers"
                )
            )

            if (
                subscribers
                is not None
                and
                subscribers
                <
                MIN_SUBSCRIBERS
            ):
                return (
                    "filtered",
                    video_id,
                    None,
                )

    # --------------------------------------------------------
    # SINGLETON CHANNEL
    # --------------------------------------------------------

    elif channel_id:
        channel_info = (
            resolve_channel(
                channel_id,
                channel_cache,
            )
        )

        if (
            channel_info
            and
            not channel_info.get(
                "lookup_failed"
            )
        ):
            subscribers = (
                channel_info.get(
                    "subscribers"
                )
            )

            if (
                subscribers
                is not None
                and
                subscribers
                <
                MIN_SUBSCRIBERS
            ):
                return (
                    "filtered",
                    video_id,
                    None,
                )

    # --------------------------------------------------------
    # VIDEO METADATA
    # --------------------------------------------------------

    (
        info,
        lookup_outcome,
    ) = fetch_video_info(
        video_id
    )

    if info is None:
        if lookup_outcome in {
            "unavailable",
            "auth_required",
            "deferred",
            "invalid",
        }:
            return (
                lookup_outcome,
                video_id,
                None,
            )

        return (
            "failed",
            video_id,
            None,
        )

    (
        resolved_channel_id,
        video_subscribers,
    ) = cache_channel_from_video(
        info,
        channel_id,
        candidate.get(
            "uploader",
            "",
        ),
        channel_cache,
    )

    if resolved_channel_id:
        channel_id = (
            resolved_channel_id
        )

    if (
        video_subscribers
        is not None
    ):
        subscribers = (
            video_subscribers
        )

    # If the subscriber count was not
    # available from either previous source,
    # try the channel page.
    if (
        subscribers is None
        and
        channel_id
    ):
        channel_info = (
            resolve_channel(
                channel_id,
                channel_cache,
            )
        )

        if (
            channel_info
            and
            not channel_info.get(
                "lookup_failed"
            )
        ):
            subscribers = (
                channel_info.get(
                    "subscribers"
                )
            )

    if subscribers is None:
        return (
            "failed",
            video_id,
            None,
        )

    if (
        subscribers
        <
        MIN_SUBSCRIBERS
    ):
        return (
            "filtered",
            video_id,
            None,
        )

    metadata = (
        build_video_metadata(
            info,
            video_id,
        )
    )

    if metadata is None:
        return (
            "failed",
            video_id,
            None,
        )

    metadata[
        "id"
    ] = video_id

    metadata.setdefault(
        "name",
        "",
    )

    metadata.setdefault(
        "uploader",
        "",
    )

    metadata.setdefault(
        "date_uploaded",
        "",
    )

    metadata.setdefault(
        "description",
        "",
    )

    with database_lock:
        if video_id in database:
            return (
                "existing",
                video_id,
                None,
            )

        database[
            video_id
        ] = metadata

    return (
        "new",
        video_id,
        metadata,
    )


# ============================================================
# CHANNEL PREFETCH
# ============================================================


def prefetch_frequent_channels(
    candidates,
    channel_cache,
):
    """
    Resolve channels that occur multiple
    times before video processing.

    A low-subscriber channel can then have
    every candidate rejected with only one
    channel lookup.
    """

    channel_counts = Counter(
        candidate.get(
            "channel_id"
        )

        for candidate
        in candidates

        if candidate.get(
            "channel_id"
        )
    )

    channel_ids = [
        channel_id

        for channel_id, count
        in channel_counts.items()

        if (
            count
            >=
            CHANNEL_PREFETCH_MIN_CANDIDATES
        )
    ]

    if not channel_ids:
        return (
            {},
            channel_counts,
        )

    safe_print()

    safe_print(
        "[*] Prefetching "
        f"{len(channel_ids):,} "
        "repeated channels with "
        f"{CHANNEL_PREFETCH_WORKERS} "
        "workers..."
    )

    resolved = {}

    executor = (
        concurrent.futures
        .ThreadPoolExecutor(
            max_workers=
                CHANNEL_PREFETCH_WORKERS
        )
    )

    try:
        future_map = {
            executor.submit(
                resolve_channel,
                channel_id,
                channel_cache,
            ):
                channel_id

            for channel_id
            in channel_ids
        }

        completed = 0

        for future in (
            concurrent.futures
            .as_completed(
                future_map
            )
        ):
            channel_id = (
                future_map[
                    future
                ]
            )

            try:
                resolved[
                    channel_id
                ] = (
                    future.result()
                )

            except Exception as error:
                safe_print(
                    "[!] Channel "
                    "prefetch failed for "
                    f"{channel_id}: "
                    f"{error}"
                )

                resolved[
                    channel_id
                ] = None

            completed += 1

            if (
                completed
                %
                PROCESS_PRINT_EVERY
                ==
                0

                or

                completed
                ==
                len(
                    channel_ids
                )
            ):
                safe_print(
                    "[CHANNELS] "
                    f"{completed:,}/"
                    f"{len(channel_ids):,} "
                    "resolved"
                )

    except KeyboardInterrupt:
        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

        raise

    else:
        executor.shutdown(
            wait=True
        )

    return (
        resolved,
        channel_counts,
    )


# ============================================================
# TXT OUTPUT
# ============================================================


def rebuild_txt(
    database,
):
    safe_print()
    safe_print(
        "[*] Rebuilding TXT output..."
    )

    temp_file = (
        OUTPUT_FILE
        +
        ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as f:

        for (
            video_id,
            video,
        ) in database.items():

            f.write(
                "=" * 80
                +
                "\n"
            )

            f.write(
                "Video uploader: "
                f"{video.get('uploader', '')}"
                "\n"
            )

            f.write(
                "Date uploaded: "
                f"{video.get('date_uploaded', '')}"
                "\n"
            )

            f.write(
                "Name: "
                f"{video.get('name', '')}"
                "\n"
            )

            f.write(
                "Video ID: "
                f"{video.get('id', video_id)}"
                "\n"
            )

            f.write(
                "Video description:\n"
            )

            description = (
                video.get(
                    "description",
                    "",
                )
            )

            if description:
                f.write(
                    description
                )

                if not description.endswith(
                    "\n"
                ):
                    f.write(
                        "\n"
                    )

            f.write(
                "\n"
            )

        f.write(
            "=" * 80
            +
            "\n"
        )

    os.replace(
        temp_file,
        OUTPUT_FILE,
    )

    safe_print(
        f"[+] Wrote "
        f"{len(database):,} "
        "videos"
    )


# ============================================================
# SEARCH PHASE
# ============================================================


def run_search_batch(
    remaining,
    all_queries,
    candidate_store,
    completed_queries,
    phase_name,
):
    """
    Run a bounded search pass and return
    queries which remained partial.
    """

    partial = []

    started = (
        time.monotonic()
    )

    finished = 0

    executor = (
        concurrent.futures
        .ThreadPoolExecutor(
            max_workers=
                SEARCH_WORKERS
        )
    )

    try:
        future_map = {}
        next_position = 0

        queue_limit = max(
            SEARCH_WORKERS,
            SEARCH_WORKERS
            *
            SEARCH_QUEUE_MULTIPLIER,
        )

        while (
            next_position
            <
            len(
                remaining
            )
            or
            future_map
        ):
            while (
                next_position
                <
                len(
                    remaining
                )
                and
                len(
                    future_map
                )
                <
                queue_limit
            ):
                query = remaining[
                    next_position
                ]

                future_map[
                    executor.submit(
                        search_youtube,
                        query,
                    )
                ] = query

                next_position += 1

            (
                done,
                _,
            ) = (
                concurrent.futures.wait(
                    future_map,
                    return_when=
                        concurrent.futures
                        .FIRST_COMPLETED,
                )
            )

            for future in done:
                query = (
                    future_map.pop(
                        future
                    )
                )

                try:
                    (
                        results,
                        complete,
                        _,
                    ) = (
                        future.result()
                    )

                except Exception as error:
                    safe_print(
                        "[!] Search worker "
                        "error for "
                        f"{query!r}: "
                        f"{error}"
                    )

                    results = []
                    complete = False

                candidate_store.add_candidates(
                    results
                )

                if complete:
                    completed_queries.add(
                        query
                    )

                else:
                    partial.append(
                        query
                    )

                finished += 1

                elapsed = max(
                    time.monotonic()
                    -
                    started,
                    0.001,
                )

                rate = (
                    finished
                    /
                    elapsed
                )

                eta = (
                    (
                        len(
                            remaining
                        )
                        -
                        finished
                    )
                    /
                    rate

                    if rate
                    else
                    0
                )

                status = (
                    "COMPLETE"
                    if complete
                    else
                    "PARTIAL"
                )

                try:
                    query_number = (
                        all_queries.index(
                            query
                        )
                        +
                        1
                    )

                except ValueError:
                    query_number = 0

                safe_print(
                    f"[{phase_name} "
                    f"{finished:,}/"
                    f"{len(remaining):,}] "
                    f"Query "
                    f"{query_number:,}/"
                    f"{len(all_queries):,} | "
                    f"{status} | "
                    f"Results: "
                    f"{len(results):,} | "
                    f"Candidates: "
                    f"{candidate_store.count():,} | "
                    f"Rate: "
                    f"{rate:.2f} q/s | "
                    f"ETA: "
                    f"{format_duration(eta)} | "
                    f"{query}"
                )

                if (
                    finished
                    %
                    SEARCH_STATE_SAVE_EVERY
                    ==
                    0
                ):
                    save_search_state(
                        completed_queries
                    )

    except KeyboardInterrupt:
        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

        raise

    else:
        executor.shutdown(
            wait=True
        )

    return partial


def run_search_phase(
    queries,
    candidate_store,
):
    completed_queries = (
        load_search_state(
            queries
        )
    )

    remaining = [
        query

        for query
        in queries

        if query
        not in
        completed_queries
    ]

    safe_print()
    safe_print(
        "=" * 80
    )
    safe_print(
        "SEARCH PHASE"
    )
    safe_print(
        "=" * 80
    )

    safe_print(
        f"[*] Queries:           "
        f"{len(queries):,}"
    )

    safe_print(
        "[*] Already searched: "
        f"{len(completed_queries):,}"
    )

    safe_print(
        "[*] Remaining:         "
        f"{len(remaining):,}"
    )

    safe_print(
        "[*] Search workers:    "
        f"{SEARCH_WORKERS}"
    )

    safe_print(
        "[*] Shared cooldown:   "
        f"{FORBIDDEN_COOLDOWN_THRESHOLD} "
        "403s -> "
        f"{FORBIDDEN_COOLDOWN_SECONDS:.0f}s"
    )

    safe_print()

    if not remaining:
        safe_print(
            "[+] Search phase "
            "already complete."
        )

        return (
            completed_queries
        )

    partial = run_search_batch(
        remaining,
        queries,
        candidate_store,
        completed_queries,
        "SEARCH",
    )

    save_search_state(
        completed_queries
    )

    if partial:
        safe_print()
        safe_print(
            "=" * 80
        )

        safe_print(
            "RETRYING PARTIAL / "
            "BLOCKED SEARCHES"
        )

        safe_print(
            "=" * 80
        )

        safe_print(
            "[*] Partial queries: "
            f"{len(partial):,}"
        )

        safe_print(
            "[*] Cooling down for "
            f"{FORBIDDEN_COOLDOWN_SECONDS:.0f}s "
            "before retry pass..."
        )

        time.sleep(
            FORBIDDEN_COOLDOWN_SECONDS
        )

        retry_remaining = [
            query

            for query
            in partial

            if query
            not in
            completed_queries
        ]

        still_partial = (
            run_search_batch(
                retry_remaining,
                queries,
                candidate_store,
                completed_queries,
                "RETRY",
            )
        )

        save_search_state(
            completed_queries
        )

        if still_partial:
            safe_print(
                f"[!] "
                f"{len(still_partial):,} "
                "queries are still partial "
                "and were NOT marked "
                "complete."
            )

            safe_print(
                "[*] They will be "
                "retried next run."
            )

        else:
            safe_print(
                "[+] All partial queries "
                "succeeded on retry."
            )

    safe_print()

    safe_print(
        "[+] Search pass complete: "
        f"{len(completed_queries):,}/"
        f"{len(queries):,} "
        "queries marked complete"
    )

    safe_print(
        "[+] Candidate IDs: "
        f"{candidate_store.count():,}"
    )

    return (
        completed_queries
    )


# ============================================================
# PROCESSING PHASE
# ============================================================


def run_processing_phase(
    database,
    channel_cache,
    candidate_store,
):
    counts = (
        candidate_store
        .status_counts()
    )

    total_candidates = (
        candidate_store.count()
    )

    candidates = list(
        candidate_store.iter_pending(
            include_auth_required=
                auth_enabled()
        )
    )

    pending = len(
        candidates
    )

    safe_print()
    safe_print(
        "=" * 80
    )
    safe_print(
        "PROCESSING PHASE"
    )
    safe_print(
        "=" * 80
    )

    safe_print(
        "[*] Candidate IDs:     "
        f"{total_candidates:,}"
    )

    safe_print(
        "[*] Eligible now:      "
        f"{pending:,}"
    )

    safe_print(
        "[*] Already accepted:  "
        f"{counts.get('new', 0):,}"
    )

    safe_print(
        "[*] Filtered:          "
        f"{counts.get('filtered', 0):,}"
    )

    safe_print(
        "[*] Previous failed:   "
        f"{counts.get('failed', 0):,}"
    )

    safe_print(
        "[*] Unavailable:       "
        f"{counts.get('unavailable', 0):,}"
    )

    safe_print(
        "[*] Auth required:     "
        f"{counts.get('auth_required', 0):,}"
    )

    safe_print(
        "[*] Deferred:          "
        f"{counts.get('deferred', 0):,}"
    )

    safe_print(
        "[*] Workers:           "
        f"{PROCESS_WORKERS}"
    )

    safe_print(
        "[*] SQLite batch size: "
        f"{SQLITE_STATUS_BATCH_SIZE}"
    )

    safe_print(
        "[*] Authentication:    "
        f"{auth_description()}"
    )

    safe_print()

    if pending == 0:
        safe_print(
            "[+] Nothing eligible "
            "for processing right now."
        )

        return {
            "new": 0,
            "existing": 0,
            "filtered": 0,
            "failed": 0,
            "unavailable": 0,
            "auth_required": 0,
            "deferred": 0,
            "invalid": 0,
        }

    stats = {
        "new": 0,
        "existing": 0,
        "filtered": 0,
        "failed": 0,
        "unavailable": 0,
        "auth_required": 0,
        "deferred": 0,
        "invalid": 0,
    }

    overall_completed = 0

    last_save = (
        time.monotonic()
    )

    completed_since_save = 0

    # --------------------------------------------------------
    # FAST PATH 0:
    # INVALID LEGACY CANDIDATES
    # --------------------------------------------------------

    invalid_ids = [
        candidate[
            "id"
        ]

        for candidate
        in candidates

        if not is_valid_video_id(
            candidate.get(
                "id"
            )
        )
    ]

    if invalid_ids:
        candidate_store.set_status_many_without_attempt(
            [
                (
                    video_id,
                    "invalid",
                )

                for video_id
                in invalid_ids
            ]
        )

        invalid_set = set(
            invalid_ids
        )

        candidates = [
            candidate

            for candidate
            in candidates

            if candidate[
                "id"
            ]
            not in
            invalid_set
        ]

        stats[
            "invalid"
        ] += len(
            invalid_ids
        )

        overall_completed += len(
            invalid_ids
        )

        safe_print(
            "[*] Rejected "
            f"{len(invalid_ids):,} "
            "invalid legacy candidate IDs "
            "without making network requests."
        )

    # --------------------------------------------------------
    # FAST PATH 1:
    # ALREADY IN PUBLIC DB
    # --------------------------------------------------------

    with database_lock:
        existing_ids = {
            candidate[
                "id"
            ]

            for candidate
            in candidates

            if candidate[
                "id"
            ]
            in database
        }

    if existing_ids:
        candidate_store.set_status_many_without_attempt(
            [
                (
                    video_id,
                    "new",
                )

                for video_id
                in existing_ids
            ]
        )

        stats[
            "existing"
        ] += len(
            existing_ids
        )

        overall_completed += len(
            existing_ids
        )

        candidates = [
            candidate

            for candidate
            in candidates

            if candidate[
                "id"
            ]
            not in
            existing_ids
        ]

        safe_print(
            "[*] Skipped "
            f"{len(existing_ids):,} "
            "candidates already present "
            "in the video database."
        )

    # --------------------------------------------------------
    # FAST PATH 2:
    # REPEATED CHANNEL PREFETCH
    # --------------------------------------------------------

    (
        prefetched_channels,
        _channel_counts,
    ) = prefetch_frequent_channels(
        candidates,
        channel_cache,
    )

    prefiltered_ids = []

    for candidate in candidates:
        channel_id = (
            candidate.get(
                "channel_id"
            )
        )

        if not channel_id:
            continue

        channel_info = (
            prefetched_channels.get(
                channel_id
            )
        )

        if (
            channel_info
            and
            not channel_info.get(
                "lookup_failed"
            )
        ):
            subscribers = (
                channel_info.get(
                    "subscribers"
                )
            )

            if (
                subscribers
                is not None
                and
                subscribers
                <
                MIN_SUBSCRIBERS
            ):
                prefiltered_ids.append(
                    candidate[
                        "id"
                    ]
                )

    if prefiltered_ids:
        candidate_store.set_status_many_without_attempt(
            [
                (
                    video_id,
                    "filtered",
                )

                for video_id
                in prefiltered_ids
            ]
        )

        prefiltered_set = set(
            prefiltered_ids
        )

        candidates = [
            candidate

            for candidate
            in candidates

            if candidate[
                "id"
            ]
            not in
            prefiltered_set
        ]

        stats[
            "filtered"
        ] += len(
            prefiltered_ids
        )

        overall_completed += len(
            prefiltered_ids
        )

        safe_print(
            "[*] Prefiltered "
            f"{len(prefiltered_ids):,} "
            "videos from channels below "
            f"{MIN_SUBSCRIBERS:,} "
            "subscribers."
        )

    metadata_total = len(
        candidates
    )

    base_completed = (
        overall_completed
    )

    safe_print(
        "[*] Video metadata "
        "lookups remaining: "
        f"{metadata_total:,}"
    )

    safe_print()

    if not candidates:
        save_all(
            database,
            channel_cache,
        )

        return stats

    # --------------------------------------------------------
    # BATCHED SQLITE STATUS PERSISTENCE
    # --------------------------------------------------------

    attempt_buffer = []
    no_attempt_buffer = []

    def flush_status_buffers():
        nonlocal attempt_buffer
        nonlocal no_attempt_buffer

        if attempt_buffer:
            candidate_store.set_status_many(
                attempt_buffer,
                increment_attempt=True,
            )

            attempt_buffer = []

        if no_attempt_buffer:
            candidate_store.set_status_many_without_attempt(
                no_attempt_buffer
            )

            no_attempt_buffer = []

    def queue_status(
        video_id,
        status,
    ):
        # Only generic failures consume the
        # permanent retry budget.
        #
        # Rate limits, unavailable videos,
        # auth requirements and successful
        # classifications do not.
        if status == "failed":
            attempt_buffer.append(
                (
                    video_id,
                    status,
                )
            )

        elif status == "existing":
            no_attempt_buffer.append(
                (
                    video_id,
                    "new",
                )
            )

        else:
            no_attempt_buffer.append(
                (
                    video_id,
                    status,
                )
            )

        if (
            len(
                attempt_buffer
            )
            >=
            SQLITE_STATUS_BATCH_SIZE

            or

            len(
                no_attempt_buffer
            )
            >=
            SQLITE_STATUS_BATCH_SIZE
        ):
            flush_status_buffers()

    # --------------------------------------------------------
    # ROLLING WORK QUEUE
    # --------------------------------------------------------

    executor = (
        concurrent.futures
        .ThreadPoolExecutor(
            max_workers=
                PROCESS_WORKERS
        )
    )

    queue_limit = max(
        PROCESS_WORKERS,
        PROCESS_WORKERS
        *
        PROCESS_BATCH_MULTIPLIER,
    )

    candidate_iter = iter(
        candidates
    )

    future_map = {}

    metadata_completed = 0

    metadata_started = (
        time.monotonic()
    )

    def fill_queue():
        while (
            len(
                future_map
            )
            <
            queue_limit
        ):
            try:
                candidate = next(
                    candidate_iter
                )

            except StopIteration:
                return

            future = executor.submit(
                process_video,
                candidate,
                database,
                channel_cache,
                prefetched_channels,
            )

            future_map[
                future
            ] = candidate[
                "id"
            ]

    fill_queue()

    try:
        while future_map:
            (
                done,
                _,
            ) = (
                concurrent.futures.wait(
                    future_map,
                    return_when=
                        concurrent.futures
                        .FIRST_COMPLETED,
                )
            )

            for future in done:
                video_id = (
                    future_map.pop(
                        future
                    )
                )

                try:
                    (
                        status,
                        _,
                        _,
                    ) = (
                        future.result()
                    )

                except Exception as error:
                    safe_print(
                        "[!] Worker error "
                        f"for {video_id}: "
                        f"{error}"
                    )

                    status = "failed"

                stats.setdefault(
                    status,
                    0,
                )

                stats[
                    status
                ] += 1

                metadata_completed += 1

                overall_completed = (
                    base_completed
                    +
                    metadata_completed
                )

                completed_since_save += 1

                queue_status(
                    video_id,
                    status,
                )

                now = (
                    time.monotonic()
                )

                metadata_elapsed = max(
                    now
                    -
                    metadata_started,
                    0.001,
                )

                metadata_rate = (
                    metadata_completed
                    /
                    metadata_elapsed
                )

                metadata_remaining = (
                    metadata_total
                    -
                    metadata_completed
                )

                eta_seconds = (
                    metadata_remaining
                    /
                    metadata_rate

                    if metadata_rate
                    >
                    0

                    else
                    0
                )

                if (
                    metadata_completed
                    %
                    PROCESS_PRINT_EVERY
                    ==
                    0

                    or

                    metadata_completed
                    ==
                    metadata_total
                ):
                    throttle_status = (
                        metadata_throttle.status()
                    )

                    penalty = (
                        throttle_status[
                            "penalty_level"
                        ]
                    )

                    penalty_text = (
                        f" | Pace L{penalty}"
                        if penalty
                        else
                        ""
                    )

                    safe_print(
                        "[PROCESS] "
                        f"Total "
                        f"{overall_completed:,}/"
                        f"{pending:,} "
                        f"("
                        f"{overall_completed / pending * 100:6.2f}"
                        f"%) | "
                        f"Metadata "
                        f"{metadata_completed:,}/"
                        f"{metadata_total:,} | "
                        f"New: "
                        f"{stats['new']:,} | "
                        f"Filtered: "
                        f"{stats['filtered']:,} | "
                        f"Unavailable: "
                        f"{stats['unavailable']:,} | "
                        f"Auth: "
                        f"{stats['auth_required']:,} | "
                        f"Deferred: "
                        f"{stats['deferred']:,} | "
                        f"Failed: "
                        f"{stats['failed']:,} | "
                        f"Rate: "
                        f"{metadata_rate:.2f}/s | "
                        f"ETA: "
                        f"{format_duration(eta_seconds)}"
                        f"{penalty_text}"
                    )

                if (
                    completed_since_save
                    >=
                    SAVE_EVERY

                    or

                    now
                    -
                    last_save
                    >=
                    SAVE_INTERVAL_SECONDS
                ):
                    flush_status_buffers()

                    save_all(
                        database,
                        channel_cache,
                    )

                    last_save = now
                    completed_since_save = 0

            fill_queue()

    except KeyboardInterrupt:
        safe_print()

        safe_print(
            "[!] Processing interrupted. "
            "Saving progress..."
        )

        flush_status_buffers()

        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

        save_all(
            database,
            channel_cache,
        )

        raise

    else:
        executor.shutdown(
            wait=True
        )

    flush_status_buffers()

    save_all(
        database,
        channel_cache,
    )

    return stats


# ============================================================
# MAIN
# ============================================================


def main():
    safe_print()

    safe_print(
        "=" * 80
    )

    safe_print(
        "                 "
        "MULTITHREADED YOUTUBE SCRAPER"
    )

    safe_print(
        "=" * 80
    )

    safe_print()

    safe_print(
        "Minimum subscribers:  "
        f"{MIN_SUBSCRIBERS:,}"
    )

    safe_print(
        "Search results/query: "
        f"{RESULTS_PER_QUERY:,}"
    )

    safe_print(
        "Search workers:       "
        f"{SEARCH_WORKERS}"
    )

    safe_print(
        "Metadata workers:     "
        f"{PROCESS_WORKERS}"
    )

    safe_print(
        "YouTube auth:         "
        f"{'Enabled' if USE_YOUTUBE_AUTH else 'Disabled'}"
    )

    safe_print()

    validate_auth_configuration()

    queries = load_queries()

    database = load_json(
        DATABASE_FILE,
        {},
    )

    channel_cache = load_json(
        CHANNEL_CACHE_FILE,
        {},
    )

    candidate_store = (
        CandidateStore(
            CANDIDATE_DB_FILE
        )
    )

    safe_print(
        "[*] Queries loaded:  "
        f"{len(queries):,}"
    )

    safe_print(
        "[*] Existing videos: "
        f"{len(database):,}"
    )

    safe_print(
        "[*] Cached channels: "
        f"{len(channel_cache):,}"
    )

    safe_print(
        "[*] Candidate IDs:   "
        f"{candidate_store.count():,}"
    )

    safe_print(
        "[*] Authentication:  "
        f"{auth_description()}"
    )

    try:
        completed_queries = (
            run_search_phase(
                queries,
                candidate_store,
            )
        )

        stats = (
            run_processing_phase(
                database,
                channel_cache,
                candidate_store,
            )
        )

        safe_print()
        safe_print(
            "[*] Saving databases..."
        )

        save_all(
            database,
            channel_cache,
        )

        save_search_state(
            completed_queries
        )

        rebuild_txt(
            database
        )

        with channel_cache_lock:
            qualified_channels = sum(
                1

                for channel
                in channel_cache.values()

                if (
                    channel.get(
                        "subscribers"
                    )
                    is not None

                    and

                    channel.get(
                        "subscribers"
                    )
                    >=
                    MIN_SUBSCRIBERS
                )
            )

        final_counts = (
            candidate_store
            .status_counts()
        )

        safe_print()
        safe_print(
            "=" * 80
        )

        safe_print(
            "                         "
            "COMPLETE"
        )

        safe_print(
            "=" * 80
        )

        safe_print()

        safe_print(
            "Search queries complete:        "
            f"{len(completed_queries):,}"
        )

        safe_print(
            "Unique search candidates:       "
            f"{candidate_store.count():,}"
        )

        safe_print(
            "New qualifying videos this run: "
            f"{stats.get('new', 0):,}"
        )

        safe_print(
            "Existing qualifying videos:     "
            f"{stats.get('existing', 0):,}"
        )

        safe_print(
            f"Filtered (<{MIN_SUBSCRIBERS:,} subscribers): "
            f"{stats.get('filtered', 0):,}"
        )

        safe_print(
            "Unavailable this run:            "
            f"{stats.get('unavailable', 0):,}"
        )

        safe_print(
            "Auth required this run:          "
            f"{stats.get('auth_required', 0):,}"
        )

        safe_print(
            "Rate-limit deferred this run:    "
            f"{stats.get('deferred', 0):,}"
        )

        safe_print(
            "Generic failed this run:         "
            f"{stats.get('failed', 0):,}"
        )

        safe_print(
            "Invalid candidate IDs:           "
            f"{stats.get('invalid', 0):,}"
        )

        safe_print(
            "Total videos in database:        "
            f"{len(database):,}"
        )

        safe_print(
            "Cached channels:                 "
            f"{len(channel_cache):,}"
        )

        safe_print(
            "Qualifying channels:             "
            f"{qualified_channels:,}"
        )

        safe_print()

        safe_print(
            "Candidate DB status:             "
            f"{final_counts}"
        )

        safe_print()

        safe_print(
            "TXT:             "
            f"{Path(OUTPUT_FILE).absolute()}"
        )

        safe_print(
            "Database:        "
            f"{Path(DATABASE_FILE).absolute()}"
        )

        safe_print(
            "Channel cache:   "
            f"{Path(CHANNEL_CACHE_FILE).absolute()}"
        )

        safe_print(
            "Candidate DB:    "
            f"{Path(CANDIDATE_DB_FILE).absolute()}"
        )

        safe_print(
            "Search state:    "
            f"{Path(SEARCH_STATE_FILE).absolute()}"
        )

        safe_print()

    finally:
        candidate_store.close()


# ============================================================
# ENTRY POINT
# ============================================================


if __name__ == "__main__":
    try:
        import yt_dlp  # noqa: F401

    except ImportError:
        print()
        print(
            "[!] yt-dlp is not installed."
        )
        print()
        print(
            "Install/update it with:"
        )
        print()
        print(
            "    pip install -U yt-dlp"
        )
        print()

        sys.exit(
            1
        )

    try:
        main()

    except KeyboardInterrupt:
        print()
        print()
        print(
            "[!] Ctrl+C detected."
        )
        print(
            "[*] Completed searches and "
            "processed videos were saved."
        )
        print(
            "[*] Run the script again "
            "to resume."
        )
        print()