import React, { useEffect, useRef, useState } from 'react';
import { Terminal, X, Play, AlertCircle, CheckCircle } from 'lucide-react';

interface LogsTerminalProps {
  runId: number;
  onClose: () => void;
  onFinished: () => void;
}

export default function LogsTerminal({ runId, onClose, onFinished }: LogsTerminalProps) {
  const [logs, setLogs] = useState<string[]>([]);
  const [status, setStatus] = useState<'running' | 'completed' | 'failed'>('running');
  const bottomRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setLogs(['[+] Connecting to logs stream...']);
    setStatus('running');

    const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';
    const es = new EventSource(`${API_URL}/api/runs/${runId}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = event.data;
      if (data === '[EOF]') {
        setLogs((prev) => [...prev, '\n[+] Run complete. Interface ready.']);
        setStatus('completed');
        onFinished();
        es.close();
      } else {
        // Append raw data chunk
        setLogs((prev) => [...prev, data]);
      }
    };

    es.onerror = (err) => {
      console.error('SSE Error:', err);
      setLogs((prev) => [...prev, '\n[-] Connection lost or task ended.']);
      setStatus('failed');
      onFinished();
      es.close();
    };

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [runId]);

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  return (
    <div className="logs-terminal-overlay">
      <div className="logs-terminal-container glass-panel fade-in">
        <div className="terminal-header">
          <div className="flex items-center gap-2">
            <Terminal size={18} className={status === 'running' ? 'text-blue-400 animate-pulse' : 'text-purple-400'} />
            <span className="terminal-title">Agent Execution Console (Run #{runId})</span>
          </div>
          <div className="flex items-center gap-3">
            <span className={`status-badge ${status}`}>
              {status === 'running' && 'Processing...'}
              {status === 'completed' && 'Finished'}
              {status === 'failed' && 'Interrupted'}
            </span>
            <button onClick={onClose} className="close-btn">
              <X size={18} />
            </button>
          </div>
        </div>
        
        <div className="terminal-body scroller">
          {logs.map((log, idx) => (
            <div key={idx} className="log-line">
              {log}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      <style>{`
        .logs-terminal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.7);
          backdrop-filter: blur(4px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 24px;
        }
        .logs-terminal-container {
          width: 100%;
          max-width: 900px;
          height: 550px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: #06070d !important;
          border: 1px solid rgba(124, 58, 237, 0.2) !important;
          box-shadow: 0 20px 50px rgba(0,0,0,0.5) !important;
        }
        .terminal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 14px 20px;
          background: #0f111e;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .terminal-title {
          font-family: var(--font-display);
          font-weight: 500;
          font-size: 14px;
          color: #a78bfa;
        }
        .status-badge {
          font-size: 11px;
          padding: 3px 8px;
          border-radius: 4px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-weight: 600;
        }
        .status-badge.running {
          background: rgba(59, 130, 246, 0.15);
          color: #60a5fa;
          border: 1px solid rgba(59, 130, 246, 0.3);
        }
        .status-badge.completed {
          background: rgba(16, 185, 129, 0.15);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .status-badge.failed {
          background: rgba(244, 63, 94, 0.15);
          color: #fb7185;
          border: 1px solid rgba(244, 63, 94, 0.3);
        }
        .close-btn {
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          transition: color 0.2s;
        }
        .close-btn:hover {
          color: #fff;
        }
        .terminal-body {
          flex: 1;
          padding: 20px;
          overflow-y: auto;
          font-family: var(--font-mono);
          font-size: 13px;
          color: #e2e8f0;
          line-height: 1.5;
          white-space: pre-wrap;
          background: #07080f;
        }
        .log-line {
          margin-bottom: 4px;
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
        .gap-3 {
          gap: 12px;
        }
        .text-blue-400 {
          color: #60a5fa;
        }
      `}</style>
    </div>
  );
}
