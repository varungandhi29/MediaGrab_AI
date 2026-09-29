/**
 * MediaGrab AI Client API Service
 */

const API_BASE = '/api';

export async function fetchMetadata(url) {
  const resp = await fetch(`${API_BASE}/metadata`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });

  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to fetch media metadata.');
  }
  return data;
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
      .then(meta => {
        if (onResult) onResult(meta);
      })
      .catch(err => {
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
  const resp = await fetch(`${API_BASE}/download`, {
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

  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to initiate download job.');
  }
  return data;
}

export async function getDownloadStatus(jobId) {
  const resp = await fetch(`${API_BASE}/download/status/${jobId}`);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to get job status.');
  }
  return data;
}

export function getFileDownloadUrl(token) {
  return `${API_BASE}/download/file/${token}`;
}

export async function detectPlatform(url) {
  const resp = await fetch(`${API_BASE}/ai/detect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!resp.ok) return null;
  return resp.json();
}

export async function getAiRecommendation({ url, use_case, available_qualities }) {
  const resp = await fetch(`${API_BASE}/ai/recommend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, use_case, available_qualities }),
  });
  if (!resp.ok) return null;
  return resp.json();
}

export async function getAiErrorExplanation({ url, raw_error }) {
  const resp = await fetch(`${API_BASE}/ai/explain-error`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, raw_error }),
  });
  if (!resp.ok) return null;
  return resp.json();
}

export async function getSystemHealth() {
  const resp = await fetch(`${API_BASE}/health`);
  if (!resp.ok) return null;
  return resp.json();
}

export async function getSystemStats() {
  const resp = await fetch(`${API_BASE}/stats`);
  if (!resp.ok) return null;
  return resp.json();
}

export async function getResilienceDashboard() {
  const resp = await fetch(`${API_BASE}/system/resilience`);
  if (!resp.ok) {
    throw new Error('Failed to fetch resilience dashboard telemetry.');
  }
  return resp.json();
}

export async function resetCircuitBreaker({ tier, domain } = {}) {
  const resp = await fetch(`${API_BASE}/system/resilience/circuits/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, domain }),
  });
  if (!resp.ok) {
    throw new Error('Failed to reset circuit breaker.');
  }
  return resp.json();
}

export async function triggerYtDlpUpdate(force = false) {
  const resp = await fetch(`${API_BASE}/system/resilience/update-ytdlp?force=${force}`, {
    method: 'POST',
  });
  if (!resp.ok) {
    throw new Error('Failed to trigger dependency self-healing update.');
  }
  return resp.json();
}

export async function triggerTestAlert(domain = 'example.com') {
  const resp = await fetch(`${API_BASE}/system/resilience/test-alert?domain=${encodeURIComponent(domain)}`, {
    method: 'POST',
  });
  return resp.json();
}

export async function refreshStreamSession(token, sourceUrl = null) {
  const query = sourceUrl ? `?url=${encodeURIComponent(sourceUrl)}` : '';
  const resp = await fetch(`${API_BASE}/stream/${token}/refresh${query}`, {
    method: 'POST',
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to refresh media stream.');
  }
  return resp.json();
}

export async function getStreamStatus(token) {
  const resp = await fetch(`${API_BASE}/stream/${token}/status`);
  if (!resp.ok) return null;
  return resp.json();
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
  const resp = await fetch(`${API_BASE}/system/resilience/run-synthetic-playback`, {
    method: 'POST',
  });
  if (!resp.ok) {
    throw new Error('Failed to run synthetic playback check.');
  }
  return resp.json();
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
  const resp = await fetch(`${API_BASE}/media/prepare`, {
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

  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to start media preparation.');
  }
  return data;
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
  const resp = await fetch(`${API_BASE}/media/status/${jobId}`);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to get media status.');
  }
  return data;
}

export async function cancelMediaJob(jobId) {
  const resp = await fetch(`${API_BASE}/media/cancel/${jobId}`, {
    method: 'POST',
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to cancel media job.');
  }
  return data;
}

export async function checkLink(url) {
  const resp = await fetch(`${API_BASE}/check-link`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to check link.');
  }
  return data;
}

export async function submitLinkReport({ url, domain, error_class, user_notes = '' }) {
  const resp = await fetch(`${API_BASE}/feedback/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, domain, error_class, user_notes }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to submit report.');
  }
  return data;
}

export async function submitRating({ url, domain, rating, action_type = 'play', comment = '' }) {
  const resp = await fetch(`${API_BASE}/feedback/rating`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, domain, rating, action_type, comment }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to submit rating.');
  }
  return data;
}

export async function getStatusBanner() {
  const resp = await fetch(`${API_BASE}/system/status-banner`);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to fetch status banner.');
  }
  return data;
}

export async function getUxMetrics() {
  const resp = await fetch(`${API_BASE}/system/ux-metrics`);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to fetch UX metrics.');
  }
  return data;
}

export async function getSupportedSites() {
  const resp = await fetch(`${API_BASE}/system/supported-sites`);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to fetch supported sites.');
  }
  return data;
}




