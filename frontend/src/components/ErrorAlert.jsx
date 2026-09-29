import React, { useState } from 'react';
import {
  AlertTriangle,
  X,
  RotateCcw,
  Copy,
  Check,
  Flag,
  ShieldAlert,
  HelpCircle,
  ExternalLink,
  Lock,
  Globe,
  Radio,
  FileQuestion,
} from 'lucide-react';
import { submitLinkReport } from '../services/api';

function extractDomain(url) {
  try {
    const parsed = new URL(url);
    let d = parsed.hostname.toLowerCase();
    if (d.startsWith('www.')) d = d.slice(4);
    return d;
  } catch (e) {
    return 'unknown domain';
  }
}

function resolveErrorClassAndDetails(rawError, url) {
  const err = (rawError || '').toLowerCase();
  const domain = extractDomain(url);
  const now = new Date().toISOString();

  // 1. SSRF / Security
  if (err.includes('ssrf') || err.includes('restricted') || err.includes('security') || err.includes('private ip')) {
    return {
      errorClass: 'invalid',
      title: 'Restricted Address',
      whatHappened: 'This link targets an internal, private, or restricted IP address which is blocked for security.',
      whatToTry: [
        'Provide a public internet URL accessible to the open web.',
        'Check for mistyped hostnames or localhost addresses.',
      ],
      canRetry: false,
      debugInfo: { error_class: 'invalid', domain, timestamp: now, summary: 'Blocked by SSRF protection' },
    };
  }

  // 1b. FILE_HOST_UNSUPPORTED
  if (err.includes('file-sharing page') || err.includes('file_host_unsupported')) {
    return {
      errorClass: 'FILE_HOST_UNSUPPORTED',
      title: 'File-Sharing Page Detected',
      whatHappened: "This looks like a file-sharing page, not a video platform. It can't be played or downloaded here. Open the page and use its own download button, or paste a direct video link (.mp4 / .m3u8) or a supported site link.",
      whatToTry: [
        'Open the page and use its own download button.',
        'Paste a direct video link (.mp4 / .m3u8).',
        'Paste a link from a supported site (e.g., YouTube or Vimeo).',
      ],
      canRetry: false,
      debugInfo: { error_class: 'FILE_HOST_UNSUPPORTED', domain, timestamp: now, summary: 'File-sharing page not supported' },
    };
  }

  // 2. File Sharing
  if (
    domain.includes('drive.google') ||
    domain.includes('dropbox') ||
    domain.includes('mega.nz') ||
    domain.includes('mediafire') ||
    domain.includes('wetransfer') ||
    domain.includes('box.com') ||
    domain.includes('onedrive')
  ) {
    return {
      errorClass: 'file_sharing',
      title: 'File-Sharing Page Detected',
      whatHappened: `${domain} is a cloud storage locker or file-sharing page, not a direct streaming host.`,
      whatToTry: [
        `Download the file directly from ${domain}'s web interface.`,
        'Obtain a direct public streaming URL ending in .mp4 or .webm.',
        'Use supported streaming platforms like YouTube, Vimeo, or Reddit.',
      ],
      canRetry: false,
      debugInfo: { error_class: 'file_sharing', domain, timestamp: now, summary: 'Cloud storage locker' },
    };
  }

  // 3. DRM
  if (
    err.includes('drm') ||
    err.includes('widevine') ||
    err.includes('encrypted') ||
    domain.includes('netflix') ||
    domain.includes('spotify') ||
    domain.includes('disneyplus') ||
    domain.includes('hulu') ||
    domain.includes('hbomax')
  ) {
    return {
      errorClass: 'drm',
      title: 'DRM-Protected Content',
      whatHappened: 'This media is protected by Digital Rights Management (DRM) encryption which cannot be extracted.',
      whatToTry: [
        'Watch or listen using the provider’s official app or web player.',
        'Try public, non-encrypted video links from YouTube or Vimeo.',
      ],
      canRetry: false,
      debugInfo: { error_class: 'drm', domain, timestamp: now, summary: 'DRM encryption present' },
    };
  }

  // 4. Private / Login Required
  if (
    err.includes('private') ||
    err.includes('login') ||
    err.includes('sign in') ||
    err.includes('members-only') ||
    err.includes('authentication')
  ) {
    return {
      errorClass: 'private_login',
      title: 'Private or Login-Only Media',
      whatHappened: 'This video is private, members-only, or requires an account login to view.',
      whatToTry: [
        'Confirm if the creator has posted a public link.',
        'Make sure the video is not restricted to paying channel members.',
      ],
      canRetry: false,
      debugInfo: { error_class: 'private_login', domain, timestamp: now, summary: 'Requires authentication' },
    };
  }

  // 5. Geo-blocked
  if (err.includes('geo') || err.includes('country') || err.includes('region') || err.includes('not available in your')) {
    return {
      errorClass: 'geo_blocked',
      title: 'Region-Restricted Content',
      whatHappened: 'The platform or content owner has made this video unavailable in our server location.',
      whatToTry: [
        'Search for an international mirror or alternate upload.',
        'Try a different public video from the same creator.',
      ],
      canRetry: false,
      debugInfo: { error_class: 'geo_blocked', domain, timestamp: now, summary: 'Geographic restriction' },
    };
  }

  // 6. Deleted / 404
  if (err.includes('deleted') || err.includes('removed') || err.includes('not found') || err.includes('404')) {
    return {
      errorClass: 'deleted',
      title: 'Video No Longer Available',
      whatHappened: 'This video was deleted by the uploader, removed for terms violations, or does not exist.',
      whatToTry: [
        'Verify the video still plays directly in your browser.',
        'Check for a newer re-upload of the video.',
      ],
      canRetry: false,
      debugInfo: { error_class: 'deleted', domain, timestamp: now, summary: 'Video removed or 404' },
    };
  }

  // 7. Site Blocking / Bot Protection
  if (
    err.includes('bot') ||
    err.includes('captcha') ||
    err.includes('turnstile') ||
    err.includes('cloudflare') ||
    err.includes('403') ||
    err.includes('rate limit') ||
    err.includes('too many requests')
  ) {
    return {
      errorClass: 'site_blocking',
      title: 'Temporary Platform Rate Limit',
      whatHappened: `${domain} is temporarily rate-limiting automated connections.`,
      whatToTry: [
        'Wait 1–2 minutes and click Retry.',
        'Try an alternative source or mirror.',
      ],
      canRetry: true,
      debugInfo: { error_class: 'site_blocking', domain, timestamp: now, summary: 'Host platform rate limit' },
    };
  }

  // 8. Timeout
  if (err.includes('timeout') || err.includes('timed out') || err.includes('504')) {
    return {
      errorClass: 'timeout',
      title: 'Connection Timed Out',
      whatHappened: `${domain} took too long to respond to the media extraction request.`,
      whatToTry: [
        'Click Retry to make another attempt.',
        'Check if the host platform is currently experiencing slow loading.',
      ],
      canRetry: true,
      debugInfo: { error_class: 'timeout', domain, timestamp: now, summary: 'Upstream timeout' },
    };
  }

  // 9. Unsupported Site
  if (err.includes('unsupported') || err.includes('no suitable extractor')) {
    return {
      errorClass: 'unsupported_site',
      title: 'Site Not Supported Yet',
      whatHappened: `MediaGrab AI does not currently have an active extractor for ${domain}.`,
      whatToTry: [
        'Try a direct link to the media file ending in .mp4, .webm, or .mp3.',
        'Use supported sites like YouTube, Vimeo, X, or Reddit.',
        'Click "Report this link" below to help us prioritize adding support!',
      ],
      canRetry: false,
      debugInfo: { error_class: 'unsupported_site', domain, timestamp: now, summary: 'Extractor not found' },
    };
  }

  // Default: Internal / Processing Error
  return {
    errorClass: 'internal_error',
    title: 'Extraction Processing Error',
    whatHappened: 'An unexpected issue occurred while analyzing this media stream.',
    whatToTry: [
      'Click Retry to run a fresh extraction attempt.',
      'Check that the video is public and accessible.',
      'Report the link below so we can inspect and fix it.',
    ],
    canRetry: true,
    debugInfo: { error_class: 'internal_error', domain, timestamp: now, summary: (rawError || '').slice(0, 100) },
  };
}

