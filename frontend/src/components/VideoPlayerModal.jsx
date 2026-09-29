import React, {
  useEffect,
  useRef,
  useState,
  useMemo,
  useCallback,
  forwardRef,
  useImperativeHandle,
} from 'react';
import {
  X,
  Download,
  Loader2,
  Play,
  Pause,
  Volume2,
  VolumeX,
  RotateCcw,
  RotateCw,
  Film,
  Maximize,
  Minimize,
  Repeat,
  PictureInPicture,
  ChevronDown,
  Clock,
  Sparkles,
  ShieldCheck,
} from 'lucide-react';
import {
  prepareMedia,
  streamMediaProgress,
  cancelMediaJob,
} from '../services/api';
import Hls from 'hls.js';

const formatTime = (secs) => {
  if (!secs || isNaN(secs) || secs < 0) return '00:00';
  const s = Math.floor(secs);
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const pad = (n) => String(n).padStart(2, '0');
  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(seconds)}`;
  }
  return `${pad(minutes)}:${pad(seconds)}`;
};

const VideoPlayerModal = forwardRef(function VideoPlayerModal(
  {
    isOpen,
    onClose,
    metadata,
    initialSelectedQuality,
    onDownload,
  },
  ref
) {
  const videoRef = useRef(null);
  const audioRef = useRef(null);
  const playerContainerRef = useRef(null);
  const eventSourceCancelRef = useRef(null);
  const activeJobIdRef = useRef(null);
  const activeJobQualityRef = useRef(null);
  const controlsTimeoutRef = useRef(null);
  const pendingSeekTimeRef = useRef(null);
  const wasPlayingRef = useRef(false);
  const hlsRef = useRef(null);
  const bufferingTimerRef = useRef(null);
  const isSeekingRef = useRef(false);
  const lastSyncTimeRef = useRef(0);
  const maxPlayableDurationRef = useRef(null);
  const audioSeekTimerRef = useRef(null);
  const audioStallTimerRef = useRef(null);
  const scrubRafRef = useRef(null);
  const accumulatedSeekRef = useRef(0);
  const seekFeedbackTimerRef = useRef(null);
  const [hoverSeekTime, setHoverSeekTime] = useState(null);
  const [hoverSeekPos, setHoverSeekPos] = useState(0);

  // Dynamic comfort resolutions (always provide selectable resolutions)
  const displayQualities = useMemo(() => {
    const raw = (metadata?.available_qualities || []).filter((q) => !q.is_audio_only);
    if (raw.length > 1) {
      return raw;
    }
    const isSourceHls = raw.some((q) => q.is_hls) || Boolean(metadata?.is_hls);
    // If only 1 or no native formats discovered, provide standard comfort resolution choices
    const sid = metadata?.stream_session_id;
    const baseStream = raw[0]?.stream_url;
    return [
      { quality_label: '1080p (Full HD)', height: 1080, format_id: '1080p', stream_url: sid ? `/api/stream/${sid}/1080p` : baseStream, is_hls: isSourceHls },
      { quality_label: '720p (HD)', height: 720, format_id: '720p', stream_url: sid ? `/api/stream/${sid}/720p` : baseStream, is_hls: isSourceHls },
      { quality_label: '480p (SD)', height: 480, format_id: '480p', stream_url: sid ? `/api/stream/${sid}/480p` : baseStream, is_hls: isSourceHls },
      { quality_label: '360p (Data Saver)', height: 360, format_id: '360p', stream_url: sid ? `/api/stream/${sid}/360p` : baseStream, is_hls: isSourceHls },
    ];
  }, [metadata]);

  // Selected quality state
  const [selectedQuality, setSelectedQuality] = useState(() => {
    return initialSelectedQuality || displayQualities[0] || null;
  });

  // Sync selectedQuality when initialSelectedQuality changes or modal opens
  useEffect(() => {
    if (initialSelectedQuality) {
      setSelectedQuality(initialSelectedQuality);
    } else if (displayQualities.length > 0) {
      setSelectedQuality(displayQualities[0]);
    }
  }, [initialSelectedQuality, displayQualities]);

  const [activeJobId, setActiveJobId] = useState(null);
  const [isJobReady, setIsJobReady] = useState(false);
  const [mediaInfo, setMediaInfo] = useState(null);
  const [downloadProgress, setDownloadProgress] = useState(null);

  // Playback states: start unmuted by default with 100% volume
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [hasStartedPlaying, setHasStartedPlaying] = useState(false);
  const [isBuffering, setIsBuffering] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(metadata?.duration_seconds || 0);
  const [isLooping, setIsLooping] = useState(false);
  const [isPipActive, setIsPipActive] = useState(false);
  const [seekFeedback, setSeekFeedback] = useState(null);

  // Fullscreen and overlay controls state
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [scrubTime, setScrubTime] = useState(0);

  // Determine the DIRECT streaming source URL with resolution fidelity
  const streamSrc = useMemo(() => {
    const qKey = selectedQuality?.height ? `${selectedQuality.height}p` : 'native';

    // 1. If active prepared job is ready AND matches current quality
    if (activeJobId && isJobReady && activeJobQualityRef.current === qKey) {
      return `/api/media/${activeJobId}/play`;
    }

    // 2. Direct stream_url on selected quality
    if (selectedQuality?.stream_url) {
      return selectedQuality.stream_url;
    }

    // 3. Find matching stream_url from metadata available_qualities
    if (metadata?.available_qualities) {
      const match = metadata.available_qualities.find(
        (q) => !q.is_audio_only && (
          (selectedQuality?.height && q.height === selectedQuality.height) ||
          (selectedQuality?.format_id && q.format_id === selectedQuality.format_id) ||
          (selectedQuality?.quality_label && q.quality_label === selectedQuality.quality_label)
        )
      );
      if (match?.stream_url) return match.stream_url;
    }

    // 4. Session token proxy fallback with target resolution
    if (metadata?.stream_session_id) {
      return `/api/stream/${metadata.stream_session_id}/${qKey}`;
    }

    // 5. Fallback to activeJobId or metadata URL
    if (activeJobId) {
      return `/api/media/${activeJobId}/play`;
    }
    return metadata?.url || '';
  }, [activeJobId, isJobReady, selectedQuality, metadata]);

  // Detect if current stream is an HLS playlist (M3U8)
  const isHlsStream = useMemo(() => {
    if (!streamSrc) return false;
    return (
      streamSrc.includes('.m3u8') ||
      streamSrc.includes('/hls') ||
      streamSrc.includes('streaming') ||
      Boolean(selectedQuality?.is_hls) ||
      Boolean(metadata?.is_hls) ||
      Boolean(metadata?.available_qualities?.some((q) => q.is_hls))
    );
  }, [streamSrc, selectedQuality, metadata]);

  // Determine if a separate audio stream is needed
  // (e.g. YouTube DASH video-only formats like 1080p, 1440p, 4K before background normalization finishes)
  const needsSeparateAudio = useMemo(() => {
    if (isHlsStream) return false;
    const qKey = selectedQuality?.height ? `${selectedQuality.height}p` : 'native';
    // When prepared job is ready, it has both video + audio merged into a single MP4 with faststart
    if (activeJobId && isJobReady && activeJobQualityRef.current === qKey) {
      return false;
    }
    // Only use separate audio if the quality format is strictly video-only (acodec === 'none')
    if (selectedQuality?.acodec === 'none') {
      return Boolean(metadata?.stream_session_id);
    }
    // If format has audio, or acodec is not 'none', no separate audio is needed!
    if (selectedQuality?.acodec && selectedQuality.acodec !== 'none') {
      return false;
    }
    // Check if the matching format in metadata has acodec === 'none'
    if (metadata?.available_qualities) {
      const match = metadata.available_qualities.find(
        (q) => !q.is_audio_only && (
          (selectedQuality?.height && q.height === selectedQuality.height) ||
          (selectedQuality?.format_id && q.format_id === selectedQuality.format_id) ||
          (selectedQuality?.quality_label && q.quality_label === selectedQuality.quality_label)
        )
      );
      if (match?.acodec === 'none') {
        return Boolean(metadata?.stream_session_id);
      }
      if (match?.acodec && match.acodec !== 'none') {
        return false;
      }
    }
    return false;
  }, [activeJobId, isJobReady, selectedQuality, metadata, isHlsStream]);

  // Dedicated audio stream URL from session cache
  const audioSrc = useMemo(() => {
    if (!needsSeparateAudio || !metadata?.stream_session_id) return '';
    return `/api/stream/${metadata.stream_session_id}/audio`;
  }, [needsSeparateAudio, metadata]);

  // Determine download source URL
  const downloadSrc = useMemo(() => {
    if (activeJobId && isJobReady) {
      return `/api/media/${activeJobId}/download`;
    }
    if (mediaInfo?.download_url) {
      return mediaInfo.download_url;
    }
    if (metadata?.stream_session_id) {
      const qKey = selectedQuality?.height ? `${selectedQuality.height}p` : 'native';
      return `/api/stream/${metadata.stream_session_id}/${qKey}?download=1`;
    }
    return streamSrc;
  }, [activeJobId, isJobReady, mediaInfo, metadata, selectedQuality, streamSrc]);

  // Auto-hide controls timer during playback
  const handleUserActivity = useCallback(() => {
    setShowControls(true);
    if (controlsTimeoutRef.current) {
      clearTimeout(controlsTimeoutRef.current);
    }
    if (isPlaying && !isScrubbing) {
      controlsTimeoutRef.current = setTimeout(() => {
        setShowControls(false);
      }, 3500);
    }
  }, [isPlaying, isScrubbing]);

  // Browser fullscreen change listener
  useEffect(() => {
    const handleFsChange = () => {
      const isFs = Boolean(
        document.fullscreenElement ||
        document.webkitFullscreenElement ||
        document.mozFullScreenElement ||
        document.msFullscreenElement
      );
      setIsFullscreen(isFs);
      setShowControls(true);
    };

    document.addEventListener('fullscreenchange', handleFsChange);
    document.addEventListener('webkitfullscreenchange', handleFsChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFsChange);
      document.removeEventListener('webkitfullscreenchange', handleFsChange);
    };
  }, []);

  // Start background preparation for offline download and faststart merge
  const startBackgroundPreparation = useCallback(
    async (qualityToPrepare) => {
      if (!metadata?.url) return;

      if (eventSourceCancelRef.current) {
        eventSourceCancelRef.current();
        eventSourceCancelRef.current = null;
      }

      const targetQuality = qualityToPrepare || selectedQuality;
      const qKey = targetQuality?.height ? `${targetQuality.height}p` : 'native';
      activeJobQualityRef.current = qKey;

      try {
        const job = await prepareMedia({
          url: metadata.url,
          quality_label: targetQuality?.quality_label || 'Best',
          format_id: targetQuality?.format_id || null,
          height: targetQuality?.height || null,
          is_audio_only: false,
        });

        activeJobIdRef.current = job.job_id;
        setActiveJobId(job.job_id);

        if (job.stage === 'ready') {
          if (activeJobQualityRef.current === qKey) {
            if (hasStartedPlaying && videoRef.current && videoRef.current.currentTime > 0) {
              pendingSeekTimeRef.current = videoRef.current.currentTime;
              wasPlayingRef.current = !videoRef.current.paused;
            } else {
              pendingSeekTimeRef.current = null;
            }
            setIsJobReady(true);
            setMediaInfo({
              token: job.token,
              stream_url: job.stream_url,
              download_url: job.download_url,
              filename: job.filename,
              filesize: job.filesize,
            });
          }
          return;
        }

        // Listen for background completion
        const cancelStream = streamMediaProgress(job.job_id, {
          onProgress: (update) => {
            setDownloadProgress(update.progress_percent || 0);
          },
          onReady: (readyData) => {
            if (activeJobQualityRef.current === qKey) {
              if (hasStartedPlaying && videoRef.current && videoRef.current.currentTime > 0) {
                pendingSeekTimeRef.current = videoRef.current.currentTime;
                wasPlayingRef.current = !videoRef.current.paused;
              } else {
                pendingSeekTimeRef.current = null;
              }
              setIsJobReady(true);
              setDownloadProgress(100);
              setMediaInfo({
                token: readyData.token,
                stream_url: readyData.stream_url,
                download_url: readyData.download_url,
                filename: readyData.filename,
                filesize: readyData.filesize,
              });
            }
          },
          onError: () => {},
        });

        eventSourceCancelRef.current = cancelStream;
      } catch (err) {}
    },
    [metadata?.url, selectedQuality]
  );

  // Reset all media job & playback state when video URL changes
  useEffect(() => {
    setActiveJobId(null);
    activeJobIdRef.current = null;
    activeJobQualityRef.current = null;
    setIsJobReady(false);
    setMediaInfo(null);
    setDownloadProgress(null);
    setDuration(metadata?.duration_seconds || 0);
    setCurrentTime(0);
    setScrubTime(0);
    pendingSeekTimeRef.current = null;
    wasPlayingRef.current = false;
    setHasStartedPlaying(false);
    setIsPlaying(false);
    if (videoRef.current) {
      try {
        videoRef.current.currentTime = 0;
      } catch (e) {}
    }
    if (audioRef.current) {
      try {
        audioRef.current.currentTime = 0;
      } catch (e) {}
    }
  }, [metadata?.url]);

  // Reset buffering, positions, and playback states to the absolute start when modal opens
  useEffect(() => {
    if (isOpen) {
      setIsBuffering(true);
      setIsPlaying(false);
      setHasStartedPlaying(false);
      setIsMuted(false);
      setVolume(1);
      setCurrentTime(0);
      setScrubTime(0);
      pendingSeekTimeRef.current = null;
      wasPlayingRef.current = false;
      accumulatedSeekRef.current = 0;
      if (videoRef.current) {
        try {
          videoRef.current.currentTime = 0;
        } catch (e) {}
      }
      if (audioRef.current) {
        try {
          audioRef.current.currentTime = 0;
        } catch (e) {}
      }
      if (metadata?.url) {
        startBackgroundPreparation(selectedQuality);
      }
    }

    return () => {
      if (eventSourceCancelRef.current) {
        eventSourceCancelRef.current();
        eventSourceCancelRef.current = null;
      }
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
    };
  }, [isOpen, metadata?.url, selectedQuality, startBackgroundPreparation]);

  // HLS stream binding via Hls.js (enables in-browser playback for M3U8 without native browser black screens)
  useEffect(() => {
    if (!isOpen || !videoRef.current || !streamSrc) return;
    const v = videoRef.current;
    setIsBuffering(true);

    if (isHlsStream && Hls.isSupported()) {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
      });
      hlsRef.current = hls;
      hls.loadSource(streamSrc);
      hls.attachMedia(v);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        setIsBuffering(false);
        const curTime = (v.currentTime && v.currentTime > 0) ? v.currentTime : 0;
        if (hasStartedPlaying && curTime > 0) {
          v.currentTime = curTime;
          setCurrentTime(curTime);
        } else if (pendingSeekTimeRef.current !== null && pendingSeekTimeRef.current > 0) {
          v.currentTime = pendingSeekTimeRef.current;
          setCurrentTime(pendingSeekTimeRef.current);
          pendingSeekTimeRef.current = null;
        } else if (!hasStartedPlaying) {
          v.currentTime = 0;
          setCurrentTime(0);
          pendingSeekTimeRef.current = null;
        }
        v.muted = false;
        v.volume = volume > 0 ? volume : 1;
        setIsMuted(false);
        const playPromise = v.play();
        if (playPromise !== undefined) {
          playPromise
            .then(() => {
              setIsPlaying(true);
              setHasStartedPlaying(true);
              setIsBuffering(false);
              setIsMuted(false);
            })
            .catch(() => {
              // Autoplay with sound restricted by browser policy, fall back to muted visual start
              v.muted = true;
              setIsMuted(true);
              v.play()
                .then(() => {
                  setIsPlaying(true);
                  setHasStartedPlaying(true);
                  setIsBuffering(false);
                })
                .catch(() => {
                  setIsPlaying(false);
                });
            });
        }
      });
      hls.on(Hls.Events.LEVEL_LOADED, (_, data) => {
        if (data.details && data.details.totalduration > 0) {
          if (!metadata?.duration_seconds || metadata.duration_seconds <= 0) {
            setDuration(data.details.totalduration);
          }
        }
      });
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (
          data.details === Hls.ErrorDetails.BUFFER_STALLED_ERROR ||
          data.details === Hls.ErrorDetails.BUFFER_SEEK_OVER_HOLE ||
          data.details === Hls.ErrorDetails.BUFFER_NUDGE_ON_STALL
        ) {
          hls.recoverMediaError();
          if (bufferingTimerRef.current) {
            clearTimeout(bufferingTimerRef.current);
            bufferingTimerRef.current = null;
          }
          setIsBuffering(false);
          return;
        }

        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              hls.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls.recoverMediaError();
              break;
            default:
              hls.destroy();
              break;
          }
        }
      });
    } else if (isHlsStream && v.canPlayType('application/vnd.apple.mpegurl')) {
      // Native Apple Safari HLS
      v.src = streamSrc;
      if (!hasStartedPlaying) {
        v.currentTime = 0;
        setCurrentTime(0);
      }
      v.muted = false;
      v.volume = volume > 0 ? volume : 1;
      setIsMuted(false);
      v.play()
        .then(() => {
          setIsPlaying(true);
          setHasStartedPlaying(true);
          setIsBuffering(false);
          setIsMuted(false);
        })
        .catch(() => {
          v.muted = true;
          setIsMuted(true);
          v.play().catch(() => {});
        });
    } else if (!isHlsStream) {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      if (v.src !== streamSrc && !v.src.endsWith(streamSrc)) {
        v.src = streamSrc;
      }
    }

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [isOpen, streamSrc, isHlsStream, hasStartedPlaying]);

  // Autoplay attempt as soon as modal opens or streamSrc is ready (for non-HLS streams)
  useEffect(() => {
    if (isOpen && videoRef.current && streamSrc && !isHlsStream) {
      const v = videoRef.current;
      const a = audioRef.current;

      const isSrcChanged = v.src !== streamSrc && !v.src.endsWith(streamSrc);
      if (isSrcChanged) {
        const curTime = (v.currentTime && v.currentTime > 0) ? v.currentTime : 0;
        v.src = streamSrc;
        if (hasStartedPlaying && curTime > 0) {
          // Seamless handoff: preserve current timestamp when src updates (e.g. background prep ready)
          v.currentTime = curTime;
          setCurrentTime(curTime);
          if (a && needsSeparateAudio) a.currentTime = curTime;
        } else if (pendingSeekTimeRef.current !== null && pendingSeekTimeRef.current > 0) {
          v.currentTime = pendingSeekTimeRef.current;
          setCurrentTime(pendingSeekTimeRef.current);
          if (a && needsSeparateAudio) a.currentTime = pendingSeekTimeRef.current;
          pendingSeekTimeRef.current = null;
        } else {
          v.currentTime = 0;
          setCurrentTime(0);
          if (a && needsSeparateAudio) a.currentTime = 0;
          pendingSeekTimeRef.current = null;
        }
      }

      v.muted = false;
      v.volume = volume > 0 ? volume : 1;
      setIsMuted(false);
      if (a && needsSeparateAudio) {
        a.muted = false;
        a.volume = volume > 0 ? volume : 1;
      }

      const playPromise = v.play();
      if (playPromise !== undefined) {
        playPromise
          .then(() => {
            setIsPlaying(true);
            setHasStartedPlaying(true);
            if (bufferingTimerRef.current) {
              clearTimeout(bufferingTimerRef.current);
              bufferingTimerRef.current = null;
            }
            setIsBuffering(false);
            setIsMuted(false);
            if (a && needsSeparateAudio && a.paused) {
              a.play().catch(() => {});
            }
          })
          .catch(() => {
            // Autoplay with audio was restricted, try muted autoplay for smooth visual transition
            v.muted = true;
            setIsMuted(true);
            if (a && needsSeparateAudio) a.muted = true;
            v.play()
              .then(() => {
                setIsPlaying(true);
                setHasStartedPlaying(true);
                if (bufferingTimerRef.current) {
                  clearTimeout(bufferingTimerRef.current);
                  bufferingTimerRef.current = null;
                }
                setIsBuffering(false);
              })
              .catch(() => {
                setIsPlaying(false);
                setIsBuffering(false);
              });
          });
      }
    }
  }, [isOpen, streamSrc, isHlsStream]);

  // Expose imperative unlock (called from user click on "Watch Video")
  useImperativeHandle(ref, () => ({
    unlock: () => {
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx) {
          if (!window.__mediaGrabAudioCtx) {
            window.__mediaGrabAudioCtx = new AudioCtx();
          }
          if (window.__mediaGrabAudioCtx.state === 'suspended') {
            window.__mediaGrabAudioCtx.resume();
          }
        }
      } catch (e) {}

      setIsMuted(false);
      setVolume(1);
      const v = videoRef.current;
      const a = audioRef.current;
      if (v) {
        v.muted = false;
        v.volume = 1;
        v.playsInline = true;
        try {
          v.currentTime = 0;
          if (a) a.currentTime = 0;
          setCurrentTime(0);
          pendingSeekTimeRef.current = null;
        } catch (e) {}
        if (v.readyState >= 2) {
          v.play()
            .then(() => {
              setIsPlaying(true);
              setHasStartedPlaying(true);
              setIsBuffering(false);
              if (a && needsSeparateAudio) a.play().catch(() => {});
            })
            .catch(() => {});
        }
      }
      if (a) {
        a.muted = false;
        a.volume = 1;
      }
    },
    getVideoElement: () => videoRef.current,
  }));

  // Global auto-unmute on first user touch/click/keypress anywhere in document if browser started muted
  useEffect(() => {
    if (isOpen && isMuted) {
      const handleGlobalUnmute = () => {
        const v = videoRef.current;
        const a = audioRef.current;
        if (v) {
          v.muted = false;
          v.volume = 1;
        }
        if (a) {
          a.muted = false;
          a.volume = 1;
        }
        setIsMuted(false);
        setVolume(1);
      };

      window.addEventListener('click', handleGlobalUnmute, { once: true, capture: true });
      window.addEventListener('keydown', handleGlobalUnmute, { once: true, capture: true });
      window.addEventListener('touchstart', handleGlobalUnmute, { once: true, capture: true });

      return () => {
        window.removeEventListener('click', handleGlobalUnmute, { capture: true });
        window.removeEventListener('keydown', handleGlobalUnmute, { capture: true });
        window.removeEventListener('touchstart', handleGlobalUnmute, { capture: true });
      };
    }
  }, [isOpen, isMuted]);

  // Toggle Play / Pause
  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    const a = audioRef.current;
    if (!v) return;
    handleUserActivity();

    // User explicitly interacted: ensure audio is unmuted
    if (v.muted || isMuted) {
      v.muted = false;
      v.volume = volume > 0 ? volume : 1;
      setIsMuted(false);
      setVolume(volume > 0 ? volume : 1);
      if (a) {
        a.muted = false;
        a.volume = volume > 0 ? volume : 1;
      }
    }

    if (v.paused) {
      if (a && needsSeparateAudio) {
        a.currentTime = v.currentTime;
        a.muted = false;
        a.volume = volume > 0 ? volume : 1;
        a.play().catch(() => {});
      }
      v.play()
        .then(() => {
          setIsPlaying(true);
          setHasStartedPlaying(true);
          setIsBuffering(false);
        })
        .catch(() => {});
    } else {
      v.pause();
      if (a) a.pause();
      setIsPlaying(false);
    }
  }, [handleUserActivity, needsSeparateAudio, isMuted, volume]);

  const handleUserPlayClick = togglePlay;


  // Centralized seek handler with bounds clamping and butter-smooth fastSeek & debounced audio sync
  const performSeek = useCallback(
    (targetTime) => {
      const v = videoRef.current;
      if (!v) return;

      handleUserActivity();

      const fullDur = Math.max(metadata?.duration_seconds || 0, v.duration || 0, duration || 0, 1000);
      const bounded = Math.max(0, Math.min(fullDur, targetTime));

      const wasPlaying = !v.paused || isPlaying;
      wasPlayingRef.current = wasPlaying;
      isSeekingRef.current = true;
      setCurrentTime(bounded);
      setScrubTime(bounded);

      // Fast seek to nearest keyframe for instantaneous zero-stutter frame decode
      if (typeof v.fastSeek === 'function') {
        try {
          v.fastSeek(bounded);
        } catch (e) {
          v.currentTime = bounded;
        }
      } else {
        v.currentTime = bounded;
      }

      if (wasPlaying) {
        v.play().catch(() => {});
      }

      // Smoothly debounce separate audio seek to eliminate audio popping & micro-buffering
      if (audioSeekTimerRef.current) {
        clearTimeout(audioSeekTimerRef.current);
      }
      audioSeekTimerRef.current = setTimeout(() => {
        const a = audioRef.current;
        if (a && needsSeparateAudio) {
          try {
            a.currentTime = bounded;
            if (wasPlaying || !v.paused) {
              a.play().catch(() => {});
            }
          } catch (e) {}
        }
      }, 50);

      // Debounce buffering overlay: do not show spinner on instant seeks
      if (bufferingTimerRef.current) {
        clearTimeout(bufferingTimerRef.current);
      }
      bufferingTimerRef.current = setTimeout(() => {
        setIsBuffering(true);
      }, 400);
    },
    [handleUserActivity, isHlsStream, duration, metadata?.duration_seconds, needsSeparateAudio, isPlaying]
  );

  // Forward & Backward Seeking (works in windowed and fullscreen with butter-smooth accumulation)
  const seekRelative = useCallback(
    (delta) => {
      const v = videoRef.current;
      if (!v) return;

      // Accumulate relative seeks if tapped multiple times in rapid succession
      accumulatedSeekRef.current = (seekFeedbackTimerRef.current ? accumulatedSeekRef.current : 0) + delta;
      const baseTime = (seekFeedbackTimerRef.current && pendingSeekTimeRef.current !== null)
        ? pendingSeekTimeRef.current
        : (isScrubbing ? scrubTime : v.currentTime);
      const targetTime = baseTime + delta;
      pendingSeekTimeRef.current = targetTime;
      performSeek(targetTime);

      const totalDelta = accumulatedSeekRef.current;
      setSeekFeedback(totalDelta > 0 ? `+${totalDelta}s` : `${totalDelta}s`);

      if (seekFeedbackTimerRef.current) {
        clearTimeout(seekFeedbackTimerRef.current);
      }
      seekFeedbackTimerRef.current = setTimeout(() => {
        setSeekFeedback(null);
        accumulatedSeekRef.current = 0;
        pendingSeekTimeRef.current = null;
        seekFeedbackTimerRef.current = null;
      }, 800);
    },
    [performSeek, isScrubbing, scrubTime]
  );

  // Scrubbing & Seeking Handlers with real-time RAF fastSeek
  const handleSeekChange = (e) => {
    const newTime = parseFloat(e.target.value);
    setScrubTime(newTime);
    setCurrentTime(newTime);

    // Live frame scrubbing via requestAnimationFrame
    if (scrubRafRef.current) {
      cancelAnimationFrame(scrubRafRef.current);
    }
    scrubRafRef.current = requestAnimationFrame(() => {
      const v = videoRef.current;
      if (v) {
        if (typeof v.fastSeek === 'function') {
          try {
            v.fastSeek(newTime);
          } catch (err) {
            v.currentTime = newTime;
          }
        } else {
          v.currentTime = newTime;
        }
      }
    });
  };

  const handleSeekStart = () => {
    setIsScrubbing(true);
    setShowControls(true);
  };

  const handleSeekEnd = (e) => {
    setIsScrubbing(false);
    const newTime = parseFloat(e.target.value);
    performSeek(newTime);
  };

  // Volume & Mute Handlers (applied simultaneously to video and audio tracks)
  const handleVolumeChange = (e) => {
    const val = parseFloat(e.target.value);
    setVolume(val);
    const muted = val === 0;
    setIsMuted(muted);
    if (videoRef.current) {
      videoRef.current.volume = val;
      videoRef.current.muted = muted;
    }
    if (audioRef.current) {
      audioRef.current.volume = val;
      audioRef.current.muted = muted;
    }
    handleUserActivity();
  };

  const toggleMute = useCallback(() => {
    const v = videoRef.current;
    const a = audioRef.current;
    if (v) {
      handleUserActivity();
      const nextMuted = !isMuted;
      v.muted = nextMuted;
      setIsMuted(nextMuted);
      if (a) a.muted = nextMuted;

      if (!nextMuted && volume === 0) {
        setVolume(1);
        v.volume = 1;
        if (a) a.volume = 1;
      }
    }
  }, [isMuted, volume, handleUserActivity]);

  // When switching quality: preserves exact playback position seamlessly
  const handleQualityChange = useCallback((newQuality) => {
    if (!newQuality) return;
    handleUserActivity();
    const currentPos = videoRef.current ? videoRef.current.currentTime : currentTime;
    pendingSeekTimeRef.current = currentPos;
    wasPlayingRef.current = isPlaying || (videoRef.current && !videoRef.current.paused);

    setSelectedQuality(newQuality);
    setIsJobReady(false);
    startBackgroundPreparation(newQuality);
  }, [currentTime, isPlaying, startBackgroundPreparation, handleUserActivity]);

  // Video metadata loaded: restore position if pending, or initialize duration
  const handleLoadedMetadata = () => {
    const v = videoRef.current;
    const a = audioRef.current;
    if (v) {
      const fullDur = Math.max(metadata?.duration_seconds || 0, v.duration || 0);
      if (fullDur > 0 && !isNaN(fullDur)) {
        setDuration(fullDur);
      }
      if (pendingSeekTimeRef.current !== null && pendingSeekTimeRef.current > 0) {
        v.currentTime = pendingSeekTimeRef.current;
        setCurrentTime(pendingSeekTimeRef.current);
        if (a && needsSeparateAudio) a.currentTime = pendingSeekTimeRef.current;
        pendingSeekTimeRef.current = null;
        if (wasPlayingRef.current) {
          v.play().then(() => {
            setIsPlaying(true);
            if (a && needsSeparateAudio) a.play().catch(() => {});
          }).catch(() => {});
        }
      } else {
        v.currentTime = 0;
        setCurrentTime(0);
        if (a && needsSeparateAudio) a.currentTime = 0;
        pendingSeekTimeRef.current = null;
      }
    }
  };

  const handleCanPlay = useCallback(() => {
    if (bufferingTimerRef.current) {
      clearTimeout(bufferingTimerRef.current);
      bufferingTimerRef.current = null;
    }
    setIsBuffering(false);
    const v = videoRef.current;
    const a = audioRef.current;
    if (v && pendingSeekTimeRef.current !== null && pendingSeekTimeRef.current > 0) {
      v.currentTime = pendingSeekTimeRef.current;
      setCurrentTime(pendingSeekTimeRef.current);
      if (a && needsSeparateAudio) a.currentTime = pendingSeekTimeRef.current;
      pendingSeekTimeRef.current = null;
      if (wasPlayingRef.current) {
        v.play().then(() => {
          setIsPlaying(true);
          if (a && needsSeparateAudio) a.play().catch(() => {});
        }).catch(() => {});
      }
    } else if (v && !hasStartedPlaying) {
      v.currentTime = 0;
      setCurrentTime(0);
      if (a && needsSeparateAudio) a.currentTime = 0;
      pendingSeekTimeRef.current = null;
    }
  }, [hasStartedPlaying, needsSeparateAudio]);

  const handleWaiting = useCallback(() => {
    if (bufferingTimerRef.current) {
      clearTimeout(bufferingTimerRef.current);
    }
    // Debounce: Only display buffering spinner if playback stalls for > 350ms!
    bufferingTimerRef.current = setTimeout(() => {
      setIsBuffering(true);
      // Only pause audio if video is genuinely stalled and paused
      if (audioRef.current && needsSeparateAudio && videoRef.current?.paused) {
        audioRef.current.pause();
      }
    }, 350);
  }, [needsSeparateAudio]);

  const handlePlaying = useCallback(() => {
    if (bufferingTimerRef.current) {
      clearTimeout(bufferingTimerRef.current);
      bufferingTimerRef.current = null;
    }
    setIsBuffering(false);
    setIsPlaying(true);
    setHasStartedPlaying(true);
    isSeekingRef.current = false;

    // Resume audio without overriding currentTime!
    if (audioRef.current && needsSeparateAudio && !videoRef.current?.paused) {
      if (audioRef.current.paused) {
        audioRef.current.play().catch(() => {});
      }
    }
  }, [needsSeparateAudio]);

  const handleTimeUpdate = () => {
    if (videoRef.current && !isScrubbing) {
      const vTime = videoRef.current.currentTime;
      setCurrentTime(vTime);
      const fullDur = Math.max(metadata?.duration_seconds || 0, videoRef.current.duration || 0);
      if (fullDur > 0 && !isNaN(fullDur)) {
        setDuration(fullDur);
      }

      // Smooth audio drift correction: glide playbackRate instead of jarring currentTime seeks
      if (audioRef.current && needsSeparateAudio && !videoRef.current.paused && !isSeekingRef.current) {
        const a = audioRef.current;
        const v = videoRef.current;

        // CRITICAL GUARD: Only evaluate drift and sync if audio is NOT currently seeking and readyState >= 2!
        if (!a.seeking && a.readyState >= 2) {
          const aTime = a.currentTime;
          const drift = vTime - aTime;
          const absDrift = Math.abs(drift);

          if (absDrift > 0.8) {
            // Large drift: throttle hard seek to once every 2.5 seconds
            const now = Date.now();
            if (now - lastSyncTimeRef.current > 2500) {
              lastSyncTimeRef.current = now;
              a.currentTime = vTime;
              if (a.paused) {
                a.play().catch(() => {});
              }
            }
          } else if (absDrift > 0.12) {
            // Mild drift: glide speed subtly by 5% to lock into sync smoothly
            a.playbackRate = drift > 0 ? 1.05 : 0.95;
          } else {
            // In sync: keep exact matching rate
            const vRate = v.playbackRate || 1;
            if (a.playbackRate !== vRate) {
              a.playbackRate = vRate;
            }
          }
        }

        if (a.paused && !v.paused && a.readyState >= 2) {
          a.play().catch(() => {});
        }
      }
    }
  };

  // Fullscreen toggle: toggles entire player container (including scrubber & controls)
  const toggleFullscreen = useCallback(() => {
    const container = playerContainerRef.current;
    if (!container) return;

    if (
      document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.mozFullScreenElement ||
      document.msFullscreenElement
    ) {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen().catch(() => {});
      }
    } else {
      if (container.requestFullscreen) {
        container.requestFullscreen().catch(() => {
          if (videoRef.current?.requestFullscreen) {
            videoRef.current.requestFullscreen().catch(() => {});
          }
        });
      } else if (container.webkitRequestFullscreen) {
        container.webkitRequestFullscreen();
      } else if (videoRef.current?.webkitEnterFullscreen) {
        videoRef.current.webkitEnterFullscreen();
      }
    }
  }, []);

  // Keyboard hotkeys for playback controls (Left/Right Arrow, J/L for seeking, Space/K for play/pause, etc.)
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      // Only ignore if typing inside a text entry input or textarea
      const isTextInput =
        (e.target.tagName === 'INPUT' && ['text', 'search', 'email', 'password', 'url', 'number'].includes(e.target.type)) ||
        e.target.tagName === 'TEXTAREA' ||
        e.target.isContentEditable;
      if (isTextInput) return;

      const key = e.key;
      const code = e.code;

      // Seeking backward -10s
      if (key === 'ArrowLeft' || code === 'ArrowLeft' || key === 'j' || key === 'J' || code === 'KeyJ') {
        e.preventDefault();
        e.stopPropagation();
        seekRelative(-10);
        return;
      }

      // Seeking forward +10s
      if (key === 'ArrowRight' || code === 'ArrowRight' || key === 'l' || key === 'L' || code === 'KeyL') {
        e.preventDefault();
        e.stopPropagation();
        seekRelative(10);
        return;
      }

      // Play / Pause
      if (key === ' ' || code === 'Space' || key === 'k' || key === 'K' || code === 'KeyK') {
        e.preventDefault();
        e.stopPropagation();
        togglePlay();
        return;
      }

      // Fullscreen
      if (key === 'f' || key === 'F' || code === 'KeyF') {
        e.preventDefault();
        e.stopPropagation();
        toggleFullscreen();
        return;
      }

      // Mute / Unmute
      if (key === 'm' || key === 'M' || code === 'KeyM') {
        e.preventDefault();
        e.stopPropagation();
        toggleMute();
        return;
      }

      // Volume Up
      if (key === 'ArrowUp' || code === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        const nextVol = Math.min(1, Math.round((volume + 0.1) * 100) / 100);
        handleVolumeChange({ target: { value: nextVol } });
        return;
      }

      // Volume Down
      if (key === 'ArrowDown' || code === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        const nextVol = Math.max(0, Math.round((volume - 0.1) * 100) / 100);
        handleVolumeChange({ target: { value: nextVol } });
        return;
      }

      // Escape
      if (key === 'Escape' || code === 'Escape') {
        if (!document.fullscreenElement) {
          onClose();
        }
        return;
      }
    };

    // Use capture phase (true) so slider focus never intercepts Left/Right arrows
    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [isOpen, onClose, toggleFullscreen, togglePlay, seekRelative, toggleMute, volume]);

  const togglePip = async () => {
    const v = videoRef.current;
    if (!v) return;
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
        setIsPipActive(false);
      } else {
        await v.requestPictureInPicture();
        setIsPipActive(true);
      }
    } catch (e) {
      console.warn('PiP unavailable', e);
    }
  };

  const toggleLoop = () => {
    setIsLooping((prev) => {
      const next = !prev;
      if (videoRef.current) {
        videoRef.current.loop = next;
      }
      if (audioRef.current) {
        audioRef.current.loop = next;
      }
      return next;
    });
  };

  // Video Click / Double-click handling (seek left/right or toggle fullscreen)
  const handleVideoClickArea = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const width = rect.width;

    if (e.detail === 2) {
      if (clickX < width * 0.35) {
        seekRelative(-10);
      } else if (clickX > width * 0.65) {
        seekRelative(10);
      } else {
        toggleFullscreen();
      }
    } else if (e.detail === 1) {
      togglePlay();
    }
  };

  // Close handler
  const handleModalClose = () => {
    if (bufferingTimerRef.current) {
      clearTimeout(bufferingTimerRef.current);
      bufferingTimerRef.current = null;
    }
    if (audioSeekTimerRef.current) {
      clearTimeout(audioSeekTimerRef.current);
      audioSeekTimerRef.current = null;
    }
    if (audioStallTimerRef.current) {
      clearTimeout(audioStallTimerRef.current);
      audioStallTimerRef.current = null;
    }
    if (document.fullscreenElement) {
      try {
        document.exitFullscreen().catch(() => {});
      } catch (e) {}
    }
    if (videoRef.current) {
      try {
        videoRef.current.pause();
        videoRef.current.currentTime = 0;
      } catch (e) {}
    }
    if (audioRef.current) {
      try {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
      } catch (e) {}
    }
    if (eventSourceCancelRef.current) {
      eventSourceCancelRef.current();
      eventSourceCancelRef.current = null;
    }
    setIsPlaying(false);
    setHasStartedPlaying(false);
    setCurrentTime(0);
    setScrubTime(0);
    pendingSeekTimeRef.current = null;
    wasPlayingRef.current = false;
    accumulatedSeekRef.current = 0;
    onClose();
  };

  if (!metadata) return null;

  const isFlezen = metadata?.platform === 'Flezen Cloud' || metadata?.source_type === 'flezen';
  const progressPercent = duration > 0 ? Math.min(100, Math.max(0, ((isScrubbing ? scrubTime : currentTime) / duration) * 100)) : 0;

  // Whether controls should be visible
  const areControlsVisible = !isFullscreen || showControls || isScrubbing || !isPlaying;

  return (
    <div
      className={
        isOpen
          ? 'fixed inset-0 z-50 flex items-center justify-center p-1 sm:p-2 md:p-3 bg-slate-950/90 backdrop-blur-md animate-fadeIn'
          : 'hidden'
      }
      role="dialog"
      aria-modal="true"
      aria-hidden={!isOpen}
    >
      {/* Massive Cinema-Sized Modal Container */}
      <div className="relative w-full max-w-[98vw] xl:max-w-[1550px] 2xl:max-w-[1750px] h-[94vh] max-h-[96vh] glass-panel rounded-2xl border border-slate-700/80 shadow-2xl overflow-hidden flex flex-col">
        {/* Compact Header Bar (shown in windowed mode) */}
        {!isFullscreen && (
          <div className="flex-shrink-0 flex items-center justify-between px-4 sm:px-6 py-2 border-b border-slate-800 bg-slate-900/90">
            <div className="flex items-center gap-3 min-w-0 pr-4">
              <span className="flex-shrink-0 px-2.5 py-0.5 rounded text-[11px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                {metadata.platform || 'Media Player'}
              </span>
              <div className="min-w-0">
                <h3 className="text-sm sm:text-base font-semibold text-white truncate leading-tight">
                  {metadata.title}
                </h3>
                {metadata.uploader && (
                  <p className="text-[11px] text-slate-400 truncate">by {metadata.uploader}</p>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                type="button"
                onClick={handleModalClose}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                aria-label="Close video player"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        )}

        {/* Unified Player Container (Video Viewport + Scrubber + Controls) */}
        <div
          ref={playerContainerRef}
          tabIndex={0}
          className={
            isFullscreen
              ? 'fixed inset-0 z-[100] w-screen h-screen bg-black flex flex-col justify-between overflow-hidden select-none cursor-default outline-none'
              : 'relative w-full flex-1 min-h-0 bg-black flex flex-col overflow-hidden select-none outline-none'
          }
          onMouseMove={handleUserActivity}
          onMouseEnter={handleUserActivity}
        >
          {/* Fullscreen Top Overlay Bar (auto-hides on idle) */}
          {isFullscreen && (
            <div
              className={`absolute top-0 left-0 right-0 z-40 bg-gradient-to-b from-black/90 via-black/60 to-transparent px-4 sm:px-8 py-4 flex items-center justify-between transition-opacity duration-300 ${
                areControlsVisible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
              }`}
            >
              <div className="flex items-center gap-3 min-w-0 pr-4">
                <span className="flex-shrink-0 px-2.5 py-0.5 rounded text-[11px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                  {metadata.platform || 'Media Player'}
                </span>
                <div className="min-w-0">
                  <h3 className="text-base sm:text-lg font-bold text-white truncate drop-shadow-md">
                    {metadata.title}
                  </h3>
                  {metadata.uploader && (
                    <p className="text-xs text-slate-300 truncate">by {metadata.uploader}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={toggleFullscreen}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900/80 hover:bg-slate-800 text-white border border-slate-700 text-xs font-semibold backdrop-blur-md transition-all shadow-lg"
                  title="Exit Fullscreen (Esc / F)"
                >
                  <Minimize className="w-4 h-4 text-emerald-400" />
                  <span>Exit Fullscreen</span>
                </button>
              </div>
            </div>
          )}

          {/* Video Viewport Area */}
          <div
            className={
              isFullscreen
                ? 'absolute inset-0 w-full h-full flex items-center justify-center cursor-pointer'
                : 'relative w-full flex-1 min-h-0 bg-black flex items-center justify-center overflow-hidden cursor-pointer'
            }
            onClick={handleVideoClickArea}
          >
            <video
              ref={videoRef}
              src={isHlsStream ? undefined : (streamSrc || undefined)}
              poster={metadata?.thumbnail_proxy || metadata?.thumbnail || ''}
              className="w-full h-full object-contain"
              playsInline
              webkit-playsinline="true"
              preload="auto"
              muted={isMuted}
              onPlay={() => {
                setIsPlaying(true);
                setHasStartedPlaying(true);
                if (audioRef.current && needsSeparateAudio && audioRef.current.paused) {
                  audioRef.current.play().catch(() => {});
                }
              }}
              onPause={() => {
                setIsPlaying(false);
                if (audioRef.current && needsSeparateAudio) {
                  audioRef.current.pause();
                }
              }}
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={handleLoadedMetadata}
              onCanPlay={handleCanPlay}
              onSeeking={() => {
                isSeekingRef.current = true;
              }}
              onSeeked={() => {
                isSeekingRef.current = false;
                if (bufferingTimerRef.current) {
                  clearTimeout(bufferingTimerRef.current);
                  bufferingTimerRef.current = null;
                }
                setIsBuffering(false);
                const a = audioRef.current;
                const v = videoRef.current;
                if (v && wasPlayingRef.current) {
                  v.play().catch(() => {});
                }
                if (a && needsSeparateAudio && v) {
                  if (wasPlayingRef.current || !v.paused) {
                    a.play().catch(() => {});
                  }
                }
              }}
              onWaiting={handleWaiting}
              onPlaying={handlePlaying}
              onRateChange={() => {
                if (audioRef.current && videoRef.current) {
                  audioRef.current.playbackRate = videoRef.current.playbackRate;
                }
              }}
            />

            {/* Synchronized Audio Stream with resilient seek & stall recovery */}
            {needsSeparateAudio && audioSrc && (
              <audio
                ref={audioRef}
                src={audioSrc}
                preload="auto"
                muted={isMuted}
                onSeeked={() => {
                  const a = audioRef.current;
                  const v = videoRef.current;
                  if (a && v && !v.paused) {
                    a.play().catch(() => {});
                  }
                }}
                onCanPlay={() => {
                  const a = audioRef.current;
                  const v = videoRef.current;
                  if (a && v && !v.paused) {
                    a.play().catch(() => {});
                  }
                }}
                onWaiting={() => {
                  if (audioStallTimerRef.current) clearTimeout(audioStallTimerRef.current);
                  audioStallTimerRef.current = setTimeout(() => {
                    const a = audioRef.current;
                    const v = videoRef.current;
                    if (a && v && !v.paused) {
                      a.play().catch(() => {});
                    }
                  }, 200);
                }}
                onStalled={() => {
                  if (audioStallTimerRef.current) clearTimeout(audioStallTimerRef.current);
                  audioStallTimerRef.current = setTimeout(() => {
                    const a = audioRef.current;
                    const v = videoRef.current;
                    if (a && v && !v.paused) {
                      if (a.readyState >= 1) {
                        a.play().catch(() => {});
                      } else {
                        a.load();
                        a.currentTime = v.currentTime;
                        a.play().catch(() => {});
                      }
                    }
                  }, 300);
                }}
                onError={() => {
                  const a = audioRef.current;
                  const v = videoRef.current;
                  if (a && v) {
                    a.load();
                    a.currentTime = v.currentTime;
                    if (!v.paused) a.play().catch(() => {});
                  }
                }}
              />
            )}

            {/* Seek ripple feedback */}
            {seekFeedback && (
              <div className="absolute z-30 flex items-center justify-center px-4 py-2 rounded-full bg-slate-950/80 border border-slate-700 text-white font-mono text-base font-bold backdrop-blur-md animate-scaleIn pointer-events-none">
                {seekFeedback}
              </div>
            )}

            {/* Buffering Loading Indicator */}
            {isBuffering && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/40 pointer-events-none z-20 transition-opacity duration-200">
                <Loader2 className="w-12 h-12 text-emerald-400 animate-spin" />
                <span className="mt-3 text-xs font-semibold text-slate-200">Buffering media stream...</span>
              </div>
            )}

            {/* Floating Unmute Banner (if browser blocked unmuted autoplay) */}
            {isMuted && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleMute();
                }}
                className="absolute top-4 left-4 z-30 flex items-center gap-2 px-3.5 py-2 rounded-full bg-amber-500 hover:bg-amber-400 text-slate-950 text-xs font-bold shadow-xl transition-all animate-bounce"
                title="Click anywhere to enable audio"
              >
                <VolumeX className="w-4 h-4 fill-current" />
                <span>Click Anywhere to Unmute Sound</span>
              </button>
            )}

            {/* Dedicated Flezen Cloud Access Overlay */}
            {isFlezen && (
              <div className="absolute inset-0 bg-slate-950/95 flex flex-col items-center justify-center p-6 text-center z-30">
                <div className="w-16 h-16 rounded-2xl bg-purple-600/20 border border-purple-500/40 flex items-center justify-center mb-4 shadow-lg shadow-purple-500/20">
                  <ShieldCheck className="w-8 h-8 text-purple-400" />
                </div>
                <h3 className="text-xl font-bold text-white mb-1">
                  Flezen Cloud Media Access
                </h3>
                <p className="text-xs sm:text-sm text-slate-300 max-w-lg mb-2">
                  <span className="font-semibold text-white">{metadata.title}</span>
                  {selectedQuality?.filesize_display && (
                    <span className="ml-2 px-2 py-0.5 rounded-full bg-slate-800 text-purple-300 border border-purple-500/30 text-[11px] font-mono">
                      {selectedQuality.filesize_display}
                    </span>
                  )}
                </p>
                <div className="max-w-md text-xs text-slate-400 mb-6 bg-slate-900/80 border border-slate-800 rounded-xl p-3 text-left space-y-1.5">
                  <div className="flex items-center gap-2 text-purple-400 font-semibold">
                    <span>How to access this file</span>
                  </div>
                  <p>
                    Flezen locks files behind their Android app and monetization ad walls. Web browsers cannot stream the raw video directly, but you can launch the app or bypass via their Telegram resolver with 1 click:
                  </p>
                </div>

                <div className="flex flex-wrap items-center justify-center gap-3 w-full max-w-md">
                  <a
                    href={`flezen://flezen.com/s/${metadata.url.split('/s/')[1] || ''}`}
                    onClick={() => {
                      setTimeout(() => {
                        window.open('https://play.google.com/store/apps/details?id=com.devlooper.flezen', '_blank');
                      }, 1200);
                    }}
                    className="flex-1 min-w-[180px] flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs sm:text-sm font-bold shadow-lg shadow-purple-600/30 transition-all hover:scale-[1.02] active:scale-95"
                  >
                    <span>⚡ Open in Flezen App</span>
                  </a>

                  <a
                    href={`https://t.me/flezendl101_bot?start=${metadata.url.split('/s/')[1] || ''}`}
                    target="_blank"
                    rel="noreferrer"
                    className="flex-1 min-w-[180px] flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs sm:text-sm font-bold shadow-lg shadow-sky-600/30 transition-all hover:scale-[1.02] active:scale-95"
                  >
                    <span>🤖 Telegram Fast Bypass</span>
                  </a>

                  <a
                    href="https://play.google.com/store/apps/details?id=com.devlooper.flezen"
                    target="_blank"
                    rel="noreferrer"
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-semibold transition-all"
                  >
                    <span>📲 Install Flezen App from Google Play</span>
                  </a>
                </div>
              </div>
            )}
          </div>

          {/* Bottom Controls Wrapper (Overlay in Fullscreen, docked in Windowed) */}
          <div
            className={
              isFullscreen
                ? `absolute bottom-0 left-0 right-0 z-40 bg-gradient-to-t from-black/95 via-black/85 to-transparent px-4 sm:px-8 pt-8 pb-4 flex flex-col gap-2 transition-opacity duration-300 ${
                    areControlsVisible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
                  }`
                : 'flex-shrink-0 bg-slate-900/95 border-t border-slate-800/80 flex flex-col'
            }
          >
            {/* Timeline Scrubber Bar (Full seeking support with butter-smooth gradient and live hover) */}
            <div className="w-full px-2 sm:px-4 pt-1.5 pb-1 select-none">
              <div
                className="relative w-full flex items-center group h-6 cursor-pointer"
                onMouseMove={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
                  const pct = rect.width > 0 ? x / rect.width : 0;
                  setHoverSeekPos(x);
                  setHoverSeekTime(pct * (duration || 0));
                }}
                onMouseLeave={() => setHoverSeekTime(null)}
              >
                {/* Floating hover time indicator badge */}
                {hoverSeekTime !== null && duration > 0 && (
                  <div
                    className="absolute -top-7 -translate-x-1/2 px-2 py-0.5 rounded-md bg-slate-900/95 border border-slate-700 text-[11px] font-mono font-bold text-emerald-400 shadow-xl pointer-events-none z-30 backdrop-blur-sm"
                    style={{ left: `${hoverSeekPos}px` }}
                  >
                    {formatTime(hoverSeekTime)}
                  </div>
                )}

                {/* Track visual container */}
                <div className="w-full h-2 sm:h-2.5 group-hover:h-3.5 bg-slate-800/90 rounded-full overflow-hidden relative transition-all duration-200 shadow-inner">
                  {/* Played progress fill */}
                  <div
                    className="h-full bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 rounded-full transition-[width] duration-75 ease-out shadow-[0_0_12px_rgba(16,185,129,0.5)]"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>

                {/* Scrubber thumb handle */}
                <div
                  className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full bg-emerald-400 border-2 border-white shadow-[0_0_8px_rgba(16,185,129,0.8)] pointer-events-none transition-transform duration-100 group-hover:scale-125"
                  style={{ left: `${progressPercent}%` }}
                />

                {/* Actual transparent range input handling interactions */}
                <input
                  type="range"
                  min="0"
                  max={duration || 100}
                  step="0.05"
                  value={isScrubbing ? scrubTime : currentTime}
                  onChange={handleSeekChange}
                  onMouseDown={handleSeekStart}
                  onMouseUp={handleSeekEnd}
                  onTouchStart={handleSeekStart}
                  onTouchEnd={handleSeekEnd}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-20 focus:outline-none"
                  aria-label="Seek video position"
                />
              </div>
            </div>

            {/* Control & Action Bar */}
            <div className="px-2 sm:px-4 py-1.5 flex flex-wrap items-center justify-between gap-2">
              {/* Left Group: Play/Pause, -10s, +10s, Volume, Time Display */}
              <div className="flex items-center gap-1.5 sm:gap-2">
                <button
                  type="button"
                  onClick={togglePlay}
                  className="p-2 rounded-xl bg-emerald-500 text-slate-950 hover:bg-emerald-400 font-bold transition-all active:scale-95 shadow-md shadow-emerald-500/20"
                  title={isPlaying ? 'Pause (Space / K)' : 'Play (Space / K)'}
                  aria-label={isPlaying ? 'Pause' : 'Play'}
                >
                  {isPlaying ? (
                    <Pause className="w-4 h-4 fill-current" />
                  ) : (
                    <Play className="w-4 h-4 fill-current ml-0.5" />
                  )}
                </button>

                {/* Rewind 10s */}
                <button
                  type="button"
                  onClick={() => seekRelative(-10)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white border border-slate-700 text-xs font-semibold transition-all active:scale-95 shadow-sm"
                  title="Rewind 10 seconds (Left Arrow / J)"
                >
                  <RotateCcw className="w-3.5 h-3.5 text-cyan-400" />
                  <span>-10s</span>
                </button>

                {/* Fast-Forward 10s */}
                <button
                  type="button"
                  onClick={() => seekRelative(10)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white border border-slate-700 text-xs font-semibold transition-all active:scale-95 shadow-sm"
                  title="Fast-forward 10 seconds (Right Arrow / L)"
                >
                  <RotateCw className="w-3.5 h-3.5 text-cyan-400" />
                  <span>+10s</span>
                </button>

                {/* Volume Toggle */}
                <button
                  type="button"
                  onClick={toggleMute}
                  className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition-colors"
                  title={isMuted ? 'Unmute (M)' : 'Mute (M)'}
                >
                  {isMuted ? (
                    <VolumeX className="w-3.5 h-3.5 text-amber-400" />
                  ) : (
                    <Volume2 className="w-3.5 h-3.5 text-slate-300" />
                  )}
                </button>

                {/* Volume Slider */}
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={isMuted ? 0 : volume}
                  onChange={handleVolumeChange}
                  className="hidden md:block w-16 sm:w-20 h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-emerald-500 focus:outline-none"
                  aria-label="Volume slider"
                />

                {/* Time Display: 00:00 / MM:SS */}
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800/90 border border-slate-700 font-mono text-xs font-semibold text-slate-200 shadow-inner">
                  <Clock className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-white font-bold">{formatTime(isScrubbing ? scrubTime : currentTime)}</span>
                  <span className="text-slate-500">/</span>
                  <span className="text-slate-400">{formatTime(duration || metadata?.duration_seconds || 0)}</span>
                </div>
              </div>

              {/* Right Group: Quality Selector, Loop, PiP, Fullscreen, Download, Close */}
              <div className="flex flex-wrap items-center gap-2 ml-auto">
                {/* Resolution Selector Dropdown */}
                {displayQualities.length > 0 && (
                  <div className="relative inline-flex items-center">
                    <select
                      value={selectedQuality?.height || selectedQuality?.format_id || selectedQuality?.quality_label || ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        const matched = displayQualities.find(
                          (q) => String(q.height) === val || q.format_id === val || q.quality_label === val
                        );
                        if (matched) handleQualityChange(matched);
                      }}
                      className="appearance-none bg-slate-800 hover:bg-slate-750 text-white pl-3 pr-8 py-1.5 rounded-xl border border-slate-700 text-xs font-semibold focus:outline-none focus:border-emerald-500 cursor-pointer shadow-sm"
                      title="Switch video quality / resolution"
                    >
                      {displayQualities.map((q, idx) => (
                        <option key={idx} value={q.height || q.format_id || q.quality_label}>
                          {q.quality_label || `${q.height}p`}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 pointer-events-none" />
                  </div>
                )}

                <button
                  type="button"
                  onClick={toggleLoop}
                  className={`flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                    isLooping
                      ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40'
                      : 'bg-slate-800 text-slate-300 border-slate-700 hover:text-white'
                  }`}
                  title="Toggle looping"
                >
                  <Repeat className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">{isLooping ? 'Loop On' : 'Loop'}</span>
                </button>

                <button
                  type="button"
                  onClick={togglePip}
                  className={`flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                    isPipActive
                      ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40'
                      : 'bg-slate-800 text-slate-300 border-slate-700 hover:text-white'
                  }`}
                  title="Picture-in-Picture (Hotkey: P)"
                >
                  <PictureInPicture className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">PiP</span>
                </button>

                {/* Direct Fullscreen Button */}
                <button
                  type="button"
                  onClick={toggleFullscreen}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 text-xs font-semibold transition-all active:scale-95 shadow-sm"
                  title={isFullscreen ? 'Exit Fullscreen (Hotkey: F / Esc)' : 'Fullscreen (Hotkey: F)'}
                >
                  {isFullscreen ? (
                    <>
                      <Minimize className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Exit Fullscreen</span>
                    </>
                  ) : (
                    <>
                      <Maximize className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Fullscreen</span>
                    </>
                  )}
                </button>

                {/* Direct Download Button */}
                {downloadSrc && (
                  <a
                    href={downloadSrc}
                    download={mediaInfo?.filename || 'video.mp4'}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all"
                    title="Download this video directly"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download MP4</span>
                  </a>
                )}

                {!isFullscreen && (
                  <button
                    type="button"
                    onClick={handleModalClose}
                    className="px-3 py-1.5 rounded-xl text-xs font-medium text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 transition-colors"
                  >
                    Close
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

export default VideoPlayerModal;
