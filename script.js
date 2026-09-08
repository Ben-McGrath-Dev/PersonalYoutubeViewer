"use strict";


// =========================================================
// DOM
// =========================================================

const videoIdInput = document.getElementById("videoId");
const filenameInput = document.getElementById("filename");
const downloadButton = document.getElementById("downloadButton");
const refreshButton = document.getElementById("refreshButton");
const statusElement = document.getElementById("status");

const videoElement = document.getElementById("player");
const placeholder = document.getElementById("placeholder");

const libraryElement = document.getElementById("library");
const videoInfoPanel = document.getElementById("videoInfoPanel");


// =========================================================
// Configuration
// =========================================================

const API_TIMEOUT = 15000;
const INFO_TIMEOUT = 30000;

const PROGRESS_INTERVAL = 750;
const MAX_PROGRESS_ERRORS = 8;

const VIDEOJS_VERSION = "8.24.0";

const VIDEOJS_CSS =
    `https://unpkg.com/video.js@${VIDEOJS_VERSION}/dist/video-js.min.css`;

const VIDEOJS_JS =
    `https://unpkg.com/video.js@${VIDEOJS_VERSION}/dist/video.min.js`;


// =========================================================
// State
// =========================================================

let activeDownloadId = null;
let progressTimer = null;
let progressRequestRunning = false;
let progressErrors = 0;

let libraryRequestRunning = false;
let infoAbortController = null;

let currentEntry = null;

let mediaPlayer = null;
let usingVideoJs = false;

let importedVideos = [];
let importQueue = [];
let importQueueRunning = false;


// =========================================================
// Helpers
// =========================================================

function setStatus(message) {
    statusElement.textContent =
        String(message || "");
}


function validVideoId(value) {
    return /^[A-Za-z0-9_-]{11}$/.test(
        String(value || "")
    );
}


function normalizeVideoId(value) {
    value =
        String(value || "").trim();

    if (validVideoId(value)) {
        return value;
    }

    try {
        const url =
            new URL(value);

        const hostname =
            url.hostname
                .toLowerCase()
                .replace(/^www\./, "");

        if (hostname === "youtu.be") {
            const id =
                url.pathname
                    .replace(/^\/+/, "")
                    .split("/")[0];

            return validVideoId(id)
                ? id
                : null;
        }

        if (
            hostname === "youtube.com" ||
            hostname.endsWith(".youtube.com")
        ) {
            const queryId =
                url.searchParams.get("v");

            if (validVideoId(queryId)) {
                return queryId;
            }

            const parts =
                url.pathname
                    .split("/")
                    .filter(Boolean);

            if (
                parts.length >= 2 &&
                ["shorts", "embed", "live"].includes(parts[0]) &&
                validVideoId(parts[1])
            ) {
                return parts[1];
            }
        }
    }
    catch {
        // Not a URL.
    }

    return null;
}


function getVideoId() {
    const id =
        normalizeVideoId(
            videoIdInput.value
        );

    if (id) {
        videoIdInput.value = id;
    }

    return id;
}


