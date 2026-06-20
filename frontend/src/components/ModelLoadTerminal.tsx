import React, { useEffect, useRef, useState } from 'react';
import { Terminal, X } from 'lucide-react';

interface ModelLoadTerminalProps {
  modelKey: string;
  onClose: () => void;
  onFinished: () => void;
}

const isProgressLine = (line: string): boolean => {
  if (/%/.test(line)) return true;
  if (/ \d+(\.\d+)?\s*(GB|MB|KB|B)\s*\/\s*\d+(\.\d+)?\s*(GB|MB|KB|B)/i.test(line)) return true;
  if (/\[[\s=#\->\.\*]{4,}\]/.test(line)) return true;
  if (/(\d+(\.\d+)?\s*(MB|KB)\/s)/i.test(line)) return true;
  if (/downloading|loading/i.test(line) && /\d/.test(line)) return true;
  return false;
};

export default function ModelLoadTerminal({ modelKey, onClose, onFinished }: ModelLoadTerminalProps) {
  const [logs, setLogs] = useState<string[]>([]);
  const [status, setStatus] = useState<'running' | 'completed' | 'failed'>('running');
  const bottomRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setLogs([`[+] Starting load sequence for: ${modelKey}...`]);
    setStatus('running');

    const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';
    const es = new EventSource(`${API_URL}/api/models/load/stream?model_key=${encodeURIComponent(modelKey)}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = event.data;
      if (data === '[SUCCESS]') {
        setLogs((prev) => [...prev, '\n[+] Model loaded successfully. Downstream processes configured.']);
        setStatus('completed');
        onFinished();
        es.close();
      } else if (data.startsWith('[ERROR]')) {
        setLogs((prev) => [...prev, `\n[-] Error: ${data.substring(7)}`]);
        setStatus('failed');
        es.close();
      } else {
        const parts = data.split(/\r/);
        const lastPart = parts[parts.length - 1].trim();
        if (!lastPart) return;

        setLogs((prev) => {
          if (prev.length === 0) {
            return [lastPart];
          }

          const lastIndex = prev.length - 1;
          const lastLine = prev[lastIndex];

          if (isProgressLine(lastPart) && isProgressLine(lastLine)) {
            const updated = [...prev];
            updated[lastIndex] = lastPart;
            return updated;
          } else {
            return [...prev, lastPart];
          }
        });
      }
    };

    es.onerror = (err) => {
      console.error('SSE Error:', err);
      setLogs((prev) => [...prev, '\n[-] Connection lost or LM Studio took too long. Check server.']);
      setStatus('failed');
      es.close();
    };

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [modelKey]);

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  return (
    <div className="model-terminal-overlay">
      <div className="model-terminal-container glass-panel fade-in">
        <div className="terminal-header">
          <div className="flex items-center gap-2">
            <Terminal size={18} className={status === 'running' ? 'text-purple-400 animate-pulse' : 'text-green-400'} />
            <span className="terminal-title">LM Studio Load Log</span>
          </div>
          <div className="flex items-center gap-3">
            <span className={`status-badge ${status}`}>
              {status === 'running' && 'Loading Model...'}
              {status === 'completed' && 'Loaded'}
              {status === 'failed' && 'Failed'}
            </span>
            <button onClick={onClose} className="close-btn" disabled={status === 'running'}>
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
        .model-terminal-overlay {
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
          z-index: 1100;
          padding: 24px;
        }
        .model-terminal-container {
          width: 100%;
          max-width: 800px;
          height: 450px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: #06070d !important;
          border: 1px solid rgba(139, 92, 246, 0.3) !important;
          box-shadow: 0 20px 50px rgba(0,0,0,0.6) !important;
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
          color: #c084fc;
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
          background: rgba(167, 139, 250, 0.15);
          color: #c084fc;
          border: 1px solid rgba(167, 139, 250, 0.3);
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
        .close-btn:disabled {
          opacity: 0.3;
          cursor: not-allowed;
        }
        .close-btn:hover:not(:disabled) {
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
      `}</style>
    </div>
  );
}
