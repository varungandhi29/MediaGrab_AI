import React, { useEffect, useRef, useState, useMemo } from 'react';
import {
  X,
  Play,
  Pause,
  Volume2,
  VolumeX,
  Download,
  RotateCcw,
  FastForward,
  Music,
  Sparkles,
  ShieldCheck,
} from 'lucide-react';

export default function AudioPlayerModal({
  isOpen,
  onClose,
  metadata,
  audioTrack,
  onDownload,
}) {
  const audioRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(metadata?.duration_seconds || 0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [isBuffering, setIsBuffering] = useState(false);

  // Determine stream source URL
  const audioSrc = useMemo(() => {
    if (audioTrack?.stream_url) return audioTrack.stream_url;
    // Look in available_qualities for audio
    const qAudio = metadata?.available_qualities?.find((q) => q.is_audio_only && q.stream_url);
    if (qAudio?.stream_url) return qAudio.stream_url;
    // Fallback to native video stream (browser decodes audio from MP4/WebM cleanly)
    const qNative = metadata?.available_qualities?.find((q) => q.stream_url);
    return qNative?.stream_url || null;
  }, [audioTrack, metadata]);

  // Format seconds to mm:ss
  const formatTime = (secs) => {
    if (!secs || isNaN(secs) || secs < 0) return '0:00';
    const s = Math.floor(secs);
    const m = Math.floor(s / 60);
    const remainingS = s % 60;
    return `${m}:${remainingS < 10 ? '0' : ''}${remainingS}`;
  };

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.target.tagName === 'INPUT') return;

      if (e.code === 'Space') {
        e.preventDefault();
        togglePlay();
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault();
        seekRelative(-5);
      } else if (e.code === 'ArrowRight') {
        e.preventDefault();
        seekRelative(5);
      } else if (e.key === 'm' || e.key === 'M') {
        e.preventDefault();
        toggleMute();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isPlaying, isMuted]);

  // Audio element listeners
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onLoadedMetadata = () => {
      if (audio.duration && !isNaN(audio.duration)) {
        setDuration(audio.duration);
      }
    };
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onWaiting = () => setIsBuffering(true);
    const onPlaying = () => setIsBuffering(false);
    const onEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
    };

    audio.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('loadedmetadata', onLoadedMetadata);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('waiting', onWaiting);
    audio.addEventListener('playing', onPlaying);
    audio.addEventListener('ended', onEnded);

    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate);
      audio.removeEventListener('loadedmetadata', onLoadedMetadata);
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('waiting', onWaiting);
      audio.removeEventListener('playing', onPlaying);
      audio.removeEventListener('ended', onEnded);
    };
  }, [audioSrc]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  };

  const seekRelative = (delta) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, Math.min(duration, audio.currentTime + delta));
  };

  const handleSeek = (e) => {
    const newTime = parseFloat(e.target.value);
    setCurrentTime(newTime);
    if (audioRef.current) {
      audioRef.current.currentTime = newTime;
    }
  };

  const handleVolumeChange = (e) => {
    const val = parseFloat(e.target.value);
    setVolume(val);
    setIsMuted(val === 0);
    if (audioRef.current) {
      audioRef.current.volume = val;
      audioRef.current.muted = val === 0;
    }
  };

  const toggleMute = () => {
    if (audioRef.current) {
      const nextMuted = !isMuted;
      setIsMuted(nextMuted);
      audioRef.current.muted = nextMuted;
    }
  };

  const handleSpeedChange = (speed) => {
    setPlaybackRate(speed);
    if (audioRef.current) {
      audioRef.current.playbackRate = speed;
    }
  };

  if (!isOpen || !metadata) return null;

  const thumbUrl = metadata.thumbnail_proxy || metadata.thumbnail;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/85 backdrop-blur-md animate-fadeIn"
      role="dialog"
      aria-modal="true"
    >
      <div className="relative w-full max-w-lg glass-panel rounded-2xl border border-slate-700/80 shadow-2xl overflow-hidden flex flex-col p-6 sm:p-8">
        
        {/* Hidden HTML5 Audio Element */}
        {audioSrc && (
          <audio
            ref={audioRef}
            src={audioSrc}
            preload="metadata"
            autoPlay
          />
        )}

        {/* Top Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
              <Music className="w-3.5 h-3.5" />
              <span>Hi-Fi Audio Stream</span>
            </span>
            <div className="flex items-center gap-1 text-[11px] text-slate-400">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>CORS Safe</span>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            aria-label="Close audio player"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Artwork & Track Information */}
        <div className="flex flex-col items-center text-center my-6">
          <div className="relative w-28 h-28 sm:w-36 sm:h-36 rounded-2xl overflow-hidden shadow-2xl border border-slate-700/60 mb-4 bg-slate-900 flex items-center justify-center group">
            {thumbUrl ? (
              <img
                src={thumbUrl}
                alt={metadata.title}
                className={`w-full h-full object-cover transition-transform duration-500 ${
                  isPlaying ? 'scale-105' : 'scale-100'
                }`}
                onError={(e) => {
                  e.target.style.display = 'none';
                }}
              />
            ) : (
              <Music className="w-12 h-12 text-slate-600" />
            )}

            {/* Pulsing ring when playing */}
            {isPlaying && (
              <div className="absolute inset-0 rounded-2xl border-2 border-emerald-400/50 animate-pulse pointer-events-none" />
            )}
          </div>

          <h3 className="text-base sm:text-lg font-bold text-white line-clamp-1 max-w-sm px-2">
            {metadata.title}
          </h3>
          {metadata.uploader && (
            <p className="text-xs text-slate-400 mt-1 line-clamp-1">
              {metadata.uploader}
            </p>
          )}
        </div>

        {/* Dynamic Frequency Waveform Visualizer */}
        <div className="w-full h-12 flex items-center justify-center gap-1 mb-4 px-2">
          {Array.from({ length: 32 }).map((_, i) => {
            const isCenter = Math.abs(i - 16) < 8;
            const baseH = isCenter ? 28 : 14;
            const animDelay = (i * 0.05).toFixed(2);
            return (
              <div
                key={i}
                className={`w-1 rounded-full transition-all duration-200 ${
                  isPlaying
                    ? 'bg-gradient-to-t from-emerald-500 to-teal-300'
                    : 'bg-slate-700'
                }`}
                style={{
                  height: isPlaying ? `${Math.max(6, Math.sin(i * 0.4 + currentTime * 4) * baseH + 18)}px` : '6px',
                  opacity: isPlaying ? 0.9 : 0.4,
                }}
              />
            );
          })}
        </div>

        {/* Seek Scrub Bar */}
        <div className="w-full mb-4">
          <input
            type="range"
            min="0"
            max={duration || 100}
            step="0.1"
            value={currentTime}
            onChange={handleSeek}
            className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-emerald-500 hover:accent-emerald-400 transition-all"
            aria-label="Seek time"
          />
          <div className="flex justify-between text-[11px] font-mono text-slate-400 mt-1 px-0.5">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>

        {/* Primary Controls */}
        <div className="flex items-center justify-center gap-4 mb-6">
          <button
            type="button"
            onClick={() => seekRelative(-10)}
            className="p-2.5 rounded-full text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
            title="Rewind 10 seconds"
          >
            <RotateCcw className="w-5 h-5" />
          </button>

          <button
            type="button"
            onClick={togglePlay}
            className="w-14 h-14 rounded-full bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 flex items-center justify-center shadow-lg shadow-emerald-500/30 hover:scale-105 active:scale-95 transition-transform"
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? (
              <Pause className="w-6 h-6 fill-current" />
            ) : (
              <Play className="w-6 h-6 fill-current ml-1" />
            )}
          </button>

          <button
            type="button"
            onClick={() => seekRelative(10)}
            className="p-2.5 rounded-full text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
            title="Fast forward 10 seconds"
          >
            <FastForward className="w-5 h-5" />
          </button>
        </div>

        {/* Volume & Speed Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-slate-800 text-xs">
          
          {/* Volume Control */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={toggleMute}
              className="text-slate-400 hover:text-white transition-colors"
              title={isMuted ? 'Unmute' : 'Mute'}
            >
              {isMuted || volume === 0 ? (
                <VolumeX className="w-4 h-4 text-rose-400" />
              ) : (
                <Volume2 className="w-4 h-4 text-slate-300" />
              )}
            </button>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={isMuted ? 0 : volume}
              onChange={handleVolumeChange}
              className="w-20 h-1 bg-slate-800 rounded appearance-none cursor-pointer accent-emerald-500"
              aria-label="Volume"
            />
          </div>

          {/* Speed Pills */}
          <div className="flex items-center gap-1">
            {[0.75, 1, 1.25, 1.5, 2].map((spd) => (
              <button
                key={spd}
                type="button"
                onClick={() => handleSpeedChange(spd)}
                className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors ${
                  playbackRate === spd
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {spd}x
              </button>
            ))}
          </div>

        </div>

        {/* Download MP3 Action Button */}
        {onDownload && (
          <div className="mt-5">
            <button
              type="button"
              onClick={() => {
                const mp3Option = metadata.available_qualities.find((q) => q.is_audio_only) || {
                  quality_label: 'Audio only (MP3)',
                  format_id: 'bestaudio/best',
                  is_audio_only: true,
                  ext: 'mp3',
                };
                onDownload(mp3Option);
                onClose();
              }}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-bold text-xs sm:text-sm shadow-lg shadow-emerald-500/25 transition-all"
            >
              <Download className="w-4 h-4" />
              <span>Download MP3 Audio</span>
            </button>
          </div>
        )}

      </div>
    </div>
  );
}
