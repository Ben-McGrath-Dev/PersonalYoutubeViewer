const videoIdInput =
    document.getElementById("videoId");

const filenameInput =
    document.getElementById("filename");

const downloadButton =
    document.getElementById("downloadButton");

const refreshButton =
    document.getElementById("refreshButton");

const statusElement =
    document.getElementById("status");

const player =
    document.getElementById("player");

const placeholder =
    document.getElementById("placeholder");

const libraryElement =
    document.getElementById("library");


let progressTimer = null;
let activeDownloadId = null;


// ---------------------------------------------------------
// Helpers
// ---------------------------------------------------------

function setStatus(message) {
    statusElement.textContent = message;
}


function validVideoId(id) {
    return /^[A-Za-z0-9_-]{11}$/.test(id);
}


function formatBytes(bytes) {

    if (!bytes || bytes <= 0) {
        return "0 B";
    }

    const units = [
        "B",
        "KiB",
        "MiB",
        "GiB"
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

    if (!bytesPerSecond || bytesPerSecond <= 0) {
        return "—";
    }

    return `${formatBytes(bytesPerSecond)}/s`;
}


function formatEta(seconds) {

    if (
        seconds === null ||
        seconds === undefined ||
        !Number.isFinite(seconds)
    ) {
        return "—";
    }

    seconds = Math.max(
        0,
        Math.floor(seconds)
    );

    const hours =
        Math.floor(seconds / 3600);

    const minutes =
        Math.floor(
            (seconds % 3600) / 60
        );

    const secs =
        seconds % 60;

    if (hours > 0) {

        return `${String(hours).padStart(2, "0")}:` +
               `${String(minutes).padStart(2, "0")}:` +
               `${String(secs).padStart(2, "0")}`;

    }

    return `${String(minutes).padStart(2, "0")}:` +
           `${String(secs).padStart(2, "0")}`;
}


function escapeHtml(value) {

    const div =
        document.createElement("div");

    div.textContent = value;

    return div.innerHTML;
}


// ---------------------------------------------------------
// Progress UI
// ---------------------------------------------------------

function showProgress(job) {

    const percent =
        Number(job.percent) || 0;

    const downloaded =
        Number(job.downloaded) || 0;

    const total =
        Number(job.total) || 0;

    const speed =
        Number(job.speed) || 0;

    const eta =
        formatEta(job.eta);


    let progressText =
        "Downloading...";


    if (job.status === "starting") {

        progressText =
            "Starting download...";

    }

    else if (
        job.status === "processing"
    ) {

        progressText =
            "Processing video...";

    }


    statusElement.innerHTML = `
        <div class="download-progress">
            <div class="progress-title">
                ${escapeHtml(progressText)}
            </div>

            <div class="progress-bar-container">
                <div
                    class="progress-bar"
                    style="width: ${Math.min(
                        100,
                        Math.max(0, percent)
                    )}%"
                ></div>
            </div>

            <div class="progress-info">
                <span>
                    ${percent.toFixed(1)}%
                </span>

                <span>
                    ${
                        total > 0
                        ? `${formatBytes(downloaded)} / ${formatBytes(total)}`
                        : formatBytes(downloaded)
                    }
                </span>

                <span>
                    ${formatSpeed(speed)}
                </span>

                <span>
                    ETA ${eta}
                </span>
            </div>

            <button
                id="cancelDownloadButton"
                class="danger cancel-download"
            >
                Cancel Download
            </button>
        </div>
    `;


    const cancelButton =
        document.getElementById(
            "cancelDownloadButton"
        );


    if (cancelButton) {

        cancelButton.onclick =
            cancelDownload;

    }
}


function showProcessing() {

    statusElement.innerHTML = `
        <div class="download-progress">
            <div class="progress-title">
                Processing video...
            </div>

            <div class="progress-bar-container">
                <div
                    class="progress-bar"
                    style="width: 100%"
                ></div>
            </div>
        </div>
    `;

}


function stopProgressPolling() {

    if (progressTimer !== null) {

        clearInterval(
            progressTimer
        );

        progressTimer = null;

    }

    activeDownloadId = null;

}


function startProgressPolling(videoId) {

    stopProgressPolling();

    activeDownloadId = videoId;

    // Immediately check instead of waiting
    // for the first 500 ms interval.
    pollProgress();


    progressTimer =
        setInterval(
            pollProgress,
            500
        );

}


async function pollProgress() {

    if (!activeDownloadId) {
        return;
    }


    const videoId =
        activeDownloadId;


    try {

        const response =
            await fetch(
                `/api/progress/${encodeURIComponent(
                    videoId
                )}`,
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            throw new Error(
                "Could not get download progress."
            );

        }


        const job =
            await response.json();


        // Make sure another download hasn't
        // replaced this one.
        if (
            activeDownloadId !== videoId
        ) {
            return;
        }


        switch (job.status) {

            case "starting":

            case "downloading":

                downloadButton.disabled =
                    true;

                showProgress(job);

                break;


            case "processing":

                downloadButton.disabled =
                    true;

                showProcessing();

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

                break;


            case "cancelled":

                stopProgressPolling();

                downloadButton.disabled =
                    false;

                setStatus(
                    "Download cancelled."
                );

                await loadLibrary();

                break;


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

                break;


            case "cancelling":

                downloadButton.disabled =
                    true;

                statusElement.innerHTML = `
                    <div class="download-progress">
                        <div class="progress-title">
                            Cancelling download...
                        </div>
                    </div>
                `;

                break;


            default:

                break;
        }

    }

    catch (error) {

        console.error(
            "Progress error:",
            error
        );

        // Don't immediately stop polling for
        // a temporary connection error.
        if (
            activeDownloadId === videoId
        ) {

            setStatus(
                "Waiting for download status..."
            );

        }

    }

}


// ---------------------------------------------------------
// Download
// ---------------------------------------------------------

async function downloadVideo() {

    const id =
        videoIdInput.value.trim();

    const filename =
        filenameInput.value.trim();


    if (!validVideoId(id)) {

        setStatus(
            "Enter a valid 11-character video ID."
        );

        return;

    }


    if (!filename) {

        setStatus(
            "Enter a filename."
        );

        return;

    }


    downloadButton.disabled =
        true;


    setStatus(
        "Starting download..."
    );


    try {

        const response =
            await fetch(
                "/api/download",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        id: id,
                        filename: filename
                    })
                }
            );


        const data =
            await response.json();


        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.error ||
                "Download failed."
            );

        }


        // Already exists in the library.
        if (data.existing) {

            downloadButton.disabled =
                false;

            setStatus(
                "Video already downloaded."
            );


            if (data.entry) {

                playVideo(
                    data.entry
                );

            }


            await loadLibrary();

            return;

        }


        // Another request was already downloading
        // this same video.
        if (
            data.already_downloading
        ) {

            setStatus(
                "Download already in progress..."
            );

            startProgressPolling(
                id
            );

            return;

        }


        // New background download.
        if (data.started) {

            setStatus(
                "Download started..."
            );

            startProgressPolling(
                id
            );

            return;

        }


        throw new Error(
            "Unexpected server response."
        );

    }

    catch (error) {

        console.error(
            "Download error:",
            error
        );

        downloadButton.disabled =
            false;

        setStatus(
            `Error: ${error.message}`
        );

    }

}


