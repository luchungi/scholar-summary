import React, { useState, useEffect } from 'react';
import { RefreshCw, Link as LinkIcon, AlertCircle, Calendar, Trash, Loader } from 'lucide-react';

interface FailedPaper {
  id: number;
  title: string;
  url: string;
  date_processed: string;
  status: string; // "failed" | "skipped"
  skip_reason?: string | null;
  relevance_rating?: number | null;
}

interface FailedPapersProps {
  onStartSync: (papers: { title: string; url: string; force?: string }[], emailsFetched: number) => void;
}

export default function FailedPapers({ onStartSync }: FailedPapersProps) {
  const [failedPapers, setFailedPapers] = useState<FailedPaper[]>([]);
  const [loading, setLoading] = useState(true);
  const [retryingId, setRetryingId] = useState<number | null>(null);

  const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

  const fetchFailed = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_URL}/api/papers/failed`);
      const data = await res.json();
      setFailedPapers(data);
    } catch (e) {
      console.error('Error fetching failed papers:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFailed();
  }, []);

  const handleRetry = async (paper: FailedPaper) => {
    setRetryingId(paper.id);
    try {
      // App.tsx's handleStartSync creates the run via POST /api/runs and opens the logs panel.
      // Do NOT also POST here, or the paper gets processed twice concurrently.
      // force bypasses the relevance pre-filter so a manual retry always gets a full analysis.
      onStartSync([{ title: paper.title, url: paper.url, force: 'true' }], 0);
    } catch (e: any) {
      alert(`Retry failed to start: ${e.message || e}`);
    } finally {
      setRetryingId(null);
    }
  };

  const handleDeleteFailed = async (paperId: number) => {
    if (confirm("Are you sure you want to delete this failed paper record?")) {
      try {
        const res = await fetch(`${API_URL}/api/papers/failed/${paperId}`, {
          method: 'DELETE'
        });
        if (res.ok) {
          setFailedPapers((prev) => prev.filter((p) => p.id !== paperId));
        } else {
          throw new Error(await res.text());
        }
      } catch (err: any) {
        alert(`Failed to delete record: ${err.message || err}`);
      }
    }
  };

  return (
    <div className="failed-papers-tab fade-in">
      <div className="tab-header">
        <div className="title-desc">
          <h2>Failed & Skipped Papers</h2>
          <p>Papers that could not be scraped or summarized (connection dropouts, paywalls, PDF errors), plus papers the relevance pre-filter skipped. Retry an extraction or force a full analysis below.</p>
        </div>
      </div>

      <div className="failed-list-container scroller">
        {loading ? (
          <div className="failed-loading">
            <Loader className="animate-spin text-purple-400" size={32} />
            <p>Loading failed extractions...</p>
          </div>
        ) : failedPapers.length === 0 ? (
          <div className="failed-empty glass-panel">
            <AlertCircle size={48} className="empty-icon text-green-500" />
            <h3>No failed papers</h3>
            <p>All paper extractions have successfully compiled into reports!</p>
          </div>
        ) : (
          <div className="failed-grid">
            {failedPapers.map((paper) => (
              <div key={paper.id} className="failed-card glass-panel">
                <div className="card-header flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <AlertCircle size={16} className={paper.status === 'skipped' ? 'text-amber-500' : 'text-red-500'} />
                    <span className="card-badge">
                      {paper.status === 'skipped'
                        ? `Skipped (relevance ${paper.relevance_rating ?? '?'}/5) #${paper.id}`
                        : `Failed Paper #${paper.id}`}
                    </span>
                  </div>
                  <button 
                    onClick={() => handleDeleteFailed(paper.id)}
                    className="delete-failed-btn"
                    title="Delete Record"
                  >
                    <Trash size={12} />
                  </button>
                </div>
                <div className="card-body">
                  <h3 className="paper-title">{paper.title}</h3>
                  {paper.status === 'skipped' && paper.skip_reason && (
                    <p className="skip-reason">{paper.skip_reason}</p>
                  )}
                  <a href={paper.url} target="_blank" rel="noopener noreferrer" className="paper-url">
                    <LinkIcon size={12} />
                    {paper.url}
                  </a>
                </div>
                <div className="card-footer">
                  <div className="date-info">
                    <Calendar size={14} />
                    <span>{new Date(paper.date_processed).toLocaleDateString()}</span>
                  </div>
                  <button
                    onClick={() => handleRetry(paper)}
                    className="btn btn-secondary btn-xs retry-btn"
                    disabled={retryingId === paper.id}
                  >
                    {retryingId === paper.id ? (
                      <Loader className="animate-spin" size={12} />
                    ) : (
                      <RefreshCw size={12} />
                    )}
                    {paper.status === 'skipped' ? 'Analyze Anyway' : 'Retry Extraction'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <style>{`
        .failed-papers-tab {
          display: flex;
          flex-direction: column;
          gap: 20px;
          height: 100%;
          overflow: hidden;
        }
        .tab-header h2 {
          font-size: 22px;
          color: #fff;
          margin-bottom: 4px;
        }
        .tab-header p {
          font-size: 13px;
          color: var(--text-muted);
          max-width: 800px;
          line-height: 1.5;
        }
        .failed-list-container {
          flex: 1;
          overflow-y: auto;
          padding-right: 8px;
        }
        .failed-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          height: 300px;
          color: var(--text-muted);
        }
        .failed-empty {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          padding: 48px;
          background: var(--bg-card);
          text-align: center;
        }
        .failed-empty h3 {
          color: #fff;
          font-size: 16px;
        }
        .failed-empty p {
          font-size: 13px;
          color: var(--text-muted);
        }
        .empty-icon.text-green-500 {
          color: var(--accent-green);
        }
        .failed-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 20px;
        }
        .failed-card {
          display: flex;
          flex-direction: column;
          background: var(--bg-card) !important;
          border: 1px solid rgba(244, 63, 94, 0.15) !important;
          height: 200px;
        }
        .failed-card:hover {
          border-color: rgba(244, 63, 94, 0.3) !important;
          box-shadow: 0 4px 20px rgba(244, 63, 94, 0.05);
        }
        .card-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px 16px;
          background: rgba(244, 63, 94, 0.03);
          border-bottom: 1px solid var(--border-color);
        }
        .card-badge {
          font-family: var(--font-display);
          font-size: 11px;
          font-weight: 500;
          color: var(--accent-red);
        }
        .card-body {
          flex: 1;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .failed-card .paper-title {
          font-size: 14px;
          font-weight: 600;
          color: #fff;
          line-height: 1.4;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        .failed-card .paper-url {
          font-size: 11px;
          color: var(--text-dark);
          text-decoration: none;
          display: flex;
          align-items: center;
          gap: 4px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          margin-top: auto;
        }
        .failed-card .paper-url:hover {
          color: var(--accent-blue);
        }
        .card-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-top: 1px solid var(--border-color);
          background: rgba(255, 255, 255, 0.01);
        }
        .text-red-500 {
          color: var(--accent-red);
        }
        .text-amber-500 {
          color: #f59e0b;
        }
        .skip-reason {
          font-size: 12px;
          color: var(--text-muted);
          font-style: italic;
          line-height: 1.4;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        .date-info {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          color: var(--text-dark);
        }
        .retry-btn {
          color: var(--text-main);
          font-family: var(--font-display);
          font-weight: 500;
        }
        .retry-btn:hover {
          background: rgba(124, 58, 237, 0.15) !important;
          border-color: var(--accent-purple) !important;
          color: #fff;
        }
        .delete-failed-btn {
          background: none;
          border: none;
          color: var(--text-dark);
          cursor: pointer;
          transition: all 0.2s ease;
          padding: 4px;
          border-radius: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .delete-failed-btn:hover {
          color: var(--accent-red);
          background: rgba(244, 63, 94, 0.1);
        }
        .flex {
          display: flex;
        }
        .justify-between {
          justify-content: space-between;
        }
        .items-center {
          align-items: center;
        }
        .gap-2 {
          gap: 8px;
        }
      `}</style>
    </div>
  );
}
