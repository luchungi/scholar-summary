import React, { useState } from 'react';
import { Mail, Check, X, ClipboardList, RefreshCw } from 'lucide-react';

interface LinkItem {
  title: string;
  url: string;
}

interface AlertItem {
  id?: string;
  subject: string;
  date: string;
  links: LinkItem[];
}

interface SyncPreviewProps {
  alerts: AlertItem[];
  onClose: () => void;
  onStartSync: (selectedPapers: LinkItem[], totalEmails: number) => void;
}

export default function SyncPreview({ alerts, onClose, onStartSync }: SyncPreviewProps) {
  // Map all links with their checked state
  // Key represents: url_title to ensure uniqueness
  const [selectedMap, setSelectedMap] = useState<Record<string, { title: string; url: string; checked: boolean }>>(() => {
    const map: Record<string, { title: string; url: string; checked: boolean }> = {};
    alerts.forEach((alert) => {
      alert.links.forEach((link) => {
        const key = `${link.url}::${link.title}`;
        map[key] = { title: link.title, url: link.url, checked: true };
      });
    });
    return map;
  });

  const handleToggle = (key: string) => {
    setSelectedMap((prev) => ({
      ...prev,
      [key]: { ...prev[key], checked: !prev[key].checked }
    }));
  };

  const handleToggleAll = (checked: boolean) => {
    setSelectedMap((prev) => {
      const next = { ...prev };
      Object.keys(next).forEach((key) => {
        next[key].checked = checked;
      });
      return next;
    });
  };

  const selectedItems = Object.values(selectedMap).filter((item) => item.checked);
  const totalItemsCount = Object.keys(selectedMap).length;

  const handleStart = () => {
    if (selectedItems.length === 0) {
      alert('Please select at least one paper to process.');
      return;
    }
    const papers = selectedItems.map((item) => ({ title: item.title, url: item.url }));
    onStartSync(papers, alerts.length);
  };

  return (
    <div className="sync-preview-overlay">
      <div className="sync-preview-container glass-panel fade-in">
        <div className="preview-header">
          <div className="header-title-container">
            <ClipboardList className="text-purple-400" size={22} />
            <div>
              <h3>Gmail Alert Inbox Preview</h3>
              <p className="subtitle">Found {alerts.length} Alert Emails containing {totalItemsCount} paper links.</p>
            </div>
          </div>
          <button onClick={onClose} className="close-btn">
            <X size={20} />
          </button>
        </div>

        <div className="bulk-actions">
          <button onClick={() => handleToggleAll(true)} className="btn btn-secondary btn-xs">
            Select All
          </button>
          <button onClick={() => handleToggleAll(false)} className="btn btn-secondary btn-xs">
            Deselect All
          </button>
          <div className="selection-count">
            Selected: <strong>{selectedItems.length}</strong> / {totalItemsCount} papers
          </div>
        </div>

        <div className="alerts-list scroller">
          {alerts.map((alert, alertIdx) => {
            const hasCheckedLinks = alert.links.some(
              (link) => selectedMap[`${link.url}::${link.title}`]?.checked
            );

            return (
              <div key={alert.id || alertIdx} className={`alert-email-card ${hasCheckedLinks ? 'active' : 'inactive'}`}>
                <div className="email-meta">
                  <div className="email-subject-line">
                    <Mail size={16} className="email-icon" />
                    <span className="email-subject">{alert.subject}</span>
                  </div>
                  <span className="email-date">{alert.date}</span>
                </div>

                <div className="papers-links-list">
                  {alert.links.length === 0 ? (
                    <div className="no-papers">No links found in this email</div>
                  ) : (
                    alert.links.map((link, linkIdx) => {
                      const key = `${link.url}::${link.title}`;
                      const isChecked = selectedMap[key]?.checked || false;

                      return (
                        <div
                          key={linkIdx}
                          className={`paper-link-row ${isChecked ? 'checked' : 'unchecked'}`}
                          onClick={() => handleToggle(key)}
                        >
                          <div className="checkbox-control">
                            <div className="custom-checkbox">
                              {isChecked && <Check size={12} className="check-icon" />}
                            </div>
                          </div>
                          <div className="paper-info">
                            <span className="paper-title">{link.title}</span>
                            <span className="paper-url">{link.url}</span>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="preview-footer">
          <button onClick={onClose} className="btn btn-secondary">
            Cancel
          </button>
          <button onClick={handleStart} className="btn btn-primary">
            <RefreshCw size={16} />
            Start Analysis ({selectedItems.length} Papers)
          </button>
        </div>
      </div>

      <style>{`
        .sync-preview-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.7);
          backdrop-filter: blur(8px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 999;
          padding: 20px;
        }
        .sync-preview-container {
          width: 100%;
          max-width: 800px;
          height: min(85vh, 750px);
          display: flex;
          flex-direction: column;
          background: var(--bg-dark) !important;
          border: 1px solid var(--border-color) !important;
          border-radius: 16px;
          overflow: hidden;
        }
        .preview-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 24px;
          border-bottom: 1px solid var(--border-color);
          flex-shrink: 0;
        }
        .header-title-container {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .preview-header h3 {
          font-family: var(--font-display);
          font-size: 18px;
          color: #fff;
        }
        .subtitle {
          font-size: 13px;
          color: var(--text-muted);
        }
        .bulk-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 16px 24px;
          background: rgba(255,255,255,0.02);
          border-bottom: 1px solid var(--border-color);
          flex-shrink: 0;
        }
        .btn-xs {
          font-size: 12px;
          padding: 6px 12px;
        }
        .selection-count {
          margin-left: auto;
          font-size: 13px;
          color: var(--text-muted);
        }
        .selection-count strong {
          color: var(--accent-purple);
        }
        .alerts-list {
          flex: 1 1 0;
          min-height: 0;
          overflow-y: auto;
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .alert-email-card {
          border: 1px solid var(--border-color);
          border-radius: 12px;
          overflow: hidden;
          background: rgba(255,255,255,0.01);
          transition: all 0.2s ease;
          flex-shrink: 0;
        }
        .alert-email-card.active {
          border-color: rgba(124, 58, 237, 0.2);
          box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }
        .alert-email-card.inactive {
          opacity: 0.7;
        }
        .email-meta {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 16px;
          background: rgba(255, 255, 255, 0.03);
          border-bottom: 1px solid var(--border-color);
        }
        .email-subject-line {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #fff;
        }
        .email-icon {
          color: var(--accent-purple);
        }
        .email-subject {
          font-weight: 500;
          font-size: 14px;
        }
        .email-date {
          font-size: 12px;
          color: var(--text-muted);
        }
        .papers-links-list {
          display: flex;
          flex-direction: column;
        }
        .paper-link-row {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 12px 16px;
          border-bottom: 1px solid rgba(255,255,255,0.03);
          cursor: pointer;
          transition: background 0.2s;
        }
        .paper-link-row:last-child {
          border-bottom: none;
        }
        .paper-link-row:hover {
          background: rgba(255,255,255,0.02);
        }
        .paper-link-row.checked {
          background: rgba(124, 58, 237, 0.03);
        }
        .paper-link-row.checked .custom-checkbox {
          border-color: var(--accent-purple);
          background: var(--accent-purple);
        }
        .checkbox-control {
          margin-top: 2px;
        }
        .custom-checkbox {
          width: 18px;
          height: 18px;
          border: 2px solid var(--border-color);
          border-radius: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
        }
        .check-icon {
          color: white;
        }
        .paper-info {
          display: flex;
          flex-direction: column;
          gap: 2px;
          min-width: 0;
        }
        .paper-title {
          font-size: 14px;
          font-weight: 500;
          color: #fff;
        }
        .paper-url {
          font-size: 12px;
          color: var(--text-muted);
          word-break: break-all;
        }
        .no-papers {
          padding: 16px;
          text-align: center;
          color: var(--text-muted);
          font-size: 13px;
        }
        .preview-footer {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          padding: 20px 24px;
          border-top: 1px solid var(--border-color);
          background: rgba(255,255,255,0.01);
          flex-shrink: 0;
        }
      `}</style>
    </div>
  );
}
