import React, { useState, useEffect } from 'react';
import { Search, Calendar, Link as LinkIcon, BookOpen, ChevronRight, Loader, Trash } from 'lucide-react';

interface PaperReport {
  id: number;
  title: string;
  url: string;
  date_processed: string;
  report_path: string;
}

interface ReportsFeedProps {
  onSelectReport: (reportId: number) => void;
}

export default function ReportsFeed({ onSelectReport }: ReportsFeedProps) {
  const [reports, setReports] = useState<PaperReport[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);

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

  const filteredReports = reports.filter((report) => {
    const titleMatch = report.title.toLowerCase().includes(searchQuery.toLowerCase());
    const urlMatch = report.url.toLowerCase().includes(searchQuery.toLowerCase());
    return titleMatch || urlMatch;
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
          <div className="reports-grid">
            {filteredReports.map((report) => (
              <div
                key={report.id}
                className="report-card glass-panel"
                onClick={() => onSelectReport(report.id)}
              >
                <div className="report-card-body">
                  <div className="flex justify-between items-start">
                    <span className="report-badge">Report #{report.id}</span>
                    <button 
                      className="delete-report-btn" 
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(report.id);
                      }}
                      title="Delete Report"
                    >
                      <Trash size={14} />
                    </button>
                  </div>
                  <h3 className="report-title-text">{report.title}</h3>
                  <a
                    href={report.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="report-url-link"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <LinkIcon size={12} />
                    {report.url}
                  </a>
                </div>
                <div className="report-card-footer">
                  <div className="date-info">
                    <Calendar size={14} className="calendar-icon" />
                    <span>{new Date(report.date_processed).toLocaleDateString(undefined, { dateStyle: 'medium' })}</span>
                  </div>
                  <button className="read-more-btn">
                    Read Report
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            ))}
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
        .reports-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 20px;
        }
        .report-card {
          display: flex;
          flex-direction: column;
          height: 220px;
          cursor: pointer;
          background: var(--bg-card) !important;
        }
        .report-card:hover {
          transform: translateY(-2px);
          border-color: rgba(124, 58, 237, 0.25);
        }
        .report-card-body {
          flex: 1;
          padding: 20px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .report-badge {
          font-family: var(--font-display);
          font-size: 11px;
          color: #a78bfa;
          background: rgba(124, 58, 237, 0.1);
          padding: 2px 8px;
          border-radius: 4px;
          width: fit-content;
          font-weight: 500;
        }
        .report-title-text {
          font-size: 15px;
          color: #fff;
          font-weight: 600;
          line-height: 1.4;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        .report-url-link {
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
        .report-url-link:hover {
          color: var(--accent-blue);
        }
        .report-card-footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 20px;
          border-top: 1px solid var(--border-color);
          background: rgba(255, 255, 255, 0.01);
        }
        .date-info {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          color: var(--text-muted);
        }
        .calendar-icon {
          color: var(--text-dark);
        }
        .read-more-btn {
          background: none;
          border: none;
          color: #a78bfa;
          font-family: var(--font-display);
          font-weight: 500;
          font-size: 12px;
          display: flex;
          align-items: center;
          gap: 4px;
          cursor: pointer;
          transition: color 0.2s;
        }
        .report-card:hover .read-more-btn {
          color: #fff;
        }
      `}</style>
    </div>
  );
}
