/**
 * Detects optimal initial streaming quality based on Network Information API.
 * Only selects from resolutions genuinely available in the source media.
 * Never fabricates unavailable resolutions. Fallback is 720p.
 */
export function getRecommendedInitialQuality(availableHeights = []) {
  if (!availableHeights || availableHeights.length === 0) {
    return 720;
  }

  // Ensure unique, numeric, sorted descending [2160, 1440, 1080, 720, 480, 360]
  const validHeights = Array.from(new Set(availableHeights.map(Number)))
    .filter(h => !isNaN(h) && h > 0)
    .sort((a, b) => b - a);

  if (validHeights.length === 0) {
    return 720;
  }

  // Network Information API detection (Chromium, Edge, Android)
  const connection =
    navigator.connection ||
    navigator.mozConnection ||
    navigator.webkitConnection;

  if (connection) {
    const { downlink, effectiveType, saveData } = connection;

    // Data saver enabled or 2G / low bandwidth -> pick lowest or 480p
    if (saveData || effectiveType === 'slow-2g' || effectiveType === '2g' || (downlink && downlink < 1.5)) {
      const low = validHeights.filter(h => h <= 480);
      return low.length > 0 ? low[0] : validHeights[validHeights.length - 1];
    }

    // 3G or medium bandwidth (1.5 - 5 Mbps) -> pick 720p or closest
    if (effectiveType === '3g' || (downlink && downlink < 5.0)) {
      const mid = validHeights.filter(h => h <= 720);
      return mid.length > 0 ? mid[0] : validHeights[validHeights.length - 1];
    }

    // Ultra high-speed (downlink >= 25 Mbps) -> pick 4K / 2K / 1080p if available
    if (downlink && downlink >= 25.0) {
      return validHeights[0];
    }

    // Normal fast 4G (5 - 25 Mbps) -> prefer 1080p if available, else 720p
    const hd = validHeights.filter(h => h <= 1080);
    return hd.length > 0 ? hd[0] : validHeights[0];
  }

  // Safe Fallback when Network Information API is not supported (Safari / Firefox)
  // Default to 720p if available
  if (validHeights.includes(720)) {
    return 720;
  }

  // Closest available height <= 720p
  const under720 = validHeights.filter(h => h <= 720);
  if (under720.length > 0) {
    return under720[0];
  }

  // Fallback to lowest available HD
  return validHeights[validHeights.length - 1];
}

/**
 * Returns human-readable connection status description.
 */
export function getConnectionDescription() {
  const connection =
    navigator.connection ||
    navigator.mozConnection ||
    navigator.webkitConnection;

  if (!connection) {
    return 'Standard Broadband (Default 720p)';
  }

  const type = connection.effectiveType ? connection.effectiveType.toUpperCase() : 'Broadband';
  const speed = connection.downlink ? `~${connection.downlink} Mbps` : '';
  const save = connection.saveData ? ' (Data Saver ON)' : '';
  return `${type} ${speed}${save}`.trim();
}