// ---------------------------------------------------------
// Cancel download
// ---------------------------------------------------------

async function cancelDownload() {

    if (!activeDownloadId) {
        return;
    }


    const videoId =
        activeDownloadId;


    const button =
        document.getElementById(
            "cancelDownloadButton"
        );


    if (button) {
        button.disabled = true;
    }


    try {

        const response =
            await fetch(
                "/api/cancel",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        id: videoId
                    })
                }
            );


        const data =
            await response.json();


        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.error ||
                "Could not cancel download."
            );

        }


        statusElement.innerHTML = `
            <div class="download-progress">
                <div class="progress-title">
                    Cancelling download...
                </div>
            </div>
        `;

    }

    catch (error) {

        console.error(
            "Cancel error:",
            error
        );


        if (button) {
            button.disabled = false;
        }


        setStatus(
            `Cancel failed: ${error.message}`
        );

    }

}


// ---------------------------------------------------------
// Player
// ---------------------------------------------------------

function playVideo(entry) {

    videoIdInput.value =
        entry.id;

    filenameInput.value =
        entry.filename;


    player.src =
        `/videos/${encodeURIComponent(
            entry.filename
        )}`;


    player.style.display =
        "block";

    placeholder.style.display =
        "none";


    player.load();


    player.play().catch(
        () => {}
    );
}


// ---------------------------------------------------------
// Library
// ---------------------------------------------------------

async function loadLibrary() {

    try {

        const response =
            await fetch(
                "/api/library",
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            throw new Error(
                "Could not load library."
            );

        }


        const library =
            await response.json();


        renderLibrary(
            library
        );

    }

    catch (error) {

        console.error(
            "Library error:",
            error
        );


        libraryElement.textContent =
            "Could not load library.";

    }

}


