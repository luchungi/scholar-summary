import React from 'react';
import { Save, X, AlertCircle } from 'lucide-react';

interface DiffViewerProps {
  diffText: string;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}

export default function DiffViewer({ diffText, onSave, onCancel, saving }: DiffViewerProps) {
  const lines = diffText.split('\n');

  // Helper to color diff lines
  const getLineClass = (line: string) => {
    if (line.startsWith('+') && !line.startsWith('+++')) return 'diff-added';
    if (line.startsWith('-') && !line.startsWith('---')) return 'diff-removed';
    if (line.startsWith('@@')) return 'diff-header';
    if (line.startsWith('+++') || line.startsWith('---')) return 'diff-file-meta';
    return 'diff-unchanged';
  };

  const isNoChanges = diffText.trim() === '' || !lines.some(l => l.startsWith('+') || l.startsWith('-'));

  return (
    <div className="diff-overlay">
      <div className="diff-container glass-panel fade-in">
        <div className="diff-header-bar">
          <h3>Proposed Profile Modifications</h3>
          <button onClick={onCancel} className="close-btn" disabled={saving}>
            <X size={20} />
          </button>
        </div>

        <div className="diff-explanation">
          <AlertCircle size={16} className="text-purple-400" />
          <p>Please review the proposed updates to your researcher interest profile below before saving.</p>
        </div>

        <div className="diff-body scroller">
          {isNoChanges ? (
            <div className="no-changes-state">No changes detected in your interest profile. Your feedback did not warrant modifying the profile.</div>
          ) : (
            <pre className="diff-pre">
              {lines.map((line, idx) => (
                <div key={idx} className={`diff-line ${getLineClass(line)}`}>
                  {line}
                </div>
              ))}
            </pre>
          )}
        </div>

        <div className="diff-footer">
          <button onClick={onCancel} className="btn btn-secondary" disabled={saving}>
            Cancel
          </button>
          {!isNoChanges && (
            <button onClick={onSave} className="btn btn-primary" disabled={saving}>
              <Save size={16} />
              {saving ? 'Saving changes...' : 'Save Profile Changes'}
            </button>
          )}
        </div>
      </div>

      <style>{`
        .diff-overlay {
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
          z-index: 1050;
          padding: 24px;
        }
        .diff-container {
          width: 100%;
          max-width: 800px;
          height: 600px;
          display: flex;
          flex-direction: column;
          background: var(--bg-dark) !important;
          border: 1px solid var(--border-color) !important;
          box-shadow: 0 25px 60px rgba(0,0,0,0.6) !important;
          overflow: hidden;
        }
        .diff-header-bar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 20px 24px;
          border-bottom: 1px solid var(--border-color);
        }
        .diff-header-bar h3 {
          font-family: var(--font-display);
          font-size: 16px;
          color: #fff;
        }
        .diff-explanation {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px 24px;
          background: rgba(124, 58, 237, 0.05);
          border-bottom: 1px solid var(--border-color);
          font-size: 13px;
          color: var(--text-muted);
        }
        .diff-body {
          flex: 1;
          padding: 24px;
          overflow-y: auto;
          background: #06070d;
        }
        .diff-pre {
          font-family: var(--font-mono);
          font-size: 12px;
          line-height: 1.6;
          color: var(--text-muted);
        }
        .diff-line {
          padding: 1px 8px;
          border-radius: 2px;
        }
        .diff-added {
          background: rgba(16, 185, 129, 0.12);
          color: #34d399;
        }
        .diff-removed {
          background: rgba(244, 63, 94, 0.12);
          color: #fb7185;
        }
        .diff-header {
          color: #60a5fa;
          background: rgba(59, 130, 246, 0.05);
          font-weight: 500;
        }
        .diff-file-meta {
          color: var(--text-dark);
          font-style: italic;
        }
        .no-changes-state {
          padding: 40px;
          text-align: center;
          color: var(--text-muted);
          font-size: 14px;
        }
        .diff-footer {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          padding: 18px 24px;
          border-top: 1px solid var(--border-color);
          background: rgba(255,255,255,0.01);
        }
      `}</style>
    </div>
  );
}
