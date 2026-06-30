import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  FileText,
  UserSquare2,
  AlertOctagon,
  Terminal,
  Compass,
  Cpu,
  Power
} from 'lucide-react';

// Component Imports
import Dashboard from './components/Dashboard';
import ReportsFeed from './components/ReportsFeed';
import ReportDetail from './components/ReportDetail';
import InterestTab from './components/InterestTab';
import FailedPapers from './components/FailedPapers';
import SyncPreview from './components/SyncPreview';
import LogsTerminal from './components/LogsTerminal';
import ModelLoadTerminal from './components/ModelLoadTerminal';

interface LinkItem {
  title: string;
  url: string;
}

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');

  // Gmail Sync Preview states
  const [showPreview, setShowPreview] = useState(false);
  const [previewAlerts, setPreviewAlerts] = useState<any[]>([]);

  // Logs Terminal Overlay states
  const [showLogs, setShowLogs] = useState(false);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);

  // Deep Navigation: Selected Report ID (when in 'reports' or clicking read more)
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);

  const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

  // Model Manager state
  const [models, setModels] = useState<{ key: string; size: string; loaded: boolean }[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [loadingModels, setLoadingModels] = useState(false);
  const [switchingModel, setSwitchingModel] = useState(false);
  const [showModelLoadTerminal, setShowModelLoadTerminal] = useState(false);
  const [modelToLoad, setModelToLoad] = useState('');
  const [serverStatus, setServerStatus] = useState<'ON' | 'OFF' | 'loading' | 'error'>('loading');

  const fetchServerStatus = async (skipIfLoading = false) => {
    if (skipIfLoading && serverStatus === 'loading') return;
    try {
      const res = await fetch(`${API_URL}/api/server/status`);
      const data = await res.json();
      setServerStatus(data.status);
      return data.status;
    } catch (e) {
      console.error('Error fetching server status:', e);
      setServerStatus('error');
      return 'error';
    }
  };

  const fetchModels = async () => {
    setLoadingModels(true);
    try {
      const res = await fetch(`${API_URL}/api/models`);
      const data = await res.json();
      setModels(data);
      const loaded = data.find((m: any) => m.loaded);
      if (loaded) {
        setSelectedModel(loaded.key);
      } else {
        setSelectedModel('none');
      }
    } catch (e) {
      console.error('Error fetching models:', e);
    } finally {
      setLoadingModels(false);
    }
  };

  useEffect(() => {
    const init = async () => {
      const status = await fetchServerStatus();
      if (status === 'ON') {
        fetchModels();
      } else {
        setModels([]);
        setSelectedModel('none');
      }
    };
    init();

    const interval = setInterval(() => fetchServerStatus(true), 5000);
    return () => clearInterval(interval);
  }, []);

  const handleToggleServer = async () => {
    const isCurrentlyOn = serverStatus === 'ON';
    setServerStatus('loading');
    try {
      const endpoint = isCurrentlyOn ? '/api/server/stop' : '/api/server/start';
      const res = await fetch(`${API_URL}${endpoint}`, { method: 'POST' });
      if (res.ok) {
        await new Promise((r) => setTimeout(r, 1000));
        const status = await fetchServerStatus();
        if (status === 'ON') {
          fetchModels();
        } else {
          setModels([]);
          setSelectedModel('none');
        }
      } else {
        alert(`Failed to ${isCurrentlyOn ? 'stop' : 'start'} server.`);
        fetchServerStatus();
      }
    } catch (e) {
      console.error(e);
      alert(`Error toggling server: ${e}`);
      fetchServerStatus();
    }
  };

  const handleLoadModel = () => {
    if (!selectedModel) return;
    
    if (selectedModel === 'none') {
      const currentLoadedModel = models.find(m => m.loaded);
      if (currentLoadedModel) {
        setModelToLoad('none');
        setShowModelLoadTerminal(true);
      }
      return;
    }

    const currentLoadedModel = models.find(m => m.loaded);
    if (currentLoadedModel && currentLoadedModel.key === selectedModel) {
      alert(`Model "${selectedModel}" is already loaded.`);
      return;
    }
    setModelToLoad(selectedModel);
    setShowModelLoadTerminal(true);
  };

  const handleModelLoadFinished = () => {
    fetchModels();
  };

  const handleShutdownBackend = async () => {
    if (confirm("Are you sure you want to shut down the backend server? You will need to restart it from the terminal to use the app again.")) {
      try {
        const res = await fetch(`${API_URL}/api/shutdown`, { method: 'POST' });
        if (res.ok) {
          alert("Backend server shutdown has been initiated. You can now close this browser window/tab.");
        } else {
          throw new Error(await res.text());
        }
      } catch (err: any) {
        alert(`Failed to shut down backend: ${err.message || err}`);
      }
    }
  };

  const handleStartSync = async (papers: LinkItem[], totalEmails: number) => {
    setShowPreview(false);

    try {
      // Trigger run API
      const res = await fetch(`${API_URL}/api/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          papers,
          emails_fetched: totalEmails
        })
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }

      const data = await res.json();

      // Open the logs panel for this run
      setActiveRunId(data.run_id);
      setShowLogs(true);
    } catch (e: any) {
      alert(`Error starting execution run: ${e.message || e}`);
    }
  };

  const handleLogsFinished = () => {
    // This hook runs when the SSE connection completes successfully
    console.log(`Run ${activeRunId} finished processing.`);
  };

  const navigateToTab = (tabName: string) => {
    setSelectedReportId(null);
    setActiveTab(tabName);
  };

  return (
    <div className="app-shell">
      {/* Background Glowing Effect */}
      <div className="glow-bg">
        <div className="glow-orb-1"></div>
        <div className="glow-orb-2"></div>
      </div>

      {/* Sidebar Navigation */}
      <aside className="sidebar glass-panel">
        <div className="logo-section">
          <Cpu className="logo-icon animate-pulse" size={24} />
          <div className="logo-text">
            <h2>ScholarAgent</h2>
            <span className="logo-badge">v1.0 Local</span>
          </div>
        </div>

        <nav className="nav-menu">
          <button
            className={`nav-item ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => navigateToTab('dashboard')}
          >
            <LayoutDashboard size={18} />
            Dashboard
          </button>

          <button
            className={`nav-item ${activeTab === 'reports' ? 'active' : ''}`}
            onClick={() => navigateToTab('reports')}
          >
            <FileText size={18} />
            Literature Reports
          </button>

          <button
            className={`nav-item ${activeTab === 'interests' ? 'active' : ''}`}
            onClick={() => navigateToTab('interests')}
          >
            <UserSquare2 size={18} />
            Research Interests
          </button>

          <button
            className={`nav-item ${activeTab === 'failed' ? 'active' : ''}`}
            onClick={() => navigateToTab('failed')}
          >
            <AlertOctagon size={18} />
            Extraction Retries
          </button>
        </nav>

        <div className="model-manager-panel">
          <div className="model-manager-title">
            <Cpu size={14} className="text-purple-400" />
            <span>LM Studio Model</span>
          </div>

          <div className="server-status-container">
            <div className="server-status-info">
              <span className="server-status-label">Server:</span>
              <div className="flex items-center gap-1.5" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <div className={`status-indicator-dot ${serverStatus.toLowerCase()}`}></div>
                <span className={`server-status-val ${serverStatus.toLowerCase()}`}>
                  {serverStatus}
                </span>
              </div>
            </div>
            <button
              onClick={handleToggleServer}
              disabled={serverStatus === 'loading'}
              className={`btn btn-server-toggle ${serverStatus === 'ON' ? 'stop' : 'start'}`}
            >
              {serverStatus === 'loading' ? 'Updating...' : (serverStatus === 'ON' ? 'Stop Server' : 'Start Server')}
            </button>
          </div>

          {serverStatus === 'ON' ? (
            loadingModels ? (
              <div className="model-loading-text">Loading model list...</div>
            ) : models.length === 0 ? (
              <div className="model-loading-text">No models found</div>
            ) : (
              <div className="model-select-container">
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="model-select"
                  disabled={showModelLoadTerminal}
                >
                  <option value="none">None (No Model Loaded)</option>
                  {models.map((model) => (
                    <option key={model.key} value={model.key}>
                      {model.key} ({model.size}){model.loaded ? ' (Loaded)' : ''}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleLoadModel}
                  className="btn btn-secondary btn-load-model"
                  disabled={showModelLoadTerminal || !selectedModel || (selectedModel === 'none' && !models.some(m => m.loaded))}
                >
                  {selectedModel === 'none' ? 'Unload Model' : (showModelLoadTerminal ? 'Loading...' : 'Load Model')}
                </button>
              </div>
            )
          ) : (
            <div className="server-offline-msg">
              Start the LM Studio server to manage and load models.
            </div>
          )}
        </div>

        <div className="sidebar-footer">
          <div className="system-indicator">
            <div className={`indicator-dot ${serverStatus === 'ON' ? 'online' : 'offline'}`}></div>
            <span>LLM Server {serverStatus === 'ON' ? 'Online' : 'Offline'}</span>
          </div>
          <button
            onClick={handleShutdownBackend}
            className="btn btn-shutdown-backend"
            title="Shut down backend server"
          >
            <Power size={12} />
            Shut Down Backend
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-viewport">
        <div className="viewport-inner">
          {/* Tab Routing Rendering */}
          {activeTab === 'dashboard' && (
            <Dashboard
              onStartSync={handleStartSync}
              onOpenPreview={(alerts) => {
                setPreviewAlerts(alerts);
                setShowPreview(true);
              }}
              onSelectTab={navigateToTab}
              onUploadStarted={(runId) => {
                setActiveRunId(runId);
                setShowLogs(true);
              }}
            />
          )}

          {activeTab === 'reports' && (
            selectedReportId ? (
              <ReportDetail
                reportId={selectedReportId}
                onBack={() => setSelectedReportId(null)}
              />
            ) : (
              <ReportsFeed
                onSelectReport={(id) => setSelectedReportId(id)}
              />
            )
          )}

          {activeTab === 'interests' && <InterestTab />}

          {activeTab === 'failed' && (
            <FailedPapers
              onStartSync={handleStartSync}
            />
          )}
        </div>
      </main>

      {/* Modal/Overlay Components */}
      {showPreview && (
        <SyncPreview
          alerts={previewAlerts}
          onClose={() => setShowPreview(false)}
          onStartSync={handleStartSync}
        />
      )}

      {showLogs && activeRunId !== null && (
        <LogsTerminal
          runId={activeRunId}
          onClose={() => setShowLogs(false)}
          onFinished={handleLogsFinished}
        />
      )}

      {showModelLoadTerminal && modelToLoad && (
        <ModelLoadTerminal
          modelKey={modelToLoad}
          onClose={() => setShowModelLoadTerminal(false)}
          onFinished={handleModelLoadFinished}
        />
      )}

      <style>{`
        .app-shell {
          display: flex;
          height: 100vh;
          width: 100vw;
          overflow: hidden;
          position: relative;
        }
        .sidebar {
          width: var(--sidebar-width);
          border-radius: 0 !important;
          border-left: none !important;
          border-top: none !important;
          border-bottom: none !important;
          display: flex;
          flex-direction: column;
          padding: 24px 16px;
          flex-shrink: 0;
          z-index: 10;
        }
        .logo-section {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 36px;
          padding-left: 8px;
        }
        .logo-icon {
          color: var(--accent-purple);
        }
        .logo-text h2 {
          font-size: 18px;
          font-family: var(--font-display);
          color: #fff;
          font-weight: 700;
          line-height: 1.1;
        }
        .logo-badge {
          font-size: 10px;
          color: var(--text-dark);
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        .nav-menu {
          display: flex;
          flex-direction: column;
          gap: 8px;
          flex: 1;
        }
        .nav-item {
          display: flex;
          align-items: center;
          gap: 12px;
          font-family: var(--font-display);
          font-size: 14px;
          font-weight: 500;
          color: var(--text-muted);
          background: none;
          border: none;
          padding: 12px 16px;
          border-radius: 10px;
          cursor: pointer;
          text-align: left;
          width: 100%;
          transition: all 0.2s ease;
        }
        .nav-item:hover {
          color: #fff;
          background: rgba(255, 255, 255, 0.03);
          transform: translateX(2px);
        }
        .nav-item.active {
          color: #fff;
          background: rgba(124, 58, 237, 0.1);
          border: 1px solid rgba(124, 58, 237, 0.2);
          box-shadow: 0 4px 20px rgba(124, 58, 237, 0.1);
        }
        .model-manager-panel {
          margin-top: 20px;
          padding: 16px 8px;
          border-top: 1px solid var(--border-color);
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .model-manager-title {
          display: flex;
          align-items: center;
          gap: 6px;
          font-family: var(--font-display);
          font-size: 12px;
          font-weight: 500;
          color: #fff;
        }
        .model-loading-text {
          font-size: 11px;
          color: var(--text-dark);
          font-style: italic;
        }
        .model-select-container {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .model-select {
          width: 100%;
          font-size: 11px;
          padding: 6px 10px;
          background: rgba(0, 0, 0, 0.2);
          border: 1px solid var(--border-color);
          border-radius: 6px;
          color: var(--text-main);
          outline: none;
        }
        .model-select option {
          background: var(--bg-dark);
          color: var(--text-main);
        }
        .btn-load-model {
          font-size: 11px;
          padding: 6px 12px;
          width: 100%;
          justify-content: center;
        }
        .sidebar-footer {
          margin-top: auto;
          padding-top: 16px;
          border-top: 1px solid var(--border-color);
        }
        .btn-shutdown-backend {
          margin-top: 12px;
          font-size: 11px;
          padding: 8px 12px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.03em;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s ease;
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          background: rgba(239, 68, 68, 0.1);
          color: #ef4444;
          border: 1px solid rgba(239, 68, 68, 0.2);
        }
        .btn-shutdown-backend:hover {
          background: rgba(239, 68, 68, 0.25);
          border-color: rgba(239, 68, 68, 0.5);
          color: #fff;
          box-shadow: 0 0 12px rgba(239, 68, 68, 0.2);
        }
        .system-indicator {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 11px;
          color: var(--text-dark);
        }
        .indicator-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
        }
        .indicator-dot.online {
          background: var(--accent-green);
          box-shadow: 0 0 8px var(--accent-green);
        }
        .indicator-dot.offline {
          background: var(--text-dark);
        }
        .server-status-container {
          display: flex;
          flex-direction: column;
          gap: 8px;
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border-color);
          border-radius: 8px;
          padding: 10px;
          margin-bottom: 8px;
        }
        .server-status-info {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 11px;
        }
        .server-status-label {
          color: var(--text-muted);
          font-weight: 500;
        }
        .server-status-val {
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          font-size: 11px;
        }
        .server-status-val.on {
          color: var(--accent-green);
        }
        .server-status-val.off {
          color: var(--text-dark);
        }
        .server-status-val.loading {
          color: #c084fc;
        }
        .server-status-val.error {
          color: var(--accent-red);
        }
        .status-indicator-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
        }
        .status-indicator-dot.on {
          background: var(--accent-green);
          box-shadow: 0 0 8px var(--accent-green);
        }
        .status-indicator-dot.off {
          background: var(--text-dark);
        }
        .status-indicator-dot.loading {
          background: #c084fc;
          animation: pulse 1.5s infinite;
        }
        .status-indicator-dot.error {
          background: var(--accent-red);
          box-shadow: 0 0 8px var(--accent-red);
        }
        .btn-server-toggle {
          font-size: 10px;
          padding: 6px 12px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.03em;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.2s ease;
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 1px solid transparent;
        }
        .btn-server-toggle.start {
          background: rgba(16, 185, 129, 0.1);
          color: #34d399;
          border-color: rgba(16, 185, 129, 0.2);
        }
        .btn-server-toggle.start:hover:not(:disabled) {
          background: rgba(16, 185, 129, 0.2);
          border-color: rgba(16, 185, 129, 0.4);
          color: #fff;
        }
        .btn-server-toggle.stop {
          background: rgba(244, 63, 94, 0.1);
          color: #fb7185;
          border-color: rgba(244, 63, 94, 0.2);
        }
        .btn-server-toggle.stop:hover:not(:disabled) {
          background: rgba(244, 63, 94, 0.2);
          border-color: rgba(244, 63, 94, 0.4);
          color: #fff;
        }
        .btn-server-toggle:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .server-offline-msg {
          font-size: 11px;
          color: var(--text-dark);
          line-height: 1.4;
          font-style: italic;
          padding: 6px 8px;
          border-left: 2px solid var(--border-color);
          margin-top: 4px;
        }
        .main-viewport {
          flex: 1;
          height: 100vh;
          overflow: hidden;
          position: relative;
        }
        .viewport-inner {
          height: 100%;
          width: 100%;
          max-width: 1200px;
          margin: 0 auto;
          padding: 40px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
      `}</style>
    </div>
  );
}
