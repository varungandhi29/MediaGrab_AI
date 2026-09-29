import { useState } from "react";

export default function JobError({ job, onRetry }) {
  const [copied, setCopied] = useState(false);

  const copyDebug = async () => {
    const text = `Job: ${job.id || job.job_id}\nError: ${job.error_class || "UNKNOWN"}\n\n${job.debug || ""}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked: ignore */
    }
  };

  return (
    <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900">
      <p className="font-medium">{job.user_message || job.error_message}</p>
      <div className="mt-3 flex gap-2">
        {onRetry && (
          <button type="button" onClick={onRetry} className="px-3 py-1.5 rounded border border-red-400 hover:bg-red-100 transition">
            Retry
          </button>
        )}
        <button type="button" onClick={copyDebug} className="px-3 py-1.5 rounded border border-red-400 hover:bg-red-100 transition">
          {copied ? "Copied" : "Copy debug info"}
        </button>
      </div>
    </div>
  );
}
