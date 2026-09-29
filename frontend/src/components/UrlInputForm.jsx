import React, { useState, useEffect } from 'react';
import {
  Search,
  Clipboard,
  X,
  ArrowRight,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  FileQuestion,
  ShieldAlert,
  Play,
  ExternalLink,
  Info,
} from 'lucide-react';
import { checkLink } from '../services/api';

const DEMO_SAMPLES = [
  { label: 'YouTube (4K / HD)', url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ', tag: 'YouTube' },
  { label: 'Vimeo (HD)', url: 'https://vimeo.com/76979871', tag: 'Vimeo' },
  { label: 'Direct MP4 Stream', url: 'https://www.w3schools.com/html/mov_bbb.mp4', tag: 'Direct File' },
];

export default function UrlInputForm({ onSubmit, isLoading, initialUrl = '' }) {
  const [url, setUrl] = useState(initialUrl);
  const [preCheck, setPreCheck] = useState(null);
  const [isCheckingLink, setIsCheckingLink] = useState(false);

  useEffect(() => {
    if (initialUrl) {
      setUrl(initialUrl);
    }
  }, [initialUrl]);

  // Global paste handler: Ctrl+V or Cmd+V anywhere on page populates input and triggers pre-check
  useEffect(() => {
    const handleGlobalPaste = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      const clipboardData = e.clipboardData || window.clipboardData;
      const pastedData = clipboardData?.getData('Text');
      if (pastedData && (pastedData.startsWith('http://') || pastedData.startsWith('https://'))) {
        e.preventDefault();
        const cleanPasted = pastedData.trim();
        setUrl(cleanPasted);
        runPreCheck(cleanPasted);
      }
    };

    window.addEventListener('paste', handleGlobalPaste);
    return () => window.removeEventListener('paste', handleGlobalPaste);
  }, []);

  // Debounced Instant Link Pre-check (< 300ms)
  const runPreCheck = async (targetUrl) => {
    if (!targetUrl || targetUrl.trim().length < 4) {
      setPreCheck(null);
      return;
    }

    setIsCheckingLink(true);
    try {
      const res = await checkLink(targetUrl.trim());
      setPreCheck(res);
    } catch (e) {
      setPreCheck(null);
    } finally {
      setIsCheckingLink(false);
    }
  };

  useEffect(() => {
    if (!url || url.trim().length < 4) {
      setPreCheck(null);
      return;
    }

    const timer = setTimeout(() => {
      runPreCheck(url);
    }, 250);

    return () => clearTimeout(timer);
  }, [url]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!url.trim() || isLoading) return;
    onSubmit(url.trim());
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        const clean = text.trim();
        setUrl(clean);
        runPreCheck(clean);
      }
    } catch (e) {
      console.warn('Clipboard read permission denied', e);
    }
  };

  const handleSelectDemo = (demoUrl) => {
    setUrl(demoUrl);
    runPreCheck(demoUrl);
    onSubmit(demoUrl);
  };

  return (
    <div className="w-full max-w-4xl mx-auto">
      <form onSubmit={handleSubmit} className="relative">
        <div className="relative flex flex-col sm:flex-row items-center gap-2 p-2 rounded-2xl glass-panel border border-slate-700/60 shadow-2xl focus-within:border-emerald-500/60 focus-within:ring-2 focus-within:ring-emerald-500/20 transition-all duration-300">
          
          {/* URL Input */}
          <div className="relative flex-1 w-full flex items-center pl-3">
            <Search className="w-5 h-5 text-slate-400 mr-2 flex-shrink-0" />
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="Paste a link from YouTube, Vimeo, X, Reddit, or direct MP4..."
              disabled={isLoading}
              className="w-full bg-transparent text-slate-100 placeholder-slate-500 text-sm sm:text-base outline-none pr-16 py-2.5"
            />

            {/* Clear or Paste Action */}
            <div className="absolute right-2 flex items-center gap-1">
              {url ? (
                <button
                  type="button"
                  onClick={() => {
                    setUrl('');
                    setPreCheck(null);
                  }}
                  className="p-1 rounded-full text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                  title="Clear input"
                >
                  <X className="w-4 h-4" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handlePaste}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium text-slate-300 bg-slate-800/80 hover:bg-slate-700 border border-slate-700 hover:text-white transition-colors"
                  title="Paste from clipboard"
                >
                  <Clipboard className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">Paste</span>
                </button>
              )}
            </div>
          </div>

          {/* Submit Action Button */}
          <button
            type="submit"
            disabled={isLoading || !url.trim()}
            className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-semibold text-sm sm:text-base shadow-lg shadow-emerald-500/25 disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-emerald-500/40 transition-all duration-200"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Checking link...</span>
              </>
            ) : (
              <>
                <span>Play &amp; Download</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>

        {/* Instant Link Pre-Check Status Feedback */}
        {isCheckingLink && (
          <div className="mt-2.5 flex items-center gap-2 px-3 text-xs text-slate-400 animate-pulse">
            <Loader2 className="w-3 h-3 animate-spin text-emerald-400" />
            <span>Checking link compatibility...</span>
          </div>
        )}

        {preCheck && !isCheckingLink && (
          <div className="mt-3">
            {/* Supported site */}
            {preCheck.status === 'supported_site' && (
              <div className="flex items-center justify-between px-3 py-1.5 rounded-xl bg-emerald-950/40 border border-emerald-500/30 text-xs text-emerald-300">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span className="font-semibold">{preCheck.label}:</span>
                  <span>{preCheck.platform_name}</span>
                </div>
                <span className="text-[11px] text-emerald-400/80">Ready to play</span>
              </div>
            )}

            {/* Direct video file */}
            {preCheck.status === 'direct_media' && (
              <div className="flex items-center justify-between px-3 py-1.5 rounded-xl bg-cyan-950/40 border border-cyan-500/30 text-xs text-cyan-300">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                  <span className="font-semibold">{preCheck.label}</span>
                  <span className="text-slate-400">({preCheck.domain})</span>
                </div>
                <span className="text-[11px] text-cyan-400/80">Direct stream ready</span>
              </div>
            )}

            {/* Probably unsupported: File-Sharing or DRM Alert Card */}
            {(preCheck.status === 'unsupported_file_sharing' ||
              preCheck.status === 'unsupported_drm' ||
              preCheck.status === 'unsupported_generic') && (
              <div className="p-4 rounded-xl bg-amber-950/40 border border-amber-500/40 text-amber-200 text-xs space-y-2 animate-fadeIn">
                <div className="flex items-center gap-2 font-bold text-amber-300">
                  <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
                  <span>{preCheck.label} — {preCheck.platform_name}</span>
                </div>
                <p className="text-amber-200/90 leading-relaxed">
                  {preCheck.explanation}
                </p>
                {preCheck.alternatives && preCheck.alternatives.length > 0 && (
                  <div className="pt-2 border-t border-amber-500/20">
                    <span className="font-semibold text-amber-300 block mb-1">What you can do instead:</span>
                    <ul className="list-disc list-inside space-y-0.5 text-amber-100/80 text-[11px]">
                      {preCheck.alternatives.map((alt, idx) => (
                        <li key={idx}>{alt}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Invalid URL */}
            {preCheck.status === 'invalid' && (
              <div className="flex items-center justify-between px-3 py-1.5 rounded-xl bg-rose-950/40 border border-rose-500/30 text-xs text-rose-300">
                <div className="flex items-center gap-2">
                  <ShieldAlert className="w-4 h-4 text-rose-400" />
                  <span className="font-semibold">{preCheck.label}</span>
                  <span className="text-rose-400/80">• {preCheck.explanation}</span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Clear Disclaimer under input */}
        <div className="mt-2.5 px-3 flex items-center justify-between text-[11px] text-slate-500">
          <p className="flex items-center gap-1.5">
            <Info className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
            <span>File-sharing pages, private videos, DRM-protected and login-only content are not supported.</span>
          </p>
        </div>
      </form>

      {/* 3 Clickable Working Demo Links */}
      <div className="mt-5 flex flex-wrap items-center justify-center gap-2.5 text-xs text-slate-400">
        <span className="text-slate-500 text-[11px] uppercase tracking-wider font-semibold">
          Try working demo:
        </span>
        {DEMO_SAMPLES.map((demo, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => handleSelectDemo(demo.url)}
            className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 hover:text-emerald-300 border border-slate-700 hover:border-emerald-500/40 transition-all shadow-sm"
          >
            <Play className="w-3 h-3 text-emerald-400" />
            <span>{demo.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
