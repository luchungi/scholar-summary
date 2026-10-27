import { useEffect, useRef, useState } from 'react';
import { Power, X } from 'lucide-react';

interface ShutdownTerminalProps {
  onClose: () => void;
  onBackendStopped: () => void;
}

type Status = 'tearing-down' | 'killing' | 'stopped' | 'failed';

const STATUS_LABEL: Record<Status, string> = {
  'tearing-down': 'Unloading / Stopping...',
  killing: 'Stopping Backend...',
  stopped: 'Backend Stopped',
  failed: 'Failed',
};

export default function ShutdownTerminal({ onClose, onBackendStopped }: ShutdownTerminalProps) {
  const [logs, setLogs] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>('tearing-down');
  const bottomRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';
    setLogs(['[+] Starting shutdown sequence...']);
    setStatus('tearing-down');

    // Phase 2: kill the backend process once the teardown stream has run to completion
    // (decision 0011). Teardown warnings never block the kill.
    const killBackend = async () => {
      setStatus('killing');
      setLogs((prev) => [...prev, '\n[+] Stopping backend server...']);
      try {
        const res = await fetch(`${API_URL}/api/shutdown`, { method: 'POST' });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (data.interrupted_run_id != null) {
          setLogs((prev) => [...prev, `[!] Run ${data.interrupted_run_id} was in progress and has been marked failed.`]);
        }
        setLogs((prev) => [...prev, '[+] Backend stopped — you can close this browser tab.']);
        setStatus('stopped');
        onBackendStopped();
      } catch (err: any) {
        setLogs((prev) => [...prev, `\n[-] Failed to stop backend: ${err.message || err}`]);
        setStatus('failed');
      }
    };

    // Phase 1: unload the resident model and stop the active LLM server
    const es = new EventSource(`${API_URL}/api/shutdown/teardown/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = event.data;
      if (data === '[SUCCESS]') {
        es.close();
        killBackend();
      } else if (data.startsWith('[ERROR]')) {
        setLogs((prev) => [...prev, `\n[-] Error: ${data.substring(7)}`]);
        setStatus('failed');
        es.close();
      } else {
        const line = data.trim();
        if (line) setLogs((prev) => [...prev, line]);
      }
    };

    es.onerror = () => {
      es.close();
      setLogs((prev) => [...prev, '\n[-] Lost connection to the backend during teardown.']);
      setStatus('failed');
    };

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const isBusy = status === 'tearing-down' || status === 'killing';

  return (
    <div className="shutdown-terminal-overlay">
      <div className="shutdown-terminal-container glass-panel fade-in">
        <div className="shutdown-terminal-header">
          <div className="flex items-center gap-2">
            <Power size={18} className={isBusy ? 'text-rose-400 animate-pulse' : 'text-green-400'} />
            <span className="shutdown-terminal-title">Backend Shutdown Log</span>
          </div>
          <div className="flex items-center gap-3">
            <span className={`shutdown-status-badge ${status}`}>{STATUS_LABEL[status]}</span>
            <button onClick={onClose} className="shutdown-close-btn" disabled={isBusy}>
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="shutdown-terminal-body scroller">
          {logs.map((log, idx) => (
            <div key={idx} className={`shutdown-log-line ${log.includes('[WARNING]') ? 'warning' : ''}`}>
              {log}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      <style>{`
        .shutdown-terminal-overlay {
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
        .shutdown-terminal-container {
          width: 100%;
          max-width: 800px;
          height: 450px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: #06070d !important;
          border: 1px solid rgba(244, 63, 94, 0.3) !important;
          box-shadow: 0 20px 50px rgba(0,0,0,0.6) !important;
        }
        .shutdown-terminal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 14px 20px;
          background: #0f111e;
          border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .shutdown-terminal-title {
          font-family: var(--font-display);
          font-weight: 500;
          font-size: 14px;
          color: #fb7185;
        }
        .shutdown-status-badge {
          font-size: 11px;
          padding: 3px 8px;
          border-radius: 4px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-weight: 600;
        }
        .shutdown-status-badge.tearing-down,
        .shutdown-status-badge.killing {
          background: rgba(244, 63, 94, 0.15);
          color: #fb7185;
          border: 1px solid rgba(244, 63, 94, 0.3);
        }
        .shutdown-status-badge.stopped {
          background: rgba(16, 185, 129, 0.15);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .shutdown-status-badge.failed {
          background: rgba(250, 204, 21, 0.15);
          color: #facc15;
          border: 1px solid rgba(250, 204, 21, 0.3);
        }
        .shutdown-close-btn {
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          transition: color 0.2s;
        }
        .shutdown-close-btn:disabled {
          opacity: 0.3;
          cursor: not-allowed;
        }
        .shutdown-close-btn:hover:not(:disabled) {
          color: #fff;
        }
        .shutdown-terminal-body {
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
        .shutdown-log-line {
          margin-bottom: 4px;
        }
        .shutdown-log-line.warning {
          color: #facc15;
        }
      `}</style>
    </div>
  );
}
