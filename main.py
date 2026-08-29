from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote
import json
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


VIDEO_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{11}$"
)

ALLOWED_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mkv",
    ".mov",
    ".m4v"
}


# ---------------------------------------------------------
# Global state
# ---------------------------------------------------------

library_lock = threading.Lock()
jobs_lock = threading.Lock()

download_jobs = {}


# ---------------------------------------------------------
# Library
# ---------------------------------------------------------

def load_library():
    try:
        with open(
            LIBRARY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, list):
            return []

        return data

    except (
        FileNotFoundError,
        json.JSONDecodeError
    ):
        return []


def save_library(library):

    temporary = LIBRARY_FILE.with_suffix(
        ".tmp"
    )

    with open(
        temporary,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            library,
            file,
            indent=2,
            ensure_ascii=False
        )

    temporary.replace(
        LIBRARY_FILE
    )


def find_entry(video_id):

    library = load_library()

    for entry in library:

        if entry.get("id") == video_id:
            return entry

    return None


# ---------------------------------------------------------
# Validation
# ---------------------------------------------------------

def valid_video_id(video_id):

    return bool(
        VIDEO_ID_PATTERN.fullmatch(
            video_id
        )
    )


def safe_filename(filename):

    filename = str(
        filename
    ).strip()

    # Remove directory components.
    filename = Path(filename).name

    # Remove illegal Windows characters.
    filename = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        filename
    )

    # Remove trailing spaces and dots.
    filename = filename.rstrip(
        " ."
    )

    if not filename:

        raise ValueError(
            "Filename cannot be empty."
        )

    extension = Path(
        filename
    ).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:

        filename += ".mp4"

    if len(filename) > 180:

        path = Path(filename)

        filename = (
            path.stem[:170]
            + path.suffix
        )

    return filename


def video_path_from_filename(
    filename
):

    filename = safe_filename(
        filename
    )

    path = VIDEOS_DIR / filename

    # Make absolutely sure the path
    # remains inside videos/.
    videos_root = (
        VIDEOS_DIR
        .resolve()
    )

    resolved = (
        path.resolve()
    )

    if (
        resolved.parent
        != videos_root
    ):

        raise ValueError(
            "Invalid video path."
        )

    return path


def find_downloaded_video(
    video_id
):

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

        path = video_path_from_filename(
            filename
        )

    except ValueError:

        return None

    if path.exists():

        return path

    return None


# ---------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------

def send_json(
    handler,
    data,
    status=200
):

    body = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    handler.send_response(
        status
    )

    handler.send_header(
        "Content-Type",
        "application/json; charset=utf-8"
    )

    handler.send_header(
        "Cache-Control",
        "no-store"
    )

    handler.send_header(
        "Content-Length",
        str(len(body))
    )

    handler.end_headers()

    handler.wfile.write(
        body
    )


def read_json(handler):

    length = int(
        handler.headers.get(
            "Content-Length",
            "0"
        )
    )

    if length > 10000:

        raise ValueError(
            "Request is too large."
        )

    body = handler.rfile.read(
        length
    )

    return json.loads(
        body.decode("utf-8")
    )


# ---------------------------------------------------------
# Download job helpers
# ---------------------------------------------------------

def create_job(
    video_id,
    filename
):

    job = {
        "id": video_id,
        "filename": filename,

        "status": "starting",

        "percent": 0.0,

        "speed": 0,

        "eta": None,

        "downloaded": 0,

        "total": 0,

        "title": None,

        "uploader": None,

        "error": None,

        "cancelled": False,

        "started": time.time(),

        "finished": None
    }

    with jobs_lock:

        download_jobs[
            video_id
        ] = job

    return job


def get_job(video_id):

    with jobs_lock:

        return download_jobs.get(
            video_id
        )


def update_job(
    video_id,
    **values
):

    with jobs_lock:

        job = download_jobs.get(
            video_id
        )

        if job is not None:
            job.update(values)


