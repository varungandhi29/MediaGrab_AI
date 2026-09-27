import React from 'react';
import { Download, Music, Check, Sparkles, HardDrive, Loader2 } from 'lucide-react';

export default function QualitySelector({
  qualities = [],
  selectedQuality,
  onSelectQuality,
  recommendedQuality,
  onDownload,
  isDownloading,
}) {
  if (!qualities || qualities.length === 0) {
    return (
      <div className="text-sm text-slate-400 py-3">
        No compatible formats discovered for this link.
      </div>
    );
  }

  // Separate video and audio options
  const videoQualities = qualities.filter(q => !q.is_audio_only);
  const audioQualities = qualities.filter(q => q.is_audio_only);

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Select Format & Resolution
          </label>
          <span className="text-[11px] text-slate-500">Genuinely available streams only</span>
        </div>

        {/* Video Resolutions Grid */}
        {videoQualities.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {videoQualities.map((item) => {
              const isSelected = selectedQuality?.format_id === item.format_id;
              const isRecommended = recommendedQuality && item.quality_label.toLowerCase().includes(recommendedQuality.toLowerCase().split(' ')[0]);

              return (
                <button
                  key={item.format_id}
                  type="button"
                  disabled={isDownloading}
                  onClick={() => onSelectQuality(item)}
                  className={`relative flex flex-col p-2.5 rounded-xl border text-left transition-all ${
                    isSelected
                      ? 'bg-emerald-500/10 border-emerald-500 text-white shadow-lg shadow-emerald-500/10'
                      : 'bg-slate-900/60 border-slate-800 hover:border-slate-700 text-slate-300'
                  }`}
                >
                  {/* AI Recommendation Badge */}
                  {isRecommended && (
                    <span className="absolute -top-2 right-2 px-1.5 py-0.5 rounded-full bg-cyan-500 text-slate-950 font-bold text-[9px] flex items-center gap-0.5 shadow-sm">
                      <Sparkles className="w-2.5 h-2.5" /> AI Pick
                    </span>
                  )}

                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-sm">{item.quality_label}</span>
                    {isSelected && <Check className="w-4 h-4 text-emerald-400" />}
                  </div>

                  <div className="mt-1 flex items-center justify-between text-[11px] text-slate-400">
                    <span className="uppercase text-[10px] font-mono px-1 py-0.2 rounded bg-slate-800 text-slate-300">
                      {item.ext}
                    </span>
                    {item.filesize_display && (
                      <span className="text-slate-400">{item.filesize_display}</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* Audio Option */}
        {audioQualities.length > 0 && (
          <div className="mt-2.5">
            {audioQualities.map((item) => {
              const isSelected = selectedQuality?.format_id === item.format_id;
              const isRecommended = recommendedQuality && recommendedQuality.toLowerCase().includes('audio');

              return (
                <button
                  key={item.format_id}
                  type="button"
                  disabled={isDownloading}
                  onClick={() => onSelectQuality(item)}
                  className={`w-full relative flex items-center justify-between p-2.5 rounded-xl border transition-all ${
                    isSelected
                      ? 'bg-cyan-500/10 border-cyan-500 text-white shadow-lg shadow-cyan-500/10'
                      : 'bg-slate-900/60 border-slate-800 hover:border-slate-700 text-slate-300'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-lg bg-cyan-500/20 text-cyan-400 flex items-center justify-center">
                      <Music className="w-4 h-4" />
                    </div>
                    <div className="text-left">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-sm">{item.quality_label}</span>
                        {isRecommended && (
                          <span className="px-1.5 py-0.2 rounded-full bg-cyan-500 text-slate-950 font-bold text-[9px] flex items-center gap-0.5">
                            <Sparkles className="w-2.5 h-2.5" /> AI Pick
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-slate-400">Extracts 320kbps high-fidelity MP3 track</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-cyan-300">
                      MP3
                    </span>
                    {isSelected && <Check className="w-4 h-4 text-cyan-400" />}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Primary Action Button */}
      <button
        type="button"
        disabled={isDownloading || !selectedQuality}
        onClick={onDownload}
        className="w-full flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-slate-950 font-bold text-base shadow-xl shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-emerald-500/35 transition-all duration-200"
      >
        {isDownloading ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>Processing Download...</span>
          </>
        ) : (
          <>
            <Download className="w-5 h-5" />
            <span>Download {selectedQuality?.quality_label || 'Selected'}</span>
          </>
        )}
      </button>
    </div>
  );
}