function sanitizeFilename(value) {
    let filename =
        String(value || "");

    filename =
        filename
            .replace(
                /[<>:"/\\|?*\x00-\x1F]/g,
                "_"
            )
            .replace(/\s+/g, " ")
            .replace(/[. ]+$/g, "")
            .trim();

    if (filename.length > 176) {
        filename =
            filename.slice(0, 176);
    }

    return filename;
}


function filenameFromTitle(title) {
    let filename =
        sanitizeFilename(title);

    if (!filename) {
        filename = "video";
    }

    filename =
        filename.replace(
            /\.[A-Za-z0-9]{2,5}$/i,
            ""
        );

    return `${filename}.mp4`;
}


function formatBytes(bytes) {
    bytes = Number(bytes);

    if (
        !Number.isFinite(bytes) ||
        bytes <= 0
    ) {
        return "0 B";
    }

    const units = [
        "B",
        "KiB",
        "MiB",
        "GiB",
        "TiB"
    ];

    let value = bytes;
    let unit = 0;

    while (
        value >= 1024 &&
        unit < units.length - 1
    ) {
        value /= 1024;
        unit++;
    }

    return `${value.toFixed(
        unit === 0 ? 0 : 1
    )} ${units[unit]}`;
}


function formatSpeed(bytesPerSecond) {
    bytesPerSecond =
        Number(bytesPerSecond);

    if (
        !Number.isFinite(bytesPerSecond) ||
        bytesPerSecond <= 0
    ) {
        return "—";
    }

    return `${formatBytes(
        bytesPerSecond
    )}/s`;
}


function formatTime(seconds) {
    seconds =
        Number(seconds);

    if (
        !Number.isFinite(seconds) ||
        seconds < 0
    ) {
        return "—";
    }

    seconds =
        Math.floor(seconds);

    const hours =
        Math.floor(
            seconds / 3600
        );

    const minutes =
        Math.floor(
            (seconds % 3600) / 60
        );

    const secs =
        seconds % 60;

    if (hours > 0) {
        return (
            `${String(hours).padStart(2, "0")}:` +
            `${String(minutes).padStart(2, "0")}:` +
            `${String(secs).padStart(2, "0")}`
        );
    }

    return (
        `${String(minutes).padStart(2, "0")}:` +
        `${String(secs).padStart(2, "0")}`
    );
}


function createElement(
    tag,
    className = "",
    text = undefined
) {
    const element =
        document.createElement(tag);

    if (className) {
        element.className =
            className;
    }

    if (text !== undefined) {
        element.textContent =
            String(text);
    }

    return element;
}


function mimeTypeFromFilename(filename) {
    const extension =
        String(filename || "")
            .split(".")
            .pop()
            ?.toLowerCase();

    switch (extension) {
        case "webm":
            return "video/webm";

        case "mov":
            return "video/quicktime";

        case "m4v":
            return "video/x-m4v";

        default:
            return "video/mp4";
    }
}


// =========================================================
// API
// =========================================================

async function apiRequest(
    url,
    options = {}
) {
    const {
        timeout = API_TIMEOUT,
        signal: externalSignal,
        ...fetchOptions
    } = options;

    const controller =
        new AbortController();

    let externalAbort = false;

    const handleExternalAbort =
        () => {
            externalAbort = true;
            controller.abort();
        };

    if (externalSignal) {
        if (externalSignal.aborted) {
            controller.abort();
        }
        else {
            externalSignal.addEventListener(
                "abort",
                handleExternalAbort,
                {
                    once: true
                }
            );
        }
    }

    const timeoutId =
        setTimeout(
            () => controller.abort(),
            timeout
        );

    try {
        const response =
            await fetch(
                url,
                {
                    cache: "no-store",
                    ...fetchOptions,
                    signal: controller.signal
                }
            );

        const contentType =
            response.headers.get(
                "content-type"
            ) || "";

        let data = null;

        if (
            contentType.includes(
                "application/json"
            )
        ) {
            try {
                data =
                    await response.json();
            }
            catch {
                data = null;
            }
        }
        else {
            const text =
                await response.text();

            if (text) {
                data = {
                    message: text
                };
            }
        }

        if (!response.ok) {
            throw new Error(
                data?.error ||
                data?.message ||
                `HTTP error ${response.status}`
            );
        }

        return data;
    }
    catch (error) {
        if (
            error.name ===
            "AbortError"
        ) {
            if (
                externalAbort ||
                externalSignal?.aborted
            ) {
                throw new Error(
                    "Request cancelled."
                );
            }

            throw new Error(
                "Request timed out."
            );
        }

        if (
            error instanceof TypeError
        ) {
            throw new Error(
                "Could not connect to the server."
            );
        }

        throw error;
    }
    finally {
        clearTimeout(
            timeoutId
        );

        externalSignal
            ?.removeEventListener(
                "abort",
                handleExternalAbort
            );
    }
}


// =========================================================
// Video.js loader
// =========================================================

function loadStylesheet(url) {
    return new Promise(
        (resolve, reject) => {
            const existing =
                document.querySelector(
                    `link[href="${url}"]`
                );

            if (existing) {
                resolve();
                return;
            }

            const link =
                document.createElement(
                    "link"
                );

            link.rel =
                "stylesheet";

            link.href =
                url;

            link.onload =
                resolve;

            link.onerror =
                () => reject(
                    new Error(
                        "Could not load Video.js CSS."
                    )
                );

            document.head.appendChild(
                link
            );
        }
    );
}


function loadScript(url) {
    return new Promise(
        (resolve, reject) => {
            if (window.videojs) {
                resolve();
                return;
            }

            const existing =
                document.querySelector(
                    `script[src="${url}"]`
                );

            if (existing) {
                existing.addEventListener(
                    "load",
                    resolve,
                    {
                        once: true
                    }
                );

                existing.addEventListener(
                    "error",
                    reject,
                    {
                        once: true
                    }
                );

                return;
            }

            const script =
                document.createElement(
                    "script"
                );

            script.src =
                url;

            script.async =
                true;

            script.onload =
                resolve;

            script.onerror =
                () => reject(
                    new Error(
                        "Could not load Video.js."
                    )
                );

            document.head.appendChild(
                script
            );
        }
    );
}


async function initializePlayer() {
    videoElement.style.display =
        "block";

    videoElement.removeAttribute(
        "controls"
    );

    videoElement.setAttribute(
        "playsinline",
        ""
    );

    videoElement.preload =
        "metadata";

    try {
        await Promise.all([
            loadStylesheet(
                VIDEOJS_CSS
            ),
            loadScript(
                VIDEOJS_JS
            )
        ]);

        if (
            typeof window.videojs !==
            "function"
        ) {
            throw new Error(
                "Video.js failed to initialize."
            );
        }

        videoElement.classList.add(
            "video-js",
            "vjs-big-play-centered"
        );

        mediaPlayer =
            window.videojs(
                videoElement,
                {
                    controls: true,
                    autoplay: false,
                    preload: "metadata",
                    responsive: true,
                    fluid: true,
                    playsinline: true,
                    inactivityTimeout: 2500,

                    playbackRates: [
                        0.5,
                        0.75,
                        1,
                        1.25,
                        1.5,
                        1.75,
                        2
                    ]
                }
            );

        usingVideoJs =
            true;

        mediaPlayer
            .el()
            .style
            .display =
                "none";

        mediaPlayer.on(
            "loadedmetadata",
            () => {
                setStatus(
                    "Video ready."
                );
            }
        );

        mediaPlayer.on(
            "waiting",
            () => {
                if (currentEntry) {
                    setStatus(
                        "Buffering..."
                    );
                }
            }
        );

        mediaPlayer.on(
            "playing",
            () => {
                if (currentEntry) {
                    setStatus(
                        `Playing ${
                            currentEntry.title ||
                            currentEntry.filename
                        }`
                    );
                }
            }
        );

        mediaPlayer.on(
            "error",
            () => {
                const error =
                    mediaPlayer.error();

                setStatus(
                    error?.message
                        ? `Playback error: ${error.message}`
                        : "Could not play this video."
                );
            }
        );
    }
    catch (error) {
        console.warn(
            "Video.js unavailable. Falling back to native player.",
            error
        );

        usingVideoJs =
            false;

        mediaPlayer =
            null;

        videoElement.controls =
            true;

        videoElement.style.display =
            "none";

        videoElement.addEventListener(
            "loadedmetadata",
            () => {
                setStatus(
                    "Video ready."
                );
            }
        );
    }
}


// =========================================================
// Player
// =========================================================

function showPlayer() {
    placeholder.style.display =
        "none";

    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        mediaPlayer
            .el()
            .style
            .display =
                "block";
    }
    else {
        videoElement.style.display =
            "block";
    }
}