export default function ErrorAlert({
  error,
  explanation,
  url,
  onDismiss,
  onRetry,
}) {
  const [copiedDebug, setCopiedDebug] = useState(false);
  const [reportState, setReportState] = useState('idle'); // 'idle' | 'sending' | 'sent' | 'error'

  if (!error && !explanation) return null;

  // Use structured explanation from server if available, otherwise resolve locally
  const localDetails = resolveErrorClassAndDetails(error, url);
  const title = explanation?.category || localDetails.title;
  const whatHappened = explanation?.what_happened || explanation?.human_summary || localDetails.whatHappened;
  const whatToTry = (explanation?.what_to_try && explanation.what_to_try.length > 0)
    ? explanation.what_to_try
    : localDetails.whatToTry;
  const canRetry = explanation?.can_retry !== undefined ? explanation.can_retry : localDetails.canRetry;
  const errorClass = explanation?.error_class || localDetails.errorClass;
  const debugData = explanation?.debug_info || localDetails.debugInfo;

  const handleCopyDebug = async () => {
    try {
      const cleanBlob = {
        error_class: debugData.error_class || errorClass,
        domain: debugData.domain || extractDomain(url),
        timestamp: debugData.timestamp || new Date().toISOString(),
        summary: debugData.summary || whatHappened,
      };
      await navigator.clipboard.writeText(JSON.stringify(cleanBlob, null, 2));
      setCopiedDebug(true);
      setTimeout(() => setCopiedDebug(false), 2500);
    } catch (e) {
      console.warn('Clipboard write failed', e);
    }
  };

  const handleReportLink = async () => {
    if (!url || reportState === 'sending' || reportState === 'sent') return;
    setReportState('sending');
    try {
      await submitLinkReport({
        url,
        domain: extractDomain(url),
        error_class: errorClass,
        user_notes: 'User reported from error alert card',
      });
      setReportState('sent');
    } catch (e) {
      setReportState('error');
    }
  };

  return (
    <div
      role="alert"
      className="w-full max-w-4xl mx-auto mt-6 rounded-2xl glass-panel border border-rose-500/40 bg-rose-950/20 shadow-2xl p-5 sm:p-6 animate-fadeIn"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3.5">
          <div className="p-2.5 rounded-xl bg-rose-500/20 text-rose-400 flex-shrink-0 mt-0.5">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div className="space-y-3">
            <div>
              <h4 className="font-bold text-base text-rose-200">{title}</h4>
              <p className="text-xs sm:text-sm text-rose-200/90 mt-1 leading-relaxed">
                {whatHappened}
              </p>
            </div>

            {/* Actionable Next Steps ("What you can try") */}
            {whatToTry && whatToTry.length > 0 && (
              <div className="p-3.5 rounded-xl bg-slate-900/80 border border-rose-500/20 text-xs">
                <span className="font-semibold text-rose-300 block mb-1.5 uppercase tracking-wider text-[11px]">
                  What you can try:
                </span>
                <ul className="list-disc list-inside space-y-1 text-slate-300">
                  {whatToTry.map((step, idx) => (
                    <li key={idx} className="leading-relaxed">
                      {step}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Action Buttons: Retry, Report Link, Copy Debug Info */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {canRetry && onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-semibold shadow-md shadow-emerald-500/20 transition-all"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Retry</span>
                </button>
              )}

              <button
                type="button"
                onClick={handleCopyDebug}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-medium transition-all"
                title="Copy sanitized debug info (no IP or cookies)"
              >
                {copiedDebug ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedDebug ? 'Debug Info Copied!' : 'Copy Debug Info'}</span>
              </button>

              <button
                type="button"
                onClick={handleReportLink}
                disabled={reportState === 'sending' || reportState === 'sent'}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 hover:text-rose-200 border border-rose-500/30 text-xs font-medium transition-all disabled:opacity-60"
              >
                <Flag className="w-3.5 h-3.5" />
                <span>
                  {reportState === 'sending'
                    ? 'Reporting...'
                    : reportState === 'sent'
                    ? 'Report Received (Thank you!)'
                    : 'Report this link'}
                </span>
              </button>
            </div>
          </div>
        </div>

        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors flex-shrink-0"
            title="Dismiss error message"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
