import React, { useState, useEffect } from 'react';
import {
  CheckCircle,
  XCircle,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  Calendar,
  ExternalLink,
  Film,
  Music,
  Video,
  FileX,
  Lock,
  Clock,
  Sparkles,
} from 'lucide-react';
import { getSupportedSites } from '../services/api';

const DEFAULT_SUPPORTED = [
  { name: 'YouTube', type: 'Video & Audio (up to 4K)', domain: 'youtube.com' },
  { name: 'Vimeo', type: 'High Bitrate HD/4K', domain: 'vimeo.com' },
  { name: 'Direct file links (.mp4, .webm, .m3u8)', type: 'Direct Video & Audio Streams', domain: '.mp4, .webm, .m3u8' },
];

const UNSUPPORTED_CATEGORIES = [
  { name: 'File-Sharing / Cloud Storage', examples: 'Google Drive, Dropbox, Mega, MediaFire, WeTransfer', reason: 'Require browser session downloads or proprietary web viewers' },
  { name: 'DRM-Encrypted Streaming', examples: 'Netflix, Spotify, Disney+, Hulu, HBO Max, Prime Video', reason: 'Protected by Widevine/FairPlay encryption and subscription walls' },
  { name: 'Private or Login-Only', examples: 'Private accounts, members-only streams, unlisted behind credentials', reason: 'Require user authentication or private access tokens' },
];

const FAQS = [
  {
    q: 'Why do some links fail to play or download?',
    a: 'MediaGrab AI extracts publicly accessible video and audio streams. Links fail when: (1) The site is a cloud storage or file-sharing locker (like Google Drive or Dropbox) rather than a media stream; (2) The media is encrypted by Digital Rights Management (DRM) like Netflix or Spotify; (3) The video is private, members-only, or requires a personal account login; or (4) The host platform is temporarily rate-limiting automated requests.',
  },
  {
    q: 'What are the quality, resolution, and file size limits?',
    a: 'We support original source resolutions up to 4K (2160p) at 60 FPS, as well as 1080p Full HD, 720p HD, and 320kbps MP3 audio. Single video downloads are capped at 2.0 GB or 3 hours in duration to preserve fair shared server capacity.',
  },
  {
    q: 'How long are downloaded files stored on the server?',
    a: 'All extracted media files are stored under cryptographically random UUID filenames with strict TTL (Time-To-Live) auto-deletion. Files are permanently purged from the server after 60 minutes. We do not maintain any persistent video library or logs of user IP addresses.',
  },
  {
    q: 'What are the terms of service and responsible use policy?',
    a: 'MediaGrab AI is provided for personal backup, offline research, and fair use of public media. We do not provide DRM bypass tools or circumvent technological access controls. Users are solely responsible for respecting the copyright and intellectual property rights of content owners.',
  },
];

export default function SupportedSitesAndFaq() {
  const [supportedSites, setSupportedSites] = useState(DEFAULT_SUPPORTED);
  const [lastUpdated, setLastUpdated] = useState('September 2026');
  const [openFaqIndex, setOpenFaqIndex] = useState(null);

  useEffect(() => {
    getSupportedSites()
      .then((data) => {
        if (data.verified_sites && data.verified_sites.length > 0) {
          setSupportedSites(data.verified_sites);
        } else if (data.sites && data.sites.length > 0) {
          setSupportedSites(data.sites);
        }
        if (data.last_updated) {
          setLastUpdated(data.last_updated);
        }
      })
      .catch(() => {});
  }, []);

  const toggleFaq = (index) => {
    setOpenFaqIndex(openFaqIndex === index ? null : index);
  };

  return (
    <div className="w-full max-w-4xl mx-auto mt-16 space-y-12">
      {/* Supported Sites Section */}
      <section className="glass-panel rounded-2xl border border-slate-700/60 p-6 sm:p-8 shadow-xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-6 border-b border-slate-800">
          <div>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold mb-2">
              <CheckCircle className="w-3.5 h-3.5" />
              <span>Verified Test Suite</span>
            </div>
            <h2 className="text-xl sm:text-2xl font-bold text-white">Supported Platforms</h2>
            <p className="text-xs sm:text-sm text-slate-400 mt-1">
              Tested and verified against our automated compliance test suite.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400 font-mono bg-slate-900/80 px-3 py-1.5 rounded-xl border border-slate-800 self-start sm:self-auto">
            <Calendar className="w-3.5 h-3.5 text-emerald-400" />
            <span>Updated: {lastUpdated}</span>
          </div>
        </div>

        {/* Supported Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5 mt-6">
          {supportedSites.map((site, idx) => (
            <div
              key={idx}
              className="p-3.5 rounded-xl bg-slate-900/70 border border-slate-800/80 hover:border-emerald-500/30 transition-all flex items-start gap-3"
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5">
                <CheckCircle className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <h4 className="font-semibold text-sm text-slate-200 truncate">{site.name}</h4>
                <p className="text-xs text-slate-400 truncate">{site.type || site.domain}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Clear Unsupported List (Honest Expectation) */}
        <div className="mt-8 pt-6 border-t border-slate-800/80">
          <h3 className="text-xs font-bold uppercase tracking-wider text-rose-400 flex items-center gap-2 mb-3">
            <XCircle className="w-4 h-4" />
            <span>Not Supported by Design</span>
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            {UNSUPPORTED_CATEGORIES.map((cat, idx) => (
              <div key={idx} className="p-3 rounded-xl bg-rose-950/20 border border-rose-500/20 text-slate-300">
                <span className="font-semibold text-rose-300 block mb-1">{cat.name}</span>
                <span className="text-[11px] text-slate-400 block mb-1.5 font-mono">{cat.examples}</span>
                <span className="text-[11px] text-rose-200/80 leading-relaxed block">{cat.reason}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Frequently Asked Questions Accordion */}
      <section className="glass-panel rounded-2xl border border-slate-700/60 p-6 sm:p-8 shadow-xl">
        <div className="mb-6">
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs font-semibold mb-2">
            <HelpCircle className="w-3.5 h-3.5" />
            <span>Transparency & Knowledge Base</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-bold text-white">Frequently Asked Questions</h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            Honest answers about video extraction, storage limits, and service boundaries.
          </p>
        </div>

        <div className="space-y-3">
          {FAQS.map((faq, idx) => {
            const isOpen = openFaqIndex === idx;
            return (
              <div
                key={idx}
                className="rounded-xl border border-slate-800 bg-slate-900/60 transition-colors overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => toggleFaq(idx)}
                  className="w-full text-left p-4 flex items-center justify-between gap-4 font-semibold text-sm sm:text-base text-slate-200 hover:text-emerald-300 transition-colors"
                >
                  <span>{faq.q}</span>
                  {isOpen ? (
                    <ChevronUp className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-slate-400 flex-shrink-0" />
                  )}
                </button>
                {isOpen && (
                  <div className="px-4 pb-4 pt-1 text-xs sm:text-sm text-slate-400 leading-relaxed border-t border-slate-800/60 bg-slate-950/40">
                    {faq.a}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
