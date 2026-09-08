from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit

import json
import mimetypes
import re
import threading
import time

import yt_dlp


HOST = "127.0.0.1"
PORT = 8000

BASE_DIR = Path(__file__).resolve().parent
VIDEOS_DIR = BASE_DIR / "videos"
LIBRARY_FILE = VIDEOS_DIR / "library.json"

VIDEOS_DIR.mkdir(exist_ok=True)

if not LIBRARY_FILE.exists():
    LIBRARY_FILE.write_text("[]", encoding="utf-8")


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

ACTIVE_JOB_STATUSES = {
    "starting",
    "downloading",
    "processing",
    "cancelling",
}

VIDEO_CHUNK_SIZE = 1024 * 1024


library_lock = threading.RLock()
jobs_lock = threading.RLock()

download_jobs = {}


class DownloadCancelledError(Exception):
    pass


# =========================================================
# Library
# =========================================================

def load_library():
    try:
        with open(
            LIBRARY_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, list):
            return data

        return []

    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
    ):
        return []


def save_library(library):
    temporary = (
        LIBRARY_FILE
        .with_suffix(".tmp")
    )

    with open(
        temporary,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            library,
            file,
            indent=2,
            ensure_ascii=False,
        )

        file.flush()

    temporary.replace(
        LIBRARY_FILE
    )


def find_entry(video_id):
    with library_lock:
        library = load_library()

        for entry in library:
            if (
                entry.get("id")
                ==
                video_id
            ):
                return dict(entry)

    return None


def update_library_entry(
    video_id,
    values,
):
    with library_lock:
        library = load_library()

        for entry in library:
            if (
                entry.get("id")
                !=
                video_id
            ):
                continue

            for key, value in values.items():
                if value is not None:
                    entry[key] = value

            save_library(
                library
            )

            return dict(entry)

    return None


# =========================================================
# Validation
# =========================================================

def valid_video_id(video_id):
    return bool(
        VIDEO_ID_PATTERN.fullmatch(
            str(video_id or "")
        )
    )


def safe_filename(filename):
    filename = (
        Path(
            str(filename or "").strip()
        )
        .name
    )

    filename = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        filename,
    )

    filename = re.sub(
        r"\s+",
        " ",
        filename,
    )

    filename = (
        filename
        .rstrip(" .")
    )

    if not filename:
        raise ValueError(
            "Filename cannot be empty."
        )

    path = Path(filename)

    if (
        path.suffix.lower()
        !=
        ".mp4"
    ):
        filename = (
            path.stem
            +
            ".mp4"
        )

    if len(filename) > 180:
        filename = (
            Path(filename).stem[:176]
            +
            ".mp4"
        )

    return filename


def video_path_from_filename(filename):
    filename = safe_filename(
        filename
    )

    path = (
        VIDEOS_DIR
        /
        filename
    )

    resolved = (
        path.resolve()
    )

    videos_root = (
        VIDEOS_DIR.resolve()
    )

    if (
        resolved.parent
        !=
        videos_root
    ):
        raise ValueError(
            "Invalid video path."
        )

    return path


def find_downloaded_video(video_id):
    entry = find_entry(
        video_id
    )

    if not entry:
        return None

    filename = entry.get(
        "filename"
    )

    if not filename:
        return None

    try:
        path = (
            video_path_from_filename(
                filename
            )
        )

    except ValueError:
        return None

    if path.exists():
        return path

    return None


# =========================================================
# JSON HTTP helpers
# =========================================================

def send_json(
    handler,
    data,
    status=200,
):
    body = (
        json.dumps(
            data,
            ensure_ascii=False,
        )
        .encode("utf-8")
    )

    handler.send_response(
        status
    )

    handler.send_header(
        "Content-Type",
        "application/json; charset=utf-8",
    )

    handler.send_header(
        "Cache-Control",
        "no-store",
    )

    handler.send_header(
        "X-Content-Type-Options",
        "nosniff",
    )

    handler.send_header(
        "Content-Length",
        str(len(body)),
    )

    handler.end_headers()

    try:
        handler.wfile.write(
            body
        )

    except (
        BrokenPipeError,
        ConnectionResetError,
    ):
        pass


