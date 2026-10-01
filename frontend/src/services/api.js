/**
 * MediaGrab AI Client API Service
 */

const API_BASE = '/api';

/**
 * Robust fetch wrapper that gracefully catches network / connection errors
 */
async function safeFetch(url, options = {}) {
  try {
    return await fetch(url, options);
  } catch (err) {
    throw new Error(
      'Network connection error: Unable to communicate with MediaGrab AI server. Please verify your internet connection or check if the backend service is running.'
    );
  }
}

/**
 * Robust JSON response parser that handles non-JSON / gateway HTML gracefully
 */
async function parseJsonResponse(resp, defaultErrorMsg = 'Request failed.') {
  const contentType = resp.headers.get('content-type') || '';
  let data = null;
  let text = '';

  if (contentType.includes('application/json')) {
    try {
      data = await resp.json();
    } catch {
      data = null;
    }
  }

  if (data === null) {
    try {
      text = await resp.text();
    } catch {
      text = '';
    }
  }

  if (!resp.ok) {
    if (data && data.detail) {
      if (typeof data.detail === 'string') {
        throw new Error(data.detail);
      } else if (Array.isArray(data.detail) && data.detail[0]?.msg) {
        throw new Error(data.detail[0].msg);
      }
    }
    if (resp.status === 502 || resp.status === 503 || resp.status === 504 || resp.status === 520 || resp.status === 530) {
      throw new Error(
        `Backend server or gateway is temporarily unreachable (HTTP ${resp.status}). The service is currently reconnecting.`
      );
    }
    if (text.includes('An error occurred') || text.includes('<!DOCTYPE') || text.includes('<html')) {
      throw new Error(`Server temporarily unavailable (HTTP ${resp.status}). Please try again in a few moments.`);
    }
    throw new Error(text || `${defaultErrorMsg} (HTTP ${resp.status})`);
  }

  if (data !== null) return data;

  try {
    return JSON.parse(text);
  } catch {
    throw new Error('Received unexpected non-JSON response from server.');
  }
}

export async function fetchMetadata(url) {
  const resp = await safeFetch(`${API_BASE}/metadata`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  return parseJsonResponse(resp, 'Failed to fetch media metadata.');
}

export function fetchMetadataStream(url, { onStage, onResult, onError }) {
  const encUrl = encodeURIComponent(url);
  const es = new EventSource(`${API_BASE}/metadata/stream?url=${encUrl}`);

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'stage') {
        if (onStage) onStage(data);
      } else if (data.type === 'result') {
        es.close();
        if (onResult) onResult(data.metadata);
      } else if (data.type === 'error') {
        es.close();
        if (onError) onError(new Error(data.error));
      }
    } catch (e) {
      console.error('SSE JSON error', e);
    }
  };

  es.onerror = () => {
    es.close();
    // Fallback to standard POST /api/metadata if SSE was disconnected
    fetchMetadata(url)
      .then((meta) => {
        if (onResult) onResult(meta);
      })
      .catch((err) => {
        if (onError) onError(err);
      });
  };

  return () => es.close();
}

export async function startDownload({
  url,
  quality_label,
  format_id,
  is_audio_only = false,
  target_format = 'mp4',
  start_time = null,
  end_time = null,
}) {
  const resp = await safeFetch(`${API_BASE}/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      quality_label,
      format_id,
      is_audio_only,
      target_format,
      start_time,
      end_time,
    }),
  });
  return parseJsonResponse(resp, 'Failed to initiate download job.');
}

export async function getDownloadStatus(jobId) {
  const resp = await safeFetch(`${API_BASE}/download/status/${jobId}`);
  return parseJsonResponse(resp, 'Failed to get job status.');
}

export function getFileDownloadUrl(token) {
  return `${API_BASE}/download/file/${token}`;
}

export async function detectPlatform(url) {
  try {
    const resp = await safeFetch(`${API_BASE}/ai/detect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    if (!resp.ok) return null;
    return await resp.json().catch(() => null);
  } catch {
    return null;
  }
}

export async function getAiRecommendation({ url, use_case, available_qualities }) {
  try {
    const resp = await safeFetch(`${API_BASE}/ai/recommend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, use_case, available_qualities }),
    });
    if (!resp.ok) return null;
    return await resp.json().catch(() => null);
  } catch {
    return null;
  }
}

export async function getAiErrorExplanation({ url, raw_error }) {
  try {
    const resp = await safeFetch(`${API_BASE}/ai/explain-error`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, raw_error }),
    });
    if (!resp.ok) return null;
    return await resp.json().catch(() => null);
  } catch {
    return null;
  }
}

export async function getSystemHealth() {
  try {
    const resp = await safeFetch(`${API_BASE}/health`);
    if (!resp.ok) return null;
    return await resp.json().catch(() => null);
  } catch {
    return null;
  }
}

export async function getSystemStats() {
  try {
    const resp = await safeFetch(`${API_BASE}/stats`);
    if (!resp.ok) return null;
    return await resp.json().catch(() => null);
  } catch {
    return null;
  }
}

export async function getResilienceDashboard() {
  const resp = await safeFetch(`${API_BASE}/system/resilience`);
  return parseJsonResponse(resp, 'Failed to fetch resilience dashboard telemetry.');
}

export async function resetCircuitBreaker({ tier, domain } = {}) {
  const resp = await safeFetch(`${API_BASE}/system/resilience/circuits/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, domain }),
  });
  return parseJsonResponse(resp, 'Failed to reset circuit breaker.');
}

