import React, { useState, useEffect } from 'react';
import { Search, Calendar, Link as LinkIcon, BookOpen, ChevronRight, Loader, Trash } from 'lucide-react';

interface PaperReport {
  id: number;
  title: string;
  url: string;
  date_processed: string;
  report_path: string;
  quality_rating?: number;
  relevance_rating?: number;
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
                          <tr key={paper.id} className="table-row">
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
        .th-title {
          width: 50%;
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
      `}</style>
    </div>
  );
}
