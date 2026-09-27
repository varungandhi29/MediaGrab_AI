import React from 'react';
import { X, Shield, Layers, Cpu, Server, Terminal, Lock, CheckCircle2 } from 'lucide-react';

export default function HowItWorksModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto glass-panel rounded-2xl border border-slate-700 p-6 sm:p-8 shadow-2xl">
        
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center border border-emerald-500/30">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">How MediaGrab AI Works</h2>
            <p className="text-xs text-slate-400">3-Tier Fallback Architecture & Defense-in-Depth Security</p>
          </div>
        </div>

        {/* Section 1: 4-Tier Fast-Fail Fallback Engine */}
        <div className="space-y-4 mb-8">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-emerald-400 uppercase tracking-wider flex items-center gap-2">
              <Layers className="w-4 h-4" /> 4-Tier Fast-Fail Extraction Pipeline
            </h3>
            <span className="text-xs text-slate-400 font-mono">Max 30s Total Cap</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300">
                  Tier 1
                </span>
                <span className="text-[10px] text-slate-500 font-mono">8s limit</span>
              </div>
              <h4 className="font-semibold text-sm text-white pt-1">yt-dlp Engine</h4>
              <p className="text-xs text-slate-400 leading-relaxed">
                Extracts metadata and format resolutions from 1,800+ recognized video & audio platforms in an isolated subprocess.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300">
                  Tier 2
                </span>
                <span className="text-[10px] text-slate-500 font-mono">5s limit</span>
              </div>
              <h4 className="font-semibold text-sm text-white pt-1">Direct Media Stream</h4>
              <p className="text-xs text-slate-400 leading-relaxed">
                If platform is unrecognized, validates HTTP Content-Type headers (.mp4, .webm, .mp3, .m3u8) for direct native streaming.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300">
                  Tier 3
                </span>
                <span className="text-[10px] text-slate-500 font-mono">5s limit</span>
              </div>
              <h4 className="font-semibold text-sm text-white pt-1">HTML5 Scraper</h4>
              <p className="text-xs text-slate-400 leading-relaxed">
                Lightweight DOM parser extracting OpenGraph video meta tags, HTML5 &lt;video&gt; elements, and embedded video sources.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300">
                  Tier 4
                </span>
                <span className="text-[10px] text-slate-500 font-mono">15s limit</span>
              </div>
              <h4 className="font-semibold text-sm text-white pt-1">Headless Browser</h4>
              <p className="text-xs text-slate-400 leading-relaxed">
                Playwright Chromium browser rendering dynamic JS, sniffing network media responses (.m3u8/.mp4) with strict SSRF route interception.
              </p>
            </div>
          </div>
        </div>

        {/* Section 2: Security Defenses */}
        <div className="space-y-4 mb-8">
          <h3 className="text-sm font-semibold text-cyan-400 uppercase tracking-wider flex items-center gap-2">
            <Lock className="w-4 h-4" /> Non-Negotiable Security Controls
          </h3>

          <div className="space-y-3">
            <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-start gap-3">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
              <div>
                <h5 className="text-xs font-semibold text-white">Full SSRF & DNS Rebinding Protection</h5>
                <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
                  Before fetching ANY target URL, system resolves hostname to all IPv4/IPv6 addresses and blocks loopback (127.0.0.0/8), private LANs (10/8, 172.16/12, 192.168/16), and cloud metadata (169.254.169.254, AWS/GCP internal). Re-checked on every single redirect hop.
                </p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-start gap-3">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
              <div>
                <h5 className="text-xs font-semibold text-white">Isolated Subprocess Sandboxing</h5>
                <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
                  yt-dlp is executed with restricted non-shell invocation (`create_subprocess_exec`). Secrets, database strings, and cloud credentials are completely purged from the child environment. Execution is bounded by hard timeouts.
                </p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-start gap-3">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
              <div>
                <h5 className="text-xs font-semibold text-white">Sliding-Window Rate Limiting & Concurrency Controls</h5>
                <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
                  Separate sliding-window rate limit buckets for metadata inspection and expensive downloads per IP. Concurrent jobs are capped to prevent server storage and bandwidth exhaustion.
                </p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-start gap-3">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
              <div>
                <h5 className="text-xs font-semibold text-white">Path Traversal Defense & 1-Hour Ephemeral Storage</h5>
                <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
                  Files are saved under cryptographically random UUID names on disk. A background daemon purges downloads older than 1 hour (TTL).
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Section 3: AI Assistant */}
        <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-500/20">
          <h4 className="text-xs font-bold text-indigo-300 uppercase tracking-wider mb-1 flex items-center gap-1.5">
            <Cpu className="w-3.5 h-3.5" /> AI Assistant Prompt-Injection Defense
          </h4>
          <p className="text-xs text-slate-300 leading-relaxed">
            All user inputs and scraped webpage texts are treated strictly as untrusted data wrapped in security delimiters before processing. The model is hard-coded to ignore command directives inside external content.
          </p>
        </div>

        {/* Modal Footer */}
        <div className="mt-6 pt-4 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold transition-colors"
          >
            Close
          </button>
        </div>

      </div>
    </div>
  );
}
