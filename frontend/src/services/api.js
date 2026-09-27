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

export async function startDownload({ url, quality_label, format_id, is_audio_only = false, target_format = 'mp4' }) {
  const resp = await fetch(`${API_BASE}/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      quality_label,
      format_id,
      is_audio_only,
      target_format,
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
