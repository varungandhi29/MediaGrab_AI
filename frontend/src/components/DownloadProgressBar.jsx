import React, { useState } from 'react';
import {
  Download,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Gauge,
  Clock,
  HardDrive,
  RefreshCw,
  X,
  Flag,
  RotateCcw,
} from 'lucide-react';
import { getFileDownloadUrl, cancelMediaJob, submitRating, submitLinkReport } from '../services/api';
import JobError from './JobError';

export default function DownloadProgressBar({
  job,
  onReset,
  onRetry,
}) {
  const [hasRated, setHasRated] = useState(false);
  const [reportState, setReportState] = useState('idle');
  const [isCancelling, setIsCancelling] = useState(false);

  if (!job) return null;

  const {
    job_id,
    url,
    domain,
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

  const handleCancel = async () => {
    if (!job_id || isCancelling) return;
    setIsCancelling(true);
    try {
      await cancelMediaJob(job_id);
    } catch (e) {}
    setIsCancelling(false);
    if (onReset) onReset();
  };

  const handleSendRating = async (ratingVal) => {
    if (hasRated) return;
    setHasRated(true);
    try {
      await submitRating({
        url: url || '',
        domain: domain || 'unknown',
        rating: ratingVal,
        action_type: 'download',
      });
    } catch (e) {}
  };

  const handleReportFailure = async () => {
    if (reportState === 'sending' || reportState === 'sent') return;
    setReportState('sending');
    try {
      await submitLinkReport({
        url: url || '',
        domain: domain || 'unknown',
        error_class: 'download_failure',
        user_notes: error_message || 'Download failed during stream processing',
      });
      setReportState('sent');
    } catch (e) {
      setReportState('error');
    }
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

        {/* Live Metrics & Cancel Button */}
        {isDownloading && (
          <div className="flex items-center gap-2 sm:gap-3 font-mono">
            <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/70 border border-cyan-500/40 text-cyan-300 font-semibold text-xs shadow-sm shadow-cyan-950/50">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
              </span>
              <Gauge className="w-3.5 h-3.5 text-cyan-400" />
              <span>{speed || 'Calculating...'}</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber-950/70 border border-amber-500/40 text-amber-300 font-semibold text-xs shadow-sm shadow-amber-950/50">
              <Clock className="w-3.5 h-3.5 text-amber-400" />
              <span>ETA: {eta || '--:--'}</span>
            </div>

            <button
              type="button"
              onClick={handleCancel}
              disabled={isCancelling}
              className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-rose-950/40 text-slate-300 hover:text-rose-300 border border-slate-700 hover:border-rose-500/40 text-xs font-semibold transition-colors"
              title="Cancel this download"
            >
              <X className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Cancel</span>
            </button>
          </div>
        )}
      </div>

      {/* Progress Bar & Numerical Metrics */}
      {isDownloading && (
        <div className="space-y-2.5 my-4">
          <div className="flex items-baseline justify-between">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 font-mono">
                {progress_percent.toFixed(1)}%
              </span>
              <span className="text-xs text-slate-400 font-medium">completed</span>
            </div>
            <span className="text-xs text-slate-300 font-medium px-2.5 py-1 rounded-lg bg-slate-800/80 border border-slate-700/60">
              {status === 'converting' ? '⚡ Merging Video & Audio with FFmpeg' : '🚀 High-Speed Direct Stream'}
            </span>
          </div>

          <div className="w-full h-3.5 bg-slate-900 rounded-full overflow-hidden p-0.5 border border-slate-800 shadow-inner">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 rounded-full transition-all duration-300 relative shadow-lg shadow-cyan-500/20"
              style={{ width: `${Math.max(4, Math.min(100, progress_percent))}%` }}
            >
              <div className="absolute inset-0 bg-white/25 animate-pulse" />
            </div>
          </div>

          {/* Prominent Live Speed & Time Remaining Card Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
            <div className="p-3 rounded-xl bg-slate-900/90 border border-cyan-500/30 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400 flex-shrink-0">
                <Gauge className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Download Speed</p>
                <p className="text-base sm:text-lg font-bold text-cyan-300 font-mono truncate">
                  {speed && speed !== '0 KB/s' && !speed.toLowerCase().includes('unknown') && speed !== 'NA' ? speed : 'Calculating speed...'}
                </p>
              </div>
            </div>

            <div className="p-3 rounded-xl bg-slate-900/90 border border-amber-500/30 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-amber-500/10 text-amber-400 flex-shrink-0">
                <Clock className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Time Remaining</p>
                <p className="text-base sm:text-lg font-bold text-amber-300 font-mono truncate">
                  {eta && eta !== '--:--' && !eta.toLowerCase().includes('unknown') && eta !== 'NA' ? `${eta} remaining` : 'Estimating time...'}
                </p>
              </div>
            </div>

            <div className="p-3 rounded-xl bg-slate-900/90 border border-emerald-500/30 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400 flex-shrink-0">
                <HardDrive className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Live Progress</p>
                <p className="text-base sm:text-lg font-bold text-emerald-300 font-mono truncate">
                  {progress_percent.toFixed(1)}% Downloaded
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Completed State Actions + Thumbs Up / Down Feedback */}
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

          <div className="flex flex-wrap items-center gap-3 w-full sm:w-auto">
            {/* Thumbs Up / Down Rating */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-800/80 border border-slate-700 text-xs text-slate-300">
              <span>Worked well?</span>
              {hasRated ? (
                <span className="text-emerald-400 font-semibold">Thank you!</span>
              ) : (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => handleSendRating('up')}
                    className="hover:scale-125 transition-transform"
                    title="Yes, download worked well"
                  >
                    👍
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSendRating('down')}
                    className="hover:scale-125 transition-transform"
                    title="Had issues"
                  >
                    👎
                  </button>
                </div>
              )}
            </div>

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

      {/* Error Message with JobError, Report, and Retry */}
      {isFailed && (
        <div className="mt-4">
          <JobError job={job} onRetry={onRetry || onReset} />
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={handleReportFailure}
              disabled={reportState === 'sending' || reportState === 'sent'}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 hover:text-rose-200 border border-rose-500/30 text-xs font-medium transition-all disabled:opacity-60"
            >
              <Flag className="w-3.5 h-3.5" />
              <span>{reportState === 'sending' ? 'Reporting...' : reportState === 'sent' ? 'Report Received' : 'Report this link'}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
