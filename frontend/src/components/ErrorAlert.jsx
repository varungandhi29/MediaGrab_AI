import React from 'react';
import { AlertTriangle, X, Sparkles, ShieldAlert } from 'lucide-react';

export default function ErrorAlert({ error, onDismiss, onExplainAi, isExplaining }) {
  if (!error) return null;

  const isSsrf = error.toLowerCase().includes('ssrf') || error.toLowerCase().includes('security');

  return (
    <div className="w-full max-w-4xl mx-auto mt-6 p-4 rounded-2xl glass-panel border border-rose-500/40 bg-rose-950/20 shadow-xl animate-fadeIn">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-xl bg-rose-500/20 text-rose-400 flex-shrink-0 mt-0.5">
            {isSsrf ? <ShieldAlert className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
          </div>
          <div>
            <h4 className="font-bold text-sm text-rose-200">
              {isSsrf ? 'Security Alert: Request Blocked' : 'Extraction Error'}
            </h4>
            <p className="text-xs text-rose-300/90 mt-1 leading-relaxed">
              {error}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {onExplainAi && (
            <button
              onClick={onExplainAi}
              disabled={isExplaining}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 text-xs font-semibold border border-indigo-500/30 transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>{isExplaining ? 'Analyzing...' : 'Explain with AI'}</span>
            </button>
          )}

          <button
            onClick={onDismiss}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
