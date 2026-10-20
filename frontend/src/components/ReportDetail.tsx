import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { ArrowLeft, Send, Sparkles, AlertCircle, Bookmark, ExternalLink, Loader, Trash, Download, FileDown, BookMarked, BookOpen, FolderOpen, CheckCircle2, X } from 'lucide-react';
import DiffViewer from './DiffViewer';

interface PaperItem {
  id: number;
  title: string;
  url: string;
  date_processed: string;
  report_path: string;
}

interface ReportDetailProps {
  reportId: number;
  onBack: () => void;
}

export default function ReportDetail({ reportId, onBack }: ReportDetailProps) {
  const [paper, setPaper] = useState<PaperItem | null>(null);
  const [markdown, setMarkdown] = useState('');
  const [loading, setLoading] = useState(true);

  // Feedback states
  const [feedback, setFeedback] = useState('');
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  
  // Diff viewer modal states
  const [showDiff, setShowDiff] = useState(false);
  const [diffData, setDiffData] = useState({ current: '', proposed: '', diff: '' });
  const [savingProfile, setSavingProfile] = useState(false);

  // Export & Download states
  const [exportStatus, setExportStatus] = useState<{
    has_pdf: boolean;
    filename_base: string;
    pdf_url?: string;
  } | null>(null);
  const [downloadingCitation, setDownloadingCitation] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [exportingEndNote, setExportingEndNote] = useState(false);
  const [exportToast, setExportToast] = useState<{ message: string; batchDir: string } | null>(null);

  const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

  const handleDeleteReport = async () => {
    if (confirm("Are you sure you want to permanently delete this report? This will remove it from the database and delete the markdown file from disk.")) {
      try {
        const res = await fetch(`${API_URL}/api/reports/${reportId}`, {
          method: 'DELETE'
        });
        if (res.ok) {
          onBack();
        } else {
          throw new Error(await res.text());
        }
      } catch (err: any) {
        alert(`Failed to delete report: ${err.message || err}`);
      }
    }
  };

  const fetchReportDetails = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_URL}/api/reports/${reportId}`);
      if (!res.ok) {
        throw new Error('Report details not found');
      }
      const data = await res.json();
      setPaper(data.paper);
      setMarkdown(data.markdown);

      // Concurrently fetch export/PDF status
      fetch(`${API_URL}/api/reports/${reportId}/export-status`)
        .then((r) => (r.ok ? r.json() : null))
        .then((sData) => {
          if (sData) setExportStatus(sData);
        })
        .catch((err) => console.warn("Failed to fetch export status:", err));
    } catch (e) {
      console.error('Error fetching report details:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReportDetails();
  }, [reportId]);

  const handleDownloadCitation = () => {
    setDownloadingCitation(true);
    const link = document.createElement('a');
    link.href = `${API_URL}/api/reports/${reportId}/citation`;
    link.setAttribute('download', '');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => setDownloadingCitation(false), 1000);
  };

  const handleDownloadPdf = () => {
    if (exportStatus && !exportStatus.has_pdf) return;
    setDownloadingPdf(true);
    const link = document.createElement('a');
    link.href = `${API_URL}/api/reports/${reportId}/pdf`;
    link.setAttribute('download', '');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => setDownloadingPdf(false), 2000);
  };

  const handleEndNoteExport = async () => {
    if (!paper) return;

    if (exportStatus && !exportStatus.has_pdf) {
      const proceed = confirm(
        "Direct PDF is unavailable for this paper (paywalled or HTML-only article).\n\nDo you want to import the citation metadata into EndNote without an attached PDF?"
      );
      if (!proceed) return;
    }

    setExportingEndNote(true);
    try {
      const res = await fetch(`${API_URL}/api/reports/endnote-export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paper_ids: [paper.id],
          skip_paywalled: false
        })
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const data = await res.json();
      setExportToast({
        message: data.with_pdf_count > 0
          ? 'Imported paper into EndNote 21 with PDF attached!'
          : 'Imported paper citation into EndNote 21 (citation-only)',
        batchDir: data.batch_dir
      });
    } catch (err: any) {
      alert(`EndNote export failed: ${err.message || err}`);
    } finally {
      setExportingEndNote(false);
    }
  };

  const handleRevealInFinder = async (path: string) => {
    try {
      const res = await fetch(`${API_URL}/api/reports/reveal-in-finder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
    } catch (err: any) {
      alert(`Could not open Finder: ${err.message || err}`);
    }
  };

  const handleFeedbackSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!feedback.trim()) return;

    setFeedbackLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/reports/${reportId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback })
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }

      const data = await res.json();
      setDiffData({
        current: data.current,
        proposed: data.proposed,
        diff: data.diff
      });
      setShowDiff(true);
    } catch (err: any) {
      alert(`Error updating profile: ${err.message || err}`);
    } finally {
      setFeedbackLoading(false);
    }
  };

  const handleSaveProfile = async () => {
    setSavingProfile(true);
    try {
      const res = await fetch(`${API_URL}/api/profile/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: diffData.proposed })
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }
      
      alert('Interest profile updated successfully! Backup created.');
      setShowDiff(false);
      setFeedback('');
    } catch (err: any) {
      alert(`Failed to save profile: ${err.message}`);
    } finally {
      setSavingProfile(false);
    }
  };

  if (loading) {
    return (
      <div className="detail-loading">
        <Loader className="animate-spin text-purple-400" size={36} />
        <p>Loading paper report details...</p>
      </div>
    );
  }

  if (!paper) {
    return (
      <div className="detail-error glass-panel fade-in">
        <AlertCircle size={40} className="text-red" />
        <h3>Failed to load report</h3>
        <p>The report record was not found or is missing content files.</p>
        <button onClick={onBack} className="btn btn-secondary">
          Go Back
        </button>
      </div>
    );
  }

  return (
    <div className="report-detail-layout fade-in">
      {/* Top Navbar */}
      <div className="detail-navbar">
        <button onClick={onBack} className="back-btn-wrapper">
          <ArrowLeft size={16} />
          Back to Reports
        </button>
        <div className="flex items-center gap-2">
          {/* EndNote / Citation Button */}
          <button
            onClick={handleDownloadCitation}
            disabled={downloadingCitation}
            className="btn btn-secondary btn-sm"
            title="Download citation file (.enw) formatted for EndNote"
          >
            <BookMarked size={13} />
            {downloadingCitation ? 'Downloading .enw...' : 'Download .enw'}
          </button>

          {/* PDF Download Button */}
          <button
            onClick={handleDownloadPdf}
            disabled={downloadingPdf || (exportStatus !== null && !exportStatus.has_pdf)}
            className={`btn btn-secondary btn-sm ${exportStatus && !exportStatus.has_pdf ? 'opacity-50 cursor-not-allowed' : ''}`}
            title={exportStatus && !exportStatus.has_pdf ? "Direct PDF not available (paywalled or HTML article)" : "Download paper PDF on-demand"}
          >
            <FileDown size={13} />
            {downloadingPdf ? 'Downloading PDF...' : exportStatus && !exportStatus.has_pdf ? 'PDF Unavailable' : 'Download PDF'}
          </button>

          {/* 1-Click Export to EndNote Button */}
          <button
            onClick={handleEndNoteExport}
            disabled={exportingEndNote}
            className="btn btn-primary btn-sm flex items-center gap-1.5"
            title="Import paper directly into EndNote with attached PDF (1-click)"
          >
            {exportingEndNote ? (
              <>
                <Loader className="animate-spin" size={13} />
                Exporting...
              </>
            ) : (
              <>
                <BookOpen size={13} />
                Export to EndNote
              </>
            )}
          </button>

          <div style={{ width: '1px', height: '18px', background: 'rgba(255, 255, 255, 0.15)', margin: '0 4px' }} />

          <a href={paper.url} target="_blank" rel="noopener noreferrer" className="btn btn-secondary btn-sm">
            Original Source
            <ExternalLink size={12} />
          </a>

          <button onClick={handleDeleteReport} className="btn btn-secondary btn-sm btn-danger-hover" title="Delete Report">
            <Trash size={12} />
          </button>
        </div>
      </div>

      <div className="detail-content-columns">
        {/* Left Column: Report Reader */}
        <div className="report-markdown-panel glass-panel scroller">
          <div className="report-meta-header">
            <div className="meta-badge-row">
              <span className="meta-badge purple">Report #{paper.id}</span>
              <span className="meta-badge date">
                {new Date(paper.date_processed).toLocaleDateString(undefined, { dateStyle: 'long' })}
              </span>
            </div>
            <h1>{paper.title}</h1>
            <a href={paper.url} target="_blank" rel="noopener noreferrer" className="url-banner">
              <Bookmark size={14} className="bookmark-icon" />
              <span className="url-text">{paper.url}</span>
            </a>
          </div>
          
          <hr className="divider" />
          
          <div className="markdown-render-body">
            <ReactMarkdown
              remarkPlugins={[remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                )
              }}
            >
              {markdown}
            </ReactMarkdown>
          </div>
        </div>

        {/* Right Column: Feedback Input */}
        <div className="feedback-control-panel glass-panel">
          <div className="panel-header">
            <Sparkles className="text-purple-400" size={20} />
            <h3>Interest Profile Refinement</h3>
          </div>
          <p className="panel-desc">
            Provide feedback on this paper analysis to update your primary research interests and keywords (e.g. <i>"I am very interested in this paper's RAG approach, please add vector search to my interests"</i>).
          </p>

          <form onSubmit={handleFeedbackSubmit} className="feedback-form">
            <textarea
              placeholder="Type your feedback about this paper here..."
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="glass-input feedback-textarea scroller"
              required
              disabled={feedbackLoading}
            />
            <button type="submit" className="btn btn-primary" disabled={feedbackLoading || !feedback.trim()}>
              {feedbackLoading ? (
                <>
                  <Loader className="animate-spin" size={16} />
                  Evaluating Feedback...
                </>
              ) : (
                <>
                  <Send size={14} />
                  Refine Interests
                </>
              )}
            </button>
          </form>
        </div>
      </div>

      {showDiff && (
        <DiffViewer
          diffText={diffData.diff}
          onSave={handleSaveProfile}
          onCancel={() => setShowDiff(false)}
          saving={savingProfile}
        />
      )}

      {/* Export Toast Notification */}
      {exportToast && (
        <div className="export-toast glass-panel fade-in">
          <div className="toast-content">
            <CheckCircle2 className="text-emerald-400 shrink-0" size={18} />
            <div className="toast-text">
              <div className="toast-msg">{exportToast.message}</div>
              <div className="toast-sub">EndNote 21 has opened to import this reference.</div>
            </div>
          </div>
          <div className="toast-actions">
            <button
              className="btn btn-secondary btn-xs flex items-center gap-1"
              onClick={() => handleRevealInFinder(exportToast.batchDir)}
              title="Open folder in macOS Finder"
            >
              <FolderOpen size={12} />
              Reveal in Finder
            </button>
            <button
              className="toast-close-btn"
              onClick={() => setExportToast(null)}
              title="Dismiss"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      <style>{`
        .report-detail-layout {
          display: flex;
          flex-direction: column;
          gap: 16px;
          height: 100%;
          overflow: hidden;
        }
        .detail-navbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .back-btn-wrapper {
          background: none;
          border: none;
          color: var(--text-muted);
          font-family: var(--font-display);
          font-size: 14px;
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
          transition: color 0.2s;
        }
        .back-btn-wrapper:hover {
          color: #fff;
        }
        .btn-sm {
          font-size: 12px;
          padding: 8px 14px;
        }
        .btn-danger-hover:hover {
          background: var(--accent-red) !important;
          border-color: var(--accent-red) !important;
          color: white !important;
        }
        .flex {
          display: flex;
        }
        .items-center {
          align-items: center;
        }
        .gap-2 {
          gap: 8px;
        }
        .detail-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          height: 80%;
          color: var(--text-muted);
        }
        .detail-error {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          padding: 40px;
          text-align: center;
          background: var(--bg-card);
          margin-top: 40px;
        }
        .detail-error h3 {
          color: #fff;
        }
        .detail-error p {
          color: var(--text-muted);
          margin-bottom: 8px;
        }
        .detail-content-columns {
          display: grid;
          grid-template-columns: 1fr 340px;
          gap: 20px;
          flex: 1;
          overflow: hidden;
        }
        @media (max-width: 900px) {
          .detail-content-columns {
            grid-template-columns: 1fr;
          }
          .feedback-control-panel {
            display: none !important; /* Hide feedback panel on small screens */
          }
        }
        .report-markdown-panel {
          padding: 32px;
          overflow-y: auto;
          background: var(--bg-card) !important;
          border-radius: 16px;
        }
        .report-meta-header {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .meta-badge-row {
          display: flex;
          gap: 8px;
        }
        .meta-badge {
          font-family: var(--font-display);
          font-size: 11px;
          font-weight: 500;
          padding: 2px 8px;
          border-radius: 4px;
        }
        .meta-badge.purple {
          background: rgba(124, 58, 237, 0.1);
          color: #a78bfa;
        }
        .meta-badge.date {
          background: rgba(255,255,255,0.03);
          color: var(--text-muted);
        }
        .report-meta-header h1 {
          font-size: 24px;
          color: #fff;
          line-height: 1.3;
        }
        .url-banner {
          display: flex;
          align-items: center;
          gap: 6px;
          background: rgba(255,255,255,0.02);
          padding: 6px 12px;
          border-radius: 6px;
          border: 1px solid var(--border-color);
          width: fit-content;
          max-width: 100%;
          text-decoration: none;
          transition: all 0.2s ease;
        }
        .url-banner:hover {
          background: rgba(255,255,255,0.05);
          border-color: rgba(124, 58, 237, 0.4);
        }
        .bookmark-icon {
          color: var(--accent-purple);
          flex-shrink: 0;
        }
        .url-text {
          font-size: 11px;
          color: var(--text-muted);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .divider {
          border: none;
          height: 1px;
          background: var(--border-color);
          margin: 24px 0;
        }
        
        /* Markdown rendering styles */
        .markdown-render-body {
          font-family: var(--font-sans);
          font-size: 15px;
          line-height: 1.7;
          color: #e2e8f0;
        }
        .markdown-render-body a {
          color: #a78bfa;
          text-decoration: none;
          font-weight: 500;
          transition: color 0.2s ease;
        }
        .markdown-render-body a:hover {
          color: #c084fc;
          text-decoration: underline;
        }
        .markdown-render-body h1, 
        .markdown-render-body h2, 
        .markdown-render-body h3 {
          color: #fff;
          margin-top: 24px;
          margin-bottom: 12px;
        }
        .markdown-render-body h1 { font-size: 20px; }
        .markdown-render-body h2 { font-size: 18px; }
        .markdown-render-body h3 { font-size: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 4px; }
        .markdown-render-body p {
          margin-bottom: 16px;
        }
        .markdown-render-body ul, 
        .markdown-render-body ol {
          margin-bottom: 16px;
          padding-left: 20px;
        }
        .markdown-render-body li {
          margin-bottom: 6px;
        }
        .markdown-render-body strong {
          color: #fff;
        }
        .markdown-render-body blockquote {
          border-left: 4px solid var(--accent-purple);
          padding-left: 16px;
          margin-bottom: 16px;
          color: var(--text-muted);
          font-style: italic;
        }
        .markdown-render-body pre {
          background: #06070d;
          padding: 16px;
          border-radius: 8px;
          border: 1px solid var(--border-color);
          overflow-x: auto;
          margin-bottom: 16px;
        }
        .markdown-render-body code {
          font-family: var(--font-mono);
          font-size: 13px;
          color: #a78bfa;
          background: rgba(167, 139, 250, 0.08);
          padding: 2px 4px;
          border-radius: 4px;
        }
        
        /* Feedback Panel */
        .feedback-control-panel {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 16px;
          background: var(--bg-card) !important;
          border-radius: 16px;
          height: fit-content;
        }
        .panel-header {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .panel-header h3 {
          color: #fff;
          font-size: 15px;
        }
        .panel-desc {
          font-size: 12px;
          color: var(--text-muted);
          line-height: 1.5;
        }
        .feedback-form {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .feedback-textarea {
          height: 160px;
          resize: none;
          font-size: 13px;
          line-height: 1.5;
        }

        /* Export Toast */
        .export-toast {
          position: fixed;
          bottom: 24px;
          right: 24px;
          z-index: 1050;
          background: #18181b;
          border: 1px solid rgba(52, 211, 153, 0.3);
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
          border-radius: 12px;
          padding: 14px 18px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          max-width: 480px;
        }
        .toast-content {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .toast-text {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .toast-msg {
          font-size: 13px;
          font-weight: 600;
          color: #fff;
        }
        .toast-sub {
          font-size: 11.5px;
          color: rgba(255, 255, 255, 0.6);
        }
        .toast-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .toast-close-btn {
          background: none;
          border: none;
          color: rgba(255, 255, 255, 0.4);
          cursor: pointer;
          padding: 2px;
          display: flex;
          align-items: center;
        }
        .toast-close-btn:hover {
          color: #fff;
        }
        .btn-xs {
          font-size: 11px;
          padding: 4px 8px;
        }
      `}</style>
    </div>
  );
}
