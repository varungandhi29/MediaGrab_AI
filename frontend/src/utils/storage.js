/**
 * Local storage manager for session download history (No login required for v1)
 */

const HISTORY_KEY = 'mediagrab_history_v1';

export function getDownloadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.error('Failed to read download history', e);
    return [];
  }
}

export function saveDownloadHistoryItem(item) {
  try {
    const existing = getDownloadHistory();
    // Prepend new item
    const updated = [
      {
        id: item.id || Date.now().toString(),
        title: item.title || 'Untitled Media',
        thumbnail: item.thumbnail || null,
        url: item.url,
        quality: item.quality,
        filesize: item.filesize,
        timestamp: new Date().toISOString(),
        downloadToken: item.downloadToken,
        platform: item.platform || 'Web',
      },
      ...existing.filter(i => i.id !== item.id)
    ].slice(0, 50); // keep max 50 items

    localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
    return updated;
  } catch (e) {
    console.error('Failed to save history item', e);
    return [];
  }
}

export function removeDownloadHistoryItem(id) {
  try {
    const existing = getDownloadHistory();
    const updated = existing.filter(i => i.id !== id);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
    return updated;
  } catch (e) {
    return [];
  }
}

export function clearDownloadHistory() {
  try {
    localStorage.removeItem(HISTORY_KEY);
    return [];
  } catch (e) {
    return [];
  }
}