function hidePlayer() {
    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        mediaPlayer
            .el()
            .style
            .display =
                "none";
    }
    else {
        videoElement.style.display =
            "none";
    }

    placeholder.style.display =
        "flex";
}


function getPlayerCurrentTime() {
    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        return (
            Number(
                mediaPlayer.currentTime()
            ) || 0
        );
    }

    return (
        Number(
            videoElement.currentTime
        ) || 0
    );
}


function getPlayerDuration() {
    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        return (
            Number(
                mediaPlayer.duration()
            ) || 0
        );
    }

    return (
        Number(
            videoElement.duration
        ) || 0
    );
}


function isPlayerPaused() {
    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        return mediaPlayer.paused();
    }

    return videoElement.paused;
}


function pausePlayer() {
    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        mediaPlayer.pause();
    }
    else {
        videoElement.pause();
    }
}


function safePlay() {
    let result;

    try {
        result =
            (
                usingVideoJs &&
                mediaPlayer
            )
                ? mediaPlayer.play()
                : videoElement.play();
    }
    catch (error) {
        console.debug(
            "Play failed:",
            error
        );

        return;
    }

    if (
        result &&
        typeof result.catch ===
        "function"
    ) {
        result.catch(
            error => {
                if (
                    error.name !==
                    "NotAllowedError"
                ) {
                    console.debug(
                        "Playback failed:",
                        error
                    );
                }
            }
        );
    }
}


function setPlayerTime(seconds) {
    seconds =
        Number(seconds);

    if (
        !Number.isFinite(seconds) ||
        seconds < 0
    ) {
        return;
    }

    const duration =
        getPlayerDuration();

    if (
        duration > 0 &&
        seconds > duration
    ) {
        seconds =
            duration;
    }

    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        mediaPlayer.currentTime(
            seconds
        );
    }
    else {
        videoElement.currentTime =
            seconds;
    }
}


function setVideoSource(
    entry,
    {
        autoplay = true,
        seekTime = null
    } = {}
) {
    const sourceUrl =
        `/videos/${encodeURIComponent(
            entry.filename
        )}`;

    const mimeType =
        mimeTypeFromFilename(
            entry.filename
        );

    currentEntry =
        entry;

    showPlayer();

    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        mediaPlayer.pause();

        mediaPlayer.src({
            src: sourceUrl,
            type: mimeType
        });

        mediaPlayer.one(
            "loadedmetadata",
            () => {
                if (
                    seekTime !== null
                ) {
                    setPlayerTime(
                        seekTime
                    );
                }

                if (autoplay) {
                    safePlay();
                }
            }
        );

        mediaPlayer.load();
    }
    else {
        videoElement.pause();

        videoElement.src =
            sourceUrl;

        videoElement.addEventListener(
            "loadedmetadata",
            () => {
                if (
                    seekTime !== null
                ) {
                    setPlayerTime(
                        seekTime
                    );
                }

                if (autoplay) {
                    safePlay();
                }
            },
            {
                once: true
            }
        );

        videoElement.load();
    }
}


function playVideo(entry) {
    if (
        !entry ||
        !entry.filename
    ) {
        setStatus(
            "Video file is missing."
        );

        return;
    }

    if (entry.id) {
        videoIdInput.value =
            entry.id;
    }

    filenameInput.value =
        entry.filename;

    setVideoSource(
        entry,
        {
            autoplay: true
        }
    );

    if (
        entry.title ||
        entry.uploader ||
        entry.channel ||
        entry.description ||
        entry.thumbnail ||
        entry.duration
    ) {
        showVideoInfo(
            entry
        );
    }
}


function clearPlayer() {
    if (
        usingVideoJs &&
        mediaPlayer
    ) {
        mediaPlayer.pause();
        mediaPlayer.reset();
    }
    else {
        videoElement.pause();

        videoElement.removeAttribute(
            "src"
        );

        videoElement.load();
    }

    currentEntry =
        null;

    hidePlayer();
}


// =========================================================
// Info
// =========================================================

