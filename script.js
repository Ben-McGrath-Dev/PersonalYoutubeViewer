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


function setStatus(message) {

    statusElement.textContent = message;

}


function validVideoId(id) {

    return /^[A-Za-z0-9_-]{11}$/.test(id);

}


function playVideo(entry) {

    videoIdInput.value = entry.id;

    filenameInput.value =
        entry.filename;

    player.src =
        `/videos/${encodeURIComponent(entry.filename)}`;

    player.style.display = "block";

    placeholder.style.display = "none";

    player.load();

    player.play().catch(() => {});

}


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


    downloadButton.disabled = true;

    setStatus("Starting download...");


    try {

        const response =
            await fetch("/api/download", {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    id: id,
                    filename: filename
                })

            });


        const data =
            await response.json();


        if (!response.ok || !data.success) {

            throw new Error(
                data.error ||
                "Download failed."
            );

        }


        if (data.existing) {

            setStatus(
                "Already downloaded."
            );

        } else {

            setStatus(
                "Download complete."
            );

        }


        playVideo(data.entry);

        await loadLibrary();

    }

    catch (error) {

        console.error(error);

        setStatus(
            `Error: ${error.message}`
        );

    }

    finally {

        downloadButton.disabled = false;

    }

}


async function loadLibrary() {

    try {

        const response =
            await fetch("/api/library");


        if (!response.ok) {

            throw new Error(
                "Could not load library."
            );

        }


        const library =
            await response.json();


        renderLibrary(library);

    }

    catch (error) {

        console.error(error);

        libraryElement.textContent =
            "Could not load library.";

    }

}


function renderLibrary(library) {

    libraryElement.innerHTML = "";


    if (library.length === 0) {

        libraryElement.innerHTML =
            `<div class="empty">
                No videos downloaded yet.
             </div>`;

        return;

    }


    for (const entry of library) {

        const card =
            document.createElement("div");

        card.className = "video-card";


        const information =
            document.createElement("div");

        information.className =
            "video-information";


        const title =
            document.createElement("div");

        title.className = "video-title";

        title.textContent =
            entry.filename;


        const id =
            document.createElement("div");

        id.className = "video-id";

        id.textContent =
            entry.id;


        information.appendChild(title);
        information.appendChild(id);


        const actions =
            document.createElement("div");

        actions.className =
            "video-actions";


        const playButton =
            document.createElement("button");

        playButton.textContent = "Play";

        playButton.onclick = () => {

            playVideo(entry);

            setStatus(
                `Playing ${entry.filename}`
            );

        };


        const renameButton =
            document.createElement("button");

        renameButton.textContent =
            "Rename";

        renameButton.className =
            "secondary";


        renameButton.onclick = async () => {

            await renameVideo(entry);

        };


        const deleteButton =
            document.createElement("button");

        deleteButton.textContent =
            "Delete";

        deleteButton.className =
            "danger";


        deleteButton.onclick = async () => {

            await deleteVideo(entry);

        };


        actions.appendChild(playButton);
        actions.appendChild(renameButton);
        actions.appendChild(deleteButton);


        card.appendChild(information);
        card.appendChild(actions);


        libraryElement.appendChild(card);

    }

}


async function renameVideo(entry) {

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

        setStatus("Renaming...");


        const response =
            await fetch("/api/rename", {

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

            });


        const data =
            await response.json();


        if (!response.ok || !data.success) {

            throw new Error(
                data.error ||
                "Rename failed."
            );

        }


        setStatus("Renamed.");

        await loadLibrary();


        if (
            videoIdInput.value.trim()
            === entry.id
        ) {

            filenameInput.value =
                data.entry.filename;

        }

    }

    catch (error) {

        console.error(error);

        setStatus(
            `Rename failed: ${error.message}`
        );

    }

}


async function deleteVideo(entry) {

    const confirmed =
        confirm(
            `Delete "${entry.filename}"?\n\n` +
            "This only deletes the local copy."
        );


    if (!confirmed) {
        return;
    }


    try {

        setStatus("Deleting...");


        const response =
            await fetch("/api/delete", {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    id: entry.id
                })

            });


        const data =
            await response.json();


        if (!response.ok || !data.success) {

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

            player.removeAttribute("src");

            player.load();

            player.style.display =
                "none";

            placeholder.style.display =
                "flex";

            filenameInput.value = "";

        }


        setStatus("Video deleted.");

        await loadLibrary();

    }

    catch (error) {

        console.error(error);

        setStatus(
            `Delete failed: ${error.message}`
        );

    }

}


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

        if (event.key === "Enter") {
            downloadVideo();
        }

    }
);


filenameInput.addEventListener(
    "keydown",
    event => {

        if (event.key === "Enter") {
            downloadVideo();
        }

    }
);


player.addEventListener(
    "loadedmetadata",
    () => {

        setStatus("Video ready.");

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


loadLibrary();