function renderLibrary(
    library
) {

    libraryElement.innerHTML = "";


    if (library.length === 0) {

        libraryElement.innerHTML =
            `<div class="empty">
                No videos downloaded yet.
             </div>`;

        return;

    }


    for (
        const entry of library
    ) {

        const card =
            document.createElement(
                "div"
            );

        card.className =
            "video-card";


        const information =
            document.createElement(
                "div"
            );

        information.className =
            "video-information";


        const title =
            document.createElement(
                "div"
            );

        title.className =
            "video-title";

        title.textContent =
            entry.filename;


        const id =
            document.createElement(
                "div"
            );

        id.className =
            "video-id";

        id.textContent =
            entry.id;


        information.appendChild(
            title
        );

        information.appendChild(
            id
        );


        const actions =
            document.createElement(
                "div"
            );

        actions.className =
            "video-actions";


        const playButton =
            document.createElement(
                "button"
            );

        playButton.textContent =
            "Play";


        playButton.onclick =
            () => {

                playVideo(
                    entry
                );

                setStatus(
                    `Playing ${entry.filename}`
                );

            };


        const renameButton =
            document.createElement(
                "button"
            );

        renameButton.textContent =
            "Rename";

        renameButton.className =
            "secondary";


        renameButton.onclick =
            async () => {

                await renameVideo(
                    entry
                );

            };


        const deleteButton =
            document.createElement(
                "button"
            );

        deleteButton.textContent =
            "Delete";

        deleteButton.className =
            "danger";


        deleteButton.onclick =
            async () => {

                await deleteVideo(
                    entry
                );

            };


        actions.appendChild(
            playButton
        );

        actions.appendChild(
            renameButton
        );

        actions.appendChild(
            deleteButton
        );


        card.appendChild(
            information
        );

        card.appendChild(
            actions
        );


        libraryElement.appendChild(
            card
        );

    }

}


// ---------------------------------------------------------
// Rename
// ---------------------------------------------------------

async function renameVideo(
    entry
) {

    const newFilename =
        prompt(
            "Enter the new filename:",
            entry.filename
        );


    if (newFilename === null) {
        return;
    }


    if (!newFilename.trim()) {

        setStatus(
            "Filename cannot be empty."
        );

        return;

    }


    try {

        setStatus(
            "Renaming..."
        );


        const response =
            await fetch(
                "/api/rename",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        id: entry.id,

                        filename:
                            newFilename.trim()
                    })
                }
            );


        const data =
            await response.json();


        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.error ||
                "Rename failed."
            );

        }


        setStatus(
            "Renamed."
        );


        await loadLibrary();


        if (
            videoIdInput.value.trim()
            === entry.id
        ) {

            filenameInput.value =
                data.entry.filename;


            // If this video is currently
            // loaded, update its source.
            const wasPlaying =
                !player.paused;


            player.src =
                `/videos/${encodeURIComponent(
                    data.entry.filename
                )}`;


            player.load();


            if (wasPlaying) {

                player.play().catch(
                    () => {}
                );

            }

        }

    }

    catch (error) {

        console.error(
            "Rename error:",
            error
        );


        setStatus(
            `Rename failed: ${error.message}`
        );

    }

}


// ---------------------------------------------------------
// Delete
// ---------------------------------------------------------

async function deleteVideo(
    entry
) {

    const confirmed =
        confirm(
            `Delete "${entry.filename}"?\n\n` +
            "This only deletes the local copy."
        );


    if (!confirmed) {
        return;
    }


    try {

        setStatus(
            "Deleting..."
        );


        const response =
            await fetch(
                "/api/delete",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        id: entry.id
                    })
                }
            );


        const data =
            await response.json();


        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.error ||
                "Delete failed."
            );

        }


        if (
            videoIdInput.value.trim()
            === entry.id
        ) {

            player.pause();

            player.removeAttribute(
                "src"
            );

            player.load();


            player.style.display =
                "none";

            placeholder.style.display =
                "flex";


            filenameInput.value =
                "";

        }


        setStatus(
            "Video deleted."
        );


        await loadLibrary();

    }

    catch (error) {

        console.error(
            "Delete error:",
            error
        );


        setStatus(
            `Delete failed: ${error.message}`
        );

    }

}


// ---------------------------------------------------------
// Events
// ---------------------------------------------------------

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
            event.key === "Enter"
        ) {

            downloadVideo();

        }

    }
);


filenameInput.addEventListener(
    "keydown",
    event => {

        if (
            event.key === "Enter"
        ) {

            downloadVideo();

        }

    }
);


player.addEventListener(
    "loadedmetadata",
    () => {

        setStatus(
            "Video ready."
        );

    }
);


player.addEventListener(
    "error",
    () => {

        setStatus(
            "Could not play the local video."
        );

    }
);


// ---------------------------------------------------------
// Initial load
// ---------------------------------------------------------

loadLibrary();