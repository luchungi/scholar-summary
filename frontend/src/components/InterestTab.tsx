import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { Eye, Edit3, Save, RotateCcw, Sparkles, Loader } from 'lucide-react';

export default function InterestTab() {
  const [content, setContent] = useState('');
  const [editContent, setEditContent] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

  const fetchProfile = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_URL}/api/profile`);
      const data = await res.json();
      setContent(data.content);
      setEditContent(data.content);
    } catch (e) {
      console.error('Error fetching user interests:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${API_URL}/api/profile/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContent })
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      setContent(editContent);
      setIsEditing(false);
      alert('Interest profile saved! Local backup stored in .backups/');
    } catch (e: any) {
      alert(`Error saving profile: ${e.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (confirm('Discard changes and revert to saved profile?')) {
      setEditContent(content);
      setIsEditing(false);
    }
  };

  if (loading) {
    return (
      <div className="interest-loading">
        <Loader className="animate-spin text-purple-400" size={32} />
        <p>Loading interest profile...</p>
      </div>
    );
  }

  return (
    <div className="interest-profile-tab fade-in">
      <div className="tab-header">
        <div className="title-desc">
          <h2>User Research Interests</h2>
          <p>This profile defines what topics, keywords, and fields the agent checks against to rate paper relevance.</p>
        </div>
        <div className="action-buttons">
          {isEditing ? (
            <>
              <button onClick={handleReset} className="btn btn-secondary btn-sm" disabled={saving}>
                <RotateCcw size={14} />
                Cancel
              </button>
              <button onClick={handleSave} className="btn btn-primary btn-sm" disabled={saving}>
                <Save size={14} />
                {saving ? 'Saving...' : 'Save Profile'}
              </button>
            </>
          ) : (
            <button onClick={() => setIsEditing(true)} className="btn btn-secondary btn-sm">
              <Edit3 size={14} />
              Edit Profile
            </button>
          )}
        </div>
      </div>

      <div className="profile-container glass-panel">
        {isEditing ? (
          <div className="editor-layout">
            <div className="editor-instructions">
              <Sparkles size={14} className="text-purple-400" />
              <span>Editing raw Markdown (user_interests.md). Maintain headers and bullet layout.</span>
            </div>
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="glass-input markdown-editor scroller"
              disabled={saving}
            />
          </div>
        ) : (
          <div className="markdown-render-body scroller">
            {content ? (
              <ReactMarkdown
                components={{
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  )
                }}
              >
                {content}
              </ReactMarkdown>
            ) : (
              <div className="empty-profile">No research interests defined. Click Edit to create one.</div>
            )}
          </div>
        )}
      </div>

      <style>{`
        .interest-profile-tab {
          display: flex;
          flex-direction: column;
          gap: 20px;
          height: 100%;
          overflow: hidden;
        }
        .tab-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 20px;
        }
        .tab-header h2 {
          font-size: 22px;
          color: #fff;
          margin-bottom: 4px;
        }
        .tab-header p {
          font-size: 13px;
          color: var(--text-muted);
        }
        .action-buttons {
          display: flex;
          gap: 10px;
        }
        .profile-container {
          flex: 1;
          display: flex;
          flex-direction: column;
          background: var(--bg-card) !important;
          border-radius: 16px;
          overflow: hidden;
        }
        .editor-layout {
          display: flex;
          flex-direction: column;
          flex: 1;
          height: 100%;
        }
        .editor-instructions {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px 20px;
          background: rgba(255,255,255,0.02);
          border-bottom: 1px solid var(--border-color);
          font-size: 12px;
          color: var(--text-muted);
        }
        .markdown-editor {
          flex: 1;
          background: #06070d;
          border: none;
          resize: none;
          font-family: var(--font-mono);
          font-size: 13px;
          padding: 24px;
          color: #e2e8f0;
          line-height: 1.6;
          outline: none;
        }
        .markdown-render-body {
          flex: 1;
          padding: 32px;
          overflow-y: auto;
        }
        /* Inherit markdown rendering styles from ReportDetail.tsx */
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
        .markdown-render-body h1 { font-size: 22px; margin-top: 0; }
        .markdown-render-body h2 { font-size: 18px; border-bottom: 1px solid var(--border-color); padding-bottom: 4px; }
        .markdown-render-body h3 { font-size: 15px; }
        .markdown-render-body p {
          margin-bottom: 16px;
          font-size: 14px;
          line-height: 1.6;
          color: #e2e8f0;
        }
        .markdown-render-body ul, 
        .markdown-render-body ol {
          margin-bottom: 16px;
          padding-left: 20px;
          color: #e2e8f0;
        }
        .markdown-render-body li {
          margin-bottom: 6px;
          font-size: 14px;
        }
        .markdown-render-body code {
          font-family: var(--font-mono);
          font-size: 13px;
          color: #a78bfa;
          background: rgba(167, 139, 250, 0.08);
          padding: 2px 4px;
          border-radius: 4px;
        }
        .empty-profile {
          text-align: center;
          padding: 40px;
          color: var(--text-muted);
          font-size: 14px;
        }
        .interest-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 12px;
          height: 80%;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
}