async function loadVideoInfo(
    videoId,
    existingEntry = null
) {
    if (
        existingEntry &&
        (
            existingEntry.title ||
            existingEntry.uploader ||
            existingEntry.channel ||
            existingEntry.description ||
            existingEntry.thumbnail ||
            existingEntry.duration
        )
    ) {
        showVideoInfo(
            existingEntry
        );

        setStatus(
            "Showing saved video information."
        );

        return existingEntry;
    }

    if (!validVideoId(videoId)) {
        setStatus(
            "Invalid video ID."
        );

        return null;
    }

    if (infoAbortController) {
        infoAbortController.abort();
    }

    const controller =
        new AbortController();

    infoAbortController =
        controller;

    setStatus(
        "Loading missing video information..."
    );

    try {
        const data =
            await apiRequest(
                `/api/info/${encodeURIComponent(
                    videoId
                )}`,
                {
                    timeout:
                        INFO_TIMEOUT,

                    signal:
                        controller.signal
                }
            );

        if (!data?.entry) {
            throw new Error(
                "No video information was returned."
            );
        }

        showVideoInfo(
            data.entry
        );

        setStatus(
            data.cached
                ? "Showing saved video information."
                : "Video information downloaded and saved."
        );

        return data.entry;
    }
    catch (error) {
        if (
            error.message !==
            "Request cancelled."
        ) {
            console.error(
                error
            );

            setStatus(
                `Info failed: ${error.message}`
            );
        }

        return null;
    }
    finally {
        if (
            infoAbortController ===
            controller
        ) {
            infoAbortController =
                null;
        }
    }
}


function showVideoInfo(entry) {
    if (!videoInfoPanel) {
        return;
    }

    videoInfoPanel.replaceChildren();

    const header =
        createElement(
            "div",
            "info-header"
        );

    if (entry.thumbnail) {
        const thumbnail =
            document.createElement(
                "img"
            );

        thumbnail.className =
            "video-thumbnail";

        thumbnail.alt =
            "";

        thumbnail.decoding =
            "async";

        thumbnail.loading =
            "eager";

        thumbnail.referrerPolicy =
            "no-referrer";

        header.appendChild(
            thumbnail
        );

        thumbnail.src =
            entry.thumbnail;

        thumbnail.addEventListener(
            "error",
            () => {
                thumbnail.remove();
            },
            {
                once: true
            }
        );
    }

    const summary =
        createElement(
            "div",
            "info-summary"
        );

    summary.appendChild(
        createElement(
            "div",
            "info-title",
            entry.title ||
            entry.filename ||
            "Unknown video"
        )
    );

    const uploader =
        entry.uploader ||
        entry.channel;

    if (uploader) {
        summary.appendChild(
            createElement(
                "div",
                "info-uploader",
                uploader
            )
        );
    }

    if (
        Number(entry.duration) > 0
    ) {
        summary.appendChild(
            createElement(
                "div",
                "info-duration",
                formatTime(
                    entry.duration
                )
            )
        );
    }

    if (entry.upload_date) {
        summary.appendChild(
            createElement(
                "div",
                "info-upload-date",
                `Uploaded: ${entry.upload_date}`
            )
        );
    }

    header.appendChild(
        summary
    );

    videoInfoPanel.appendChild(
        header
    );

    if (entry.description) {
        videoInfoPanel.appendChild(
            createElement(
                "div",
                "info-description",
                entry.description
            )
        );
    }

    videoInfoPanel.hidden =
        false;
}


// =========================================================
// Progress UI
// =========================================================

function showProgress(job) {
    const percent =
        Math.min(
            100,
            Math.max(
                0,
                Number(job.percent) || 0
            )
        );

    const downloaded =
        Number(job.downloaded) || 0;

    const total =
        Number(job.total) || 0;

    const speed =
        Number(job.speed) || 0;

    statusElement.replaceChildren();

    const wrapper =
        createElement(
            "div",
            "download-progress"
        );

    let text =
        "Downloading...";

    if (
        job.status ===
        "starting"
    ) {
        text =
            "Starting download...";
    }
    else if (
        job.status ===
        "processing"
    ) {
        text =
            "Processing video...";
    }
    else if (
        job.status ===
        "cancelling"
    ) {
        text =
            "Cancelling download...";
    }

    wrapper.appendChild(
        createElement(
            "div",
            "progress-title",
            text
        )
    );

    const barContainer =
        createElement(
            "div",
            "progress-bar-container"
        );

    const bar =
        createElement(
            "div",
            "progress-bar"
        );

    if (
        job.status === "processing" ||
        job.status === "cancelling"
    ) {
        bar.classList.add(
            "progress-indeterminate"
        );
    }
    else {
        bar.style.width =
            `${percent}%`;
    }

    barContainer.appendChild(
        bar
    );

    wrapper.appendChild(
        barContainer
    );

    if (
        job.status === "starting" ||
        job.status === "downloading"
    ) {
        const info =
            createElement(
                "div",
                "progress-info"
            );

        info.append(
            createElement(
                "span",
                "",
                `${percent.toFixed(1)}%`
            ),

            createElement(
                "span",
                "",
                total > 0
                    ? `${formatBytes(downloaded)} / ${formatBytes(total)}`
                    : formatBytes(downloaded)
            ),

            createElement(
                "span",
                "",
                formatSpeed(speed)
            ),

            createElement(
                "span",
                "",
                `ETA ${formatTime(job.eta)}`
            )
        );

        wrapper.appendChild(
            info
        );
    }

    if (
        job.status !== "processing" &&
        job.status !== "cancelling"
    ) {
        const cancelButton =
            createElement(
                "button",
                "danger cancel-download",
                "Cancel Download"
            );

        cancelButton.type =
            "button";

        cancelButton.addEventListener(
            "click",
            cancelDownload
        );

        wrapper.appendChild(
            cancelButton
        );
    }

    statusElement.appendChild(
        wrapper
    );
}


