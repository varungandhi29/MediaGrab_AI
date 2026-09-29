import { useEffect, useRef, useState } from "react";

/**
 * VideoPlayer.jsx  --  drop-in player for MediaGrab AI
 *
 * Usage:
 *   <VideoPlayer jobId={job.id} />
 *
 * Rules this component follows (each one fixes a bug you hit):
 *  1. PLAY uses <video src=".../play">  -> never navigates, never downloads.
 *  2. DOWNLOAD is a separate <a href=".../download" download> button.
 *  3. video.play() is only called inside a tap/click handler.
 *  4. Starts muted (browsers allow muted playback), with an unmute button.
 *  5. play() errors are handled by name, so a valid link never shows a false "blocked".
 */

const API_BASE = ""; // e.g. "https://your-domain.com" if the API is on another origin

export default function VideoPlayer({ jobId }) {
  const videoRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [message, setMessage] = useState("");
  const [fatal, setFatal] = useState(false);

  const playUrl = `${API_BASE}/api/media/${jobId}/play`;
  const downloadUrl = `${API_BASE}/api/media/${jobId}/download`;

  // Clean up when the player unmounts or the job changes
  useEffect(() => {
    setPlaying(false);
    setMessage("");
    setFatal(false);
    const v = videoRef.current;
    return () => {
      if (v) {
        try {
          v.pause();
        } catch (e) {}
      }
    };
  }, [jobId]);

  // Called ONLY from a click/tap. No await before play().
  const handlePlayClick = async () => {
    const v = videoRef.current;
    if (!v) return;
    setMessage("");
    v.muted = true; // muted playback is always allowed
    setMuted(true);
    try {
      await v.play();
      setPlaying(true);
    } catch (err) {
      handlePlayError(err);
    }
  };

  const handlePlayError = (err) => {
    const name = err && err.name;
    if (name === "NotAllowedError") {
      // Normal state: the user just needs to tap again. Not an error.
      setPlaying(false);
      setMessage("Tap the play button to start.");
    } else if (name === "NotSupportedError") {
      setFatal(true);
      setMessage(
        "This video format can't be played in your browser. You can still download it."
      );
    } else if (name === "AbortError") {
      // Source reloaded while starting. Retry once.
      const v = videoRef.current;
      if (v) v.play().then(() => setPlaying(true)).catch(() => {});
    } else {
      setFatal(true);
      setMessage("Playback failed. You can still download the video.");
      console.error("play() failed:", err);
    }
  };

  // Errors that happen while loading / decoding
  const handleVideoError = () => {
    const v = videoRef.current;
    const code = v && v.error ? v.error.code : 0;
    setPlaying(false);
    setFatal(true);
    if (code === 4) {
      setMessage("This video isn't available or its format isn't supported. Try downloading it.");
    } else if (code === 3) {
      setMessage("The video couldn't be decoded in your browser. Try downloading it.");
    } else if (code === 2) {
      setMessage("Network problem while loading the video. Check your connection and retry.");
    } else {
      setMessage("The video couldn't be loaded. Try downloading it.");
    }
    console.error("video error code:", code);
  };

  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  };

  const retry = () => {
    const v = videoRef.current;
    if (!v) return;
    setFatal(false);
    setMessage("");
    v.load();
  };

  return (
    <div className="w-full max-w-3xl mx-auto">
      <div className="relative bg-black rounded-lg overflow-hidden">
        <video
          ref={videoRef}
          src={playUrl}
          className="w-full h-auto max-h-[70vh]"
          controls
          playsInline
          webkit-playsinline="true"
          preload="metadata"
          muted
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onError={handleVideoError}
        />

        {!playing && !fatal && (
          <button
            type="button"
            onClick={handlePlayClick}
            aria-label="Play video"
            className="absolute inset-0 flex items-center justify-center bg-black/30"
          >
            <span className="flex items-center justify-center w-20 h-20 rounded-full bg-white/90 text-black text-3xl">
              &#9654;
            </span>
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 mt-3">
        {/* Separate, always-available download. Never tied to playback. */}
        <a
          href={downloadUrl}
          download
          className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition"
        >
          Download
        </a>

        <button
          type="button"
          onClick={toggleMute}
          className="px-4 py-2 rounded-md border border-gray-400 text-sm hover:bg-gray-100 transition"
        >
          {muted ? "Unmute" : "Mute"}
        </button>

        {fatal && (
          <button
            type="button"
            onClick={retry}
            className="px-4 py-2 rounded-md border border-gray-400 text-sm hover:bg-gray-100 transition"
          >
            Retry
          </button>
        )}
      </div>

      {message && (
        <p role="status" className="mt-3 text-sm text-gray-700">
          {message}
        </p>
      )}
    </div>
  );
}
