import React from 'react';
import { History, Download, Trash2, ArrowUpRight, Film, Music, Clock } from 'lucide-react';
import { getFileDownloadUrl } from '../services/api';

export default function DownloadHistory({
  history = [],
  onClearHistory,
  onRemoveItem,
  onReopenUrl,
}) {
  const formatTime = (isoString) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString();
    } catch (e) {
      return 'Recently';
    }
  };

  const formatBytes = (bytes) => {
    if (!bytes) return null;
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
  };

  return (
    <div className="w-full max-w-4xl mx-auto mt-6 glass-panel rounded-2xl border border-slate-700/70 p-6 shadow-2xl animate-fadeIn">
      
      {/* Header */}
      <div className="flex items-center justify-between pb-4 mb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <History className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-bold text-white">Session Download History</h2>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
            {history.length} {history.length === 1 ? 'item' : 'items'}
          </span>
        </div>

        {history.length > 0 && (
          <button
            onClick={onClearHistory}
            className="flex items-center gap-1.5 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-950/30 px-3 py-1.5 rounded-lg border border-rose-500/20 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Clear History</span>
          </button>
        )}
      </div>

      {/* History Items List */}
      {history.length === 0 ? (
        <div className="py-12 text-center text-slate-500 space-y-2">
          <History className="w-10 h-10 mx-auto text-slate-600" />
          <p className="text-sm font-medium text-slate-400">No downloads recorded yet in this session.</p>
          <p className="text-xs text-slate-500">Paste a URL above to start grabbing media.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {history.map((item) => {
            const isAudio = item.quality?.toLowerCase().includes('audio') || item.quality?.toLowerCase().includes('mp3');

            return (
              <div
                key={item.id}
                className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-colors"
              >
                {/* Media Details */}
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-lg bg-slate-800 text-slate-300 flex items-center justify-center flex-shrink-0 border border-slate-700">
                    {isAudio ? <Music className="w-5 h-5 text-cyan-400" /> : <Film className="w-5 h-5 text-emerald-400" />}
                  </div>

                  <div className="min-w-0">
                    <div className="font-semibold text-sm text-white truncate max-w-sm sm:max-w-md">
                      {item.title}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
                      <span className="font-medium text-emerald-400">{item.quality}</span>
                      <span>•</span>
                      <span>{item.platform}</span>
                      {item.filesize && (
                        <>
                          <span>•</span>
                          <span>{formatBytes(item.filesize)}</span>
                        </>
                      )}
                      <span>•</span>
                      <span className="flex items-center gap-1 text-slate-500">
                        <Clock className="w-3 h-3" />
                        {formatTime(item.timestamp)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 self-end sm:self-center">
                  {item.downloadToken && (
                    <a
                      href={getFileDownloadUrl(item.downloadToken)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-semibold transition-colors"
                      title="Direct download file if within 1hr TTL"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Re-download</span>
                    </a>
                  )}

                  <button
                    type="button"
                    onClick={() => onReopenUrl(item.url)}
                    className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
                    title="Load original URL"
                  >
                    <ArrowUpRight className="w-4 h-4" />
                  </button>

                  <button
                    type="button"
                    onClick={() => onRemoveItem(item.id)}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-950/20 transition-colors"
                    title="Remove from history"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Storage TTL Notice */}
      <div className="mt-4 pt-3 border-t border-slate-800 text-[11px] text-slate-500 flex items-center justify-between">
        <span>Files on disk auto-expire after 1 hour (TTL) for privacy & disk hygiene.</span>
        <span>Client-side session only</span>
      </div>

    </div>
  );
}
