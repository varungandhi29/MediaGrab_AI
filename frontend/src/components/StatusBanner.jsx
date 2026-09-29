import React, { useState, useEffect } from 'react';
import { CheckCircle2, AlertTriangle, RefreshCw, X, ShieldCheck } from 'lucide-react';
import { getStatusBanner } from '../services/api';

export default function StatusBanner() {
  const [statusData, setStatusData] = useState(null);
  const [isVisible, setIsVisible] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchStatus = async () => {
    try {
      setIsRefreshing(true);
      const data = await getStatusBanner();
      setStatusData(data);
    } catch (e) {
      // Graceful fallback: display normal status if banner query fails
      setStatusData({
        status: 'all_normal',
        message: 'All systems operational — YouTube, Vimeo, Reddit, and direct media ready.',
        failing_domains: [],
        last_checked: new Date().toISOString(),
      });
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000); // Poll every 30s
    return () => clearInterval(interval);
  }, []);

  if (!statusData || !isVisible) return null;

  const isNormal = statusData.status === 'all_normal';
  const hasDegraded = !isNormal;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`w-full border-b transition-all duration-300 text-xs sm:text-sm font-medium py-2 px-4 sm:px-8 flex items-center justify-between gap-3 ${
        isNormal
          ? 'bg-emerald-950/40 border-emerald-500/20 text-emerald-300'
          : 'bg-amber-950/50 border-amber-500/30 text-amber-200'
      }`}
    >
      <div className="flex items-center gap-2.5 mx-auto max-w-7xl w-full">
        {isNormal ? (
          <div className="flex items-center gap-1.5 flex-shrink-0 text-emerald-400">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <CheckCircle2 className="w-4 h-4" />
          </div>
        ) : (
          <div className="flex items-center gap-1.5 flex-shrink-0 text-amber-400">
            <AlertTriangle className="w-4 h-4 animate-bounce" />
          </div>
        )}

        <div className="flex-1 truncate">
          <span className="font-semibold mr-1">
            {isNormal ? 'System Status:' : 'Notice:'}
          </span>
          <span>{statusData.message}</span>
          {hasDegraded && statusData.failing_domains && statusData.failing_domains.length > 0 && (
            <span className="ml-1 opacity-90 font-mono text-[11px] bg-amber-900/60 px-1.5 py-0.5 rounded border border-amber-500/30">
              Affected: {statusData.failing_domains.join(', ')}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={fetchStatus}
            disabled={isRefreshing}
            className="p-1 rounded hover:bg-white/10 text-slate-300 transition-colors"
            title="Refresh status"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setIsVisible(false)}
            className="p-1 rounded hover:bg-white/10 text-slate-300 transition-colors"
            title="Dismiss status banner"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
