# Personal YouTube Video Viewer

A private, local video viewer built with **Python, HTML, CSS, JavaScript, and yt-dlp**.

The application runs entirely on your computer and uses a local HTML5 `<video>` player rather than a YouTube iframe.

> **Important:** Use this project only to download videos you own or otherwise have permission to download. YouTube's terms and the uploader's rights still apply.

---

## Features

* No YouTube API key required
* No Google Cloud project required
* No application account or login
* No database
* No analytics or telemetry
* Runs locally on your computer
* Uses an HTML5 `<video>` player
* Downloads videos through yt-dlp
* Automatically stores downloaded videos locally
* Reuses videos that have already been downloaded
* Keeps downloaded videos out of Git
* Python backend
* Simple web interface

---

# 1. Requirements

You need:

* Windows 10/11
* Python 3.9 or newer
* FFmpeg
* Internet connection
* yt-dlp

You can check whether Python is installed with:

```powershell
python --version
```

You should see something similar to:

```text
Python 3.x.x
```

If Python isn't installed, download it from:

[Python.org](https://www.python.org/downloads/?utm_source=chatgpt.com)

During installation, make sure **"Add Python to PATH"** is enabled.

---

# 2. Create the Project Folder

Create a folder wherever you want.

For example:

```text
C:\Users\YourName\youtube-viewer
```

The final project will look like:

```text
youtube-viewer/
├── server.py
├── index.html
├── style.css
├── script.js
├── README.md
├── .gitignore
└── videos/
    └── .gitkeep
```

---

# 3. Install yt-dlp

Open PowerShell inside the project folder.

Run:

```powershell
python -m pip install -U yt-dlp
```

Check that it installed:

```powershell
yt-dlp --version
```

You should get a version number.

You can also check it through Python:

```powershell
python -c "import yt_dlp; print(yt_dlp.version.__version__)"
```

---

# 4. Install FFmpeg

FFmpeg is required because YouTube can provide video and audio as separate streams.

yt-dlp may download:

```text
Video stream
+
Audio stream
```

FFmpeg combines them into a playable file.

## Option A — winget

On Windows, the easiest method is:

```powershell
winget install Gyan.FFmpeg
```

After installation, close PowerShell and open a new PowerShell window.

Check:

```powershell
ffmpeg -version
```

If FFmpeg is installed correctly, you should see its version information.

## Option B — manual installation

Download a Windows FFmpeg build from:

[FFmpeg downloads](https://ffmpeg.org/download.html?utm_source=chatgpt.com)

A commonly used Windows build is available from:

[Gyan FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/?utm_source=chatgpt.com)

Install it and make sure the directory containing:

```text
ffmpeg.exe
```

is included in your Windows PATH.

Then open a new PowerShell window and run:

```powershell
ffmpeg -version
```

---

# 5. Create the `videos` Folder

Inside the project folder, create:

```text
videos
```

Then create an empty file inside it called:

```text
.gitkeep
```

So you have:

```text
videos/
└── .gitkeep
```

The `.gitkeep` file allows Git to preserve the otherwise-empty directory.

Downloaded videos will eventually appear here.

For example:

```text
videos/
├── dQw4w9WgXcQ.mp4
├── abc12345678.mp4
└── xyz98765432.mp4
```

---

# 6. Add the Project Files

Your project needs these files:

```text
server.py
index.html
style.css
script.js
.gitignore
```

The Python server is responsible for:

* Running the local web server
* Communicating with yt-dlp
* Downloading authorized videos
* Saving videos
* Checking whether a video is already downloaded
* Serving the video files

The frontend is responsible for:

* Entering video IDs
* Starting downloads
* Displaying status
* Playing downloaded videos

---

# 7. Start the Server

Open PowerShell in the project folder.

Run:

```powershell
python server.py
```

You should see:

```text
======================================
       PERSONAL YOUTUBE VIEWER
======================================

Open: http://127.0.0.1:8000

No YouTube API key.
No iframe.
Local server only.

Press Ctrl+C to stop.
```

Keep this PowerShell window open while using the application.

---

# 8. Open the Website

Open your browser and go to:

```text
http://127.0.0.1:8000
```

You should see:

```text
Personal YouTube Viewer

YouTube Video ID

[________________________] [Download & Play]
```

---

# 9. Find a YouTube Video ID

A normal YouTube URL looks like:

```text
https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

The video ID is:

```text
dQw4w9WgXcQ
```

You only need the ID.

Enter:

```text
dQw4w9WgXcQ
```

into the application.

---

# 10. Download the Video

Click:

```text
Download & Play
```

The application sends the ID to the Python server.

The server then passes the corresponding YouTube URL to yt-dlp.

The general process is:

```text
Video ID
    ↓
Python server
    ↓
yt-dlp
    ↓
Video + Audio
    ↓
FFmpeg
    ↓
MP4
    ↓
videos/
```

The downloaded file will be stored locally.

For example:

```text
videos/dQw4w9WgXcQ.mp4
```

---

# 11. The Video Plays Automatically

After the download finishes, the application loads the resulting file into an HTML5 video element.

There is **no YouTube iframe** involved.

The player is essentially:

```html
<video controls>
    ...
</video>
```

The browser plays the local file directly.

---

# 12. Downloaded Videos Are Reused

If you enter the same ID again, the application first checks:

```text
videos/<VIDEO_ID>.*
```

If the video already exists, it won't download it again.

Instead:

```text
Existing file
     ↓
Load file
     ↓
HTML5 player
```

This saves bandwidth and download time.

---

# 13. Where Are the Videos Stored?

All downloaded videos are stored here:

```text
youtube-viewer/videos/
```

For example:

```text
youtube-viewer/
└── videos/
    ├── dQw4w9WgXcQ.mp4
    ├── abcdef12345.mp4
    └── xyzxyzxyz12.mp4
```

You can delete these files normally through Windows Explorer.

Deleting a video does not affect the application.

If you enter its ID again, the application can download it again if you're authorized to do so.

---

# 14. Stopping the Server

Go back to the PowerShell window running the server.

Press:

```text
Ctrl+C
```

The server will stop.

You can start it again later with:

```powershell
python server.py
```

---

# 15. Updating the Project

Whenever you change the code:

```powershell
git add .
git commit -m "Describe your changes"
git push
```

Because of `.gitignore`, your downloaded videos remain on your computer.

---

# 16. Privacy

This application is designed to run locally.

The Python server uses:

```python
HOST = "127.0.0.1"
```

This means it listens only on your own computer.

It is not intentionally exposed to other devices on your network.

The application has:

* No user accounts
* No application login
* No database
* No analytics
* No telemetry
* No API key
* No Google Cloud project
* No remote application server

Your downloaded files remain in:

```text
videos/
```

on your computer.

---

# 17. Troubleshooting

## `python` is not recognized

Try:

```powershell
py --version
```

If that works, you can use:

```powershell
py server.py
```

and:

```powershell
py -m pip install -U yt-dlp
```

If neither works, install Python from:

[Python.org](https://www.python.org/downloads/?utm_source=chatgpt.com)

---

## `No module named yt_dlp`

Run:

```powershell
python -m pip install -U yt-dlp
```

Then restart the server.

---

## `ffmpeg is not installed`

Run:

```powershell
ffmpeg -version
```

If that fails, install FFmpeg and reopen PowerShell.

For example:

```powershell
winget install Gyan.FFmpeg
```

---

## `Error: You have requested merging of multiple formats`

This means yt-dlp found separate video and audio streams but cannot merge them.

Install FFmpeg:

```powershell
winget install Gyan.FFmpeg
```

Then verify:

```powershell
ffmpeg -version
```

Restart `server.py`.

---

## Video downloads but doesn't play

Check the `videos` folder.

You should have something like:

```text
videos/
└── VIDEO_ID.mp4
```

If the file exists but the browser cannot play it, check the server's PowerShell output for errors.

---

## Port 8000 is already in use

Another program is already using port 8000.

Change:

```python
PORT = 8000
```

to:

```python
PORT = 8001
```

Then open:

```text
http://127.0.0.1:8001
```

---

# 18. Basic Architecture

The project works like this:

```text
                  Browser
                     │
                     │ HTTP
                     ▼
              Python server.py
                     │
                     │
             ┌───────┴────────┐
             │                │
             ▼                ▼
          yt-dlp          videos/
             │                │
             ▼                │
          YouTube             │
             │                │
             ▼                │
          FFmpeg              │
             │                │
             └───────┬────────┘
                     │
                     ▼
                HTML5 <video>
```

The browser never needs a YouTube iframe.

---

# 19. Important Legal/Usage Note. (not important lolol)

Only use the downloader for videos you own or have permission to download.

The fact that a video is publicly accessible does not automatically mean you have permission to download or redistribute it.

You are responsible for complying with YouTube's terms and applicable copyright rules.

---

# 20. Future Improvements

Possible future features include:

* YouTube URL input instead of requiring the ID
* Automatic ID extraction
* Download progress bar
* Download speed display
* Estimated remaining time
* Download cancellation
* Video library
* Search through downloaded videos
* Recently watched videos
* Watch history
* Custom video controls
* Playback speed
* Fullscreen
* Keyboard shortcuts
* Resume playback
* Remember playback position
* Multiple video formats
* Automatic cleanup
* Video thumbnails
* Metadata stored locally
* Dark/light themes
* Drag-and-drop video importing

---

# 21. Quick Start

Once everything has been installed, the entire process is simply:

```powershell
cd C:\path\to\youtube-viewer
python server.py
```

Then open:

```text
http://127.0.0.1:8000
```

Enter the video ID:

```text
XXXXXXXXXXX
```

Click:

```text
Download & Play
```

The application downloads the authorized video, stores it locally, and plays it through the HTML5 video player.

---

## Project Status

Current version:

```text
Local YouTube Video Viewer
```

Technology:

```text
Python
HTML
CSS
JavaScript
yt-dlp
FFmpeg
```

Architecture:

```text
Local Python server
+
HTML5 video player
+
Local video storage
```

API key required:

```text
NO
```

YouTube iframe required:

```text
NO
```

Application login required:

```text
NO
```
