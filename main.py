from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote
import json
import re
import threading

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

ALLOWED_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mkv",
    ".mov",
    ".m4v"
}


library_lock = threading.Lock()


def valid_video_id(video_id):
    return bool(VIDEO_ID_PATTERN.fullmatch(video_id))


def load_library():
    try:
        with open(LIBRARY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            return []

        return data

    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_library(library):
    temporary = LIBRARY_FILE.with_suffix(".tmp")

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(
            library,
            file,
            indent=2,
            ensure_ascii=False
        )

    temporary.replace(LIBRARY_FILE)


def find_entry(video_id):
    library = load_library()

    for entry in library:
        if entry.get("id") == video_id:
            return entry

    return None


def safe_filename(filename):
    """
    Convert a user supplied filename into a safe filename
    that remains inside videos/.
    """

    filename = str(filename).strip()

    # Remove directory components.
    filename = Path(filename).name

    # Remove illegal Windows filename characters.
    filename = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        filename
    )

    # Remove trailing spaces/dots.
    filename = filename.rstrip(" .")

    if not filename:
        raise ValueError("Filename cannot be empty.")

    # Make sure the file has a video extension.
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        filename += ".mp4"

    if len(filename) > 180:
        path = Path(filename)

        filename = (
            path.stem[:170] +
            path.suffix
        )

    return filename


def video_path_from_filename(filename):
    filename = safe_filename(filename)

    path = VIDEOS_DIR / filename

    # Extra safety check.
    if path.parent.resolve() != VIDEOS_DIR.resolve():
        raise ValueError("Invalid video path.")

    return path


def send_json(handler, data, status=200):
    body = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    handler.send_response(status)

    handler.send_header(
        "Content-Type",
        "application/json; charset=utf-8"
    )

    handler.send_header(
        "Content-Length",
        str(len(body))
    )

    handler.end_headers()

    handler.wfile.write(body)


def find_downloaded_video(video_id):
    entry = find_entry(video_id)

    if entry:
        filename = entry.get("filename")

        if filename:
            try:
                path = video_path_from_filename(
                    filename
                )

                if path.exists():
                    return path

            except ValueError:
                pass

    return None