// =========================================================
// Progress polling
// =========================================================

function stopProgressPolling() {
    if (
        progressTimer !== null
    ) {
        clearTimeout(
            progressTimer
        );

        progressTimer =
            null;
    }

    activeDownloadId =
        null;

    progressErrors =
        0;

    progressRequestRunning =
        false;
}


function scheduleProgressPoll(
    delay = PROGRESS_INTERVAL
) {
    if (!activeDownloadId) {
        return;
    }

    if (
        progressTimer !== null
    ) {
        clearTimeout(
            progressTimer
        );
    }

    progressTimer =
        setTimeout(
            () => {
                progressTimer =
                    null;

                pollProgress();
            },
            delay
        );
}


function startProgressPolling(
    videoId
) {
    stopProgressPolling();

    activeDownloadId =
        videoId;

    progressErrors =
        0;

    scheduleProgressPoll(0);
}


async function pollProgress() {
    if (
        !activeDownloadId ||
        progressRequestRunning
    ) {
        return;
    }

    const videoId =
        activeDownloadId;

    progressRequestRunning =
        true;

    let nextDelay =
        null;

    try {
        const job =
            await apiRequest(
                `/api/progress/${encodeURIComponent(
                    videoId
                )}`,
                {
                    timeout: 10000
                }
            );

        if (
            activeDownloadId !==
            videoId
        ) {
            return;
        }

        progressErrors =
            0;

        switch (job.status) {
            case "starting":
            case "downloading":
            case "processing":
            case "cancelling":
                downloadButton.disabled =
                    true;

                showProgress(
                    job
                );

                nextDelay =
                    PROGRESS_INTERVAL;

                break;


            case "completed":
                stopProgressPolling();

                downloadButton.disabled =
                    false;

                setStatus(
                    "Download complete."
                );

                if (job.entry) {
                    playVideo(
                        job.entry
                    );
                }

                await loadLibrary();

                await continueImportQueue();

                return;


            case "cancelled":
                stopProgressPolling();

                downloadButton.disabled =
                    false;

                setStatus(
                    "Download cancelled."
                );

                await loadLibrary();

                importQueue =
                    [];

                importQueueRunning =
                    false;

                return;


            case "error":
                stopProgressPolling();

                downloadButton.disabled =
                    false;

                setStatus(
                    `Download failed: ${
                        job.error ||
                        "Unknown error."
                    }`
                );

                await loadLibrary();

                await continueImportQueue();

                return;


            case "not_found":
                throw new Error(
                    "Download job not found."
                );


            default:
                throw new Error(
                    `Unknown download status: ${job.status}`
                );
        }
    }
    catch (error) {
        console.error(
            error
        );

        progressErrors++;

        if (
            progressErrors >=
            MAX_PROGRESS_ERRORS
        ) {
            stopProgressPolling();

            downloadButton.disabled =
                false;

            setStatus(
                `Lost download status: ${error.message}`
            );

            return;
        }

        nextDelay =
            Math.min(
                5000,
                PROGRESS_INTERVAL *
                (
                    progressErrors +
                    1
                )
            );
    }
    finally {
        progressRequestRunning =
            false;

        if (
            nextDelay !== null &&
            activeDownloadId ===
            videoId
        ) {
            scheduleProgressPoll(
                nextDelay
            );
        }
    }
}


// =========================================================
// Download
// =========================================================

async function startDownload(
    videoId,
    filename,
    {
        autoplayExisting = true
    } = {}
) {
    filename =
        sanitizeFilename(
            filename
        );

    filename =
        filename.replace(
            /\.[A-Za-z0-9]{2,5}$/i,
            ""
        );

    filename +=
        ".mp4";

    const data =
        await apiRequest(
            "/api/download",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify({
                        id:
                            videoId,

                        filename
                    }),

                timeout:
                    30000
            }
        );

    if (!data?.success) {
        throw new Error(
            data?.error ||
            "Could not start download."
        );
    }

    if (data.existing) {
        if (
            autoplayExisting &&
            data.entry
        ) {
            playVideo(
                data.entry
            );
        }

        return {
            existing: true,
            entry: data.entry
        };
    }

    if (
        data.started ||
        data.already_downloading
    ) {
        startProgressPolling(
            videoId
        );

        return {
            started: true
        };
    }

    throw new Error(
        "Unexpected server response."
    );
}