def is_cancelled(
    video_id
):

    with jobs_lock:

        job = download_jobs.get(
            video_id
        )

        if not job:
            return False

        return job.get(
            "cancelled",
            False
        )


def cancel_job(
    video_id
):

    with jobs_lock:

        job = download_jobs.get(
            video_id
        )

        if not job:
            return False

        job["cancelled"] = True
        job["status"] = "cancelling"

        return True


# ---------------------------------------------------------
# yt-dlp progress hook
# ---------------------------------------------------------

def progress_hook(
    video_id,
    data
):

    if is_cancelled(
        video_id
    ):

        raise yt_dlp.utils.DownloadCancelled(
            "Download cancelled by user."
        )

    status = data.get(
        "status"
    )

    if status == "downloading":

        downloaded = (
            data.get(
                "downloaded_bytes"
            )
            or 0
        )

        total = (
            data.get(
                "total_bytes"
            )
            or data.get(
                "total_bytes_estimate"
            )
            or 0
        )

        percent = 0.0

        if total > 0:

            percent = (
                downloaded
                / total
                * 100
            )

        speed = (
            data.get(
                "speed"
            )
            or 0
        )

        eta = data.get(
            "eta"
        )

        update_job(
            video_id,

            status="downloading",

            percent=percent,

            downloaded=downloaded,

            total=total,

            speed=speed,

            eta=eta
        )

    elif status == "finished":

        update_job(
            video_id,

            status="processing",

            percent=100.0,

            downloaded=(
                data.get(
                    "downloaded_bytes"
                )
                or 0
            )
        )


# ---------------------------------------------------------
# Download worker
# ---------------------------------------------------------

def download_worker(
    video_id,
    filename
):

    temporary_prefix = (
        f".download_{video_id}"
    )

    temporary_template = str(
        VIDEOS_DIR
        / f"{temporary_prefix}.%(ext)s"
    )

    destination = (
        VIDEOS_DIR
        / filename
    )

    try:

        update_job(
            video_id,
            status="starting"
        )

        options = {

            "format":
                "bv*+ba/b",

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

            "progress_hooks":
                [
                    lambda data:
                    progress_hook(
                        video_id,
                        data
                    )
                ],

            # Keep partial files so we can
            # remove them ourselves on cancel.
            "continuedl":
                True
        }

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                (
                    "https://www.youtube.com/"
                    "watch?v="
                    + video_id
                ),
                download=True
            )

            title = info.get(
                "title",
                "Unknown"
            )

            uploader = info.get(
                "uploader",
                "Unknown"
            )

        update_job(
            video_id,

            title=title,

            uploader=uploader,

            status="processing"
        )

        # Check whether cancellation happened
        # while yt-dlp was finishing.
        if is_cancelled(
            video_id
        ):

            raise yt_dlp.utils.DownloadCancelled(
                "Download cancelled."
            )

        downloaded_files = list(
            VIDEOS_DIR.glob(
                f"{temporary_prefix}.*"
            )
        )

        downloaded_files = [
            path
            for path in downloaded_files
            if path.is_file()
        ]

        if not downloaded_files:

            raise RuntimeError(
                "yt-dlp finished but no video file was found."
            )

        source = downloaded_files[0]

        # Don't overwrite another existing file.
        if destination.exists():

            raise FileExistsError(
                f"The file '{filename}' "
                "already exists."
            )

        source.replace(
            destination
        )

        # Add to library.
        entry = {
            "id": video_id,
            "filename": filename
        }

        with library_lock:

            library = load_library()

            library = [
                item
                for item in library
                if item.get("id")
                != video_id
            ]

            library.append(
                entry
            )

            save_library(
                library
            )

        update_job(
            video_id,

            status="completed",

            percent=100.0,

            finished=time.time(),

            entry=entry
        )

    except yt_dlp.utils.DownloadCancelled:

        update_job(
            video_id,

            status="cancelled",

            cancelled=True,

            finished=time.time()
        )

    except Exception as error:

        print(
            f"Download error for "
            f"{video_id}: {error}"
        )

        update_job(
            video_id,

            status="error",

            error=str(error),

            finished=time.time()
        )

    finally:

        # Remove incomplete yt-dlp files.
        for path in VIDEOS_DIR.glob(
            f"{temporary_prefix}.*"
        ):

            try:

                if path.is_file():
                    path.unlink()

            except OSError:
                pass