def read_json(handler):
    raw_length = (
        handler.headers.get(
            "Content-Length",
            "0",
        )
    )

    try:
        length = int(
            raw_length
        )

    except ValueError as error:
        raise ValueError(
            "Invalid Content-Length."
        ) from error

    if length <= 0:
        raise ValueError(
            "Request body is empty."
        )

    if length > 2_000_000:
        raise ValueError(
            "Request is too large."
        )

    body = (
        handler.rfile.read(
            length
        )
    )

    try:
        data = json.loads(
            body.decode("utf-8")
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError(
            "Request body must contain valid JSON."
        ) from error

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            "JSON request must be an object."
        )

    return data


# =========================================================
# Metadata
# =========================================================

def youtube_url(video_id):
    return (
        "https://www.youtube.com/watch?v="
        +
        video_id
    )


def clean_metadata(info):
    if not isinstance(
        info,
        dict,
    ):
        return {}

    description = (
        info.get("description")
        or
        ""
    )

    if not isinstance(
        description,
        str,
    ):
        description = str(
            description
        )

    uploader = (
        info.get("uploader")
        or
        info.get("channel")
        or
        ""
    )

    channel = (
        info.get("channel")
        or
        info.get("uploader")
        or
        ""
    )

    thumbnail = (
        info.get("thumbnail")
        or
        ""
    )

    duration = (
        info.get("duration")
    )

    try:
        if duration is not None:
            duration = int(
                duration
            )

    except (
        TypeError,
        ValueError,
    ):
        duration = None

    return {
        "title":
            (
                info.get("title")
                or
                "Unknown video"
            ),

        "uploader":
            uploader,

        "channel":
            channel,

        "description":
            description,

        "thumbnail":
            thumbnail,

        "duration":
            duration,
    }


def has_cached_metadata(entry):
    return bool(
        entry
        and
        entry.get("title")
        and
        (
            entry.get("uploader")
            or
            entry.get("channel")
        )
    )


def fetch_video_metadata(video_id):
    if not valid_video_id(
        video_id
    ):
        raise ValueError(
            "Invalid video ID."
        )

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(
        options
    ) as ydl:
        info = ydl.extract_info(
            youtube_url(
                video_id
            ),
            download=False,
        )

    if not info:
        raise RuntimeError(
            "Could not retrieve video information."
        )

    metadata = (
        clean_metadata(
            info
        )
    )

    metadata["id"] = (
        info.get("id")
        or
        video_id
    )

    return metadata


# =========================================================
# Import parser
# =========================================================

