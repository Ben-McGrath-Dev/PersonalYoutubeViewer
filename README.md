[![GitHub](https://img.shields.io/badge/GitHub-PersonalYoutubeViewer-181717?logo=github\&logoColor=white)](https://github.com/Ben-McGrath-Dev/PersonalYoutubeViewer)

![GitHub stars](https://img.shields.io/github/stars/Ben-McGrath-Dev/PersonalYoutubeViewer)
![GitHub last commit](https://img.shields.io/github/last-commit/Ben-McGrath-Dev/PersonalYoutubeViewer)
![GitHub repo size](https://img.shields.io/github/repo-size/Ben-McGrath-Dev/PersonalYoutubeViewer)
![GitHub top language](https://img.shields.io/github/languages/top/Ben-McGrath-Dev/PersonalYoutubeViewer)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python\&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-ES6%2B-F7DF1E?logo=javascript\&logoColor=black)
![yt-dlp](https://img.shields.io/badge/yt--dlp-Powered-FF0000)
![FFmpeg](https://img.shields.io/badge/FFmpeg-Recommended-007808?logo=ffmpeg\&logoColor=white)
![Video.js](https://img.shields.io/badge/Video.js-Player-2B333F)
![SQLite](https://img.shields.io/badge/SQLite-Scraper%20State-003B57?logo=sqlite\&logoColor=white)

![Privacy Focused](https://img.shields.io/badge/Privacy-Focused-success)
![No Ads](https://img.shields.io/badge/Ads-None-success)
![No Analytics](https://img.shields.io/badge/Analytics-None-success)
![No Telemetry](https://img.shields.io/badge/Telemetry-None-success)
![No Tracking](https://img.shields.io/badge/Tracking-None-success)
![No App Cookies](https://img.shields.io/badge/App%20Cookies-None-success)
![Local Only](https://img.shields.io/badge/Local-Only-success)
![CLI Search](https://img.shields.io/badge/CLI%20Search-Yes-informational)
![Bulk Import](https://img.shields.io/badge/Bulk%20Import-Yes-blueviolet)
![HTTP Range](https://img.shields.io/badge/Seeking-HTTP%20Range-blue)

# Personal YouTube Viewer

A privacy-focused, local, self-hosted YouTube downloader, video library, discovery scraper, and metadata search toolkit built with Python, JavaScript, HTML, CSS, SQLite, `yt-dlp`, and FFmpeg.

The project is designed around a simple principle:

> **Discover remotely when necessary, store locally, search locally, watch locally, and keep control of your own data.**

There are no project accounts, advertisements, analytics systems, tracking SDKs, telemetry services, or project-operated cloud libraries.

Most importantly, these claims are not hidden behind a privacy policy.

**The complete source code is available for you to inspect yourself.**

---

# Table of Contents

* [Why This Project Exists](#why-this-project-exists)
* [Privacy at a Glance](#privacy-at-a-glance)
* [Quick Start](#quick-start)
* [How the Project Fits Together](#how-the-project-fits-together)
* [How the Viewer Works](#how-the-viewer-works)
* [How Downloads Work](#how-downloads-work)
* [Local Playback and HTTP Range Requests](#local-playback-and-http-range-requests)
* [Bulk Import](#bulk-import)
* [How the Scraper Works](#how-the-scraper-works)
* [Query Files](#query-files)
* [SearchQueries.py](#searchqueriespy)
* [Storage Management](#storage-management)
* [Privacy Deep Dive](#privacy-deep-dive)
* [What Uses the Internet](#what-uses-the-internet)
* [Privacy Limits](#privacy-limits)
* [Security Considerations](#security-considerations)
* [File Responsibilities](#file-responsibilities)
* [Why TXT, JSON and SQLite](#why-txt-json-and-sqlite)
* [Scraper State and Resume Support](#scraper-state-and-resume-support)
* [Performance and Rate Limiting](#performance-and-rate-limiting)
* [Project Structure](#project-structure)
* [Troubleshooting](#troubleshooting)
* [Updating yt-dlp](#updating-yt-dlp)
* [Roadmap](#roadmap)
* [Non-Goals](#non-goals)
* [Legal](#legal)

---

# Why This Project Exists

YouTube is extremely useful for finding content, but there are situations where keeping selected media locally is useful.

This project is intended to provide a simple workflow for:

* Discovering videos
* Searching large discovery datasets
* Selecting videos worth keeping
* Downloading selected media
* Preserving useful content locally
* Watching downloaded videos offline
* Maintaining your own local metadata library
* Avoiding a project-controlled account or cloud database
* Reducing unnecessary requests after metadata has already been cached

It also solves a practical problem that appeared while developing the scraper:

**thousands of discovered videos are useful as metadata, but loading thousands of results into a browser just to search them is slow and unnecessary.**

That is why the repository now contains three main components.

---

# Privacy at a Glance

| Feature                                              | Personal YouTube Viewer |
| ---------------------------------------------------- | ----------------------- |
| Project advertisements                               | **None**                |
| Project analytics                                    | **None**                |
| Project telemetry                                    | **None**                |
| Project tracking SDK                                 | **None**                |
| Application login account                            | **None**                |
| Project-operated cloud library                       | **None**                |
| Project-operated watch-history server                | **None**                |
| Application-set tracking cookies                     | **None**                |
| Browser-cookie login required                        | **No**                  |
| Local metadata storage                               | **Yes**                 |
| Local downloaded media                               | **Yes**                 |
| Local CLI search                                     | **Yes**                 |
| Source code available for inspection                 | **Yes**                 |
| YouTube contacted when downloading/searching YouTube | **Yes, necessarily**    |

The important distinction is:

> **The application does not collect your activity for the project author, but requests to YouTube still have to reach YouTube.**

---

# Quick Start

## Viewer

Install/update `yt-dlp`:

```bash
pip install -U yt-dlp
```

Make sure FFmpeg is installed:

```bash
ffmpeg -version
```

Start the local server:

```bash
python main.py
```

Then open:

```text
http://127.0.0.1:8000
```

---

## Scraper

Run:

```bash
python youtube_scraper_improved.py
```

The scraper reads:

```text
queries_small.txt
```

and produces metadata including:

```text
youtube_videos_small.txt
```

---

## CLI Search

Search the scraper output interactively:

```bash
python SearchQueries.py
```

Or perform a one-shot search:

```bash
python SearchQueries.py minecraft
```

---

# Recommended Workflow

The intended workflow is:

```text
Search YouTube broadly
        ↓
Store discovery metadata locally
        ↓
Search it with SearchQueries.py
        ↓
Find interesting videos
        ↓
Import/select only what you want
        ↓
Download selected videos
        ↓
Watch locally
        ↓
Delete old media when no longer needed
```

This is preferable to downloading thousands of videos simply because the scraper discovered them.

---

# How the Project Fits Together

```text
                              YouTube
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
                 ▼                               ▼
          Direct download                 Search queries
                 │                               │
                 ▼                               ▼
              main.py               youtube_scraper_improved.py
                 │                               │
                 │                               ▼
                 │                    Candidate SQLite DB
                 │                               │
                 │                               ▼
                 │                     Channel/video filtering
                 │                               │
                 │                               ▼
                 │                    youtube_videos_small.txt
                 │                               │
                 │                    ┌──────────┴──────────┐
                 │                    │                     │
                 │                    ▼                     ▼
                 │            SearchQueries.py       Bulk importer
                 │                                          │
                 └──────────────────────────────────────────┘
                                      │
                                      ▼
                                videos/
                                      │
                                      ▼
                            Local HTML5 playback
```

---

# Main Components

## Personal YouTube Viewer

Files:

```text
main.py
index.html
style.css
script.js
```

Responsibilities:

* Local web server
* Download API
* Video library
* Metadata caching
* Video playback
* File rename/delete
* Bulk list importing
* HTTP Range support

---

## YouTube Scraper

File:

```text
youtube_scraper_improved.py
```

Responsibilities:

* Search YouTube
* Collect candidate IDs
* Deduplicate results
* Cache channel information
* Filter channels
* Retrieve metadata
* Track candidate processing state
* Resume interrupted jobs
* Generate importable metadata files

It discovers videos.

It does **not** download all of those videos.

---

## SearchQueries

File:

```text
SearchQueries.py
```

Responsibilities:

* Read scraper TXT output
* Parse video records
* Search metadata locally
* Filter by field
* Search dates
* Support AND/OR matching
* Support regular expressions
* Output IDs or URLs
* Avoid loading thousands of records into HTML

---

# How the Viewer Works

Running:

```bash
python main.py
```

starts Python's local HTTP server.

By default:

```python
HOST = "127.0.0.1"
PORT = 8000
```

The browser connects to:

```text
http://127.0.0.1:8000
```

The application architecture is therefore:

```text
Your browser
     │
     │ HTTP
     ▼
127.0.0.1:8000
     │
     ▼
main.py
     │
     ├── index.html
     ├── style.css
     ├── script.js
     ├── videos/library.json
     └── videos/*.mp4
```

There is no project-operated server between your browser and the local Python process.

---

# Viewer Startup

When the page loads, `script.js` retrieves the local library through:

```text
GET /api/library
```

Conceptually:

```text
Browser
   │
   ▼
GET /api/library
   │
   ▼
main.py
   │
   ▼
videos/library.json
   │
   ▼
JSON response
   │
   ▼
Render local library
```

Metadata already stored locally does not need to be repeatedly retrieved from YouTube every time you open the viewer.

---

# Library Metadata

An entry in:

```text
videos/library.json
```

can look similar to:

```json
{
  "id": "tCoEYFbDVoI",
  "filename": "Simulating the Evolution of Rock, Paper, Scissors.mp4",
  "title": "Simulating the Evolution of Rock, Paper, Scissors",
  "uploader": "Primer",
  "channel": "Primer",
  "description": "Video description...",
  "thumbnail": "https://i.ytimg.com/...",
  "duration": 1234
}
```

The local metadata is used for:

* Library rendering
* Video titles
* Uploader information
* Video descriptions
* Local filenames
* Rename operations
* Delete operations
* Video Info
* Avoiding repeated metadata requests

---

# Library Controls

Each video contains:

```text
Play | Rename | Info | Delete
```

## Play

Loads the local media file into the player.

## Rename

Renames both:

```text
videos/old-name.mp4
```

and the corresponding library metadata entry.

## Info

Displays:

* Thumbnail
* Title
* Uploader
* Duration
* Description

The backend first checks the cached local metadata.

## Delete

Removes:

* The actual media file
* Its `library.json` entry

For storage management, deleting through the viewer is preferable to manually deleting files.

---

# How Downloads Work

When a user provides a YouTube URL or video ID, the browser sends a local request to:

```text
POST /api/download
```

The flow is approximately:

```text
User enters YouTube URL/ID
          │
          ▼
       script.js
          │
          ▼
POST /api/download
          │
          ▼
        main.py
          │
          ▼
Validate video ID
          │
          ▼
        yt-dlp
          │
          ├── retrieve metadata
          ├── choose formats
          └── download
          │
          ▼
FFmpeg merge when necessary
          │
          ▼
videos/video-name.mp4
          │
          ▼
videos/library.json
```

---

# Download Format Selection

The downloader attempts to prefer browser-compatible formats.

In particular, it prefers combinations similar to:

```text
H.264 / AVC video
+
AAC / M4A audio
```

when available.

This helps produce media that modern browsers can play directly.

If YouTube provides separate audio and video streams, FFmpeg can merge them.

---

# Download Progress

During a download, the frontend can request:

```text
GET /api/progress/<video-id>
```

The backend tracks information such as:

```text
percentage
downloaded bytes
total bytes
speed
ETA
download status
```

This communication occurs between:

```text
your browser
↕
your local Python process
```

It is not analytics telemetry.

---

# Download Cancellation

The application also provides:

```text
POST /api/cancel
```

for active jobs.

A cancelled job is stopped through the download state handled by the Python process.

---

# Local Playback and HTTP Range Requests

Once a video has been downloaded, playback uses the local file.

```text
videos/example.mp4
       │
       ▼
main.py
       │
       ▼
127.0.0.1:8000/videos/example.mp4
       │
       ▼
Browser player
```

The media does not have to be streamed from YouTube every time you watch it.

---

# HTTP Range Support

The local server supports HTTP Range requests.

A browser might request:

```text
Range: bytes=50000000-60000000
```

and receive:

```text
HTTP/1.1 206 Partial Content
Accept-Ranges: bytes
Content-Range: ...
```

This lets the browser request only part of a large file.

That enables:

* Seeking
* Jumping forward
* Jumping backward
* Starting part-way through a video
* Efficient playback of large media

---

# Video Player

The viewer can use Video.js, with the browser's native HTML5 player available as a fallback.

Keyboard controls:

| Key           | Action             |
| ------------- | ------------------ |
| `Space`       | Play / Pause       |
| `K`           | Play / Pause       |
| `J`           | Back 10 seconds    |
| `Left Arrow`  | Back 10 seconds    |
| `L`           | Forward 10 seconds |
| `Right Arrow` | Forward 10 seconds |
| `Home`        | Beginning          |
| `End`         | End                |

If Video.js is loaded from an external CDN in your version of the frontend, that asset request is an external network request. Users wanting the strictest possible local-only frontend can host the Video.js assets locally or rely on the native player fallback.

The project itself does not use Video.js for analytics or tracking.

---

# Bulk Import

The viewer understands lists formatted like:

```text
================================================================================
Video uploader: Primer
Date uploaded: 20240713
Name: Simulating the Evolution of Rock, Paper, Scissors
Video ID: tCoEYFbDVoI
Video description:
Description...

================================================================================
```

The text is sent locally to:

```text
POST /api/import-list
```

The backend parses it into structured video records.

```text
Raw text
   │
   ▼
main.py
   │
   ▼
Parsed records
   │
   ▼
script.js
   │
   ▼
Checkboxes / download controls
```

---

# Bulk Download Queue

Selected videos are downloaded sequentially.

```text
Video 1
   ↓
Download
   ↓
Finish
   ↓
Video 2
   ↓
Download
   ↓
Finish
```

This avoids launching a large number of simultaneous download and FFmpeg jobs.

It also reduces:

* Bandwidth competition
* Disk contention
* CPU contention
* Request bursts

Videos already present in the library are skipped.

---

# How the Scraper Works

The scraper has two main phases:

```text
SEARCH
   │
   ▼
Candidate IDs
   │
   ▼
PROCESSING
```

---

# Phase 1: Load Queries

The default file is:

```text
queries_small.txt
```

Each non-empty line is treated as a YouTube search query.

Lines beginning with:

```text
#
```

are ignored.

Duplicate queries are also removed.

---

# Search Queries Are Not Channel Subscriptions

For example:

```text
Mattbatwings
```

is a search query.

It can therefore discover:

* Mattbatwings uploads
* Videos about Mattbatwings
* Collaborations
* Reaction videos
* Related redstone content

This behaviour is intentional.

The scraper is designed for discovery rather than simply mirroring specific channels.

---

# Phase 2: YouTube Search

The scraper uses `yt-dlp` to perform searches.

Default:

```python
RESULTS_PER_QUERY = 500
```

A query can therefore produce hundreds of raw results.

The scraper extracts useful lightweight information such as:

```text
video ID
channel ID
uploader
```

before performing expensive metadata processing.

---

# Candidate Validation

YouTube search output can contain objects other than ordinary videos.

The scraper validates candidate video IDs.

This prevents items such as:

```text
channel IDs
playlist IDs
non-video search objects
```

from accidentally entering the metadata queue.

---

# Candidate Database

Candidates are stored in:

```text
youtube_candidates_small.sqlite3
```

SQLite stores information such as:

```text
video_id
channel_id
uploader
status
attempt count
updated timestamp
```

This is important for large runs because processing state survives program restarts.

---

# Repeated-Channel Prefiltering

One of the scraper's largest optimisations is checking frequently repeated channels before retrieving every video's full metadata.

Example:

```text
Search results
      │
      ├── 150 videos from Channel A
      ├── 80 videos from Channel B
      └── 1 video from Channel C
```

If Channel A has:

```text
8,000 subscribers
```

and the configured minimum is:

```python
MIN_SUBSCRIBERS = 10_000
```

then:

```text
Resolve Channel A once
        ↓
8,000 subscribers
        ↓
Below threshold
        ↓
Filter all 150 candidates
```

This can save a very large number of individual metadata lookups.

---

# Channel Cache

Channel information is cached in:

```text
youtube_channels_small.json
```

This prevents the scraper from repeatedly retrieving the same channel information.

Cached information can include:

```text
channel ID
uploader
subscriber count
qualification result
fetch timestamp
```

Cache entries can expire so very old information is eventually refreshed.

---

# Video Metadata Processing

Candidates that survive prefiltering are processed concurrently.

A typical configuration is:

```python
PROCESS_WORKERS = 12
```

Each worker can retrieve metadata including:

```text
video ID
title
uploader
upload date
description
channel
subscriber count
```

---

# Subscriber Filtering

Default:

```python
MIN_SUBSCRIBERS = 10_000
```

A video associated with a channel below the threshold is filtered.

Example:

```text
Candidate
   │
   ▼
Channel = 4,300 subscribers
   │
   ▼
Threshold = 10,000
   │
   ▼
Filtered
```

You can change the threshold inside the scraper.

---

# Query Files

## `queries_small.txt`

The included small list currently contains **21 queries**.

It reflects creators and topics I personally like and is intended as:

* A working example
* A test dataset
* A starting point

Create your own list for regular use.

---

## `queries.txt`

The repository also contains a much larger example with approximately **85 queries**.

It includes a broader collection of creators/topics.

This file is intentionally larger than the recommended single-run size.

---

# Recommended Query Count

For normal usage:

```text
10–30 queries per run
```

is recommended.

With:

```python
RESULTS_PER_QUERY = 500
```

the theoretical raw search counts are:

```text
10 × 500 = up to 5,000
20 × 500 = up to 10,000
21 × 500 = up to 10,500
30 × 500 = up to 15,000
85 × 500 = up to 42,500
```

These counts occur before:

* Deduplication
* Subscriber filtering
* Availability checks
* Metadata failures

---

# Real-World Scale

In one development run using the 21-query example list, the scraper accumulated approximately:

```text
9,908 unique candidate IDs
```

That illustrates why even a small-looking query file can create a substantial processing job.

This is also why:

* Channel prefiltering
* SQLite state
* Resume support
* Metadata caching
* Moderate concurrency

matter.

---

# Splitting Large Query Files

The 85-query file is better treated as several batches.

For example:

```text
Batch 1: queries 1–30
Batch 2: queries 31–60
Batch 3: queries 61–85
```

This reduces the likelihood of large bursts of YouTube requests.

---

# Scraper Output

## `youtube_videos_example.txt`

A small example output.

Useful for:

* Testing the importer
* Testing SearchQueries
* Understanding the TXT format

---

## `youtube_videos_small.txt`

The larger human-readable scraper output.

Despite `_small` in the filename, this file can become very large.

The included example can approach **10 MB** because full video descriptions are preserved.

Descriptions can include:

* Timestamps
* Links
* Sponsor information
* Credits
* Social links
* Music credits
* References
* Discord invites
* Patreon links
* Other uploader-provided text

---

# Importer Format Specification

Each record starts with:

```text
================================================================================
```

and contains:

```text
Video uploader: <text>
Date uploaded: <YYYYMMDD>
Name: <title>
Video ID: <11-character YouTube ID>
Video description:
<zero or more description lines>
```

Then another separator begins the next record.

This simple format makes the data:

* Human-readable
* Easy to generate
* Easy to parse
* Easy to search
* Easy to import

Other scripts can generate compatible files if they follow this structure.

---

# SearchQueries.py

Large metadata files should not need to be rendered into thousands of HTML elements merely to search them.

`SearchQueries.py` solves that problem.

Run:

```bash
python SearchQueries.py
```

The program:

```text
youtube_videos_small.txt
         │
         ▼
Parse records once
         │
         ▼
Store parsed records in RAM
         │
         ▼
Interactive search prompt
```

After the initial load, repeated searches operate against the already parsed list.

---

# Interactive Search

Example:

```text
========================================================================
                PERSONAL YOUTUBE DATABASE SEARCH
========================================================================

File:   youtube_videos_small.txt
Videos: 5,367
Loaded: 0.08s

Search >
```

Then:

```text
Search > mattbatwings
```

---

# Search Fields

Search:

```text
all
name
uploader
id
date
description
```

For example:

```text
/field uploader
```

followed by:

```text
"Mumbo Jumbo"
```

---

# AND / OR Search

Default:

```text
/mode and
```

Search:

```text
minecraft redstone
```

requires both terms.

Switch to:

```text
/mode or
```

to require only one.

---

# Date Search

Examples:

```text
/after 2025
/before 202608
```

Dates are stored in:

```text
YYYYMMDD
```

format.

---

# Regex

Enable:

```text
/regex on
```

Example:

```text
^How .* Minecraft
```

---

# One-Shot Search Examples

Search everything:

```bash
python SearchQueries.py minecraft
```

Uploader:

```bash
python SearchQueries.py "Mumbo Jumbo" --field uploader
```

Titles:

```bash
python SearchQueries.py redstone --field name
```

OR:

```bash
python SearchQueries.py mumbo purplers --mode or
```

Count:

```bash
python SearchQueries.py minecraft --count
```

IDs only:

```bash
python SearchQueries.py minecraft --ids-only
```

URLs only:

```bash
python SearchQueries.py minecraft --urls-only
```

Full descriptions:

```bash
python SearchQueries.py primer --description
```

After 2025:

```bash
python SearchQueries.py minecraft --after 2025
```

Unlimited results:

```bash
python SearchQueries.py minecraft --limit 0
```

---

# Why CLI Search Is Fast

Rendering thousands of browser entries can require:

```text
DOM creation
layout
buttons
checkboxes
event handlers
CSS processing
text rendering
browser memory
```

The CLI instead does:

```text
Parse file
   ↓
Compare Python strings
   ↓
Print matching records
```

It is intentionally simple.

---

# Storage Management

## This Is Important

The scraper's metadata is relatively cheap to store.

Downloaded video files are not.

A video might occupy:

```text
100 MB
500 MB
1 GB
2 GB+
```

depending on:

* Duration
* Resolution
* Video bitrate
* Audio bitrate
* Available format

---

# Example Disk Usage

```text
25 videos × 300 MB  = 7.5 GB
100 videos × 500 MB = 50 GB
250 videos × 700 MB = 175 GB
500 videos × 700 MB = 350 GB
```

A large library can therefore consume hundreds of gigabytes.

---

# Delete Old Videos Regularly

Users should regularly review the local library and delete videos they no longer need.

Recommended routine:

1. Open the viewer.
2. Look through older downloads.
3. Delete media you no longer want.
4. Check the size of the `videos/` directory.
5. Keep enough free storage available.

The viewer intentionally does **not** automatically delete your media.

The software should not decide which of your personal files are no longer valuable.

That also means disk-space management is your responsibility.

---

# Prefer the Delete Button

Use:

```text
Delete
```

inside the viewer whenever possible.

This removes:

```text
video.mp4
+
library.json entry
```

together.

Manually deleting only the video file can leave stale metadata behind.

---

# Metadata vs Media

There is an important difference:

```text
Scraper metadata
       │
       ▼
Usually MB

Downloaded media
       │
       ▼
Potentially hundreds of GB
```

A good rule is:

> **Keep lots of metadata. Keep only the videos you actually want.**

That is one of the reasons `SearchQueries.py` exists.

---

# Privacy Deep Dive

The privacy model is a consequence of the architecture rather than simply a written policy.

Most local operations follow:

```text
Your browser
     │
     ▼
127.0.0.1
     │
     ▼
Your Python process
     │
     ▼
Your files
```

There is no project-controlled account server required for ordinary operation.

---

# No Project Ads

The viewer does not contain its own advertising system.

There are no project-inserted:

* Banner ads
* Pre-roll ads
* Mid-roll ads
* Pop-ups
* Sponsored recommendation placements
* Advertising SDKs
* Advertising identifiers

Downloaded media is played as a local media file.

---

# No Project Analytics

The application does not intentionally include analytics platforms such as:

```text
Google Analytics
Google Tag Manager
Meta Pixel
Mixpanel
Amplitude
Hotjar
Segment
```

for reporting your usage to the project author.

---

# No Telemetry

The project does not need to report:

```text
what you watch
what you search locally
how often you open the application
how many videos you store
what videos you delete
how long you watch something
```

to a project backend.

---

# No Project Account

There is no Personal YouTube Viewer user-account system.

You do not need to supply:

* Name
* Email
* Phone number
* Username
* Password
* Billing details
* Profile details

to the application.

---

# No Project Cloud Library

Your library lives in:

```text
videos/
videos/library.json
```

Scraper state lives in local:

```text
TXT
JSON
SQLite
```

files.

---

# No Application Tracking Cookies

The project does not require application tracking cookies or an application login cookie for the local viewer.

The project also does not require importing your browser's YouTube cookies for the normal anonymous workflow.

This does **not** mean YouTube itself never uses cookies or other session mechanisms when its own servers are contacted.

It means this project does not require a project-owned tracking-cookie system.

---

# Verify the Privacy Claims Yourself

This is one of the most important features of an open-source privacy project.

Do not rely only on this README.

Inspect the code.

Relevant files include:

```text
main.py
script.js
index.html
youtube_scraper_improved.py
SearchQueries.py
```

Search for terms such as:

```text
analytics
telemetry
document.cookie
tracking
Google Analytics
fetch(
XMLHttpRequest
requests.
urllib
socket
http
```

Then inspect what each network operation actually does.

You can also inspect:

* Every API route
* Every JSON write
* Every SQLite operation
* Every JavaScript request
* Every external URL
* Every local file access

The privacy claims are intended to be technically auditable.

---

# What Uses the Internet

Not every action is offline.

## Local-only operations

Once required data exists locally, actions such as these can be local:

```text
Browse the cached library
Play a downloaded video
Pause
Seek
Rename
Delete
Search youtube_videos_small.txt with SearchQueries
Inspect cached descriptions
```

---

## Operations that need YouTube

These require external communication:

```text
Search YouTube
Retrieve new YouTube metadata
Download a new video
Retrieve metadata missing from an old entry
```

That request has to reach YouTube because YouTube owns the requested source data.

---

# What the Project Does Not Need

The project does not need a central project service for:

```text
Play
Pause
Rename
Delete
Local search
Local library browsing
Local video seeking
```

There is no intended pipeline like:

```text
Viewer
   │
   ▼
Project analytics server
   │
   ▼
Central behavioural database
```

---

# Privacy Limits

Privacy-focused does not mean anonymous from every party on the internet.

When contacting YouTube:

* YouTube can receive the request.
* Your public IP address may be visible to YouTube.
* Normal network infrastructure still exists.
* Your ISP/network administrator may be able to observe network metadata.
* YouTube may apply its own rate limits or anti-abuse systems.

When using your local machine:

* Other users with access to your operating-system account may be able to inspect downloaded files.
* Your browser may keep normal browser history.
* Malware or compromised software on your computer is outside this project's threat model.

This application is therefore:

> **local-first and privacy-focused, not an anonymity network.**

---

# Security Considerations

## Do Not Expose the Server Publicly

Default:

```python
HOST = "127.0.0.1"
```

This is important.

The viewer includes endpoints capable of:

* Starting downloads
* Renaming files
* Deleting files
* Reading local library metadata

There is no reason to expose those APIs publicly for normal use.

Do not casually change:

```python
HOST = "127.0.0.1"
```

to:

```python
HOST = "0.0.0.0"
```

because that can make the service reachable from other devices on your network.

---

# No Authentication Layer

The local web UI is intended for localhost use.

It should not be treated as an internet-facing authenticated web application.

If you intentionally expose it to a network, you should add appropriate authentication, transport security, and access controls yourself.

---

# Keep Dependencies Updated

Especially:

```bash
pip install -U yt-dlp
```

YouTube changes frequently and older extractor code may stop working.

---

# File Responsibilities

| File                               | Purpose                                                                      |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| `main.py`                          | Local HTTP server, API, downloading, library management, local video serving |
| `index.html`                       | Main viewer interface                                                        |
| `style.css`                        | Viewer styling                                                               |
| `script.js`                        | Frontend library, player, import and download logic                          |
| `youtube_scraper_improved.py`      | Bulk YouTube discovery and metadata processing                               |
| `SearchQueries.py`                 | Fast local CLI metadata search                                               |
| `queries_small.txt`                | Recommended-size example query list                                          |
| `queries.txt`                      | Large example query collection                                               |
| `youtube_videos_example.txt`       | Small scraper-output example                                                 |
| `youtube_videos_small.txt`         | Main human-readable scraper output                                           |
| `youtube_videos_small.json`        | Structured video metadata                                                    |
| `youtube_channels_small.json`      | Channel metadata cache                                                       |
| `youtube_candidates_small.sqlite3` | Candidate processing database                                                |
| `youtube_search_state_small.json`  | Completed query state                                                        |
| `videos/library.json`              | Viewer library metadata                                                      |
| `videos/*.mp4`                     | Actual downloaded media                                                      |

---

# Included vs Generated Files

## Included examples

The repository can include:

```text
queries_small.txt
queries.txt
youtube_videos_example.txt
youtube_videos_small.txt
```

to demonstrate real formats and workflows.

## Generated state

Files such as these may be generated or updated while running the scraper:

```text
youtube_videos_small.json
youtube_channels_small.json
youtube_candidates_small.sqlite3
youtube_search_state_small.json
```

The viewer also creates/updates:

```text
videos/library.json
videos/*.mp4
```

---

# Why TXT, JSON and SQLite

The project intentionally uses different formats for different jobs.

## TXT

```text
youtube_videos_small.txt
```

Advantages:

* Human-readable
* Easy to copy
* Easy to inspect
* Easy to import
* Searchable by CLI
* Simple format

---

## JSON

Used for structured metadata and caches.

Advantages:

* Easy for Python/JavaScript
* Human-readable
* Simple to back up
* Easy to inspect manually

---

## SQLite

Used for scraper candidate state.

Advantages:

* Efficient for thousands of records
* Persistent
* Transactional
* Queryable
* Better suited to processing status than one giant JSON document

The combination is intentional:

```text
TXT      → humans/import
JSON     → metadata/cache
SQLite   → scalable processing state
```

---

# Scraper State and Resume Support

The scraper is designed so an interrupted run does not necessarily lose hours of work.

---

# Search State

Stored in:

```text
youtube_search_state_small.json
```

Completed queries are remembered.

Example:

```text
Query 1 complete
Query 2 complete
Query 3 complete
Ctrl+C
```

Next run:

```text
Query 1 → skip
Query 2 → skip
Query 3 → skip
Query 4 → continue
```

---

# Candidate State

Stored in:

```text
youtube_candidates_small.sqlite3
```

Processing status can distinguish categories such as:

```text
pending
new
filtered
failed
unavailable
auth_required
deferred
invalid
```

depending on the current scraper version and response received.

---

# Periodic Saves

The scraper periodically persists:

* Video metadata
* Channel cache
* Candidate status
* Search state

This reduces lost progress if the process is stopped.

---

# Ctrl+C

If the scraper is interrupted:

```text
Ctrl+C
```

completed work is saved where possible.

Run the scraper again to continue.

---

# Performance and Rate Limiting

The scraper uses worker threads because metadata retrieval is network-bound.

Typical configuration:

```python
SEARCH_WORKERS = 1
PROCESS_WORKERS = 12
```

The idea is not to create as many workers as possible.

The goal is to keep multiple requests progressing while avoiding excessive pressure on YouTube.

---

# Why More Workers Can Be Worse

Too much concurrency can cause:

```text
403 responses
429 responses
temporary throttling
session rate limiting
slower responses
more retries
more failed requests
```

So:

> **More workers does not automatically mean more throughput.**

---

# Filtering Saves Requests

Repeated-channel prefiltering can greatly reduce work.

If:

```text
1 channel
=
200 candidate videos
```

and that channel fails the subscriber threshold, rejecting it once is much cheaper than retrieving full metadata for all 200 videos.

---

# Example Processing Scale

A development run using the 21-query example produced approximately:

```text
9,908 unique candidate IDs
```

That is why a modest query list can still require significant processing.

The optimized scraper uses:

* Channel prefetching
* Channel cache
* SQLite state
* Batched writes
* Multiple metadata workers
* Resume support
* Failure tracking

to keep these workloads practical.

---

# Failure Types

A metadata lookup may fail because a video is:

* Deleted
* Private
* Unavailable
* Age/sign-in restricted
* Temporarily unavailable
* Scheduled for the future
* Rate limited
* A malformed candidate
* A network failure

These situations are not all equivalent.

The scraper attempts to preserve enough status information that temporary failures do not necessarily have to be treated the same as permanently unavailable videos.

---

# Project Structure

```text
PersonalYoutubeViewer/
│
├── README.md
│
├── index.html
├── style.css
├── script.js
├── main.py
│
├── youtube_scraper_improved.py
├── SearchQueries.py
│
├── queries_small.txt
├── queries.txt
│
├── youtube_videos_example.txt
├── youtube_videos_small.txt
│
├── youtube_videos_small.json
├── youtube_channels_small.json
├── youtube_candidates_small.sqlite3
├── youtube_search_state_small.json
│
└── videos/
    ├── library.json
    ├── Video One.mp4
    ├── Video Two.mp4
    └── ...
```

---

# Suggested `.gitignore`

Downloaded media generally should not be committed.

A starting point could be:

```gitignore
# Python
__pycache__/
*.pyc
.venv/

# Downloaded media
videos/*.mp4
videos/*.mkv
videos/*.webm
videos/*.part

# Temporary files
*.tmp

# Scraper state that may be machine-specific
youtube_candidates_small.sqlite3
youtube_candidates_small.sqlite3-shm
youtube_candidates_small.sqlite3-wal
youtube_search_state_small.json
```

Whether you ignore generated JSON/TXT files depends on whether you intentionally want to include examples in the repository.

For example, you may want to keep:

```text
youtube_videos_example.txt
queries_small.txt
queries.txt
```

under version control.

---

# Platform Notes

Development examples in this project commonly use Windows paths and commands.

For example:

```powershell
python main.py
python youtube_scraper_improved.py
python SearchQueries.py
```

or:

```powershell
py main.py
```

The Python code is generally intended to remain portable where its dependencies are supported.

---

# Troubleshooting

## `yt-dlp` suddenly stopped working

Update it:

```bash
pip install -U yt-dlp
```

YouTube changes frequently.

---

## FFmpeg not found

Check:

```bash
ffmpeg -version
```

If the command fails, install FFmpeg and add it to your system `PATH`.

---

## Port 8000 is already in use

Another application may already be listening on:

```text
127.0.0.1:8000
```

Close the conflicting process or change the viewer's port.

---

## Video says unavailable

The video may be:

* Deleted
* Private
* Region restricted
* Removed
* Temporarily unavailable

This does not necessarily indicate a bug in the viewer.

---

## Scraper is rate limited

Large runs can trigger YouTube throttling.

Consider:

* Using fewer queries
* Keeping worker counts conservative
* Waiting before retrying
* Updating `yt-dlp`
* Splitting large query files into batches

---

## `SearchQueries.py` says the file does not exist

By default it expects:

```text
youtube_videos_small.txt
```

in the current working directory.

Specify another file with:

```bash
python SearchQueries.py primer -f youtube_videos_example.txt
```

---

## My `videos/` folder is enormous

Delete old videos.

Use the viewer's:

```text
Delete
```

button so the media file and library entry are removed together.

Do this regularly.

Downloaded media can consume tens or hundreds of gigabytes.

---

## Metadata is missing for an older library entry

Older entries containing only a filename/video ID may need metadata retrieved once.

After retrieval, the expanded information can be cached locally.

---

# Custom Tooling

The project deliberately uses simple data formats.

That means you can write your own tools around:

```text
youtube_videos_small.txt
youtube_videos_small.json
videos/library.json
youtube_candidates_small.sqlite3
```

Possible custom tools include:

* Statistics
* Duplicate detection
* Additional search interfaces
* Exporters
* Playlist builders
* Local recommendation systems
* Storage reports
* Metadata cleanup
* Archive management

You do not have to use the provided HTML interface for every task.

`SearchQueries.py` is itself an example of this philosophy.

---

# Design Philosophy

The project generally prefers:

```text
Local over cloud
Simple files over opaque services
Auditable source over trust
Explicit network activity over hidden telemetry
User-controlled storage over automatic cloud retention
Small tools over unnecessary frameworks
Metadata discovery over downloading everything
```

---

# Roadmap

Possible future improvements include:

* Viewer-side library search
* Sort by uploader
* Sort by download date
* Sort by file size
* Display total library disk usage
* Storage warning thresholds
* Better duplicate detection
* Scheduled/upcoming video classification
* Improved scraper rate-limit recovery
* Additional export formats
* Local thumbnail caching
* Playlist support
* More detailed scraper statistics
* SearchQueries sorting
* SearchQueries result export
* SearchQueries interactive selection
* Optional automatic archival workflows

These are ideas rather than guarantees.

---

# Non-Goals

This project is not intended to be:

* A hosted streaming platform
* A social network
* A replacement for YouTube's entire website
* A public multi-user server
* An advertising blocker
* A Google account manager
* A tool for bypassing subscriptions
* A tool for bypassing paywalls
* A tool for bypassing access controls
* A system for automatically mirroring all of YouTube

The focus is:

> **personal discovery, selective local preservation, local organisation, local search, and local playback.**

---

# Updating yt-dlp

YouTube changes frequently.

If downloads or searches begin failing unexpectedly:

```bash
pip install -U yt-dlp
```

Then restart the application.

---

# Legal

This project is intended for personal media preservation, archiving, offline access, and maintaining access to media that may later become unavailable, removed, restricted, altered, or censored.

It was **not created to bypass advertisements, subscriptions, paywalls, monetisation systems, or other access controls**.

Use this project only for content you are legally permitted to access and store.

This project does not grant rights to videos, music, images, descriptions, or other material obtained from YouTube.

You are responsible for complying with:

* YouTube's applicable terms and policies
* Copyright law
* Local laws
* Content licences
* Access restrictions
* Rights held by content owners

Descriptions, URLs, credits, sponsorship text, and other metadata appearing inside scraper-generated files originate from the corresponding YouTube videos and their uploaders.

Their presence in an output file does not imply endorsement by this project.

---

# Final Summary

## Privacy

```text
No project ads
No project analytics
No project telemetry
No project tracking SDK
No project account
No project cloud library
No application tracking-cookie system
Source code is auditable
```

## Viewer

```text
YouTube video
      ↓
yt-dlp
      ↓
Local media file
      ↓
videos/library.json
      ↓
Local playback
```

## Discovery

```text
queries_small.txt
      ↓
youtube_scraper_improved.py
      ↓
Candidate SQLite database
      ↓
Channel/video filtering
      ↓
youtube_videos_small.txt
```

## Search

```text
youtube_videos_small.txt
      ↓
SearchQueries.py
      ↓
Fast local metadata search
```

## Storage

```text
Metadata
   ↓
Usually MB

Downloaded videos
   ↓
Potentially many GB
   ↓
Delete old videos regularly
```

## Overall Workflow

```text
Discover broadly
      ↓
Keep metadata locally
      ↓
Search locally
      ↓
Download selectively
      ↓
Watch locally
      ↓
Delete old media regularly
```

> **Your local library belongs on your machine, your local searches stay local, and the project's privacy behaviour can be independently checked by reading the source code.**