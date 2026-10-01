import { useEffect, useRef, useState } from "react";

/**
 * VideoPlayer.jsx -- fixes "seeks forward, then freezes on a frame".
 *
 * Root cause: some browsers internally pause the video while they fetch the
 * new range after a seek, and don't reliably resume playback on their own.
 * Fix: remember whether it was playing right before the seek (onSeeking),
 * and explicitly resume it once the seek finishes (onSeeked).
 *
 * Also: a slow range fetch now shows a small "Buffering..." indicator
 * instead of looking frozen, and a stuck buffer nudges itself after 4s
 * (micro-seek) before giving up.
 */

const API_BASE = "";

export default function VideoPlayer({ jobId }) {
  const videoRef = useRef(null);
  const wasPlayingBeforeSeekRef = useRef(false);
  const stallTimerRef = useRef(null);

  const [playing, setPlaying] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [muted, setMuted] = useState(true);
  const [message, setMessage] = useState("");
  const [fatal, setFatal] = useState(false);

  const playUrl = `${API_BASE}/api/media/${jobId}/play`;
  const downloadUrl = `${API_BASE}/api/media/${jobId}/download`;

  useEffect(() => {
    setPlaying(false);
    setBuffering(false);
    setMessage("");
    setFatal(false);
    const v = videoRef.current;
    return () => {
      clearTimeout(stallTimerRef.current);
      if (v) {
        v.pause();
        v.removeAttribute("src");
        v.load();
      }
    };
  }, [jobId]);

  const handlePlayClick = async () => {
    const v = videoRef.current;
    if (!v) return;
    setMessage("");
    v.muted = true;
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
      setPlaying(false);
      setMessage("Tap the play button to start.");
    } else if (name === "NotSupportedError") {
      setFatal(true);
      setMessage("This video format can't be played in your browser. You can still download it.");
    } else if (name === "AbortError") {
      const v = videoRef.current;
      if (v) v.play().then(() => setPlaying(true)).catch(() => {});
    } else {
      setFatal(true);
      setMessage("Playback failed. You can still download the video.");
      console.error("play() failed:", err);
    }
  };

  // --- the actual fix: remember + restore play state across a seek --------
  const handleSeeking = () => {
    const v = videoRef.current;
    wasPlayingBeforeSeekRef.current = v ? !v.paused && !v.ended : false;
    setBuffering(true);
    clearTimeout(stallTimerRef.current);
    stallTimerRef.current = setTimeout(() => {
      const v2 = videoRef.current;
      if (v2 && v2.readyState < 3) {
        v2.currentTime = v2.currentTime + 0.01; // soft recovery nudge
      }
    }, 4000);
  };

  const handleSeeked = () => {
    clearTimeout(stallTimerRef.current);
    setBuffering(false);
    const v = videoRef.current;
    if (v && wasPlayingBeforeSeekRef.current && v.paused) {
      v.play().then(() => setPlaying(true)).catch(handlePlayError);
    }
  };

  const handleWaiting = () => setBuffering(true);
  const handlePlaying = () => {
    setBuffering(false);
    setPlaying(true);
  };

  const handleVideoError = () => {
    const v = videoRef.current;
    const code = v && v.error ? v.error.code : 0;
    if (!code) return; // ignore spurious error events with no real MediaError
    setPlaying(false);
    setBuffering(false);
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
          onSeeking={handleSeeking}
          onSeeked={handleSeeked}
          onWaiting={handleWaiting}
          onPlaying={handlePlaying}
          onError={handleVideoError}
        />

        {!playing && !fatal && !buffering && (
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

        {buffering && !fatal && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/20 pointer-events-none">
            <span className="px-3 py-1 rounded bg-black/60 text-white text-xs">Buffering...</span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 mt-3">
        <a href={downloadUrl} download className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium">
          Download
        </a>
        <button type="button" onClick={toggleMute} className="px-4 py-2 rounded-md border border-gray-400 text-sm">
          {muted ? "Unmute" : "Mute"}
        </button>
        {fatal && (
          <button type="button" onClick={retry} className="px-4 py-2 rounded-md border border-gray-400 text-sm">
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
