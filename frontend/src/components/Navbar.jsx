import React from 'react';
import { Shield, Sparkles, History, HelpCircle, FileText, Activity, Keyboard, LogIn, LogOut, ChevronDown, User } from 'lucide-react';

export default function Navbar({ 
  activeTab, 
  setActiveTab, 
  onOpenHowItWorks, 
  onOpenLegal, 
  onOpenShortcuts, 
  onOpenAuth,
  onLogout,
  currentUser,
  historyCount = 0 
}) {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-cyber-border/70 bg-cyber-dark/85 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Brand Logo */}
        <div 
          onClick={() => setActiveTab('home')}
          className="flex items-center gap-3 cursor-pointer group"
        >
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-500 flex items-center justify-center text-white shadow-lg shadow-emerald-500/20 group-hover:scale-105 transition-transform duration-200">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-300 bg-clip-text text-transparent">
                MediaGrab
              </span>
              <span className="text-xs px-2 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                AI v1.0
              </span>
            </div>
            <p className="text-[10px] text-slate-400 hidden sm:block">Universal Media Engine • SSRF Protected</p>
          </div>
        </div>

        {/* Navigation Actions */}
        <nav className="flex items-center gap-1 sm:gap-2">
          {/* SSRF Shield Status Badge */}
          <div 
            onClick={onOpenHowItWorks}
            title="SSRF Protection Active: All URLs validated against private RFC networks before fetching"
            className="hidden md:flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-950/40 text-emerald-300 border border-emerald-500/30 cursor-pointer hover:bg-emerald-900/30 transition-colors"
          >
            <Shield className="w-3.5 h-3.5 text-emerald-400" />
            <span>SSRF Shield Active</span>
          </div>

          <button
            onClick={() => setActiveTab('home')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'home'
                ? 'bg-slate-800 text-white shadow-sm'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
            }`}
          >
            Downloader
          </button>

          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'history'
                ? 'bg-slate-800 text-white shadow-sm'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
            }`}
          >
            <History className="w-4 h-4" />
            <span>History</span>
            {historyCount > 0 && (
              <span className="text-[11px] px-1.5 py-0.2 rounded-full bg-cyan-500/20 text-cyan-300 font-bold">
                {historyCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('resilience')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'resilience'
                ? 'bg-slate-800 text-white shadow-sm'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
            }`}
          >
            <Activity className="w-4 h-4 text-emerald-400" />
            <span>Resilience</span>
          </button>

          <button
            onClick={onOpenShortcuts}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
            title="Keyboard Shortcuts Cheatsheet (Hotkey: ?)"
          >
            <Keyboard className="w-4 h-4 text-emerald-400" />
            <span className="hidden sm:inline">Shortcuts</span>
          </button>

          <button
            onClick={onOpenHowItWorks}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
            title="How MediaGrab AI Works & Security Architecture"
          >
            <HelpCircle className="w-4 h-4" />
            <span className="hidden sm:inline">FAQ</span>
          </button>

          <button
            onClick={onOpenLegal}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800/50 transition-colors"
            title="Legal & Terms of Use"
          >
            <FileText className="w-4 h-4" />
            <span className="hidden sm:inline">Legal</span>
          </button>

          {/* Authentication Button / User Profile Menu */}
          <div className="pl-1 sm:pl-2">
            {currentUser ? (
              <div className="relative group">
                <button
                  type="button"
                  className="flex items-center gap-2 pl-2 pr-3 py-1 rounded-full bg-slate-800/90 border border-emerald-500/40 text-xs font-semibold text-white hover:bg-slate-700/80 transition-all shadow-sm"
                >
                  <div className="w-6 h-6 rounded-full bg-gradient-to-tr from-emerald-500 to-teal-400 text-slate-950 flex items-center justify-center font-bold text-xs">
                    {currentUser.name ? currentUser.name.charAt(0).toUpperCase() : 'U'}
                  </div>
                  <span className="max-w-[90px] truncate hidden sm:inline">{currentUser.name || 'Account'}</span>
                  <ChevronDown className="w-3.5 h-3.5 text-slate-400 group-hover:rotate-180 transition-transform" />
                </button>

                <div className="absolute right-0 mt-2 w-52 py-1.5 rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl backdrop-blur-md hidden group-hover:block animate-fadeIn z-50">
                  <div className="px-3.5 py-2.5 border-b border-slate-800">
                    <p className="text-xs font-bold text-white truncate">{currentUser.name}</p>
                    <p className="text-[11px] text-slate-400 truncate">{currentUser.email}</p>
                    <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                      {currentUser.tier || 'Pro Member'}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setActiveTab('history')}
                    className="w-full text-left px-3.5 py-2 text-xs text-slate-300 hover:text-white hover:bg-slate-800/60 flex items-center gap-2"
                  >
                    <History className="w-3.5 h-3.5 text-cyan-400" />
                    <span>My Downloads</span>
                  </button>
                  <button
                    type="button"
                    onClick={onLogout}
                    className="w-full text-left px-3.5 py-2 text-xs text-rose-400 hover:bg-rose-500/10 flex items-center gap-2 border-t border-slate-800/80 mt-1"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={onOpenAuth}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 shadow-md shadow-emerald-500/20 transition-all hover:scale-105 active:scale-95"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>Login</span>
              </button>
            )}
          </div>

        </nav>
      </div>
    </header>
  );
}