async function downloadVideo() {
    if (activeDownloadId) {
        setStatus(
            "A download is already active."
        );

        return;
    }

    const videoId =
        getVideoId();

    if (!videoId) {
        setStatus(
            "Enter a valid YouTube video ID or URL."
        );

        return;
    }

    let filename =
        filenameInput.value.trim();

    if (!filename) {
        const info =
            await loadVideoInfo(
                videoId
            );

        if (info?.title) {
            filename =
                filenameFromTitle(
                    info.title
                );
        }
    }

    if (!filename) {
        setStatus(
            "Enter a filename."
        );

        return;
    }

    filename =
        filenameFromTitle(
            filename
                .replace(
                    /\.mp4$/i,
                    ""
                )
        );

    filenameInput.value =
        filename;

    downloadButton.disabled =
        true;

    setStatus(
        "Starting download..."
    );

    try {
        const result =
            await startDownload(
                videoId,
                filename
            );

        if (result.existing) {
            downloadButton.disabled =
                false;

            setStatus(
                "Video already downloaded."
            );

            await loadLibrary();
        }
    }
    catch (error) {
        console.error(
            error
        );

        downloadButton.disabled =
            false;

        setStatus(
            `Download failed: ${error.message}`
        );
    }
}


// =========================================================
// Cancel
// =========================================================

async function cancelDownload() {
    if (!activeDownloadId) {
        return;
    }

    const videoId =
        activeDownloadId;

    showProgress({
        status:
            "cancelling"
    });

    try {
        await apiRequest(
            "/api/cancel",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify({
                        id:
                            videoId
                    })
            }
        );

        scheduleProgressPoll(
            250
        );
    }
    catch (error) {
        setStatus(
            `Cancel failed: ${error.message}`
        );

        scheduleProgressPoll();
    }
}


// =========================================================
// Library
// =========================================================

async function loadLibrary() {
    if (libraryRequestRunning) {
        return;
    }

    libraryRequestRunning =
        true;

    refreshButton.disabled =
        true;

    try {
        const data =
            await apiRequest(
                "/api/library"
            );

        if (!Array.isArray(data)) {
            throw new Error(
                "Invalid library response."
            );
        }

        renderLibrary(
            data
        );
    }
    catch (error) {
        libraryElement.replaceChildren(
            createElement(
                "div",
                "empty",
                `Could not load library: ${error.message}`
            )
        );
    }
    finally {
        libraryRequestRunning =
            false;

        refreshButton.disabled =
            false;
    }
}


function renderLibrary(library) {
    libraryElement.replaceChildren();

    if (!library.length) {
        libraryElement.appendChild(
            createElement(
                "div",
                "empty",
                "No videos downloaded yet."
            )
        );

        return;
    }

    for (const entry of library) {
        const card =
            createElement(
                "div",
                "video-card"
            );

        const information =
            createElement(
                "div",
                "video-information"
            );

        const title =
            createElement(
                "div",
                "video-title",
                entry.title ||
                entry.filename
            );

        information.appendChild(
            title
        );

        const uploader =
            entry.uploader ||
            entry.channel;

        if (uploader) {
            information.appendChild(
                createElement(
                    "div",
                    "video-uploader",
                    uploader
                )
            );
        }

        const details = [];

        if (entry.id) {
            details.push(
                entry.id
            );
        }

        if (
            Number(entry.duration) > 0
        ) {
            details.push(
                formatTime(
                    entry.duration
                )
            );
        }

        if (details.length) {
            information.appendChild(
                createElement(
                    "div",
                    "video-id",
                    details.join(" • ")
                )
            );
        }

        const actions =
            createElement(
                "div",
                "video-actions"
            );

        const playButton =
            createElement(
                "button",
                "",
                "Play"
            );

        const renameButton =
            createElement(
                "button",
                "secondary",
                "Rename"
            );

        const infoButton =
            createElement(
                "button",
                "secondary",
                "Info"
            );

        const deleteButton =
            createElement(
                "button",
                "danger",
                "Delete"
            );

        playButton.type =
            "button";

        renameButton.type =
            "button";

        infoButton.type =
            "button";

        deleteButton.type =
            "button";

        playButton.addEventListener(
            "click",
            () => {
                playVideo(
                    entry
                );
            }
        );

        renameButton.addEventListener(
            "click",
            async () => {
                await renameVideo(
                    entry
                );
            }
        );

        infoButton.addEventListener(
            "click",
            async () => {
                const hasMetadata =
                    Boolean(
                        entry.title ||
                        entry.uploader ||
                        entry.channel ||
                        entry.description ||
                        entry.thumbnail ||
                        entry.duration
                    );

                if (hasMetadata) {
                    showVideoInfo(
                        entry
                    );

                    setStatus(
                        "Showing saved video information."
                    );

                    return;
                }

                infoButton.disabled =
                    true;

                try {
                    const info =
                        await loadVideoInfo(
                            entry.id
                        );

                    if (info) {
                        loadLibrary();
                    }
                }
                finally {
                    if (
                        infoButton.isConnected
                    ) {
                        infoButton.disabled =
                            false;
                    }
                }
            }
        );

        deleteButton.addEventListener(
            "click",
            async () => {
                await deleteVideo(
                    entry
                );
            }
        );

        actions.append(
            playButton,
            renameButton,
            infoButton,
            deleteButton
        );

        card.append(
            information,
            actions
        );

        libraryElement.appendChild(
            card
        );
    }
}


// =========================================================
// Rename
// =========================================================