def download_video(video_id, filename):

    filename = safe_filename(filename)

    requested_path = VIDEOS_DIR / filename

    if requested_path.exists():
        raise FileExistsError(
            f"A file named '{filename}' already exists."
        )

    temporary_template = str(
        VIDEOS_DIR /
        f".download_{video_id}.%(ext)s"
    )

    options = {
        "format": "bv*+ba/b",

        "outtmpl": temporary_template,

        "merge_output_format": "mp4",

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:

        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
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

    downloaded_files = list(
        VIDEOS_DIR.glob(
            f".download_{video_id}.*"
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

    source.replace(requested_path)

    return {
        "title": title,
        "uploader": uploader,
        "filename": filename,
        "path": requested_path
    }


class Handler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(BASE_DIR),
            **kwargs
        )

    def do_GET(self):

        # Return the complete local library.
        if self.path == "/api/library":

            with library_lock:
                library = load_library()

            # Remove entries whose files no longer exist.
            result = []

            for entry in library:

                try:
                    filename = entry["filename"]
                    path = video_path_from_filename(filename)

                    if path.exists():
                        result.append(entry)

                except (KeyError, ValueError):
                    continue

            send_json(
                self,
                result
            )

            return

        # Check one video.
        if self.path.startswith("/api/check/"):

            video_id = unquote(
                self.path[len("/api/check/"):]
            )

            if not valid_video_id(video_id):

                send_json(
                    self,
                    {
                        "error": "Invalid video ID."
                    },
                    400
                )

                return

            entry = find_entry(video_id)

            path = find_downloaded_video(
                video_id
            )

            send_json(
                self,
                {
                    "exists": path is not None,
                    "entry": entry
                }
            )

            return

        super().do_GET()

    def do_POST(self):

        if self.path not in {
            "/api/download",
            "/api/rename",
            "/api/delete"
        }:

            send_json(
                self,
                {
                    "error": "Unknown endpoint."
                },
                404
            )

            return

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            if length > 10000:
                raise ValueError(
                    "Request is too large."
                )

            body = self.rfile.read(length)

            data = json.loads(
                body.decode("utf-8")
            )

        except Exception as error:

            send_json(
                self,
                {
                    "error": str(error)
                },
                400
            )

            return

        # -----------------------------------------
        # DOWNLOAD
        # -----------------------------------------

        if self.path == "/api/download":

            video_id = str(
                data.get("id", "")
            ).strip()

            filename = str(
                data.get("filename", "")
            ).strip()

            if not valid_video_id(video_id):

                send_json(
                    self,
                    {
                        "error": "Invalid video ID."
                    },
                    400
                )

                return

            try:
                filename = safe_filename(filename)

            except ValueError as error:

                send_json(
                    self,
                    {
                        "error": str(error)
                    },
                    400
                )

                return

            existing = find_entry(video_id)

            if existing:

                path = find_downloaded_video(
                    video_id
                )

                if path:

                    send_json(
                        self,
                        {
                            "success": True,
                            "existing": True,
                            "entry": existing
                        }
                    )

                    return

            try:

                result = download_video(
                    video_id,
                    filename
                )

                entry = {
                    "id": video_id,
                    "filename": result["filename"]
                }

                with library_lock:

                    library = load_library()

                    library = [
                        item
                        for item in library
                        if item.get("id") != video_id
                    ]

                    library.append(entry)

                    save_library(library)

                send_json(
                    self,
                    {
                        "success": True,
                        "existing": False,
                        "entry": entry,
                        "title": result["title"],
                        "uploader": result["uploader"]
                    }
                )

            except Exception as error:

                print(
                    f"Download error: {error}"
                )

                send_json(
                    self,
                    {
                        "success": False,
                        "error": str(error)
                    },
                    500
                )

            return

        # -----------------------------------------
        # RENAME
        # -----------------------------------------

        if self.path == "/api/rename":

            video_id = str(
                data.get("id", "")
            ).strip()

            new_filename = str(
                data.get("filename", "")
            ).strip()

            if not valid_video_id(video_id):

                send_json(
                    self,
                    {
                        "error": "Invalid video ID."
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
                        "error": str(error)
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
                        if item.get("id") == video_id
                    ),
                    None
                )

                if entry is None:

                    send_json(
                        self,
                        {
                            "error": "Video is not in the library."
                        },
                        404
                    )

                    return

                old_filename = entry.get(
                    "filename"
                )

                try:

                    old_path = video_path_from_filename(
                        old_filename
                    )

                    new_path = video_path_from_filename(
                        new_filename
                    )

                except ValueError as error:

                    send_json(
                        self,
                        {
                            "error": str(error)
                        },
                        400
                    )

                    return

                if not old_path.exists():

                    send_json(
                        self,
                        {
                            "error": "Video file does not exist."
                        },
                        404
                    )

                    return

                if (
                    new_path.exists()
                    and new_path.resolve()
                    != old_path.resolve()
                ):

                    send_json(
                        self,
                        {
                            "error":
                            "A file with that name already exists."
                        },
                        409
                    )

                    return

                old_path.rename(new_path)

                entry["filename"] = new_filename

                save_library(library)

            send_json(
                self,
                {
                    "success": True,
                    "entry": entry
                }
            )

            return

        # -----------------------------------------
        # DELETE
        # -----------------------------------------

        if self.path == "/api/delete":

            video_id = str(
                data.get("id", "")
            ).strip()

            if not valid_video_id(video_id):

                send_json(
                    self,
                    {
                        "error": "Invalid video ID."
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
                        if item.get("id") == video_id
                    ),
                    None
                )

                if entry is None:

                    send_json(
                        self,
                        {
                            "error": "Video not found."
                        },
                        404
                    )

                    return

                try:

                    path = video_path_from_filename(
                        entry["filename"]
                    )

                    if path.exists():
                        path.unlink()

                except ValueError as error:

                    send_json(
                        self,
                        {
                            "error": str(error)
                        },
                        400
                    )

                    return

                library = [
                    item
                    for item in library
                    if item.get("id") != video_id
                ]

                save_library(library)

            send_json(
                self,
                {
                    "success": True
                }
            )

            return


server = ThreadingHTTPServer(
    (HOST, PORT),
    Handler
)


print()
print("======================================")
print("       PERSONAL YOUTUBE VIEWER")
print("======================================")
print()
print(f"Open: http://{HOST}:{PORT}")
print()
print("No YouTube API key.")
print("No iframe.")
print("Local server only.")
print()
print("Press Ctrl+C to stop.")
print()


try:

    server.serve_forever()

except KeyboardInterrupt:

    print("\nStopping server...")

finally:

    server.server_close()