# ---------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------

class Handler(
    SimpleHTTPRequestHandler
):

    def __init__(
        self,
        *args,
        **kwargs
    ):

        super().__init__(
            *args,

            directory=str(
                BASE_DIR
            ),

            **kwargs
        )

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    def do_GET(self):

        # ---------------------------------------------
        # Library
        # ---------------------------------------------

        if self.path == "/api/library":

            with library_lock:

                library = load_library()

            result = []

            for entry in library:

                try:

                    filename = entry[
                        "filename"
                    ]

                    path = (
                        video_path_from_filename(
                            filename
                        )
                    )

                    if path.exists():

                        result.append(
                            entry
                        )

                except (
                    KeyError,
                    ValueError
                ):

                    continue

            send_json(
                self,
                result
            )

            return

        # ---------------------------------------------
        # Progress
        # ---------------------------------------------

        if self.path.startswith(
            "/api/progress/"
        ):

            video_id = unquote(
                self.path[
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
                    400
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
                    }
                )

                return

            with jobs_lock:

                response = dict(
                    job
                )

            send_json(
                self,
                response
            )

            return

        # ---------------------------------------------
        # Check
        # ---------------------------------------------

        if self.path.startswith(
            "/api/check/"
        ):

            video_id = unquote(
                self.path[
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
                    400
                )

                return

            entry = find_entry(
                video_id
            )

            path = find_downloaded_video(
                video_id
            )

            send_json(
                self,
                {
                    "exists":
                        path is not None,

                    "entry":
                        entry
                }
            )

            return

        super().do_GET()

    # -----------------------------------------------------
    # POST
    # -----------------------------------------------------

    def do_POST(self):

        allowed = {
            "/api/download",
            "/api/cancel",
            "/api/rename",
            "/api/delete"
        }

        if self.path not in allowed:

            send_json(
                self,
                {
                    "error":
                        "Unknown endpoint."
                },
                404
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
                400
            )

            return

        # =================================================
        # DOWNLOAD
        # =================================================

        if self.path == "/api/download":

            video_id = str(
                data.get(
                    "id",
                    ""
                )
            ).strip()

            filename = str(
                data.get(
                    "filename",
                    ""
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
                    400
                )

                return

            try:

                filename = safe_filename(
                    filename
                )

            except ValueError as error:

                send_json(
                    self,
                    {
                        "error":
                            str(error)
                    },
                    400
                )

                return

            # Already downloading?
            with jobs_lock:

                existing_job = (
                    download_jobs.get(
                        video_id
                    )
                )

                if existing_job:

                    status = existing_job.get(
                        "status"
                    )

                    if status in {
                        "starting",
                        "downloading",
                        "processing",
                        "cancelling"
                    }:

                        send_json(
                            self,
                            {
                                "success":
                                    True,

                                "already_downloading":
                                    True,

                                "job":
                                    dict(
                                        existing_job
                                    )
                            }
                        )

                        return

            # Already downloaded?
            existing = find_entry(
                video_id
            )

            if existing:

                path = find_downloaded_video(
                    video_id
                )

                if path:

                    send_json(
                        self,
                        {
                            "success":
                                True,

                            "existing":
                                True,

                            "entry":
                                existing
                        }
                    )

                    return

            # Make sure requested filename
            # doesn't already belong to another
            # video.
            destination = (
                VIDEOS_DIR
                / filename
            )

            if destination.exists():

                send_json(
                    self,
                    {
                        "error":
                            "A file with that "
                            "name already exists."
                    },
                    409
                )

                return

            job = create_job(
                video_id,
                filename
            )

            thread = threading.Thread(
                target=download_worker,

                args=(
                    video_id,
                    filename
                ),

                daemon=True
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
                        dict(job)
                }
            )

            return

        # =================================================
        # CANCEL
        # =================================================

        if self.path == "/api/cancel":

            video_id = str(
                data.get(
                    "id",
                    ""
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
                    400
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
                    404
                )

                return

            send_json(
                self,
                {
                    "success":
                        True
                }
            )

            return

        # =================================================
        # RENAME
        # =================================================

        if self.path == "/api/rename":

            video_id = str(
                data.get(
                    "id",
                    ""
                )
            ).strip()

            new_filename = str(
                data.get(
                    "filename",
                    ""
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
                    400
                )

                return

            try:

                new_filename = safe_filename(
                    new_filename
                )

            except ValueError as error:

                send_json(
                    self,
                    {
                        "error":
                            str(error)
                    },
                    400
                )

                return

            with library_lock:

                library = load_library()

                entry = next(
                    (
                        item
                        for item in library
                        if item.get("id")
                        == video_id
                    ),
                    None
                )

                if entry is None:

                    send_json(
                        self,
                        {
                            "error":
                                "Video is not "
                                "in the library."
                        },
                        404
                    )

                    return

                old_filename = entry.get(
                    "filename"
                )

                try:

                    old_path = (
                        video_path_from_filename(
                            old_filename
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
                        400
                    )

                    return

                if not old_path.exists():

                    send_json(
                        self,
                        {
                            "error":
                                "Video file "
                                "does not exist."
                        },
                        404
                    )

                    return

                if (
                    new_path.exists()
                    and
                    new_path.resolve()
                    != old_path.resolve()
                ):

                    send_json(
                        self,
                        {
                            "error":
                                "A file with that "
                                "name already exists."
                        },
                        409
                    )

                    return

                old_path.rename(
                    new_path
                )

                entry[
                    "filename"
                ] = new_filename

                save_library(
                    library
                )

            send_json(
                self,
                {
                    "success":
                        True,

                    "entry":
                        entry
                }
            )

            return

        # =================================================
        # DELETE
        # =================================================

        if self.path == "/api/delete":

            video_id = str(
                data.get(
                    "id",
                    ""
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
                    400
                )

                return

            # Don't delete something that is
            # currently downloading.
            job = get_job(
                video_id
            )

            if job:

                if job.get(
                    "status"
                ) in {
                    "starting",
                    "downloading",
                    "processing",
                    "cancelling"
                }:

                    send_json(
                        self,
                        {
                            "error":
                                "Cancel the "
                                "download first."
                        },
                        409
                    )

                    return

            with library_lock:

                library = load_library()

                entry = next(
                    (
                        item
                        for item in library
                        if item.get("id")
                        == video_id
                    ),
                    None
                )

                if entry is None:

                    send_json(
                        self,
                        {
                            "error":
                                "Video not found."
                        },
                        404
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
                        400
                    )

                    return

                library = [
                    item
                    for item in library
                    if item.get("id")
                    != video_id
                ]

                save_library(
                    library
                )

            send_json(
                self,
                {
                    "success":
                        True
                }
            )

            return


# ---------------------------------------------------------
# Start server
# ---------------------------------------------------------

server = ThreadingHTTPServer(
    (HOST, PORT),
    Handler
)


print()
print("======================================")
print("       PERSONAL YOUTUBE VIEWER")
print("======================================")
print()
print(
    f"Open: http://{HOST}:{PORT}"
)
print()
print("No YouTube API key.")
print("No iframe.")
print("Local server only.")
print()
print(
    "Download progress enabled."
)
print(
    "Download cancellation enabled."
)
print()
print("Press Ctrl+C to stop.")
print()


try:

    server.serve_forever()

except KeyboardInterrupt:

    print(
        "\nStopping server..."
    )

finally:

    server.server_close()