async function renameVideo(entry) {
    const value =
        prompt(
            "Enter the new filename:",
            entry.filename
        );

    if (value === null) {
        return;
    }

    const newFilename =
        filenameFromTitle(
            value.replace(
                /\.mp4$/i,
                ""
            )
        );

    if (
        newFilename ===
        entry.filename
    ) {
        return;
    }

    try {
        const wasCurrent =
            currentEntry?.id ===
            entry.id;

        const currentTime =
            wasCurrent
                ? getPlayerCurrentTime()
                : 0;

        const wasPlaying =
            wasCurrent
                ? !isPlayerPaused()
                : false;

        const data =
            await apiRequest(
                "/api/rename",
                {
                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            id:
                                entry.id,

                            filename:
                                newFilename
                        })
                }
            );

        if (
            wasCurrent &&
            data.entry
        ) {
            setVideoSource(
                data.entry,
                {
                    autoplay:
                        wasPlaying,

                    seekTime:
                        currentTime
                }
            );
        }

        setStatus(
            "Renamed."
        );

        await loadLibrary();
    }
    catch (error) {
        setStatus(
            `Rename failed: ${error.message}`
        );
    }
}


// =========================================================
// Delete
// =========================================================

async function deleteVideo(entry) {
    const confirmed =
        confirm(
            `Delete "${entry.title || entry.filename}"?\n\n` +
            "This deletes the local copy."
        );

    if (!confirmed) {
        return;
    }

    try {
        await apiRequest(
            "/api/delete",
            {
                method:
                    "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body:
                    JSON.stringify({
                        id:
                            entry.id
                    })
            }
        );

        if (
            currentEntry?.id ===
            entry.id
        ) {
            clearPlayer();
        }

        setStatus(
            "Video deleted."
        );

        await loadLibrary();
    }
    catch (error) {
        setStatus(
            `Delete failed: ${error.message}`
        );
    }
}


// =========================================================
// Import UI
// =========================================================

function createImportSection() {
    if (
        document.getElementById(
            "importVideoSection"
        )
    ) {
        return;
    }

    const section =
        createElement(
            "section",
            "import-section"
        );

    section.id =
        "importVideoSection";

    const heading =
        createElement(
            "h2",
            "",
            "Import Video List"
        );

    const description =
        createElement(
            "p",
            "library-description",
            "Paste a yt-dlp style video list, select the videos you want, then download them as a queue."
        );

    const textarea =
        document.createElement(
            "textarea"
        );

    textarea.id =
        "importText";

    textarea.rows =
        12;

    textarea.placeholder =
        "Paste your video list here...";

    textarea.style.width =
        "100%";

    textarea.style.boxSizing =
        "border-box";

    textarea.style.resize =
        "vertical";

    const controls =
        createElement(
            "div",
            "video-actions"
        );

    const parseButton =
        createElement(
            "button",
            "",
            "Read Video List"
        );

    const selectAllButton =
        createElement(
            "button",
            "secondary",
            "Select All"
        );

    const clearButton =
        createElement(
            "button",
            "secondary",
            "Clear"
        );

    const downloadSelectedButton =
        createElement(
            "button",
            "",
            "Download Selected"
        );

    parseButton.type =
        "button";

    selectAllButton.type =
        "button";

    clearButton.type =
        "button";

    downloadSelectedButton.type =
        "button";

    controls.append(
        parseButton,
        selectAllButton,
        clearButton,
        downloadSelectedButton
    );

    const results =
        createElement(
            "div",
            "import-results"
        );

    results.id =
        "importResults";

    parseButton.addEventListener(
        "click",
        parseImportedVideoList
    );

    selectAllButton.addEventListener(
        "click",
        () => {
            results
                .querySelectorAll(
                    'input[type="checkbox"]'
                )
                .forEach(
                    checkbox => {
                        checkbox.checked =
                            true;
                    }
                );
        }
    );

    clearButton.addEventListener(
        "click",
        () => {
            textarea.value =
                "";

            importedVideos =
                [];

            results.replaceChildren();

            setStatus(
                "Import list cleared."
            );
        }
    );

    downloadSelectedButton.addEventListener(
        "click",
        queueSelectedImportedVideos
    );

    section.append(
        heading,
        description,
        textarea,
        controls,
        results
    );

    const librarySection =
        libraryElement.closest(
            "section"
        );

    if (librarySection) {
        librarySection.parentNode.insertBefore(
            section,
            librarySection
        );
    }
    else {
        document.querySelector(
            "main"
        )?.appendChild(
            section
        );
    }
}


async function parseImportedVideoList() {
    const textarea =
        document.getElementById(
            "importText"
        );

    const text =
        textarea.value.trim();

    if (!text) {
        setStatus(
            "Paste a video list first."
        );

        return;
    }

    try {
        setStatus(
            "Reading video list..."
        );

        const data =
            await apiRequest(
                "/api/import-list",
                {
                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            text
                        }),

                    timeout:
                        30000
                }
            );

        importedVideos =
            data.videos || [];

        renderImportedVideos(
            importedVideos
        );

        setStatus(
            `Found ${importedVideos.length} videos.`
        );
    }
    catch (error) {
        setStatus(
            `Import failed: ${error.message}`
        );
    }
}