def parse_video_list(text):
    text = (
        str(text or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    sections = re.split(
        r"(?m)^\s*={10,}\s*$",
        text,
    )

    videos = []
    seen_ids = set()

    for section in sections:
        section = (
            section.strip()
        )

        if not section:
            continue

        uploader_match = re.search(
            r"(?m)^Video uploader:\s*(.*?)\s*$",
            section,
        )

        date_match = re.search(
            r"(?m)^Date uploaded:\s*(.*?)\s*$",
            section,
        )

        name_match = re.search(
            r"(?m)^Name:\s*(.*?)\s*$",
            section,
        )

        id_match = re.search(
            r"(?m)^Video ID:\s*([A-Za-z0-9_-]{11})\s*$",
            section,
        )

        description_match = re.search(
            r"(?ms)^Video description:\s*\n?(.*)$",
            section,
        )

        if not id_match:
            continue

        video_id = (
            id_match
            .group(1)
            .strip()
        )

        if video_id in seen_ids:
            continue

        seen_ids.add(
            video_id
        )

        videos.append(
            {
                "id":
                    video_id,

                "uploader":
                    (
                        uploader_match.group(1).strip()
                        if uploader_match
                        else ""
                    ),

                "upload_date":
                    (
                        date_match.group(1).strip()
                        if date_match
                        else ""
                    ),

                "title":
                    (
                        name_match.group(1).strip()
                        if name_match
                        else video_id
                    ),

                "description":
                    (
                        description_match.group(1).strip()
                        if description_match
                        else ""
                    ),
            }
        )

    return videos


# =========================================================
# Jobs
# =========================================================

def create_job(
    video_id,
    filename,
):
    job = {
        "id":
            video_id,

        "filename":
            filename,

        "status":
            "starting",

        "percent":
            0.0,

        "speed":
            0,

        "eta":
            None,

        "downloaded":
            0,

        "total":
            0,

        "title":
            None,

        "uploader":
            None,

        "error":
            None,

        "cancelled":
            False,

        "started":
            time.time(),

        "finished":
            None,
    }

    with jobs_lock:
        download_jobs[
            video_id
        ] = job

    return job


def get_job(video_id):
    with jobs_lock:
        job = (
            download_jobs.get(
                video_id
            )
        )

        if job is None:
            return None

        return dict(
            job
        )


def update_job(
    video_id,
    **values,
):
    with jobs_lock:
        job = (
            download_jobs.get(
                video_id
            )
        )

        if job is not None:
            job.update(
                values
            )


def is_cancelled(video_id):
    with jobs_lock:
        job = (
            download_jobs.get(
                video_id
            )
        )

        return bool(
            job
            and
            job.get(
                "cancelled",
                False,
            )
        )


def cancel_job(video_id):
    with jobs_lock:
        job = (
            download_jobs.get(
                video_id
            )
        )

        if not job:
            return False

        if (
            job.get("status")
            not in
            ACTIVE_JOB_STATUSES
        ):
            return False

        job["cancelled"] = True
        job["status"] = (
            "cancelling"
        )

        return True


# =========================================================
# Progress hook
# =========================================================

def progress_hook(
    video_id,
    data,
):
    if is_cancelled(
        video_id
    ):
        raise DownloadCancelledError(
            "Download cancelled."
        )

    status = data.get(
        "status"
    )

    if (
        status
        ==
        "downloading"
    ):
        downloaded = (
            data.get(
                "downloaded_bytes"
            )
            or
            0
        )

        total = (
            data.get(
                "total_bytes"
            )
            or
            data.get(
                "total_bytes_estimate"
            )
            or
            0
        )

        percent = (
            downloaded
            /
            total
            *
            100
        ) if total > 0 else 0.0

        update_job(
            video_id,

            status=
                "downloading",

            percent=
                percent,

            downloaded=
                downloaded,

            total=
                total,

            speed=
                (
                    data.get("speed")
                    or
                    0
                ),

            eta=
                data.get("eta"),
        )

    elif (
        status
        ==
        "finished"
    ):
        update_job(
            video_id,

            status=
                "processing",

            percent=
                100.0,

            downloaded=
                (
                    data.get(
                        "downloaded_bytes"
                    )
                    or
                    0
                ),

            speed=
                0,

            eta=
                0,
        )


# =========================================================
# Download worker
# =========================================================

def download_worker(
    video_id,
    filename,
):
    temporary_prefix = (
        f".download_{video_id}"
    )

    temporary_template = str(
        VIDEOS_DIR
        /
        f"{temporary_prefix}.%(ext)s"
    )

    destination = (
        VIDEOS_DIR
        /
        filename
    )

    try:
        update_job(
            video_id,
            status="starting",
        )

        options = {
            "format":
                (
                    "bv*[ext=mp4][vcodec^=avc1]"
                    "+ba[ext=m4a]"
                    "/b[ext=mp4][vcodec^=avc1]"
                    "/bv*[ext=mp4]+ba[ext=m4a]"
                    "/b[ext=mp4]"
                    "/bv*+ba/b"
                ),

            "outtmpl":
                temporary_template,

            "merge_output_format":
                "mp4",

            "noplaylist":
                True,

            "quiet":
                True,

            "no_warnings":
                True,

            "continuedl":
                True,

            "progress_hooks": [
                lambda data:
                    progress_hook(
                        video_id,
                        data,
                    )
            ],
        }

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:
            info = ydl.extract_info(
                youtube_url(
                    video_id
                ),
                download=True,
            )

        if is_cancelled(
            video_id
        ):
            raise DownloadCancelledError(
                "Download cancelled."
            )

        metadata = (
            clean_metadata(
                info
            )
        )

        update_job(
            video_id,

            title=
                metadata.get(
                    "title"
                ),

            uploader=
                metadata.get(
                    "uploader"
                ),

            status=
                "processing",
        )

        downloaded_files = []

        for path in VIDEOS_DIR.glob(
            f"{temporary_prefix}.*"
        ):
            if not path.is_file():
                continue

            lower_name = (
                path.name.lower()
            )

            if (
                lower_name.endswith(".part")
                or
                ".part-" in lower_name
                or
                lower_name.endswith(".ytdl")
            ):
                continue

            downloaded_files.append(
                path
            )

        if not downloaded_files:
            raise RuntimeError(
                "yt-dlp finished but no completed video file was found."
            )

        source = next(
            (
                path
                for path
                in downloaded_files
                if (
                    path.suffix.lower()
                    ==
                    ".mp4"
                )
            ),
            downloaded_files[0],
        )

        if destination.exists():
            raise FileExistsError(
                (
                    f"The file '{filename}' "
                    "already exists."
                )
            )

        source.replace(
            destination
        )

        entry = {
            "id":
                video_id,

            "filename":
                filename,

            **metadata,
        }

        with library_lock:
            library = [
                item
                for item
                in load_library()
                if (
                    item.get("id")
                    !=
                    video_id
                )
            ]

            library.append(
                entry
            )

            save_library(
                library
            )

        update_job(
            video_id,

            status=
                "completed",

            percent=
                100.0,

            speed=
                0,

            eta=
                0,

            finished=
                time.time(),

            entry=
                entry,
        )

    except DownloadCancelledError:
        update_job(
            video_id,

            status=
                "cancelled",

            cancelled=
                True,

            finished=
                time.time(),
        )

    except Exception as error:
        if is_cancelled(
            video_id
        ):
            update_job(
                video_id,

                status=
                    "cancelled",

                cancelled=
                    True,

                finished=
                    time.time(),
            )

        else:
            print(
                (
                    f"Download error for "
                    f"{video_id}: "
                    f"{error}"
                )
            )

            update_job(
                video_id,

                status=
                    "error",

                error=
                    str(error),

                finished=
                    time.time(),
            )

    finally:
        for path in VIDEOS_DIR.glob(
            f"{temporary_prefix}.*"
        ):
            try:
                if path.is_file():
                    path.unlink()

            except OSError:
                pass


# =========================================================
# Range support
# =========================================================

def parse_range_header(
    header_value,
    file_size,
):
    if (
        not header_value
        or
        not header_value.startswith(
            "bytes="
        )
    ):
        return None

    value = (
        header_value[
            len("bytes="):
        ]
        .strip()
        .split(",", 1)[0]
        .strip()
    )

    if "-" not in value:
        return None

    start_text, end_text = (
        value.split(
            "-",
            1,
        )
    )

    try:
        if not start_text:
            suffix_length = int(
                end_text
            )

            if suffix_length <= 0:
                return None

            suffix_length = min(
                suffix_length,
                file_size,
            )

            start = (
                file_size
                -
                suffix_length
            )

            end = (
                file_size
                -
                1
            )

        else:
            start = int(
                start_text
            )

            end = (
                int(end_text)
                if end_text
                else file_size - 1
            )

    except ValueError:
        return None

    if (
        start < 0
        or
        start >= file_size
    ):
        return "invalid"

    end = min(
        end,
        file_size - 1,
    )

    if end < start:
        return "invalid"

    return (
        start,
        end,
    )


# =========================================================
# HTTP Handler
# =========================================================

class Handler(
    SimpleHTTPRequestHandler
):
    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,

            directory=str(
                BASE_DIR
            ),

            **kwargs,
        )


    def end_headers(self):
        request_path = (
            urlsplit(
                self.path
            )
            .path
            .lower()
        )

        if request_path.endswith(
            (
                ".js",
                ".css",
                ".html",
                "/",
            )
        ):
            self.send_header(
                "Cache-Control",
                "no-cache, must-revalidate",
            )

        super().end_headers()


    # =====================================================
    # Video streaming
    # =====================================================

    def serve_video(
        self,
        head_only=False,
    ):
        request_path = (
            urlsplit(
                self.path
            )
            .path
        )

        encoded_filename = (
            request_path[
                len("/videos/"):
            ]
        )

        filename = unquote(
            encoded_filename
        )

        if (
            not filename
            or
            filename
            !=
            Path(filename).name
        ):
            self.send_error(
                400,
                "Invalid video filename.",
            )

            return

        try:
            path = (
                video_path_from_filename(
                    filename
                )
            )

        except ValueError:
            self.send_error(
                400,
                "Invalid video filename.",
            )

            return

        if (
            not path.exists()
            or
            not path.is_file()
        ):
            self.send_error(
                404,
                "Video not found.",
            )

            return

        file_size = (
            path.stat()
            .st_size
        )

        content_type = (
            mimetypes.guess_type(
                path.name
            )[0]
            or
            "application/octet-stream"
        )

        requested_range = (
            parse_range_header(
                self.headers.get(
                    "Range"
                ),
                file_size,
            )
        )

        if (
            requested_range
            ==
            "invalid"
        ):
            self.send_response(
                416
            )

            self.send_header(
                "Content-Range",
                f"bytes */{file_size}",
            )

            self.send_header(
                "Accept-Ranges",
                "bytes",
            )

            self.end_headers()

            return

        if requested_range:
            start, end = (
                requested_range
            )

            content_length = (
                end
                -
                start
                +
                1
            )

            self.send_response(
                206
            )

            self.send_header(
                "Content-Type",
                content_type,
            )

            self.send_header(
                "Accept-Ranges",
                "bytes",
            )

            self.send_header(
                "Content-Range",
                (
                    f"bytes "
                    f"{start}-{end}/"
                    f"{file_size}"
                ),
            )

            self.send_header(
                "Content-Length",
                str(
                    content_length
                ),
            )

            self.send_header(
                "Cache-Control",
                "private, max-age=3600",
            )

            self.end_headers()

            if head_only:
                return

            try:
                with open(
                    path,
                    "rb",
                ) as file:
                    file.seek(
                        start
                    )

                    remaining = (
                        content_length
                    )

                    while remaining > 0:
                        chunk = file.read(
                            min(
                                VIDEO_CHUNK_SIZE,
                                remaining,
                            )
                        )

                        if not chunk:
                            break

                        self.wfile.write(
                            chunk
                        )

                        remaining -= (
                            len(chunk)
                        )

            except (
                BrokenPipeError,
                ConnectionResetError,
            ):
                pass

            return

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Accept-Ranges",
            "bytes",
        )

        self.send_header(
            "Content-Length",
            str(file_size),
        )

        self.send_header(
            "Cache-Control",
            "private, max-age=3600",
        )

        self.end_headers()

        if head_only:
            return

        try:
            with open(
                path,
                "rb",
            ) as file:
                while True:
                    chunk = file.read(
                        VIDEO_CHUNK_SIZE
                    )

                    if not chunk:
                        break

                    self.wfile.write(
                        chunk
                    )

        except (
            BrokenPipeError,
            ConnectionResetError,
        ):
            pass


    # =====================================================
    # HEAD
    # =====================================================

    def do_HEAD(self):
        request_path = (
            urlsplit(
                self.path
            )
            .path
        )

        if request_path.startswith(
            "/videos/"
        ):
            self.serve_video(
                head_only=True
            )

            return

        super().do_HEAD()


    # =====================================================
    # GET
    # =====================================================

    def do_GET(self):
        request_path = (
            urlsplit(
                self.path
            )
            .path
        )


        if request_path.startswith(
            "/videos/"
        ):
            self.serve_video()

            return


        if (
            request_path
            ==
            "/api/library"
        ):
            with library_lock:
                library = (
                    load_library()
                )

            result = []

            for entry in library:
                try:
                    path = (
                        video_path_from_filename(
                            entry[
                                "filename"
                            ]
                        )
                    )

                    if path.exists():
                        result.append(
                            entry
                        )

                except (
                    KeyError,
                    ValueError,
                ):
                    continue

            send_json(
                self,
                result,
            )

            return


        if request_path.startswith(
            "/api/info/"
        ):
            video_id = unquote(
                request_path[
                    len("/api/info/"):
                ]
            )

            if not valid_video_id(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Invalid video ID."
                    },
                    400,
                )

                return

            existing = find_entry(
                video_id
            )

            if has_cached_metadata(
                existing
            ):
                send_json(
                    self,
                    {
                        "success":
                            True,

                        "cached":
                            True,

                        "entry":
                            existing,
                    },
                )

                return

            try:
                metadata = (
                    fetch_video_metadata(
                        video_id
                    )
                )

                if existing:
                    updated = (
                        update_library_entry(
                            video_id,
                            metadata,
                        )
                    )

                    entry = (
                        updated
                        or
                        {
                            **existing,
                            **metadata,
                        }
                    )

                else:
                    entry = {
                        "id":
                            video_id,

                        **metadata,
                    }

                send_json(
                    self,
                    {
                        "success":
                            True,

                        "cached":
                            False,

                        "entry":
                            entry,
                    },
                )

            except Exception as error:
                print(
                    (
                        f"Info error for "
                        f"{video_id}: "
                        f"{error}"
                    )
                )

                send_json(
                    self,
                    {
                        "error":
                            str(error)
                    },
                    502,
                )

            return


        if request_path.startswith(
            "/api/progress/"
        ):
            video_id = unquote(
                request_path[
                    len("/api/progress/"):
                ]
            )

            if not valid_video_id(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Invalid video ID."
                    },
                    400,
                )

                return

            job = get_job(
                video_id
            )

            if not job:
                send_json(
                    self,
                    {
                        "status":
                            "not_found"
                    },
                )

                return

            send_json(
                self,
                job,
            )

            return


        if request_path.startswith(
            "/api/check/"
        ):
            video_id = unquote(
                request_path[
                    len("/api/check/"):
                ]
            )

            if not valid_video_id(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Invalid video ID."
                    },
                    400,
                )

                return

            send_json(
                self,
                {
                    "exists":
                        (
                            find_downloaded_video(
                                video_id
                            )
                            is not None
                        ),

                    "entry":
                        find_entry(
                            video_id
                        ),
                },
            )

            return

        super().do_GET()


    # =====================================================
    # POST
    # =====================================================

    def do_POST(self):
        request_path = (
            urlsplit(
                self.path
            )
            .path
        )

        allowed = {
            "/api/download",
            "/api/cancel",
            "/api/rename",
            "/api/delete",
            "/api/import-list",
        }

        if (
            request_path
            not in
            allowed
        ):
            send_json(
                self,
                {
                    "error":
                        "Unknown endpoint."
                },
                404,
            )

            return

        try:
            data = read_json(
                self
            )

        except Exception as error:
            send_json(
                self,
                {
                    "error":
                        str(error)
                },
                400,
            )

            return


        # -------------------------------------------------
        # Import list
        # -------------------------------------------------

        if (
            request_path
            ==
            "/api/import-list"
        ):
            text = str(
                data.get(
                    "text",
                    "",
                )
            )

            if not text.strip():
                send_json(
                    self,
                    {
                        "error":
                            "No video list was provided."
                    },
                    400,
                )

                return

            videos = (
                parse_video_list(
                    text
                )
            )

            send_json(
                self,
                {
                    "success":
                        True,

                    "count":
                        len(videos),

                    "videos":
                        videos,
                },
            )

            return


        # -------------------------------------------------
        # Download
        # -------------------------------------------------

        if (
            request_path
            ==
            "/api/download"
        ):
            video_id = str(
                data.get(
                    "id",
                    "",
                )
            ).strip()

            filename = str(
                data.get(
                    "filename",
                    "",
                )
            ).strip()

            if not valid_video_id(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Invalid video ID."
                    },
                    400,
                )

                return

            try:
                filename = (
                    safe_filename(
                        filename
                    )
                )

            except ValueError as error:
                send_json(
                    self,
                    {
                        "error":
                            str(error)
                    },
                    400,
                )

                return

            existing_job = (
                get_job(
                    video_id
                )
            )

            if (
                existing_job
                and
                existing_job.get(
                    "status"
                )
                in
                ACTIVE_JOB_STATUSES
            ):
                send_json(
                    self,
                    {
                        "success":
                            True,

                        "already_downloading":
                            True,

                        "job":
                            existing_job,
                    },
                )

                return

            existing = find_entry(
                video_id
            )

            if (
                existing
                and
                find_downloaded_video(
                    video_id
                )
            ):
                send_json(
                    self,
                    {
                        "success":
                            True,

                        "existing":
                            True,

                        "entry":
                            existing,
                    },
                )

                return

            destination = (
                VIDEOS_DIR
                /
                filename
            )

            if destination.exists():
                send_json(
                    self,
                    {
                        "error":
                            "A file with that name already exists."
                    },
                    409,
                )

                return

            job = create_job(
                video_id,
                filename,
            )

            thread = (
                threading.Thread(
                    target=
                        download_worker,

                    args=(
                        video_id,
                        filename,
                    ),

                    daemon=True,
                )
            )

            thread.start()

            send_json(
                self,
                {
                    "success":
                        True,

                    "started":
                        True,

                    "job":
                        dict(job),
                },
            )

            return


        # -------------------------------------------------
        # Cancel
        # -------------------------------------------------

        if (
            request_path
            ==
            "/api/cancel"
        ):
            video_id = str(
                data.get(
                    "id",
                    "",
                )
            ).strip()

            if not valid_video_id(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Invalid video ID."
                    },
                    400,
                )

                return

            if not cancel_job(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "No active download found."
                    },
                    404,
                )

                return

            send_json(
                self,
                {
                    "success":
                        True
                },
            )

            return


        # -------------------------------------------------
        # Rename
        # -------------------------------------------------

        if (
            request_path
            ==
            "/api/rename"
        ):
            video_id = str(
                data.get(
                    "id",
                    "",
                )
            ).strip()

            new_filename = str(
                data.get(
                    "filename",
                    "",
                )
            ).strip()

            if not valid_video_id(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Invalid video ID."
                    },
                    400,
                )

                return

            try:
                new_filename = (
                    safe_filename(
                        new_filename
                    )
                )

            except ValueError as error:
                send_json(
                    self,
                    {
                        "error":
                            str(error)
                    },
                    400,
                )

                return

            with library_lock:
                library = (
                    load_library()
                )

                entry = next(
                    (
                        item
                        for item
                        in library
                        if (
                            item.get("id")
                            ==
                            video_id
                        )
                    ),
                    None,
                )

                if entry is None:
                    send_json(
                        self,
                        {
                            "error":
                                "Video is not in the library."
                        },
                        404,
                    )

                    return

                try:
                    old_path = (
                        video_path_from_filename(
                            entry[
                                "filename"
                            ]
                        )
                    )

                    new_path = (
                        video_path_from_filename(
                            new_filename
                        )
                    )

                except ValueError as error:
                    send_json(
                        self,
                        {
                            "error":
                                str(error)
                        },
                        400,
                    )

                    return

                if not old_path.exists():
                    send_json(
                        self,
                        {
                            "error":
                                "Video file does not exist."
                        },
                        404,
                    )

                    return

                if (
                    new_path.exists()
                    and
                    new_path.resolve()
                    !=
                    old_path.resolve()
                ):
                    send_json(
                        self,
                        {
                            "error":
                                "A file with that name already exists."
                        },
                        409,
                    )

                    return

                if (
                    old_path.resolve()
                    !=
                    new_path.resolve()
                ):
                    old_path.rename(
                        new_path
                    )

                entry[
                    "filename"
                ] = new_filename

                save_library(
                    library
                )

                updated_entry = (
                    dict(entry)
                )

            send_json(
                self,
                {
                    "success":
                        True,

                    "entry":
                        updated_entry,
                },
            )

            return


        # -------------------------------------------------
        # Delete
        # -------------------------------------------------

        if (
            request_path
            ==
            "/api/delete"
        ):
            video_id = str(
                data.get(
                    "id",
                    "",
                )
            ).strip()

            if not valid_video_id(
                video_id
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Invalid video ID."
                    },
                    400,
                )

                return

            job = get_job(
                video_id
            )

            if (
                job
                and
                job.get(
                    "status"
                )
                in
                ACTIVE_JOB_STATUSES
            ):
                send_json(
                    self,
                    {
                        "error":
                            "Cancel the download first."
                    },
                    409,
                )

                return

            with library_lock:
                library = (
                    load_library()
                )

                entry = next(
                    (
                        item
                        for item
                        in library
                        if (
                            item.get("id")
                            ==
                            video_id
                        )
                    ),
                    None,
                )

                if entry is None:
                    send_json(
                        self,
                        {
                            "error":
                                "Video not found."
                        },
                        404,
                    )

                    return

                try:
                    path = (
                        video_path_from_filename(
                            entry[
                                "filename"
                            ]
                        )
                    )

                    if path.exists():
                        path.unlink()

                except ValueError as error:
                    send_json(
                        self,
                        {
                            "error":
                                str(error)
                        },
                        400,
                    )

                    return

                library = [
                    item
                    for item
                    in library
                    if (
                        item.get("id")
                        !=
                        video_id
                    )
                ]

                save_library(
                    library
                )

            send_json(
                self,
                {
                    "success":
                        True
                },
            )

            return


# =========================================================
# Start server
# =========================================================

server = ThreadingHTTPServer(
    (
        HOST,
        PORT,
    ),
    Handler,
)


print()
print(
    "======================================"
)
print(
    "       PERSONAL YOUTUBE VIEWER"
)
print(
    "======================================"
)
print()

print(
    f"Open: http://{HOST}:{PORT}"
)

print()
print(
    "Video.js support enabled."
)
print(
    "Video metadata cache enabled."
)
print(
    "Video list importer enabled."
)
print(
    "Sequential import download queue enabled."
)
print(
    "HTTP byte-range video serving enabled."
)
print(
    "Browser-compatible MP4 preference enabled."
)
print(
    "Download progress enabled."
)
print(
    "Download cancellation enabled."
)
print()
print(
    "Press Ctrl+C to stop."
)
print()


try:
    server.serve_forever()

except KeyboardInterrupt:
    print(
        "\nStopping server..."
    )

finally:
    server.server_close()