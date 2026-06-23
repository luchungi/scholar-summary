import React, { useState, useEffect } from 'react';
import { Mail, Link, AlertTriangle, CheckCircle, Activity, Loader, Database, Search, Upload } from 'lucide-react';

interface PaperItem {
  title: string;
  url: string;
}

interface DashboardProps {
  onStartSync: (papers: PaperItem[], emailsFetched: number) => void;
  onOpenPreview: (alerts: any[]) => void;
  onSelectTab: (tab: string) => void;
  onUploadStarted?: (runId: number) => void;
}

export default function Dashboard({ onStartSync, onOpenPreview, onSelectTab, onUploadStarted }: DashboardProps) {
  const [stats, setStats] = useState({
    totalPapers: 0,
    totalRuns: 0,
    succeeded: 0,
    failed: 0
  });
  
  const [recentRuns, setRecentRuns] = useState<any[]>([]);
  const [loadingStats, setLoadingStats] = useState(true);
  const [fetchingGmail, setFetchingGmail] = useState(false);
  
  // Manual URL/File state
  const [analysisMode, setAnalysisMode] = useState<'url' | 'file'>('url');
  const [uploading, setUploading] = useState(false);
  const [manualUrl, setManualUrl] = useState('');
  const [manualTitle, setManualTitle] = useState('');
  const [manualRunning, setManualRunning] = useState(false);

  const handleFileUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      alert('Only PDF files are supported.');
      return;
    }
    
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const res = await fetch(`${API_URL}/api/reports/upload`, {
        method: 'POST',
        body: formData
      });
      
      if (!res.ok) {
        throw new Error(await res.text());
      }
      
      const data = await res.json();
      if (data.status === 'success') {
        if (onUploadStarted) {
          onUploadStarted(data.run_id);
        }
      }
    } catch (e: any) {
      alert(`Error uploading file: ${e.message || e}`);
    } finally {
      setUploading(false);
    }
  };

  const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

  const fetchStatsAndRecent = async () => {
    try {
      setLoadingStats(true);
      // Fetch runs
      const resRuns = await fetch(`${API_URL}/api/runs`);
      const dataRuns = await resRuns.json();
      setRecentRuns(dataRuns.slice(0, 5));

      // Fetch reports
      const resReports = await fetch(`${API_URL}/api/reports`);
      const dataReports = await resReports.json();

      // Fetch failed papers
      const resFailed = await fetch(`${API_URL}/api/papers/failed`);
      const dataFailed = await resFailed.json();

      setStats({
        totalPapers: dataReports.length + dataFailed.length,
        totalRuns: dataRuns.length,
        succeeded: dataReports.length,
        failed: dataFailed.length
      });
    } catch (e) {
      console.error('Error fetching dashboard statistics:', e);
    } finally {
      setLoadingStats(false);
    }
  };

  useEffect(() => {
    fetchStatsAndRecent();
  }, []);

  const handleFetchGmail = async () => {
    setFetchingGmail(true);
    try {
      const res = await fetch(`${API_URL}/api/alerts`);
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const alerts = await res.json();
      if (alerts.length === 0) {
        alert('No new Google Scholar Alert emails found in inbox.');
      } else {
        onOpenPreview(alerts);
      }
    } catch (e: any) {
      alert(`Gmail API Error: ${e.message || e}`);
    } finally {
      setFetchingGmail(false);
    }
  };

  const handleManualAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualUrl) {
      alert('Please enter a valid paper URL.');
      return;
    }
    
    // Call parent handler to execute single POST request and show terminal logs
    onStartSync([{ title: manualTitle.trim(), url: manualUrl.trim() }], 0);
    setManualUrl('');
    setManualTitle('');
  };

  return (
    <div className="dashboard-content fade-in">
      <div className="welcome-banner">
        <h2>Scholar Summary Assistant</h2>
        <p>Retrieve Google Scholar Alerts from your Gmail account, summarize papers using your local LLM, and build your interest profile.</p>
      </div>

      {/* Statistics Cards */}
      <div className="stats-grid">
        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper purple">
            <Activity size={24} />
          </div>
          <div className="stat-details">
            <span className="stat-value">{loadingStats ? '...' : stats.totalRuns}</span>
            <span className="stat-label">Total Sync Runs</span>
          </div>
        </div>

        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper blue">
            <Database size={24} />
          </div>
          <div className="stat-details">
            <span className="stat-value">{loadingStats ? '...' : stats.totalPapers}</span>
            <span className="stat-label">Papers Discovered</span>
          </div>
        </div>

        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper green">
            <CheckCircle size={24} />
          </div>
          <div className="stat-details">
            <span className="stat-value">{loadingStats ? '...' : stats.succeeded}</span>
            <span className="stat-label">Summarized Reports</span>
          </div>
        </div>

        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper red">
            <AlertTriangle size={24} />
          </div>
          <div className="stat-details" onClick={() => onSelectTab('failed')} style={{ cursor: 'pointer' }}>
            <span className="stat-value">{loadingStats ? '...' : stats.failed}</span>
            <span className="stat-label">Failed Extractions</span>
          </div>
        </div>
      </div>

      <div className="actions-section">
        {/* Gmail Sync Area */}
        <div className="sync-card glass-panel">
          <h3>Fetch Google Alerts</h3>
          <p>Scan your Gmail inbox for recent emails sent by `scholaralerts-noreply@google.com`. Select which papers to process in the preview checklist.</p>
          <button
            onClick={handleFetchGmail}
            className="btn btn-primary"
            disabled={fetchingGmail}
          >
            {fetchingGmail ? (
              <>
                <Loader className="animate-spin" size={16} />
                Scanning Gmail Inbox...
              </>
            ) : (
              <>
                <Mail size={16} />
                Sync Gmail Alerts
              </>
            )}
          </button>
        </div>

        {/* Manual Input (URL or Upload) */}
        <div className="manual-card glass-panel">
          <h3>Direct Paper Analysis</h3>
          <p>Analyze any single academic paper directly by URL or upload a PDF to evaluate it against your profile.</p>
          
          <div className="tab-toggle">
            <button
              type="button"
              className={`tab-toggle-btn ${analysisMode === 'url' ? 'active' : ''}`}
              onClick={() => setAnalysisMode('url')}
            >
              <Link size={14} /> URL Link
            </button>
            <button
              type="button"
              className={`tab-toggle-btn ${analysisMode === 'file' ? 'active' : ''}`}
              onClick={() => setAnalysisMode('file')}
            >
              <Upload size={14} /> PDF File
            </button>
          </div>

          {analysisMode === 'url' ? (
            <form onSubmit={handleManualAnalyze} className="manual-form">
              <input
                type="text"
                placeholder="Paper Title (optional, e.g. Attention is All You Need)"
                value={manualTitle}
                onChange={(e) => setManualTitle(e.target.value)}
                className="glass-input"
              />
              <div className="url-input-row">
                <input
                  type="url"
                  placeholder="https://arxiv.org/abs/2304.00001"
                  value={manualUrl}
                  onChange={(e) => setManualUrl(e.target.value)}
                  className="glass-input flex-1"
                  required
                />
                <button type="submit" className="btn btn-secondary" disabled={manualRunning}>
                  {manualRunning ? <Loader className="animate-spin" size={16} /> : <Search size={16} />}
                  Analyze
                </button>
              </div>
            </form>
          ) : (
            <div 
              className={`dropzone glass-panel ${uploading ? 'loading' : ''}`}
              onClick={() => !uploading && document.getElementById('file-input')?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                e.currentTarget.classList.add('dragover');
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                e.currentTarget.classList.remove('dragover');
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.currentTarget.classList.remove('dragover');
                if (uploading) return;
                const file = e.dataTransfer.files[0];
                if (file) handleFileUpload(file);
              }}
            >
              <input
                id="file-input"
                type="file"
                accept=".pdf"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file);
                }}
                style={{ display: 'none' }}
                disabled={uploading}
              />
              {uploading ? (
                <div className="upload-loading">
                  <Loader className="animate-spin text-purple-400" size={32} />
                  <p>Uploading and analyzing paper...</p>
                  <span>This might take 10-15 seconds for LLM analysis.</span>
                </div>
              ) : (
                <div className="upload-prompt">
                  <Upload size={32} className="text-purple-400" />
                  <p>Drag & drop PDF here, or <strong>browse files</strong></p>
                  <span>Only .pdf files are supported</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Recent Runs List */}
      <div className="recent-activity-section glass-panel">
        <h3>Recent Run History</h3>
        <div className="runs-list scroller">
          {loadingStats ? (
            <div className="loading-state">Loading runs...</div>
          ) : recentRuns.length === 0 ? (
            <div className="empty-state">No execution runs recorded. Run your first sync above!</div>
          ) : (
            recentRuns.map((run) => (
              <div key={run.id} className="run-row">
                <div className="run-meta">
                  <span className="run-id">Run #{run.id}</span>
                  <span className="run-time">
                    {new Date(run.timestamp).toLocaleString()}
                  </span>
                </div>
                <div className="run-stats">
                  <span>Emails fetched: <strong>{run.emails_fetched}</strong></span>
                  <span className="text-green">Processed: <strong>{run.papers_processed}</strong></span>
                  <span className="text-red">Failed: <strong>{run.papers_failed}</strong></span>
                </div>
                <div className="run-status-badge">
                  <span className={`status-badge-inline ${run.status}`}>
                    {run.status}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <style>{`
        .dashboard-content {
          display: flex;
          flex-direction: column;
          gap: 24px;
          height: 100%;
          overflow-y: auto;
          padding-right: 8px;
        }
        .welcome-banner {
          padding: 8px 0;
        }
        .welcome-banner h2 {
          font-size: 26px;
          color: #fff;
          margin-bottom: 6px;
          background: linear-gradient(135deg, #fff 0%, #a78bfa 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
        .welcome-banner p {
          font-size: 14px;
          color: var(--text-muted);
          max-width: 700px;
        }
        .stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 20px;
        }
        .stat-card {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 20px;
          background: var(--bg-card) !important;
        }
        .stat-icon-wrapper {
          width: 48px;
          height: 48px;
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .stat-icon-wrapper.purple {
          background: rgba(124, 58, 237, 0.15);
          color: #a78bfa;
          border: 1px solid rgba(124, 58, 237, 0.2);
        }
        .stat-icon-wrapper.blue {
          background: rgba(59, 130, 246, 0.15);
          color: #60a5fa;
          border: 1px solid rgba(59, 130, 246, 0.2);
        }
        .stat-icon-wrapper.green {
          background: rgba(16, 185, 129, 0.15);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.2);
        }
        .stat-icon-wrapper.red {
          background: rgba(244, 63, 94, 0.15);
          color: #fb7185;
          border: 1px solid rgba(244, 63, 94, 0.2);
        }
        .stat-details {
          display: flex;
          flex-direction: column;
        }
        .stat-value {
          font-family: var(--font-display);
          font-size: 24px;
          font-weight: 700;
          color: #fff;
          line-height: 1;
          margin-bottom: 4px;
        }
        .stat-label {
          font-size: 12px;
          color: var(--text-muted);
        }
        .actions-section {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 20px;
        }
        @media (max-width: 768px) {
          .actions-section {
            grid-template-columns: 1fr;
          }
        }
        .sync-card, .manual-card {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .sync-card h3, .manual-card h3 {
          color: #fff;
          font-size: 16px;
        }
        .sync-card p, .manual-card p {
          font-size: 13px;
          color: var(--text-muted);
          line-height: 1.5;
          flex: 1;
        }
        .tab-toggle {
          display: flex;
          gap: 8px;
          margin-bottom: 4px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.05);
          padding-bottom: 8px;
        }
        .tab-toggle-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 13px;
          font-family: var(--font-display);
          font-weight: 500;
          color: var(--text-muted);
          background: none;
          border: none;
          padding: 6px 12px;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .tab-toggle-btn:hover {
          color: #fff;
          background: rgba(255, 255, 255, 0.03);
        }
        .tab-toggle-btn.active {
          color: #fff;
          background: rgba(124, 58, 237, 0.1);
          border: 1px solid rgba(124, 58, 237, 0.2);
        }
        .dropzone {
          border: 2px dashed rgba(124, 58, 237, 0.3);
          border-radius: 12px;
          padding: 30px 20px;
          text-align: center;
          cursor: pointer;
          transition: all 0.2s ease;
          background: rgba(124, 58, 237, 0.02) !important;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-height: 140px;
          margin-top: 6px;
        }
        .dropzone:hover, .dropzone.dragover {
          border-color: var(--accent-purple);
          background: rgba(124, 58, 237, 0.05) !important;
          box-shadow: 0 4px 20px rgba(124, 58, 237, 0.1);
        }
        .upload-prompt, .upload-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
        }
        .upload-prompt p, .upload-loading p {
          font-size: 14px;
          color: #fff;
          margin: 0;
        }
        .upload-prompt span, .upload-loading span {
          font-size: 11px;
          color: var(--text-muted);
        }
        .manual-form {
          display: flex;
          flex-direction: column;
          gap: 10px;
          margin-top: 12px;
        }
        .url-input-row {
          display: flex;
          gap: 8px;
        }
        .flex-1 {
          flex: 1;
        }
        .recent-activity-section {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .recent-activity-section h3 {
          font-size: 16px;
          color: #fff;
        }
        .runs-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
          max-height: 280px;
          overflow-y: auto;
        }
        .run-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border: 1px solid var(--border-color);
          border-radius: 8px;
          background: rgba(255,255,255,0.01);
        }
        .run-meta {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .run-id {
          font-family: var(--font-display);
          font-weight: 500;
          font-size: 14px;
          color: #fff;
        }
        .run-time {
          font-size: 11px;
          color: var(--text-dark);
        }
        .run-stats {
          display: flex;
          gap: 16px;
          font-size: 13px;
          color: var(--text-muted);
        }
        .run-stats strong {
          color: #fff;
        }
        .text-green strong {
          color: var(--accent-green);
        }
        .text-red strong {
          color: var(--accent-red);
        }
        .status-badge-inline {
          font-size: 11px;
          padding: 2px 6px;
          border-radius: 4px;
          text-transform: capitalize;
        }
        .status-badge-inline.running {
          background: rgba(59, 130, 246, 0.1);
          color: #60a5fa;
        }
        .status-badge-inline.completed {
          background: rgba(16, 185, 129, 0.1);
          color: #34d399;
        }
        .status-badge-inline.failed {
          background: rgba(244, 63, 94, 0.1);
          color: #fb7185;
        }
        .loading-state, .empty-state {
          padding: 20px;
          text-align: center;
          color: var(--text-muted);
          font-size: 13px;
        }
        .animate-spin {
          animation: spin 1s linear infinite;
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
