import React from 'react';
import { X, Scale, AlertOctagon, FileCheck, ShieldAlert } from 'lucide-react';

export default function LegalTermsModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto glass-panel rounded-2xl border border-slate-700 p-6 sm:p-8 shadow-2xl">
        
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center border border-amber-500/30">
            <Scale className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Terms of Service & Legal Disclaimer</h2>
            <p className="text-xs text-slate-400">Responsible Usage and Copyright Compliance Notice</p>
          </div>
        </div>

        {/* Important Warning Banner */}
        <div className="p-4 rounded-xl bg-amber-950/30 border border-amber-500/30 text-amber-200 text-xs mb-6 space-y-2">
          <div className="flex items-center gap-2 font-bold text-amber-300">
            <AlertOctagon className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span>CRITICAL USER RESPONSIBILITY NOTICE</span>
          </div>
          <p className="leading-relaxed">
            MediaGrab AI is an automated media extraction tool designed strictly for retrieving content you own, have explicit authorization to download, or which is distributed under open licenses (such as Creative Commons, public domain, or open educational resources).
          </p>
        </div>

        {/* Legal Clauses */}
        <div className="space-y-5 text-xs text-slate-300 leading-relaxed">
          
          <div>
            <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-1.5">
              <FileCheck className="w-4 h-4 text-emerald-400" /> 1. Copyright Compliance & Intellectual Property
            </h3>
            <p className="text-slate-400">
              Users are solely responsible for verifying copyright ownership and ensuring their use complies with applicable intellectual property laws, fair use doctrines, and local regulations. MediaGrab AI does not host, index, or distribute copyrighted media files.
            </p>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-1.5">
              <ShieldAlert className="w-4 h-4 text-rose-400" /> 2. Prohibition of DRM Circumvention & Piracy
            </h3>
            <p className="text-slate-400">
              MediaGrab AI contains zero capabilities for circumventing digital rights management (DRM) technologies (including Widevine, FairPlay, or PlayReady). Any attempt to utilize this tool for unauthorized commercial exploitation, copyright infringement, or bypassing technological protection measures is strictly prohibited.
            </p>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-1.5">
              <Scale className="w-4 h-4 text-cyan-400" /> 3. Terms of Service Adherence
            </h3>
            <p className="text-slate-400">
              Users must adhere to the terms of service of third-party platforms from which they access media. You agree to hold the developers, operators, and maintainers of MediaGrab AI harmless against any claims arising from misuse of this software.
            </p>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-white mb-1">
              4. Ephemeral Storage & Privacy
            </h3>
            <p className="text-slate-400">
              Files temporarily retrieved are stored in cryptographically random isolated files and automatically destroyed after 60 minutes. We store no personally identifiable information (PII) and maintain only anonymous, aggregate operational metrics.
            </p>
          </div>

        </div>

        {/* Modal Footer */}
        <div className="mt-8 pt-4 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-6 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-md transition-colors"
          >
            I Understand & Agree
          </button>
        </div>

      </div>
    </div>
  );
}