function renderImportedVideos(videos) {
    const results =
        document.getElementById(
            "importResults"
        );

    results.replaceChildren();

    if (!videos.length) {
        results.appendChild(
            createElement(
                "div",
                "empty",
                "No valid videos found."
            )
        );

        return;
    }

    videos.forEach(
        (video, index) => {
            const row =
                createElement(
                    "div",
                    "video-card import-video"
                );

            const selector =
                document.createElement(
                    "input"
                );

            selector.type =
                "checkbox";

            selector.checked =
                true;

            selector.dataset.index =
                String(index);

            selector.style.marginRight =
                "12px";

            const information =
                createElement(
                    "div",
                    "video-information"
                );

            information.appendChild(
                createElement(
                    "div",
                    "video-title",
                    video.title ||
                    video.id
                )
            );

            const details = [
                video.uploader ||
                "Unknown uploader",
                video.id
            ];

            if (video.upload_date) {
                details.push(
                    video.upload_date
                );
            }

            information.appendChild(
                createElement(
                    "div",
                    "video-id",
                    details.join(" • ")
                )
            );

            const downloadButton =
                createElement(
                    "button",
                    "",
                    "Download"
                );

            downloadButton.type =
                "button";

            downloadButton.addEventListener(
                "click",
                () => {
                    queueImportedVideos([
                        video
                    ]);
                }
            );

            row.append(
                selector,
                information,
                downloadButton
            );

            results.appendChild(
                row
            );
        }
    );
}


function queueSelectedImportedVideos() {
    const results =
        document.getElementById(
            "importResults"
        );

    const selected =
        [];

    results
        .querySelectorAll(
            'input[type="checkbox"]:checked'
        )
        .forEach(
            checkbox => {
                const index =
                    Number(
                        checkbox.dataset.index
                    );

                const video =
                    importedVideos[index];

                if (video) {
                    selected.push(
                        video
                    );
                }
            }
        );

    if (!selected.length) {
        setStatus(
            "No imported videos selected."
        );

        return;
    }

    queueImportedVideos(
        selected
    );
}


function queueImportedVideos(videos) {
    if (
        importQueueRunning ||
        activeDownloadId
    ) {
        setStatus(
            "A download or import queue is already running."
        );

        return;
    }

    importQueue =
        [...videos];

    importQueueRunning =
        true;

    continueImportQueue();
}


async function continueImportQueue() {
    if (!importQueueRunning) {
        return;
    }

    if (activeDownloadId) {
        return;
    }

    if (!importQueue.length) {
        importQueueRunning =
            false;

        setStatus(
            "Import queue complete."
        );

        await loadLibrary();

        return;
    }

    const video =
        importQueue.shift();

    const filename =
        filenameFromTitle(
            video.title ||
            video.id
        );

    videoIdInput.value =
        video.id;

    filenameInput.value =
        filename;

    setStatus(
        `Starting ${video.title || video.id}... ` +
        `${importQueue.length} remaining after this.`
    );

    try {
        const result =
            await startDownload(
                video.id,
                filename,
                {
                    autoplayExisting:
                        false
                }
            );

        if (result.existing) {
            setStatus(
                `"${video.title}" already exists. Continuing...`
            );

            setTimeout(
                continueImportQueue,
                150
            );
        }
    }
    catch (error) {
        console.error(
            error
        );

        setStatus(
            `Could not download "${video.title}": ${error.message}`
        );

        setTimeout(
            continueImportQueue,
            500
        );
    }
}


// =========================================================
// Keyboard controls
// =========================================================

document.addEventListener(
    "keydown",
    event => {
        if (
            event.target instanceof HTMLInputElement ||
            event.target instanceof HTMLTextAreaElement
        ) {
            return;
        }

        if (!currentEntry) {
            return;
        }

        switch (
            event.key.toLowerCase()
        ) {
            case " ":
            case "k":
                event.preventDefault();

                if (isPlayerPaused()) {
                    safePlay();
                }
                else {
                    pausePlayer();
                }

                break;


            case "j":
            case "arrowleft":
                event.preventDefault();

                setPlayerTime(
                    Math.max(
                        0,
                        getPlayerCurrentTime() -
                        10
                    )
                );

                break;


            case "l":
            case "arrowright":
                event.preventDefault();

                setPlayerTime(
                    getPlayerCurrentTime() +
                    10
                );

                break;


            case "home":
                event.preventDefault();

                setPlayerTime(
                    0
                );

                break;


            case "end":
                event.preventDefault();

                setPlayerTime(
                    getPlayerDuration()
                );

                break;
        }
    }
);


// =========================================================
// Events
// =========================================================

downloadButton.addEventListener(
    "click",
    downloadVideo
);


refreshButton.addEventListener(
    "click",
    loadLibrary
);


videoIdInput.addEventListener(
    "keydown",
    event => {
        if (
            event.key ===
            "Enter"
        ) {
            event.preventDefault();

            downloadVideo();
        }
    }
);


filenameInput.addEventListener(
    "keydown",
    event => {
        if (
            event.key ===
            "Enter"
        ) {
            event.preventDefault();

            downloadVideo();
        }
    }
);


videoIdInput.addEventListener(
    "paste",
    () => {
        setTimeout(
            () => {
                const id =
                    getVideoId();

                if (id) {
                    setStatus(
                        "YouTube video detected."
                    );
                }
            },
            0
        );
    }
);


window.addEventListener(
    "beforeunload",
    () => {
        stopProgressPolling();

        infoAbortController
            ?.abort();

        if (
            usingVideoJs &&
            mediaPlayer
        ) {
            mediaPlayer.dispose();
        }
    }
);


// =========================================================
// Startup
// =========================================================

async function startApplication() {
    createImportSection();

    await initializePlayer();

    await loadLibrary();

    setStatus(
        usingVideoJs
            ? "Ready — Video.js player loaded."
            : "Ready — native player fallback."
    );
}


startApplication();