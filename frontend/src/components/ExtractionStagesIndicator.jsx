import React, { useState, useEffect } from 'react';
import { Layers, Loader2, CheckCircle2, Globe, FileVideo, Code2, MonitorPlay, Clock } from 'lucide-react';

const TIERS = [
  { tier: 1, key: 'ytdlp', label: 'yt-dlp Engine', desc: '1,800+ video & audio platforms', icon: Layers, maxTime: '8s' },
  { tier: 2, key: 'direct', label: 'Direct Media Check', desc: 'HTTP Content-Type inspection', icon: FileVideo, maxTime: '5s' },
  { tier: 3, key: 'static_scrape', label: 'Static HTML Scraper', desc: 'OpenGraph & HTML5 tags', icon: Code2, maxTime: '5s' },
  { tier: 4, key: 'headless_browser', label: 'Headless Browser', desc: 'Playwright Chromium render', icon: MonitorPlay, maxTime: '15s' },
];

export default function ExtractionStagesIndicator({
  currentStage,
  isVisible,
}) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!isVisible) {
      setElapsedSeconds(0);
      return;
    }
    const timer = setInterval(() => {
      setElapsedSeconds(s => s + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [isVisible]);

  if (!isVisible) return null;

  const currentTierNum = currentStage?.tier || 1;
  const currentMessage = currentStage?.message || 'Analyzing media source...';

  return (
    <div className="w-full max-w-4xl mx-auto mt-5 glass-panel rounded-2xl border border-emerald-500/30 p-4 sm:p-5 shadow-2xl animate-fadeIn">
      
      {/* Top Status Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 mb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Loader2 className="w-4 h-4 text-emerald-400 animate-spin" />
          <span className="text-sm font-bold text-white">Multi-Tier Extraction Active</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            Fast-Fail Pipeline
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-slate-400 font-mono">
          <Clock className="w-3.5 h-3.5 text-cyan-400" />
          <span>Elapsed: {elapsedSeconds}s / 45s max</span>
        </div>
      </div>

      {/* 4-Tier Steps Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        {TIERS.map((t) => {
          const Icon = t.icon;
          const isCurrent = currentTierNum === t.tier;
          const isPassed = currentTierNum > t.tier;
          const isRetry = isCurrent && currentStage?.stage === 'retry';
          const isCircuitSkip = currentStage?.stage === 'circuit_skip' && currentTierNum === t.tier;

          return (
            <div
              key={t.tier}
              className={`p-3 rounded-xl border text-left transition-all relative overflow-hidden ${
                isRetry
                  ? 'bg-amber-950/40 border-amber-500/80 text-white shadow-lg shadow-amber-500/10'
                  : isCurrent
                  ? 'bg-emerald-950/30 border-emerald-500 text-white shadow-lg shadow-emerald-500/10'
                  : isPassed
                  ? 'bg-slate-900/40 border-slate-800/80 text-slate-400 opacity-75'
                  : 'bg-slate-900/20 border-slate-800/40 text-slate-600'
              }`}
            >
              {/* Active Pulse Border Effect */}
              {isCurrent && (
                <div className={`absolute top-0 left-0 right-0 h-0.5 ${
                  isRetry ? 'bg-amber-400 animate-pulse' : 'bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 animate-pulse'
                }`} />
              )}

              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                    isRetry ? 'bg-amber-500 text-slate-950' : isCurrent ? 'bg-emerald-500 text-slate-950' : 'bg-slate-800 text-slate-400'
                  }`}>
                    Tier {t.tier}
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">({t.maxTime})</span>
                </div>

                {isRetry && <span className="text-[9px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 font-bold">RETRY</span>}
                {isCurrent && !isRetry && <Loader2 className="w-3.5 h-3.5 text-emerald-400 animate-spin" />}
                {isPassed && <CheckCircle2 className="w-3.5 h-3.5 text-slate-500" />}
              </div>

              <div className="flex items-center gap-1.5 mt-1">
                <Icon className={`w-3.5 h-3.5 ${isRetry ? 'text-amber-400' : isCurrent ? 'text-emerald-400' : 'text-slate-500'}`} />
                <span className="text-xs font-semibold truncate text-slate-200">{t.label}</span>
              </div>

              <div className="text-[10px] text-slate-400 mt-0.5 truncate">{t.desc}</div>
            </div>
          );
        })}
      </div>

      {/* Current Real-Time Status Message */}
      <div className={`mt-3.5 px-3 py-2 rounded-xl border flex items-center justify-between text-xs transition-colors ${
        currentStage?.stage === 'retry'
          ? 'bg-amber-950/40 border-amber-500/40 text-amber-200'
          : currentStage?.stage === 'circuit_skip'
          ? 'bg-purple-950/40 border-purple-500/40 text-purple-200'
          : 'bg-slate-900/80 border-slate-800 text-slate-300'
      }`}>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full animate-ping ${
            currentStage?.stage === 'retry' ? 'bg-amber-400' : 'bg-emerald-400'
          }`} />
          <span className="font-medium">{currentMessage}</span>
        </div>
        <span className="text-[11px] text-slate-500 hidden sm:inline">Self-healing pipeline active</span>
      </div>

    </div>
  );
}
