import React, { useState, useRef } from 'react';
import {
  Clock,
  User,
  Layers,
  Video,
  ShieldCheck,
  Play,
  Scissors,
  ImageDown,
  Headphones,
  Subtitles,
  ChevronDown,
  ChevronUp,
  Download,
  Check,
  RotateCcw,
} from 'lucide-react';
import QualitySelector from './QualitySelector';
import VideoPlayerModal from './VideoPlayerModal';
import AudioPlayerModal from './AudioPlayerModal';

export default function MediaMetadataCard({
  metadata,
  onDownload,
  isDownloading,
  recommendedQuality,
  selectedQuality,
  setSelectedQuality,
}) {
  const [isPlayerOpen, setIsPlayerOpen] = useState(false);
  const [isAudioOpen, setIsAudioOpen] = useState(false);
  const [isTrimOpen, setIsTrimOpen] = useState(false);
  const [isSubtitlesOpen, setIsSubtitlesOpen] = useState(false);
  const videoPlayerModalRef = useRef(null);

  // Synchronous user-gesture player opening & unlocking
  const handleOpenPlayer = () => {
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

    setIsPlayerOpen(true);
    if (videoPlayerModalRef.current?.unlock) {
      videoPlayerModalRef.current.unlock();
    }
  };

  // Trimming states
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');

  if (!metadata) return null;

  const {
    title,
    thumbnail,
    thumbnail_proxy,
    duration_formatted,
    duration_seconds,
    uploader,
    platform,
    description,
    available_qualities = [],
    subtitles = [],
    extraction_tier,
  } = metadata;

  const displayThumbnail = thumbnail_proxy || thumbnail;

  const tierLabels = {
    1: 'Tier 1: yt-dlp Native Extractor',
    2: 'Tier 2: Direct Media Stream',
    3: 'Tier 3: Embedded HTML5 Scraper',
    4: 'Tier 4: Headless Browser Render (Playwright)',
  };

  const hasPlayableStream = available_qualities.some((q) => !q.is_audio_only);
  const hasAudioOption = available_qualities.some((q) => q.is_audio_only || q.stream_url);

  // Download wrapper to attach clip trimming parameters if configured
  const handleExecuteDownload = (customQuality = null) => {
    const q = customQuality || selectedQuality;
    const clipOpts = {};
    if (startTime.trim()) clipOpts.startTime = startTime.trim();
    if (endTime.trim()) clipOpts.endTime = endTime.trim();
    onDownload(q, clipOpts);
  };

  // Helper to validate timestamp format mm:ss or hh:mm:ss
  const isValidTimestamp = (val) => {
    if (!val) return true;
    return /^[0-9]+(:[0-9]{2})?(:[0-9]{2})?(\.[0-9]+)?$/.test(val.trim());
  };

  const isTrimValid = isValidTimestamp(startTime) && isValidTimestamp(endTime);

  return (
    <>
      <div className="w-full max-w-4xl mx-auto mt-8 glass-panel rounded-2xl border border-slate-700/70 p-4 sm:p-6 shadow-2xl overflow-hidden animate-fadeIn">
        
        {/* Header Info Banner */}
        <div className="flex flex-wrap items-center justify-between gap-2 pb-4 mb-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              {platform}
            </span>
            <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-300 border border-slate-700">
              {tierLabels[extraction_tier] || 'Verified Source'}
            </span>
          </div>

          <div className="flex items-center gap-3 text-xs text-slate-400">
            {subtitles && subtitles.length > 0 && (
              <span className="flex items-center gap-1 text-indigo-400 font-medium">
                <Subtitles className="w-3.5 h-3.5" />
                <span>{subtitles.length} Subtitle{subtitles.length !== 1 ? 's' : ''} Available</span>
              </span>
            )}
            <div className="flex items-center gap-1.5 text-emerald-400">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>SSRF Verified Safe</span>
            </div>
          </div>
        </div>

        {/* Main Content Layout */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
          
          {/* Left Column: Thumbnail, Duration & Quick Tools */}
          <div className="md:col-span-5 flex flex-col">
            <div
              className={`relative aspect-video w-full rounded-xl overflow-hidden bg-slate-900 border border-slate-800 group shadow-md ${
                hasPlayableStream ? 'cursor-pointer' : ''
              }`}
              onClick={() => {
                if (hasPlayableStream) handleOpenPlayer();
              }}
              title={hasPlayableStream ? 'Click to watch in-browser' : undefined}
            >
              {displayThumbnail ? (
                <img
                  src={displayThumbnail}
                  alt={title}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                  onError={(e) => {
                    // Fallback to raw thumbnail if proxy errored or vice versa
                    if (e.target.src !== thumbnail && thumbnail) {
                      e.target.src = thumbnail;
                    } else {
                      e.target.style.display = 'none';
                    }
                  }}
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center text-slate-600 gap-2">
                  <Video className="w-12 h-12" />
                  <span className="text-xs">No Thumbnail Preview</span>
                </div>
              )}

              {/* In-Browser Play Hover Overlay */}
              {hasPlayableStream && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/45 opacity-0 group-hover:opacity-100 transition-opacity backdrop-blur-[2px]">
                  <div className="w-13 h-13 rounded-full bg-emerald-500 text-slate-950 flex items-center justify-center shadow-lg shadow-emerald-500/50 hover:scale-110 transition-transform">
                    <Play className="w-6 h-6 fill-slate-950 ml-0.5" />
                  </div>
                  <span className="mt-2 text-xs font-semibold text-white drop-shadow">
                    Watch in Player
                  </span>
                </div>
              )}

              {/* Duration Badge */}
              {duration_formatted && (
                <div className="absolute bottom-2 right-2 flex items-center gap-1 px-2 py-0.5 rounded-md bg-black/80 backdrop-blur-sm text-white text-xs font-mono font-medium z-10">
                  <Clock className="w-3 h-3 text-slate-300" />
                  <span>{duration_formatted}</span>
                </div>
              )}
            </div>

            {/* Quick Action Bar under Thumbnail */}
            <div className="mt-2.5 grid grid-cols-2 gap-2 text-xs">
              {/* HD Thumbnail Download */}
              {thumbnail && (
                <a
                  href={thumbnail_proxy ? `${thumbnail_proxy}&download=1` : thumbnail}
                  download="thumbnail.jpg"
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-center gap-1.5 py-1.5 px-2.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/60 transition-all font-medium"
                  title="Download highest resolution thumbnail"
                >
                  <ImageDown className="w-3.5 h-3.5 text-cyan-400" />
                  <span>HD Thumbnail</span>
                </a>
              )}

              {/* Audio Preview Modal Trigger */}
              {hasAudioOption && (
                <button
                  type="button"
                  onClick={() => setIsAudioOpen(true)}
                  className="flex items-center justify-center gap-1.5 py-1.5 px-2.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/60 transition-all font-medium"
                  title="Listen to audio track with visualizer"
                >
                  <Headphones className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Audio Preview</span>
                </button>
              )}
            </div>

            {/* Subtitles (CC) Dropdown Button */}
            {subtitles && subtitles.length > 0 && (
              <div className="mt-2 relative">
                <button
                  type="button"
                  onClick={() => setIsSubtitlesOpen((p) => !p)}
                  className="w-full flex items-center justify-between py-1.5 px-3 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-xs font-medium transition-all"
                >
                  <div className="flex items-center gap-1.5">
                    <Subtitles className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Download Subtitles ({subtitles.length})</span>
                  </div>
                  {isSubtitlesOpen ? (
                    <ChevronUp className="w-3.5 h-3.5" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5" />
                  )}
                </button>

                {/* Subtitles list popup */}
                {isSubtitlesOpen && (
                  <div className="mt-1.5 p-2 rounded-xl bg-slate-900 border border-indigo-500/30 shadow-xl max-h-48 overflow-y-auto space-y-1 animate-fadeIn">
                    {subtitles.map((sub, idx) => (
                      <a
                        key={idx}
                        href={`${sub.proxy_url}&download=1`}
                        download={`${sub.name || 'subtitles'}.vtt`}
                        className="flex items-center justify-between p-1.5 rounded-lg hover:bg-indigo-500/20 text-xs text-slate-300 hover:text-white transition-colors"
                      >
                        <span className="truncate pr-2 font-medium">{sub.name}</span>
                        <div className="flex items-center gap-1 flex-shrink-0 text-[10px] text-indigo-400 font-mono">
                          <span className="uppercase">{sub.ext || 'VTT'}</span>
                          <Download className="w-3 h-3" />
                        </div>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Meta Attributes */}
            <div className="mt-3 flex items-center justify-between text-xs text-slate-400 px-1">
              {uploader && (
                <div className="flex items-center gap-1.5 truncate">
                  <User className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
                  <span className="truncate font-medium text-slate-300">{uploader}</span>
                </div>
              )}
              <div className="flex items-center gap-1 text-slate-500">
                <Layers className="w-3.5 h-3.5" />
                <span>
                  {available_qualities.length} format{available_qualities.length !== 1 ? 's' : ''}
                </span>
              </div>
            </div>
          </div>

          {/* Right Column: Title, Description, Trimmer & Quality Selector */}
          <div className="md:col-span-7 flex flex-col justify-between">
            <div>
              <h2 className="text-lg sm:text-xl font-bold text-white leading-snug line-clamp-2">
                {title}
              </h2>

              {description && (
                <p className="mt-2 text-xs sm:text-sm text-slate-400 line-clamp-2 leading-relaxed">
                  {description}
                </p>
              )}

              {/* Special Flezen App & Telegram Bypass Quick Actions */}
              {(platform === 'Flezen Cloud' || metadata.source_type === 'flezen') && (
                <div className="mt-3 p-3.5 rounded-xl bg-purple-950/40 border border-purple-500/30 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-purple-300 flex items-center gap-1.5">
                      <ShieldCheck className="w-4 h-4 text-purple-400" />
                      <span>Flezen Cloud Media Access</span>
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30 font-medium">
                      App-Locked File
                    </span>
                  </div>
                  <p className="text-xs text-slate-300">
                    Flezen requires their Android app or Telegram bot to decrypt and access this video. Choose an instant 1-click option:
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                    <a
                      href={`flezen://flezen.com/s/${metadata.url.split('/s/')[1] || ''}`}
                      onClick={() => {
                        setTimeout(() => {
                          window.open('https://play.google.com/store/apps/details?id=com.devlooper.flezen', '_blank');
                        }, 1200);
                      }}
                      className="flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold shadow-md transition-all active:scale-95"
                    >
                      <span>⚡ Open in Flezen App</span>
                    </a>
                    <a
                      href={`https://t.me/flezendl101_bot?start=${metadata.url.split('/s/')[1] || ''}`}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-bold shadow-md transition-all active:scale-95"
                    >
                      <span>🤖 Telegram Fast Bot</span>
                    </a>
                  </div>
                </div>
              )}
            </div>

            {/* Video Clip Trimmer Collapsible Panel */}
            <div className="mt-4 pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setIsTrimOpen((p) => !p)}
                className="w-full flex items-center justify-between py-1.5 px-3 rounded-xl bg-slate-900/60 hover:bg-slate-900 border border-slate-800 hover:border-slate-700 text-xs text-slate-300 transition-all font-medium"
              >
                <div className="flex items-center gap-2">
                  <Scissors className={`w-3.5 h-3.5 ${startTime || endTime ? 'text-emerald-400' : 'text-slate-400'}`} />
                  <span>Trim Video / Audio Clip</span>
                  {(startTime || endTime) && (
                    <span className="px-1.5 py-0.2 rounded-full bg-emerald-500/20 text-emerald-400 font-mono text-[10px]">
                      {startTime || '00:00'} → {endTime || 'End'}
                    </span>
                  )}
                </div>
                {isTrimOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>

              {/* Trimmer Inputs */}
              {isTrimOpen && (
                <div className="mt-2.5 p-3 rounded-xl bg-slate-900/90 border border-slate-700/60 text-xs animate-fadeIn space-y-2.5">
                  <div className="flex items-center justify-between text-slate-400">
                    <span className="font-semibold text-slate-200">Custom Clip Timestamps</span>
                    <span className="text-[11px] text-slate-500">Format: hh:mm:ss or mm:ss</span>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">Start Time</label>
                      <input
                        type="text"
                        placeholder="00:00:15"
                        value={startTime}
                        onChange={(e) => setStartTime(e.target.value)}
                        className={`w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border ${
                          isValidTimestamp(startTime) ? 'border-slate-700 text-white' : 'border-rose-500 text-rose-300'
                        } text-xs font-mono outline-none focus:border-emerald-500`}
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">End Time</label>
                      <input
                        type="text"
                        placeholder="00:01:30"
                        value={endTime}
                        onChange={(e) => setEndTime(e.target.value)}
                        className={`w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border ${
                          isValidTimestamp(endTime) ? 'border-slate-700 text-white' : 'border-rose-500 text-rose-300'
                        } text-xs font-mono outline-none focus:border-emerald-500`}
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-1 text-[11px] text-slate-500">
                    <span>Downloads only the specified segment without fetching entire file</span>
                    {(startTime || endTime) && (
                      <button
                        type="button"
                        onClick={() => {
                          setStartTime('');
                          setEndTime('');
                        }}
                        className="flex items-center gap-1 text-slate-400 hover:text-rose-400 transition-colors"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Reset</span>
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Quality Selector */}
            <div className="mt-4 pt-4 border-t border-slate-800/80">
              <QualitySelector
                qualities={available_qualities}
                selectedQuality={selectedQuality}
                onSelectQuality={setSelectedQuality}
                recommendedQuality={recommendedQuality}
                onDownload={() => handleExecuteDownload()}
                onPlay={hasPlayableStream ? handleOpenPlayer : null}
                isDownloading={isDownloading}
              />
            </div>

          </div>

        </div>

      </div>

      {/* Video Player Modal */}
      {metadata && (
        <VideoPlayerModal
          ref={videoPlayerModalRef}
          isOpen={isPlayerOpen}
          onClose={() => setIsPlayerOpen(false)}
          metadata={metadata}
          initialSelectedQuality={selectedQuality}
          onDownload={() => handleExecuteDownload()}
        />
      )}

      {/* Audio Player Modal */}
      {isAudioOpen && (
        <AudioPlayerModal
          isOpen={isAudioOpen}
          onClose={() => setIsAudioOpen(false)}
          metadata={metadata}
          audioTrack={selectedQuality?.is_audio_only ? selectedQuality : null}
          onDownload={() => handleExecuteDownload()}
        />
      )}
    </>
  );
}
