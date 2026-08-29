const videoIdInput =
    document.getElementById("videoId");

const downloadButton =
    document.getElementById("downloadButton");

const statusElement =
    document.getElementById("status");

const displayId =
    document.getElementById("displayId");

const displayTitle =
    document.getElementById("displayTitle");

const displayUploader =
    document.getElementById("displayUploader");

const displayFile =
    document.getElementById("displayFile");

const videoPlayer =
    document.getElementById("videoPlayer");

const placeholder =
    document.getElementById("placeholder");


function getVideoId() {

    return videoIdInput.value.trim();

}


function validVideoId(id) {

    return /^[A-Za-z0-9_-]{11}$/.test(id);

}


function setStatus(text) {

    statusElement.textContent = text;

}


function playVideo(id, filename) {

    const url =
        `/videos/${encodeURIComponent(filename)}`;

    videoPlayer.src = url;

    videoPlayer.style.display = "block";

    placeholder.style.display = "none";

    videoPlayer.load();

}


async function downloadVideo() {

    const id = getVideoId();

    displayId.textContent = id || "—";


    if (!validVideoId(id)) {

        setStatus(
            "Enter a valid 11-character video ID."
        );

        return;

    }


    downloadButton.disabled = true;

    setStatus("Checking...");

    displayTitle.textContent = "—";
    displayUploader.textContent = "—";
    displayFile.textContent = "—";


    try {

        // Check whether we already have the video.

        const checkResponse =
            await fetch(
                `/api/check/${encodeURIComponent(id)}`
            );

        const checkData =
            await checkResponse.json();


        if (!checkResponse.ok) {

            throw new Error(
                checkData.error ||
                "Could not check video."
            );

        }


        if (checkData.exists) {

            setStatus("Already downloaded");

            displayFile.textContent =
                checkData.filename;

            playVideo(
                id,
                checkData.filename
            );

            return;

        }


        // Tell Python to download it.

        setStatus("Downloading...");


        const response =
            await fetch("/api/download", {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    video_id: id
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


        displayTitle.textContent =
            data.title || "—";

        displayUploader.textContent =
            data.uploader || "—";

        displayFile.textContent =
            data.filename || "—";


        setStatus("Download complete");


        playVideo(
            id,
            data.filename
        );

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


downloadButton.addEventListener(
    "click",
    downloadVideo
);


videoIdInput.addEventListener(
    "keydown",
    event => {

        if (event.key === "Enter") {
            downloadVideo();
        }

    }
);


videoPlayer.addEventListener(
    "loadedmetadata",
    () => {

        setStatus("Video ready");

    }
);


videoPlayer.addEventListener(
    "error",
    () => {

        setStatus(
            "The downloaded video could not be played."
        );

    }
);