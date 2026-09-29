/**
 * Pre-Flight Browser & Hardware Feature Detection
 * Evaluates browser codec support, streaming engines, and platform constraints once per session.
 * Reused across all player instances to eliminate redundant DOM probing.
 */

const STORAGE_KEY = 'mediagrab_playback_capabilities_v1';
let cachedCapabilities = null;

export function getBrowserPlaybackCapabilities() {
  if (cachedCapabilities) {
    return cachedCapabilities;
  }

  // Try retrieving from sessionStorage
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored) {
      cachedCapabilities = JSON.parse(stored);
      return cachedCapabilities;
    }
  } catch (e) {
    // sessionStorage may be blocked in strict private browsing
  }

  const dummyVideo = typeof document !== 'undefined' ? document.createElement('video') : null;

  // 1. Native HLS Detection
  const nativeHls = dummyVideo ? dummyVideo.canPlayType('application/vnd.apple.mpegurl') : '';
  const hasNativeHls = nativeHls === 'probably' || nativeHls === 'maybe';

  // 2. MediaSource Extensions (MSE) Detection for HLS.js
  const hasMSE = typeof window !== 'undefined' && 'MediaSource' in window;
  let mseSupportsMp4 = false;
  if (hasMSE && typeof MediaSource.isTypeSupported === 'function') {
    try {
      mseSupportsMp4 = MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E,mp4a.40.2"');
    } catch (e) {
      mseSupportsMp4 = false;
    }
  }

  // 3. Codec Probing
  const codecs = {
    h264_aac: dummyVideo ? dummyVideo.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"') : '',
    h264_high: dummyVideo ? dummyVideo.canPlayType('video/mp4; codecs="avc1.640028, mp4a.40.2"') : '',
    vp9: dummyVideo ? dummyVideo.canPlayType('video/webm; codecs="vp9, opus"') : '',
    av1: dummyVideo ? dummyVideo.canPlayType('video/mp4; codecs="av01.0.05M.08"') : '',
    hevc: dummyVideo ? (dummyVideo.canPlayType('video/mp4; codecs="hvc1.1.6.L93.B0"') || dummyVideo.canPlayType('video/mp4; codecs="hev1.1.6.L93.B0"')) : '',
    mkv: dummyVideo ? dummyVideo.canPlayType('video/x-matroska') : '',
  };

  // 4. Platform & Browser Detection
  const ua = typeof navigator !== 'undefined' ? (navigator.userAgent || '') : '';
  const platform = typeof navigator !== 'undefined' ? (navigator.platform || '') : '';
  
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (platform === 'MacIntel' && typeof navigator !== 'undefined' && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/.test(ua);
  const isMobile = isIOS || isAndroid || /Mobi|Tablet/.test(ua);

  let browserName = 'Other';
  if (/Edg\//.test(ua)) {
    browserName = 'Edge';
  } else if (/Chrome\//.test(ua) && !/Edg\//.test(ua)) {
    browserName = 'Chrome';
  } else if (/Safari\//.test(ua) && !/Chrome\//.test(ua)) {
    browserName = 'Safari';
  } else if (/Firefox\//.test(ua)) {
    browserName = 'Firefox';
  }

  // 5. Network Information API
  const conn = typeof navigator !== 'undefined' ? (navigator.connection || navigator.mozConnection || navigator.webkitConnection) : null;
  const network = {
    effectiveType: conn?.effectiveType || '4g',
    downlink: conn?.downlink || 10,
    rtt: conn?.rtt || 50,
    saveData: Boolean(conn?.saveData),
  };

  const capabilities = {
    hasNativeHls,
    hasMSE,
    mseSupportsMp4,
    canUseHlsJs: hasMSE && mseSupportsMp4,
    codecs: {
      h264: Boolean(codecs.h264_aac || codecs.h264_high),
      vp9: Boolean(codecs.vp9),
      av1: Boolean(codecs.av1),
      hevc: Boolean(codecs.hevc),
      mkv: Boolean(codecs.mkv),
    },
    platform: {
      isIOS,
      isAndroid,
      isMobile,
      browserName,
      userAgent: ua.slice(0, 150),
    },
    network,
    timestamp: Date.now(),
  };

  cachedCapabilities = capabilities;

  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(capabilities));
  } catch (e) {
    // Ignore storage quota/permission errors
  }

  return capabilities;
}

/**
 * Evaluates whether a specific format can be played directly by the browser.
 */
export function isFormatNativelyPlayable(format, capabilities) {
  if (!format) return false;
  const caps = capabilities || getBrowserPlaybackCapabilities();

  // MKV is practically never supported in browser HTML5 <video>
  if (format.ext === 'mkv') return false;

  // HLS formats
  if (format.is_hls || (format.stream_url && format.stream_url.includes('.m3u8'))) {
    return caps.hasNativeHls || caps.canUseHlsJs;
  }

  const vcodec = (format.vcodec || '').toLowerCase();
  
  // HEVC / H.265 requires hardware / Safari support
  if (vcodec.includes('hevc') || vcodec.includes('h265') || vcodec.includes('hvc1')) {
    return caps.codecs.hevc;
  }

  // AV1 check
  if (vcodec.includes('av01') || vcodec.includes('av1')) {
    return caps.codecs.av1;
  }

  // VP9 check
  if (vcodec.includes('vp9') || vcodec.includes('vp09')) {
    return caps.codecs.vp9;
  }

  // Default H.264 / AVC MP4
  return caps.codecs.h264;
}
