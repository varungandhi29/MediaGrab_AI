import React from 'react';
import { Download, CheckCircle2, AlertTriangle, Loader2, Gauge, Clock, HardDrive, RefreshCw } from 'lucide-react';
import { getFileDownloadUrl } from '../services/api';

export default function DownloadProgressBar({
  job,
  onReset,
}) {
  if (!job) return null;

  const {
    status,
    progress_percent = 0,
    speed = '0 KB/s',
    eta = '--:--',
    error_message,
    download_token,
    filename,
    filesize,
  } = job;

  const isCompleted = status === 'completed';
  const isFailed = status === 'failed';
  const isDownloading = status === 'downloading' || status === 'pending' || status === 'converting';

  // Format bytes for display
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

  const statusDescriptions = {
    pending: 'Queueing download in sandboxed subprocess...',
    downloading: 'Streaming media chunks...',
    converting: 'Merging video & audio streams with FFmpeg...',
    completed: 'Media successfully processed and ready for download!',
    failed: 'Download processing encountered an issue.',
  };

  return (
    <div className="w-full max-w-4xl mx-auto mt-6 glass-panel rounded-2xl border border-slate-700/70 p-6 shadow-2xl animate-fadeIn">
      
      {/* Status Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          {isCompleted && <CheckCircle2 className="w-5 h-5 text-emerald-400" />}
          {isFailed && <AlertTriangle className="w-5 h-5 text-rose-400" />}
          {isDownloading && <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />}

          <div>
            <h3 className="font-bold text-white text-base">
              {isCompleted ? 'Ready to Save' : isFailed ? 'Download Failed' : 'Processing Media...'}
            </h3>
            <p className="text-xs text-slate-400">{statusDescriptions[status] || status}</p>
          </div>
        </div>

        {/* Live Metrics */}
        {isDownloading && (
          <div className="flex items-center gap-4 text-xs font-mono">
            <div className="flex items-center gap-1 text-slate-300">
              <Gauge className="w-3.5 h-3.5 text-cyan-400" />
              <span>{speed}</span>
            </div>
            <div className="flex items-center gap-1 text-slate-300">
              <Clock className="w-3.5 h-3.5 text-amber-400" />
              <span>ETA: {eta}</span>
            </div>
          </div>
        )}
      </div>

      {/* Progress Bar */}
      {isDownloading && (
        <div className="space-y-2 my-4">
          <div className="w-full h-3 bg-slate-900 rounded-full overflow-hidden p-0.5 border border-slate-800">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 rounded-full transition-all duration-300 relative"
              style={{ width: `${Math.max(4, Math.min(100, progress_percent))}%` }}
            >
              <div className="absolute inset-0 bg-white/20 animate-pulse" />
            </div>
          </div>

          <div className="flex justify-between text-xs text-slate-400 font-mono">
            <span>{progress_percent.toFixed(1)}%</span>
            <span>{status === 'converting' ? 'Post-processing' : 'Direct Streaming'}</span>
          </div>
        </div>
      )}

      {/* Completed State Actions */}
      {isCompleted && (
        <div className="mt-4 p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/30 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0">
              <HardDrive className="w-5 h-5" />
            </div>
            <div>
              <div className="font-medium text-white text-sm truncate max-w-xs sm:max-w-md">
                {filename || 'Media file'}
              </div>
              <div className="text-xs text-slate-400">
                {formatBytes(filesize)} • Encrypted UUID Storage • Auto-deleted in 1 hour
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto">
            <a
              href={getFileDownloadUrl(download_token)}
              download={filename}
              className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-6 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-sm shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/40 transition-all duration-150"
            >
              <Download className="w-4 h-4" />
              <span>Save to Browser</span>
            </a>

            <button
              onClick={onReset}
              className="p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
              title="Download another video"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Error Message */}
      {isFailed && (
        <div className="mt-4 p-4 rounded-xl bg-rose-950/30 border border-rose-500/30 text-rose-200 text-xs sm:text-sm">
          <p className="font-semibold text-rose-300 mb-1">Download Error</p>
          <p>{error_message || 'An unexpected error occurred during extraction.'}</p>

          <button
            onClick={onReset}
            className="mt-3 px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors"
          >
            Try Again
          </button>
        </div>
      )}
    </div>
  );
}
