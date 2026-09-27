import React from 'react';
import { Clock, User, Layers, Video, ShieldCheck, ExternalLink } from 'lucide-react';
import QualitySelector from './QualitySelector';

export default function MediaMetadataCard({
  metadata,
  onDownload,
  isDownloading,
  recommendedQuality,
  selectedQuality,
  setSelectedQuality,
}) {
  if (!metadata) return null;

  const {
    title,
    thumbnail,
    duration_formatted,
    uploader,
    platform,
    description,
    available_qualities,
    extraction_tier,
    url,
  } = metadata;

  const tierLabels = {
    1: 'Tier 1: yt-dlp Native Extractor',
    2: 'Tier 2: Direct Media Stream',
    3: 'Tier 3: Embedded HTML5 Scraper',
    4: 'Tier 4: Headless Browser Render (Playwright)',
  };

  return (
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

        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>SSRF Verified Safe</span>
        </div>
      </div>

      {/* Main Content Layout */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        
        {/* Left: Thumbnail & Duration */}
        <div className="md:col-span-5 flex flex-col">
          <div className="relative aspect-video w-full rounded-xl overflow-hidden bg-slate-900 border border-slate-800 group shadow-md">
            {thumbnail ? (
              <img
                src={thumbnail}
                alt={title}
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                onError={(e) => {
                  e.target.style.display = 'none';
                }}
              />
            ) : (
              <div className="w-full h-full flex flex-col items-center justify-center text-slate-600 gap-2">
                <Video className="w-12 h-12" />
                <span className="text-xs">No Thumbnail Preview</span>
              </div>
            )}

            {/* Duration Badge */}
            {duration_formatted && (
              <div className="absolute bottom-2 right-2 flex items-center gap-1 px-2 py-0.5 rounded-md bg-black/80 backdrop-blur-sm text-white text-xs font-mono font-medium">
                <Clock className="w-3 h-3 text-slate-300" />
                <span>{duration_formatted}</span>
              </div>
            )}
          </div>

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
              <span>{available_qualities.length} format{available_qualities.length !== 1 ? 's' : ''} available</span>
            </div>
          </div>
        </div>

        {/* Right: Title, Description & Quality Selection */}
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
          </div>

          {/* Quality Selector */}
          <div className="mt-4 pt-4 border-t border-slate-800/80">
            <QualitySelector
              qualities={available_qualities}
              selectedQuality={selectedQuality}
              onSelectQuality={setSelectedQuality}
              recommendedQuality={recommendedQuality}
              onDownload={onDownload}
              isDownloading={isDownloading}
            />
          </div>

        </div>

      </div>

    </div>
  );
}
