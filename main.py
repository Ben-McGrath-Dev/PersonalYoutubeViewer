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

VIDEOS_DIR.mkdir(exist_ok=True)


def valid_video_id(video_id):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id))


def send_json(handler, data, status=200):
    body = json.dumps(data).encode("utf-8")

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()

    handler.wfile.write(body)


def find_downloaded_video(video_id):
    """
    Find a downloaded video regardless of whether yt-dlp
    produced mp4, webm, mkv, etc.
    """

    matches = list(VIDEOS_DIR.glob(f"{video_id}.*"))

    matches = [
        path for path in matches
        if not path.name.startswith(f".{video_id}.")
    ]

    return matches[0] if matches else None


def download_video(video_id):
    """
    Download the requested YouTube video with yt-dlp.

    This is intended for videos the user is authorized
    to download.
    """

    output_template = str(
        VIDEOS_DIR / f"{video_id}.%(ext)s"
    )

    ydl_options = {
        # Prefer a format suitable for browser playback.
        "format": "bv*+ba/b",

        "outtmpl": output_template,

        # Let yt-dlp/FFmpeg merge separate streams.
        "merge_output_format": "mp4",

        # Do not download playlists.
        "noplaylist": True,

        # Useful metadata returned to our server.
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_options) as ydl:

        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=True
        )

        title = info.get("title", "Unknown")
        uploader = info.get("uploader", "Unknown")

    video_path = find_downloaded_video(video_id)

    if video_path is None:
        raise RuntimeError(
            "yt-dlp completed but no video file was found."
        )

    return {
        "path": video_path,
        "filename": video_path.name,
        "title": title,
        "uploader": uploader,
    }


class Handler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(BASE_DIR),
            **kwargs
        )

    def do_GET(self):

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

            video_path = find_downloaded_video(
                video_id
            )

            send_json(
                self,
                {
                    "exists": video_path is not None,
                    "video_id": video_id,
                    "filename": (
                        video_path.name
                        if video_path
                        else None
                    )
                }
            )

            return

        super().do_GET()

    def do_POST(self):

        if self.path != "/api/download":

            send_json(
                self,
                {
                    "error": "Unknown endpoint."
                },
                404
            )

            return

        content_length = int(
            self.headers.get("Content-Length", 0)
        )

        # Request body should only contain the video ID.
        if content_length > 1000:

            send_json(
                self,
                {
                    "error": "Invalid request."
                },
                400
            )

            return

        try:

            body = self.rfile.read(
                content_length
            ).decode("utf-8")

            data = json.loads(body)

            video_id = str(
                data.get("video_id", "")
            ).strip()

        except Exception:

            send_json(
                self,
                {
                    "error": "Invalid JSON request."
                },
                400
            )

            return

        if not valid_video_id(video_id):

            send_json(
                self,
                {
                    "error": "Invalid YouTube video ID."
                },
                400
            )

            return

        existing = find_downloaded_video(
            video_id
        )

        if existing:

            send_json(
                self,
                {
                    "success": True,
                    "already_downloaded": True,
                    "video_id": video_id,
                    "filename": existing.name,
                }
            )

            return

        # Download in the request thread.
        # This keeps the first version simple.
        try:

            result = download_video(
                video_id
            )

            send_json(
                self,
                {
                    "success": True,
                    "already_downloaded": False,
                    "video_id": video_id,
                    "filename": result["filename"],
                    "title": result["title"],
                    "uploader": result["uploader"],
                }
            )

        except Exception as error:

            print(
                f"Download error for {video_id}: "
                f"{error}"
            )

            send_json(
                self,
                {
                    "success": False,
                    "error": str(error),
                },
                500
            )


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