export async function triggerYtDlpUpdate(force = false) {
  const resp = await safeFetch(`${API_BASE}/system/resilience/update-ytdlp?force=${force}`, {
    method: 'POST',
  });
  return parseJsonResponse(resp, 'Failed to trigger dependency self-healing update.');
}

export async function triggerTestAlert(domain = 'example.com') {
  try {
    const resp = await safeFetch(`${API_BASE}/system/resilience/test-alert?domain=${encodeURIComponent(domain)}`, {
      method: 'POST',
    });
    return await resp.json().catch(() => null);
  } catch {
    return null;
  }
}

export async function refreshStreamSession(token, sourceUrl = null) {
  const query = sourceUrl ? `?url=${encodeURIComponent(sourceUrl)}` : '';
  const resp = await safeFetch(`${API_BASE}/stream/${token}/refresh${query}`, {
    method: 'POST',
  });
  return parseJsonResponse(resp, 'Failed to refresh media stream.');
}

export async function getStreamStatus(token) {
  try {
    const resp = await safeFetch(`${API_BASE}/stream/${token}/status`);
    if (!resp.ok) return null;
    return await resp.json().catch(() => null);
  } catch {
    return null;
  }
}

export function sendPlaybackRUM(telemetry) {
  const url = `${API_BASE}/system/rum/playback`;
  const body = JSON.stringify(telemetry);
  if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
    const blob = new Blob([body], { type: 'application/json' });
    navigator.sendBeacon(url, blob);
  } else {
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {});
  }
}

export async function triggerSyntheticPlaybackCheck() {
  const resp = await safeFetch(`${API_BASE}/system/resilience/run-synthetic-playback`, {
    method: 'POST',
  });
  return parseJsonResponse(resp, 'Failed to run synthetic playback check.');
}

export async function prepareMedia({
  url,
  quality_label = 'Best',
  format_id = null,
  height = null,
  is_audio_only = false,
  start_time = null,
  end_time = null,
}) {
  const resp = await safeFetch(`${API_BASE}/media/prepare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      quality_label,
      format_id,
      height,
      is_audio_only,
      start_time,
      end_time,
    }),
  });
  return parseJsonResponse(resp, 'Failed to start media preparation.');
}

export function streamMediaProgress(jobId, { onProgress, onReady, onError }) {
  const es = new EventSource(`${API_BASE}/media/progress/${jobId}`);

  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.stage === 'ready') {
        es.close();
        if (onReady) onReady(data);
      } else if (data.stage === 'failed') {
        es.close();
        if (onError) onError(new Error(data.error_message || 'Media preparation failed.'));
      } else {
        if (onProgress) onProgress(data);
      }
    } catch (e) {
      console.error('SSE JSON error', e);
    }
  };

  es.onerror = () => {
    es.close();
    // Fallback polling getMediaStatus if SSE disconnected
    getMediaStatus(jobId)
      .then((data) => {
        if (data.stage === 'ready' && onReady) onReady(data);
        else if (data.stage === 'failed' && onError) onError(new Error(data.error_message || 'Media preparation failed.'));
        else if (onProgress) onProgress(data);
      })
      .catch((err) => {
        if (onError) onError(err);
      });
  };

  return () => es.close();
}

export async function getMediaStatus(jobId) {
  const resp = await safeFetch(`${API_BASE}/media/status/${jobId}`);
  return parseJsonResponse(resp, 'Failed to get media status.');
}

export async function cancelMediaJob(jobId) {
  const resp = await safeFetch(`${API_BASE}/media/cancel/${jobId}`, {
    method: 'POST',
  });
  return parseJsonResponse(resp, 'Failed to cancel media job.');
}

export async function checkLink(url) {
  const resp = await safeFetch(`${API_BASE}/check-link`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  return parseJsonResponse(resp, 'Failed to check link.');
}

export async function submitLinkReport({ url, domain, error_class, user_notes = '' }) {
  const resp = await safeFetch(`${API_BASE}/feedback/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, domain, error_class, user_notes }),
  });
  return parseJsonResponse(resp, 'Failed to submit report.');
}

export async function submitRating({ url, domain, rating, action_type = 'play', comment = '' }) {
  const resp = await safeFetch(`${API_BASE}/feedback/rating`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, domain, rating, action_type, comment }),
  });
  return parseJsonResponse(resp, 'Failed to submit rating.');
}

export async function getStatusBanner() {
  const resp = await safeFetch(`${API_BASE}/system/status-banner`);
  return parseJsonResponse(resp, 'Failed to fetch status banner.');
}

export async function getUxMetrics() {
  const resp = await safeFetch(`${API_BASE}/system/ux-metrics`);
  return parseJsonResponse(resp, 'Failed to fetch UX metrics.');
}

export async function getSupportedSites() {
  const resp = await safeFetch(`${API_BASE}/system/supported-sites`);
  return parseJsonResponse(resp, 'Failed to fetch supported sites.');
}
