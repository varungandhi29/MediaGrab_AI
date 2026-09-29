import React, { useEffect } from 'react';
import { X, Command, Keyboard, Zap } from 'lucide-react';

export default function KeyboardShortcutsModal({ isOpen, onClose }) {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const shortcuts = [
    {
      category: 'Global Navigation',
      items: [
        { keys: ['Ctrl', 'V'], description: 'Paste URL from clipboard anywhere to analyze & fetch media' },
        { keys: ['?'], description: 'Open this keyboard shortcuts reference cheatsheet' },
        { keys: ['Esc'], description: 'Dismiss active modal, video player, or popup' },
      ],
    },
    {
      category: 'Video & Audio Player Controls',
      items: [
        { keys: ['Space'], description: 'Play or Pause playback' },
        { keys: ['←', '→'], description: 'Seek backward / forward by 5 seconds' },
        { keys: ['J', 'L'], description: 'Seek backward / forward by 10 seconds' },
        { keys: ['M'], description: 'Toggle audio Mute / Unmute' },
        { keys: ['F'], description: 'Toggle Fullscreen mode' },
        { keys: ['P'], description: 'Toggle Picture-in-Picture (PiP) floating window' },
        { keys: ['0', '—', '9'], description: 'Jump to 0% through 90% of the media timeline' },
      ],
    },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn"
      role="dialog"
      aria-modal="true"
    >
      <div className="relative w-full max-w-lg glass-panel rounded-2xl border border-slate-700/80 shadow-2xl p-6 sm:p-7 overflow-hidden">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Keyboard className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Keyboard Shortcuts</h3>
              <p className="text-xs text-slate-400">Boost your workflow with instant hotkeys</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            aria-label="Close shortcuts modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content list */}
        <div className="mt-5 space-y-6 max-h-[65vh] overflow-y-auto pr-1">
          {shortcuts.map((group, gIdx) => (
            <div key={gIdx}>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-3 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5" />
                <span>{group.category}</span>
              </h4>
              <div className="space-y-2">
                {group.items.map((item, iIdx) => (
                  <div
                    key={iIdx}
                    className="flex items-center justify-between p-2 rounded-xl bg-slate-900/60 border border-slate-800/80 text-xs"
                  >
                    <span className="text-slate-300 pr-3">{item.description}</span>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      {item.keys.map((k, kIdx) => (
                        <kbd
                          key={kIdx}
                          className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-[11px] font-mono font-bold text-slate-200 shadow-sm"
                        >
                          {k}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer tip */}
        <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500">
          <span>Press <kbd className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300">Esc</kbd> anytime to dismiss</span>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition-colors"
          >
            Got it
          </button>
        </div>

      </div>
    </div>
  );
}
