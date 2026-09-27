import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import UrlInputForm from './components/UrlInputForm';
import MediaMetadataCard from './components/MediaMetadataCard';
import DownloadProgressBar from './components/DownloadProgressBar';
import AiAssistantPanel from './components/AiAssistantPanel';
import DownloadHistory from './components/DownloadHistory';
import HowItWorksModal from './components/HowItWorksModal';
import LegalTermsModal from './components/LegalTermsModal';
import ErrorAlert from './components/ErrorAlert';
import ExtractionStagesIndicator from './components/ExtractionStagesIndicator';

import {
  fetchMetadata,
  fetchMetadataStream,
  startDownload,
  getDownloadStatus,
  getAiRecommendation,
  getAiErrorExplanation,
  getSystemStats,
} from './services/api';

import {
  getDownloadHistory,
  saveDownloadHistoryItem,
  removeDownloadHistoryItem,
  clearDownloadHistory,
} from './utils/storage';

export default function App() {
  const [activeTab, setActiveTab] = useState('home');
  const [currentUrl, setCurrentUrl] = useState('');
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  const [metadata, setMetadata] = useState(null);
  const [selectedQuality, setSelectedQuality] = useState(null);
  const [recommendedQuality, setRecommendedQuality] = useState(null);
  const [extractionStage, setExtractionStage] = useState(null);

  const [activeJob, setActiveJob] = useState(null);
  const [isDownloading, setIsDownloading] = useState(false);

  const [errorMessage, setErrorMessage] = useState(null);
  const [errorExplanation, setErrorExplanation] = useState(null);
  const [isExplainingError, setIsExplainingError] = useState(false);

  const [history, setHistory] = useState([]);
  const [isHowItWorksOpen, setIsHowItWorksOpen] = useState(false);
  const [isLegalOpen, setIsLegalOpen] = useState(false);
  const [stats, setStats] = useState(null);

  // Load download history and system stats on mount
  useEffect(() => {
    setHistory(getDownloadHistory());
    getSystemStats().then(setStats).catch(() => {});
  }, []);

  // Fetch Metadata Flow with Live Fast-Fail Multi-Tier Streaming
  const handleFetchMetadata = (url) => {
    setCurrentUrl(url);
    setIsLoadingMetadata(true);
    setErrorMessage(null);
    setErrorExplanation(null);
    setMetadata(null);
    setActiveJob(null);
    setExtractionStage({ tier: 1, stage: 'ytdlp', message: 'Trying standard extraction (yt-dlp)...' });

    fetchMetadataStream(url, {
      onStage: (stageData) => {
        setExtractionStage(stageData);
      },
      onResult: async (data) => {
        setIsLoadingMetadata(false);
        setMetadata(data);

        // Default quality selection
        if (data.available_qualities && data.available_qualities.length > 0) {
          const preferred = data.available_qualities.find(q => !q.is_audio_only && (q.quality_label.includes('1080p') || q.quality_label.includes('720p')))
            || data.available_qualities[0];
          setSelectedQuality(preferred);

          // Fetch AI recommendation automatically for standard viewing
          try {
            const qualityLabels = data.available_qualities.map(q => q.quality_label);
            const aiRec = await getAiRecommendation({
              url,
              use_case: 'standard',
              available_qualities: qualityLabels,
            });
            if (aiRec) {
              setRecommendedQuality(aiRec.recommended_quality);
            }
          } catch (e) {
            // AI recommendation is progressive enhancement
          }
        }
      },
      onError: (err) => {
        setIsLoadingMetadata(false);
        const rawErr = err.message || 'Failed to fetch media.';
        setErrorMessage(rawErr);
        handleExplainError(url, rawErr);
      }
    });
  };

  // AI Error Explainer
  const handleExplainError = async (urlToExplain, errToExplain) => {
    const targetUrl = urlToExplain || currentUrl;
    const targetErr = errToExplain || errorMessage;
    if (!targetErr) return;

    setIsExplainingError(true);
    try {
      const explanation = await getAiErrorExplanation({
        url: targetUrl,
        raw_error: targetErr,
      });
      setErrorExplanation(explanation);
    } catch (e) {
      console.error('Failed to explain error', e);
    } finally {
      setIsExplainingError(false);
    }
  };

  // Download Execution Flow
  const handleStartDownload = async () => {
    if (!metadata || !selectedQuality) return;

    setIsDownloading(true);
    setErrorMessage(null);

    try {
      const job = await startDownload({
        url: metadata.url,
        quality_label: selectedQuality.quality_label,
        format_id: selectedQuality.format_id,
        is_audio_only: selectedQuality.is_audio_only,
        target_format: selectedQuality.ext || 'mp4',
      });

      setActiveJob(job);
      subscribeToJobProgress(job.job_id);
    } catch (err) {
      setIsDownloading(false);
      setErrorMessage(err.message || 'Failed to start download job.');
    }
  };

  // SSE or Polling Progress Subscription
  const subscribeToJobProgress = (jobId) => {
    let sseSource = null;
    let pollInterval = null;

    const cleanup = () => {
      if (sseSource) sseSource.close();
      if (pollInterval) clearInterval(pollInterval);
      setIsDownloading(false);
    };

    // Try Server-Sent Events (SSE)
    try {
      sseSource = new EventSource(`/api/download/progress/${jobId}`);

      sseSource.onmessage = (event) => {
        try {
          const jobUpdate = JSON.parse(event.data);
          setActiveJob(jobUpdate);

          if (jobUpdate.status === 'completed') {
            cleanup();
            // Record in download history
            const updatedHistory = saveDownloadHistoryItem({
              id: jobUpdate.job_id,
              title: metadata?.title || jobUpdate.filename || 'Media file',
              thumbnail: metadata?.thumbnail,
              url: metadata?.url || currentUrl,
              quality: selectedQuality?.quality_label || 'Default',
              filesize: jobUpdate.filesize,
              downloadToken: jobUpdate.download_token,
              platform: metadata?.platform || 'Web',
            });
            setHistory(updatedHistory);
          } else if (jobUpdate.status === 'failed') {
            cleanup();
            setErrorMessage(jobUpdate.error_message || 'Download failed during extraction.');
          }
        } catch (e) {
          console.error('Failed to parse SSE data', e);
        }
      };

      sseSource.onerror = () => {
        // Fallback to polling if SSE is interrupted
        if (sseSource) sseSource.close();
        pollInterval = setInterval(async () => {
          try {
            const status = await getDownloadStatus(jobId);
            setActiveJob(status);
            if (status.status === 'completed' || status.status === 'failed') {
              clearInterval(pollInterval);
              setIsDownloading(false);
              if (status.status === 'completed') {
                const updatedHistory = saveDownloadHistoryItem({
                  id: status.job_id,
                  title: metadata?.title || status.filename || 'Media file',
                  thumbnail: metadata?.thumbnail,
                  url: metadata?.url || currentUrl,
                  quality: selectedQuality?.quality_label || 'Default',
                  filesize: status.filesize,
                  downloadToken: status.download_token,
                  platform: metadata?.platform || 'Web',
                });
                setHistory(updatedHistory);
              }
            }
          } catch (e) {
            clearInterval(pollInterval);
            setIsDownloading(false);
          }
        }, 1500);
      };
    } catch (e) {
      // Direct polling fallback
      pollInterval = setInterval(async () => {
        try {
          const status = await getDownloadStatus(jobId);
          setActiveJob(status);
          if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(pollInterval);
            setIsDownloading(false);
          }
        } catch (e) {
          clearInterval(pollInterval);
          setIsDownloading(false);
        }
      }, 1500);
    }
  };

  const handleResetJob = () => {
    setActiveJob(null);
    setIsDownloading(false);
  };

  const handleApplyAiRecommendation = (qualityOption) => {
    setSelectedQuality(qualityOption);
  };

  const handleRemoveHistoryItem = (id) => {
    const updated = removeDownloadHistoryItem(id);
    setHistory(updated);
  };

  const handleClearHistory = () => {
    clearDownloadHistory();
    setHistory([]);
  };

  const handleReopenUrl = (url) => {
    setActiveTab('home');
    handleFetchMetadata(url);
  };

  return (
    <div className="min-h-screen flex flex-col bg-cyber-dark text-slate-100 selection:bg-emerald-500 selection:text-slate-950">
      
      {/* Top Navigation */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onOpenHowItWorks={() => setIsHowItWorksOpen(true)}
        onOpenLegal={() => setIsLegalOpen(true)}
        historyCount={history.length}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        
        {activeTab === 'home' && (
          <div>
            {/* Hero Header */}
            <div className="text-center max-w-2xl mx-auto mb-8 sm:mb-12">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold mb-4">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                <span>Next-Gen Media Extraction Engine</span>
              </div>

              <h1 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-white mb-4">
                Universal Media Downloader <br className="hidden sm:inline" />
                <span className="bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 bg-clip-text text-transparent">
                  Powered by AI
                </span>
              </h1>

              <p className="text-sm sm:text-base text-slate-400 leading-relaxed">
                Paste any link from 1,800+ platforms or direct media streams. Download genuine source resolutions up to 4K and high-fidelity MP3 audio.
              </p>
            </div>

            {/* URL Input Form */}
            <UrlInputForm
              onSubmit={handleFetchMetadata}
              isLoading={isLoadingMetadata}
              initialUrl={currentUrl}
            />

            {/* Real-Time Multi-Tier Extraction Stages Indicator */}
            <ExtractionStagesIndicator
              currentStage={extractionStage}
              isVisible={isLoadingMetadata}
            />

            {/* Error Alert */}
            <ErrorAlert
              error={errorMessage}
              onDismiss={() => setErrorMessage(null)}
              onExplainAi={() => handleExplainError(currentUrl, errorMessage)}
              isExplaining={isExplainingError}
            />

            {/* AI Assistant Panel */}
            <AiAssistantPanel
              url={currentUrl}
              metadata={metadata}
              onApplyRecommendation={handleApplyAiRecommendation}
              rawError={errorMessage}
              errorExplanation={errorExplanation}
            />

            {/* Download Progress Bar (shown when active job exists) */}
            {activeJob && (
              <DownloadProgressBar
                job={activeJob}
                onReset={handleResetJob}
              />
            )}

            {/* Media Metadata Card */}
            {metadata && (
              <MediaMetadataCard
                metadata={metadata}
                onDownload={handleStartDownload}
                isDownloading={isDownloading}
                recommendedQuality={recommendedQuality}
                selectedQuality={selectedQuality}
                setSelectedQuality={setSelectedQuality}
              />
            )}
          </div>
        )}

        {/* Download History Tab */}
        {activeTab === 'history' && (
          <DownloadHistory
            history={history}
            onClearHistory={handleClearHistory}
            onRemoveItem={handleRemoveHistoryItem}
            onReopenUrl={handleReopenUrl}
          />
        )}

      </main>

      {/* Footer */}
      <footer className="w-full border-t border-slate-800/80 bg-cyber-dark/80 py-8 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-300">MediaGrab AI</span>
            <span>•</span>
            <span>Zero-Trust SSRF Architecture</span>
            <span>•</span>
            <span>Ephemeral TTL Storage</span>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={() => setIsHowItWorksOpen(true)}
              className="hover:text-slate-300 transition-colors"
            >
              How It Works & Security
            </button>
            <button
              onClick={() => setIsLegalOpen(true)}
              className="hover:text-slate-300 transition-colors"
            >
              Legal & Copyright Notice
            </button>
          </div>
        </div>
      </footer>

      {/* Modals */}
      <HowItWorksModal
        isOpen={isHowItWorksOpen}
        onClose={() => setIsHowItWorksOpen(false)}
      />

      <LegalTermsModal
        isOpen={isLegalOpen}
        onClose={() => setIsLegalOpen(false)}
      />

    </div>
  );
}
