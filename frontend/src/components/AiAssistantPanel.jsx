import React, { useState } from 'react';
import { Sparkles, Bot, Smartphone, Monitor, Film, Headphones, Check, HelpCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { getAiRecommendation } from '../services/api';

const USE_CASES = [
  { id: 'standard', label: 'Standard HD', icon: Monitor, desc: 'Balanced 1080p/720p for laptop & desktop viewing' },
  { id: 'mobile', label: 'Mobile / Data Saver', icon: Smartphone, desc: 'Lightweight 480p/720p, saves 70% data' },
  { id: 'archive', label: 'Pro Archive / 4K', icon: Film, desc: 'Highest resolution & bitrate for editing in Premiere' },
  { id: 'podcast', label: 'Podcast / Music', icon: Headphones, desc: '320kbps MP3 audio only, saves 85% storage' },
];

export default function AiAssistantPanel({
  url,
  metadata,
  onApplyRecommendation,
  rawError,
  errorExplanation,
}) {
  const [isOpen, setIsOpen] = useState(true);
  const [activeUseCase, setActiveUseCase] = useState('standard');
  const [isRecommending, setIsRecommending] = useState(false);
  const [recommendationResult, setRecommendationResult] = useState(null);

  const handleSelectUseCase = async (useCaseId) => {
    setActiveUseCase(useCaseId);
    if (!metadata || !metadata.available_qualities) return;

    setIsRecommending(true);
    try {
      const qualityLabels = metadata.available_qualities.map(q => q.quality_label);
      const res = await getAiRecommendation({
        url: url || metadata.url,
        use_case: useCaseId,
        available_qualities: qualityLabels,
      });

      if (res) {
        setRecommendationResult(res);
        // Find corresponding quality object and apply it
        const matched = metadata.available_qualities.find(
          q => q.quality_label.toLowerCase().includes(res.recommended_quality.toLowerCase().split(' ')[0])
        ) || (useCaseId === 'podcast' ? metadata.available_qualities.find(q => q.is_audio_only) : metadata.available_qualities[0]);

        if (matched && onApplyRecommendation) {
          onApplyRecommendation(matched);
        }
      }
    } catch (e) {
      console.error('AI Recommendation failed', e);
    } finally {
      setIsRecommending(false);
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto mt-6 glass-panel rounded-2xl border border-indigo-500/20 bg-gradient-to-b from-indigo-950/20 via-slate-900/60 to-slate-950/80 shadow-2xl overflow-hidden transition-all">
      
      {/* Header Bar */}
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between p-4 cursor-pointer hover:bg-white/5 transition-colors border-b border-indigo-500/10"
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center border border-indigo-500/30">
            <Bot className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-white">MediaGrab AI Assistant</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-semibold border border-indigo-500/30 flex items-center gap-1">
                <Sparkles className="w-2.5 h-2.5" /> Smart Guidance
              </span>
            </div>
            <p className="text-[11px] text-slate-400">Intelligent format selector & plain-language diagnostics</p>
          </div>
        </div>

        <button className="text-slate-400 hover:text-white p-1">
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {/* Collapsible Content */}
      {isOpen && (
        <div className="p-4 sm:p-5 space-y-4">
          
          {/* Error Diagnostics (if present) */}
          {errorExplanation && (
            <div className="p-3.5 rounded-xl bg-amber-950/30 border border-amber-500/30 text-amber-200 text-xs space-y-1.5 animate-fadeIn">
              <div className="flex items-center gap-2 font-semibold text-amber-300">
                <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
                <span>AI Error Breakdown: {errorExplanation.category}</span>
              </div>
              <p className="text-slate-300 pl-6 leading-relaxed">
                {errorExplanation.human_summary}
              </p>
              <div className="pl-6 pt-1 text-[11px] text-amber-400 font-medium">
                👉 Suggested Next Step: {errorExplanation.suggested_action}
              </div>
            </div>
          )}

          {/* Goal-Based Quality Recommender */}
          {metadata && metadata.available_qualities?.length > 0 && (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2.5 flex items-center justify-between">
                <span>Select Your Goal to Auto-Tune Format</span>
                <span className="text-[10px] text-indigo-300 font-normal">Click goal to apply</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                {USE_CASES.map((uc) => {
                  const Icon = uc.icon;
                  const isSelected = activeUseCase === uc.id;

                  return (
                    <button
                      key={uc.id}
                      type="button"
                      disabled={isRecommending}
                      onClick={() => handleSelectUseCase(uc.id)}
                      className={`p-3 rounded-xl border text-left transition-all flex flex-col justify-between ${
                        isSelected
                          ? 'bg-indigo-600/20 border-indigo-500 text-white shadow-md shadow-indigo-500/10'
                          : 'bg-slate-900/50 border-slate-800 hover:border-slate-700 text-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <div className={`p-1.5 rounded-lg ${isSelected ? 'bg-indigo-500 text-white' : 'bg-slate-800 text-slate-400'}`}>
                          <Icon className="w-3.5 h-3.5" />
                        </div>
                        {isSelected && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                      </div>

                      <div>
                        <div className="font-semibold text-xs text-white">{uc.label}</div>
                        <div className="text-[10px] text-slate-400 mt-0.5 leading-snug">{uc.desc}</div>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Recommendation Rationale Display */}
              {recommendationResult && (
                <div className="mt-3 p-3 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-300 space-y-1">
                  <div className="flex items-center gap-1.5 text-cyan-400 font-medium">
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Selected: {recommendationResult.recommended_quality}</span>
                  </div>
                  <p className="text-slate-400 text-[11px] leading-relaxed">{recommendationResult.reason}</p>
                  {recommendationResult.tips?.[0] && (
                    <p className="text-slate-500 text-[10px] italic">💡 Tip: {recommendationResult.tips[0]}</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Security Notice for AI */}
          <div className="pt-2 border-t border-slate-800 flex items-center justify-between text-[10px] text-slate-500">
            <span>External content parsed as untrusted inert data (Prompt-Injection Hardened)</span>
            <span className="font-mono text-emerald-400">Zero-Trust Active</span>
          </div>

        </div>
      )}
    </div>
  );
}
