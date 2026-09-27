import React, { useState, useEffect } from 'react';
import { Search, Clipboard, X, ArrowRight, Loader2, Sparkles, CheckCircle2, ShieldAlert } from 'lucide-react';
import { detectPlatform } from '../services/api';

const SAMPLE_URLS = [
  { label: 'YouTube Video', url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ' }, // Big Buck Bunny public CC
  { label: 'Direct MP4 Stream', url: 'https://www.w3schools.com/html/mov_bbb.mp4' },
  { label: 'Vimeo Creative', url: 'https://vimeo.com/76979871' },
];

export default function UrlInputForm({ onSubmit, isLoading, initialUrl = '' }) {
  const [url, setUrl] = useState(initialUrl);
  const [detected, setDetected] = useState(null);

  useEffect(() => {
    if (initialUrl) {
      setUrl(initialUrl);
    }
  }, [initialUrl]);

  // Live platform auto-detection debounce
  useEffect(() => {
    if (!url || url.length < 5) {
      setDetected(null);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const info = await detectPlatform(url);
        setDetected(info);
      } catch (e) {
        setDetected(null);
      }
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
        setUrl(text.trim());
      }
    } catch (e) {
      console.warn('Clipboard read permission denied', e);
    }
  };

  const handleSelectSample = (sampleUrl) => {
    setUrl(sampleUrl);
    onSubmit(sampleUrl);
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
              placeholder="Paste any media link (YouTube, Vimeo, TikTok, X, direct MP4, etc.)..."
              disabled={isLoading}
              className="w-full bg-transparent text-slate-100 placeholder-slate-500 text-sm sm:text-base outline-none pr-16 py-2.5"
            />

            {/* Clear or Paste Action */}
            <div className="absolute right-2 flex items-center gap-1">
              {url ? (
                <button
                  type="button"
                  onClick={() => setUrl('')}
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
                <span>Analyzing Media...</span>
              </>
            ) : (
              <>
                <span>Fetch Media</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>

        {/* Live Auto-detected Platform Chip */}
        {detected && (
          <div className="mt-2.5 flex items-center justify-between px-3 text-xs">
            <div className="flex items-center gap-2 text-emerald-400">
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="font-medium">Detected: {detected.platform}</span>
              <span className="text-slate-500">•</span>
              <span className="text-slate-400 hidden sm:inline">{detected.confirmation}</span>
            </div>
            <span className="text-[11px] text-slate-500">SSRF Pre-flight Active</span>
          </div>
        )}
      </form>

      {/* Quick Test Samples */}
      <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-xs text-slate-400">
        <span className="text-slate-500">Try quick sample:</span>
        {SAMPLE_URLS.map((sample, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => handleSelectSample(sample.url)}
            className="px-2.5 py-1 rounded-full bg-slate-800/60 hover:bg-slate-800 text-slate-300 hover:text-emerald-300 border border-slate-700/60 hover:border-emerald-500/40 transition-all"
          >
            {sample.label}
          </button>
        ))}
      </div>
    </div>
  );
}
