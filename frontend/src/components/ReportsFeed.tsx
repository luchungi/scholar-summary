import React, { useState, useEffect } from 'react';
import { Search, Calendar, Link as LinkIcon, BookOpen, ChevronRight, Loader, Trash, Download, X, AlertTriangle, CheckCircle2, FolderOpen } from 'lucide-react';

interface PaperReport {
  id: number;
  title: string;
  url: string;
  date_processed: string;
  report_path: string;
  quality_rating?: number;
  relevance_rating?: number;
}

interface PreflightPaper {
  id: number;
  title: string;
  has_pdf: boolean;
  filename_base: string;
}

interface PreflightData {
  total: number;
  ready_count: number;
  missing_count: number;
  all_have_pdf: boolean;
  papers: PreflightPaper[];
}

interface ExportToast {
  message: string;
  batchDir: string;
}

const getRatingClass = (rating?: number): string => {
  if (rating === undefined || rating === null) return 'rating-na';
  if (rating >= 4.5) return 'rating-high';
  if (rating >= 3.5) return 'rating-medium';
  return 'rating-low';
};

interface ReportsFeedProps {
  onSelectReport: (reportId: number) => void;
}

export default function ReportsFeed({ onSelectReport }: ReportsFeedProps) {
  const [reports, setReports] = useState<PaperReport[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'quality' | 'relevance'>('quality');
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>('desc');

  // Multi-selection & bulk export states
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [exportingZip, setExportingZip] = useState(false);
  const [exportingDirect, setExportingDirect] = useState(false);
  const [preflightModalOpen, setPreflightModalOpen] = useState(false);
  const [preflightData, setPreflightData] = useState<PreflightData | null>(null);
  const [exportToast, setExportToast] = useState<ExportToast | null>(null);

  const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

  const fetchReports = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_URL}/api/reports`);
      const data = await res.json();
      setReports(data);
    } catch (e) {
      console.error('Error fetching reports:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReports();
  }, []);

  const handleDelete = async (reportId: number) => {
    if (confirm("Are you sure you want to permanently delete this report? This will remove it from the database and delete the markdown file from disk.")) {
      try {
        const res = await fetch(`${API_URL}/api/reports/${reportId}`, {
          method: 'DELETE'
        });
        if (res.ok) {
          setReports((prev) => prev.filter((r) => r.id !== reportId));
        } else {
          throw new Error(await res.text());
        }
      } catch (err: any) {
        alert(`Failed to delete report: ${err.message || err}`);
      }
    }
  };

  const handleSort = (field: 'quality' | 'relevance') => {
    if (sortBy === field) {
      setSortDir(sortDir === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(field);
      setSortDir('desc');
    }
  };

  const filteredReports = reports.filter((report) => {
    const titleMatch = report.title.toLowerCase().includes(searchQuery.toLowerCase());
    const urlMatch = report.url.toLowerCase().includes(searchQuery.toLowerCase());
    return titleMatch || urlMatch;
  });

  const toggleSelectPaper = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectGroup = (papers: PaperReport[]) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const allGroupSelected = papers.length > 0 && papers.every((p) => next.has(p.id));
      if (allGroupSelected) {
        papers.forEach((p) => next.delete(p.id));
      } else {
        papers.forEach((p) => next.add(p.id));
      }
      return next;
    });
  };

  const toggleSelectAllFiltered = () => {
    setSelectedIds((prev) => {
      const allSelected = filteredReports.length > 0 && filteredReports.every((p) => prev.has(p.id));
      if (allSelected) return new Set();
      return new Set(filteredReports.map((p) => p.id));
    });
  };

  const handleInitiateEndNoteExport = async () => {
    if (selectedIds.size === 0) return;
    setExportingDirect(true);
    try {
      const res = await fetch(`${API_URL}/api/reports/export-preflight`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paper_ids: Array.from(selectedIds) })
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const data: PreflightData = await res.json();
      if (data.all_have_pdf) {
        // Fast-path: 100% of papers have PDFs, export directly with 0 friction
        await handleExecuteEndNoteExport(false);
      } else {
        // Missing PDFs: prompt user with confirmation modal
        setPreflightData(data);
        setPreflightModalOpen(true);
        setExportingDirect(false);
      }
    } catch (err: any) {
      alert(`Pre-flight check failed: ${err.message || err}`);
      setExportingDirect(false);
    }
  };

  const handleExecuteEndNoteExport = async (skipPaywalled: boolean) => {
    setExportingDirect(true);
    setPreflightModalOpen(false);
    try {
      const res = await fetch(`${API_URL}/api/reports/endnote-export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paper_ids: Array.from(selectedIds),
          skip_paywalled: skipPaywalled
        })
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const data = await res.json();
      setSelectedIds(new Set());
      setExportToast({
        message: `Exported ${data.total_exported} paper${data.total_exported === 1 ? '' : 's'} to EndNote 21 (${data.with_pdf_count} with PDF attached${data.citation_only_count > 0 ? `, ${data.citation_only_count} citation-only` : ''})!`,
        batchDir: data.batch_dir
      });
    } catch (err: any) {
      alert(`EndNote export failed: ${err.message || err}`);
    } finally {
      setExportingDirect(false);
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

  const handleBulkExport = async () => {
    if (selectedIds.size === 0) return;
    setExportingZip(true);
    try {
      const res = await fetch(`${API_URL}/api/reports/bulk-export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paper_ids: Array.from(selectedIds) })
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const disposition = res.headers.get('Content-Disposition');
      let filename = `EndNote_Export_${new Date().toISOString().slice(0, 10)}.zip`;
      if (disposition && disposition.includes('filename=')) {
        const match = disposition.match(/filename="?([^";]+)"?/);
        if (match && match[1]) filename = match[1];
      }
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(`Failed to export reports: ${err.message || err}`);
    } finally {
      setExportingZip(false);
    }
  };

  // Group filtered reports by date (YYYY-MM-DD)
  const groups: { [key: string]: { label: string; date: Date; papers: PaperReport[] } } = {};
  filteredReports.forEach((report) => {
    if (!report.date_processed) return;
    const dateObj = new Date(report.date_processed);
    const yyyymmdd = dateObj.toISOString().split('T')[0];
    if (!groups[yyyymmdd]) {
      const label = dateObj.toLocaleDateString(undefined, { dateStyle: 'long' });
      groups[yyyymmdd] = {
        label,
        date: dateObj,
        papers: []
      };
    }
    groups[yyyymmdd].papers.push(report);
  });

  // Sort dates descending (newest on top)
  const sortedDateKeys = Object.keys(groups).sort((a, b) => b.localeCompare(a));

  // Sort papers within each date group
  sortedDateKeys.forEach((key) => {
    groups[key].papers.sort((a, b) => {
      const valA = sortBy === 'quality' ? (a.quality_rating ?? 0) : (a.relevance_rating ?? 0);
      const valB = sortBy === 'quality' ? (b.quality_rating ?? 0) : (b.relevance_rating ?? 0);
      
      if (valA === valB) {
        return a.title.localeCompare(b.title);
      }
      return sortDir === 'desc' ? valB - valA : valA - valB;
    });
  });

  return (
    <div className="reports-feed fade-in">
      <div className="feed-header">
        <div className="title-desc">
          <h2>Summarized Literature Reports</h2>
          <p>Browse through academic papers processed by your local language model assistant.</p>
        </div>
        <div className="search-bar-container glass-panel">
          <Search size={18} className="search-icon" />
          <input
            type="text"
            placeholder="Search papers by title or source URL..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
          />
        </div>
      </div>

      {selectedIds.size > 0 && (
        <div className="bulk-export-bar glass-panel fade-in">
          <div className="bulk-bar-info">
            <span className="selected-count-badge">{selectedIds.size}</span>
            <span>{selectedIds.size === 1 ? 'paper' : 'papers'} selected for EndNote</span>
          </div>
          <div className="bulk-bar-actions">
            <button
              onClick={handleInitiateEndNoteExport}
              disabled={exportingDirect || exportingZip}
              className="btn btn-primary btn-sm flex items-center gap-1.5"
              title="Directly export and launch EndNote 21 with all papers and PDFs attached"
            >
              {exportingDirect ? (
                <>
                  <Loader className="animate-spin" size={13} />
                  Exporting to EndNote...
                </>
              ) : (
                <>
                  <BookOpen size={13} />
                  Export to EndNote (1-Click)
                </>
              )}
            </button>
            <button
              onClick={handleBulkExport}
              disabled={exportingZip || exportingDirect}
              className="btn btn-secondary btn-sm flex items-center gap-1.5"
              title="Download portable ZIP archive with combined citations_all.enw and all PDFs"
            >
              {exportingZip ? (
                <>
                  <Loader className="animate-spin" size={13} />
                  Packaging ZIP...
                </>
              ) : (
                <>
                  <Download size={13} />
                  Download ZIP
                </>
              )}
            </button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="btn btn-secondary btn-sm"
              title="Clear all selections"
            >
              <X size={13} />
              Clear
            </button>
          </div>
        </div>
      )}

      {/* Preflight Missing PDFs Modal */}
      {preflightModalOpen && preflightData && (
        <div className="modal-backdrop fade-in" onClick={() => setPreflightModalOpen(false)}>
          <div className="modal-content glass-panel" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-row">
                <AlertTriangle className="text-amber-400" size={20} />
                <h3>Missing PDFs Detected</h3>
              </div>
              <button className="modal-close-btn" onClick={() => setPreflightModalOpen(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="modal-body">
              <p className="modal-desc">
                <strong>{preflightData.ready_count}</strong> of <strong>{preflightData.total}</strong> selected papers have downloadable PDFs ready.
                The following <strong>{preflightData.missing_count}</strong> paper{preflightData.missing_count > 1 ? 's' : ''} {preflightData.missing_count > 1 ? 'do' : 'does'} not have an open-access PDF (paywalled or HTML-only):
              </p>
              <div className="missing-papers-list scroller">
                {preflightData.papers.filter(p => !p.has_pdf).map(p => (
                  <div key={p.id} className="missing-paper-item">
                    <span className="missing-badge">No PDF</span>
                    <span className="missing-title">{p.title}</span>
                  </div>
                ))}
              </div>
              <p className="modal-hint">
                EndNote requires local PDF files to bind attachments. How would you like to proceed?
              </p>
            </div>
            <div className="modal-footer">
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setPreflightModalOpen(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleExecuteEndNoteExport(false)}
                title="Import all selected papers into EndNote, attaching PDFs where available and importing citation-only for the rest"
              >
                Export All ({preflightData.missing_count} Citation-Only)
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => handleExecuteEndNoteExport(true)}
                title="Only export papers that have direct PDF attachments"
              >
                Export Only {preflightData.ready_count} with PDFs
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Export Toast Notification */}
      {exportToast && (
        <div className="export-toast glass-panel fade-in">
          <div className="toast-content">
            <CheckCircle2 className="text-emerald-400 shrink-0" size={18} />
            <div className="toast-text">
              <div className="toast-msg">{exportToast.message}</div>
              <div className="toast-sub">EndNote 21 has opened to import your references.</div>
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

      <div className="reports-list-container scroller">
        {loading ? (
          <div className="feed-loading">
            <Loader className="animate-spin text-purple-400" size={32} />
            <p>Loading reports...</p>
          </div>
        ) : filteredReports.length === 0 ? (
          <div className="feed-empty glass-panel">
            <BookOpen size={48} className="empty-icon" />
            <h3>No reports found</h3>
            <p>{searchQuery ? 'Try adjusting your search keywords.' : 'No papers have been successfully processed yet.'}</p>
          </div>
        ) : (
          <div className="reports-tables-container">
            {sortedDateKeys.map((dateKey) => {
              const group = groups[dateKey];
              return (
                <div key={dateKey} className="date-group-section">
                  <div className="date-group-header">
                    <Calendar size={16} className="date-group-icon" />
                    <h3>{group.label}</h3>
                    <span className="papers-count-badge">{group.papers.length} {group.papers.length === 1 ? 'paper' : 'papers'}</span>
                  </div>
                  
                  <div className="table-wrapper glass-panel">
                    <table className="reports-table">
                      <thead>
                        <tr>
                          <th className="th-select">
                            <input
                              type="checkbox"
                              checked={group.papers.length > 0 && group.papers.every((p) => selectedIds.has(p.id))}
                              onChange={() => toggleSelectGroup(group.papers)}
                              title="Select / deselect all in this section"
                              className="checkbox-input"
                            />
                          </th>
                          <th className="th-title">Title of the Paper</th>
                          <th 
                            className={`th-rating sortable ${sortBy === 'quality' ? 'active' : ''}`}
                            onClick={() => handleSort('quality')}
                          >
                            <div className="th-content">
                              <span>Quality Rating</span>
                              <span className="sort-arrow">
                                {sortBy === 'quality' ? (sortDir === 'desc' ? ' ▼' : ' ▲') : ''}
                              </span>
                            </div>
                          </th>
                          <th 
                            className={`th-rating sortable ${sortBy === 'relevance' ? 'active' : ''}`}
                            onClick={() => handleSort('relevance')}
                          >
                            <div className="th-content">
                              <span>Relevancy Rating</span>
                              <span className="sort-arrow">
                                {sortBy === 'relevance' ? (sortDir === 'desc' ? ' ▼' : ' ▲') : ''}
                              </span>
                            </div>
                          </th>
                          <th className="th-link">Link</th>
                          <th className="th-actions">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.papers.map((paper) => (
                          <tr key={paper.id} className={`table-row ${selectedIds.has(paper.id) ? 'row-selected' : ''}`}>
                            <td className="td-select">
                              <input
                                type="checkbox"
                                checked={selectedIds.has(paper.id)}
                                onChange={() => toggleSelectPaper(paper.id)}
                                onClick={(e) => e.stopPropagation()}
                                className="checkbox-input"
                              />
                            </td>
                            <td className="td-title">
                              <button 
                                className="paper-title-link"
                                onClick={() => onSelectReport(paper.id)}
                              >
                                {paper.title}
                              </button>
                            </td>
                            <td className="td-rating">
                              <span className={`rating-badge ${getRatingClass(paper.quality_rating)}`}>
                                {paper.quality_rating !== undefined && paper.quality_rating !== null 
                                  ? paper.quality_rating.toFixed(1) 
                                  : 'N/A'}
                              </span>
                            </td>
                            <td className="td-rating">
                              <span className={`rating-badge ${getRatingClass(paper.relevance_rating)}`}>
                                {paper.relevance_rating !== undefined && paper.relevance_rating !== null 
                                  ? paper.relevance_rating.toFixed(1) 
                                  : 'N/A'}
                              </span>
                            </td>
                            <td className="td-link">
                              <a 
                                href={paper.url} 
                                target="_blank" 
                                rel="noopener noreferrer" 
                                className="paper-external-link"
                                onClick={(e) => e.stopPropagation()}
                              >
                                Link
                              </a>
                            </td>
                            <td className="td-actions">
                              <button 
                                className="delete-report-btn" 
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDelete(paper.id);
                                }}
                                title="Delete Report"
                              >
                                <Trash size={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <style>{`
        .reports-feed {
          display: flex;
          flex-direction: column;
          gap: 20px;
          height: 100%;
          overflow: hidden;
        }
        .flex {
          display: flex;
        }
        .justify-between {
          justify-content: space-between;
        }
        .items-start {
          align-items: flex-start;
        }
        .delete-report-btn {
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
        .delete-report-btn:hover {
          color: var(--accent-red);
          background: rgba(244, 63, 94, 0.1);
        }
        .feed-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 20px;
        }
        @media (max-width: 768px) {
          .feed-header {
            flex-direction: column;
            align-items: flex-start;
          }
        }
        .feed-header h2 {
          font-size: 22px;
          color: #fff;
          margin-bottom: 4px;
        }
        .feed-header p {
          font-size: 13px;
          color: var(--text-muted);
        }
        .search-bar-container {
          display: flex;
          align-items: center;
          padding: 8px 16px;
          width: 100%;
          max-width: 380px;
          background: var(--bg-card);
        }
        .search-icon {
          color: var(--text-muted);
          margin-right: 10px;
        }
        .search-input {
          background: none;
          border: none;
          color: #fff;
          font-family: var(--font-sans);
          font-size: 14px;
          outline: none;
          width: 100%;
        }
        .reports-list-container {
          flex: 1;
          overflow-y: auto;
          padding-right: 8px;
        }
        .feed-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          height: 300px;
          color: var(--text-muted);
          font-size: 14px;
        }
        .feed-empty {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          padding: 48px;
          text-align: center;
          background: var(--bg-card);
        }
        .empty-icon {
          color: var(--text-dark);
        }
        .feed-empty h3 {
          color: #fff;
          font-size: 16px;
        }
        .feed-empty p {
          font-size: 13px;
          color: var(--text-muted);
        }
        .reports-tables-container {
          display: flex;
          flex-direction: column;
          gap: 32px;
          margin-top: 10px;
        }
        .date-group-section {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .date-group-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding-left: 4px;
        }
        .date-group-icon {
          color: #a78bfa;
        }
        .date-group-header h3 {
          font-size: 16px;
          color: #fff;
          font-weight: 600;
          font-family: var(--font-display);
        }
        .papers-count-badge {
          font-size: 11px;
          color: var(--text-muted);
          background: rgba(255, 255, 255, 0.05);
          padding: 2px 8px;
          border-radius: 20px;
          font-weight: 500;
        }
        .table-wrapper {
          overflow-x: auto;
          background: var(--bg-card) !important;
          border: 1px solid var(--border-color);
          border-radius: 12px;
        }
        .reports-table {
          width: 100%;
          border-collapse: collapse;
          text-align: left;
          font-size: 13px;
        }
        .reports-table th {
          padding: 14px 18px;
          font-weight: 600;
          color: var(--text-muted);
          font-family: var(--font-display);
          border-bottom: 1px solid var(--border-color);
          user-select: none;
          font-size: 12px;
          letter-spacing: 0.02em;
        }
        .reports-table th.sortable {
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .reports-table th.sortable:hover {
          color: #fff;
          background: rgba(255, 255, 255, 0.02);
        }
        .reports-table th.sortable.active {
          color: #a78bfa;
          background: rgba(167, 139, 250, 0.05);
        }
        .th-content {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .bulk-export-bar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 20px;
          margin-bottom: 20px;
          border-radius: 12px;
          background: rgba(124, 58, 237, 0.15);
          border: 1px solid rgba(124, 58, 237, 0.35);
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        }
        .bulk-bar-info {
          display: flex;
          align-items: center;
          gap: 10px;
          font-weight: 500;
          font-size: 14px;
          color: #fff;
        }
        .selected-count-badge {
          background: #8b5cf6;
          color: #fff;
          padding: 2px 9px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 700;
        }
        .bulk-bar-actions {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .th-select, .td-select {
          width: 40px;
          text-align: center;
          padding-left: 14px !important;
          padding-right: 6px !important;
        }
        .checkbox-input {
          width: 16px;
          height: 16px;
          accent-color: #8b5cf6;
          cursor: pointer;
          border-radius: 4px;
        }
        .row-selected {
          background-color: rgba(124, 58, 237, 0.09) !important;
        }
        .th-title {
          width: 46%;
        }
        .th-rating {
          width: 18%;
        }
        .th-link {
          width: 10%;
        }
        .th-actions {
          width: 8%;
          text-align: right;
        }
        .reports-table td {
          padding: 14px 18px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.03);
          vertical-align: middle;
          color: var(--text-main);
        }
        .table-row {
          transition: background-color 0.2s ease;
        }
        .table-row:hover {
          background-color: rgba(255, 255, 255, 0.01);
        }
        .table-row:last-child td {
          border-bottom: none;
        }
        .td-title {
          font-weight: 500;
        }
        .paper-title-link {
          background: none;
          border: none;
          color: #fff;
          text-align: left;
          font-weight: 500;
          font-size: 13.5px;
          cursor: pointer;
          padding: 0;
          line-height: 1.4;
          transition: color 0.15s ease;
          width: 100%;
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .paper-title-link:hover {
          color: #a78bfa;
          text-decoration: none;
        }
        .td-rating {
          font-weight: 600;
        }
        .rating-badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 4px 10px;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 700;
          width: 44px;
        }
        .rating-high {
          background: rgba(16, 185, 129, 0.12);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.2);
        }
        .rating-medium {
          background: rgba(245, 158, 11, 0.12);
          color: #fbbf24;
          border: 1px solid rgba(245, 158, 11, 0.2);
        }
        .rating-low {
          background: rgba(239, 68, 68, 0.12);
          color: #f87171;
          border: 1px solid rgba(239, 68, 68, 0.2);
        }
        .rating-na {
          background: rgba(255, 255, 255, 0.05);
          color: var(--text-dark);
          border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .paper-external-link {
          color: #a78bfa;
          text-decoration: none;
          font-weight: 500;
          transition: color 0.15s ease;
        }
        .paper-external-link:hover {
          color: #fff;
          text-decoration: underline;
        }
        .td-link {
          font-weight: 500;
        }
        .td-actions {
          text-align: right;
        }
        .sort-arrow {
          font-size: 9px;
          opacity: 0.8;
        }

        /* Preflight Modal & Export Toast */
        .modal-backdrop {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.75);
          backdrop-filter: blur(4px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 20px;
        }
        .modal-content {
          width: 100%;
          max-width: 540px;
          border-radius: 14px;
          border: 1px solid rgba(255, 255, 255, 0.15);
          background: #18181b;
          box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }
        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .modal-title-row {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .modal-title-row h3 {
          margin: 0;
          font-size: 16px;
          font-weight: 600;
          color: #fff;
        }
        .modal-close-btn {
          background: none;
          border: none;
          color: rgba(255, 255, 255, 0.5);
          cursor: pointer;
          padding: 4px;
          border-radius: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .modal-close-btn:hover {
          color: #fff;
          background: rgba(255, 255, 255, 0.1);
        }
        .modal-body {
          padding: 18px 20px;
          font-size: 13.5px;
          line-height: 1.5;
          color: rgba(255, 255, 255, 0.85);
        }
        .modal-desc {
          margin: 0 0 12px 0;
        }
        .missing-papers-list {
          max-height: 180px;
          overflow-y: auto;
          background: rgba(0, 0, 0, 0.35);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 8px;
          padding: 8px 12px;
          margin-bottom: 12px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .missing-paper-item {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          font-size: 12.5px;
        }
        .missing-badge {
          background: rgba(239, 68, 68, 0.15);
          color: #f87171;
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 4px;
          padding: 1px 6px;
          font-size: 10px;
          font-weight: 600;
          white-space: nowrap;
          margin-top: 1px;
        }
        .missing-title {
          color: rgba(255, 255, 255, 0.9);
          word-break: break-word;
        }
        .modal-hint {
          margin: 0;
          font-size: 12.5px;
          color: rgba(255, 255, 255, 0.6);
        }
        .modal-footer {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 10px;
          padding: 14px 20px;
          border-top: 1px solid rgba(255, 255, 255, 0.1);
          background: rgba(0, 0, 0, 0.2);
        }
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
      `}</style>
    </div>
  );
}
