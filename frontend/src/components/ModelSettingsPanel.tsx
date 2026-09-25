import { useEffect, useState } from 'react';
import { SlidersHorizontal } from 'lucide-react';

interface ModelSettingsPanelProps {
  modelKey: string;
}

interface CreatorGuidance {
  temperature?: number;
  top_p?: number;
  top_k?: number;
  reasoning?: boolean;
  source?: string;
}

interface ModelSettings {
  model_key: string;
  guidance: CreatorGuidance;
  overrides: { temperature?: number; thinking?: boolean };
  effective: {
    temperature: number;
    temperature_source: 'override' | 'creator' | 'env';
    thinking: boolean;
    thinking_source: 'override' | 'env';
  };
}

const TEMPERATURE_SOURCE_LABEL: Record<string, string> = {
  override: 'your override',
  creator: 'creator recommendation',
  env: '.env default',
};

// Settings for the full paper analysis only; short calls always run with thinking off
// (docs/agent/decisions/0002, 0004).
export default function ModelSettingsPanel({ modelKey }: ModelSettingsPanelProps) {
  const API_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [temperatureInput, setTemperatureInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const applySettings = (data: ModelSettings) => {
    setSettings(data);
    setTemperatureInput(String(data.effective.temperature));
  };

  useEffect(() => {
    setSettings(null);
    setError('');
    fetch(`${API_URL}/api/model-settings?model_key=${encodeURIComponent(modelKey)}`)
      .then((res) => res.json())
      .then(applySettings)
      .catch((e) => setError(`Could not load settings: ${e}`));
  }, [modelKey]);

  const save = async (temperature: number | null, thinking: boolean | null) => {
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/model-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_key: modelKey, temperature, thinking }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      applySettings(await res.json());
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  if (error && !settings) return <div className="model-settings-error">{error}</div>;
  if (!settings) return <div className="model-loading-text">Loading report settings...</div>;

  const { guidance, overrides, effective } = settings;
  const currentTempOverride = overrides.temperature ?? null;
  const currentThinkingOverride = overrides.thinking ?? null;
  const hasGuidance = guidance.temperature !== undefined || guidance.top_p !== undefined || guidance.top_k !== undefined;

  const commitTemperature = () => {
    const value = parseFloat(temperatureInput);
    if (Number.isNaN(value) || value === effective.temperature) {
      setTemperatureInput(String(effective.temperature));
      return;
    }
    save(value, currentThinkingOverride);
  };

  return (
    <div className="model-settings">
      <div className="model-settings-title">
        <SlidersHorizontal size={12} />
        <span>Paper analysis settings</span>
      </div>

      <label className="model-settings-row">
        <span>
          Thinking
          <span className={`model-settings-badge ${guidance.reasoning ? 'supported' : 'unknown'}`}>
            {guidance.reasoning ? 'supports thinking' : 'unknown'}
          </span>
        </span>
        <input
          type="checkbox"
          checked={effective.thinking}
          disabled={saving}
          onChange={(e) => save(currentTempOverride, e.target.checked)}
        />
      </label>

      <label className="model-settings-row">
        <span>Temperature</span>
        <input
          type="number"
          className="model-settings-temp"
          min={0}
          max={2}
          step={0.05}
          value={temperatureInput}
          disabled={saving}
          onChange={(e) => setTemperatureInput(e.target.value)}
          onBlur={commitTemperature}
          onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
        />
      </label>
      <div className="model-settings-hint">
        Using {TEMPERATURE_SOURCE_LABEL[effective.temperature_source]}
        {effective.thinking_source === 'override' ? '; thinking set by you' : '; thinking from .env default'}
      </div>

      {hasGuidance ? (
        <div className="model-settings-guidance">
          Creator recommends: temp {guidance.temperature ?? '—'} · top_p {guidance.top_p ?? '—'} · top_k{' '}
          {guidance.top_k ?? '—'}
          <span className="model-settings-source"> ({guidance.source})</span>
        </div>
      ) : (
        <div className="model-settings-guidance">No creator recommendation found for this model.</div>
      )}

      {(currentTempOverride !== null || currentThinkingOverride !== null) && (
        <button className="btn btn-secondary model-settings-reset" disabled={saving} onClick={() => save(null, null)}>
          Reset to recommended
        </button>
      )}
      {error && <div className="model-settings-error">{error}</div>}

      <style>{`
        .model-settings {
          display: flex;
          flex-direction: column;
          gap: 6px;
          padding: 10px;
          border: 1px solid var(--border-color);
          border-radius: 8px;
          background: rgba(0, 0, 0, 0.15);
        }
        .model-settings-title {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          font-weight: 500;
          color: var(--text-main);
        }
        .model-settings-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          font-size: 11px;
          color: var(--text-muted);
        }
        .model-settings-badge {
          margin-left: 6px;
          font-size: 9px;
          padding: 1px 5px;
          border-radius: 4px;
          border: 1px solid var(--border-color);
        }
        .model-settings-badge.supported {
          color: var(--accent-green);
          border-color: rgba(16, 185, 129, 0.3);
        }
        .model-settings-badge.unknown {
          color: var(--text-dark);
        }
        .model-settings-temp {
          width: 64px;
          font-size: 11px;
          padding: 3px 6px;
          background: rgba(0, 0, 0, 0.2);
          border: 1px solid var(--border-color);
          border-radius: 4px;
          color: var(--text-main);
          outline: none;
        }
        .model-settings-hint,
        .model-settings-guidance {
          font-size: 10px;
          color: var(--text-dark);
          line-height: 1.4;
        }
        .model-settings-source {
          font-family: var(--font-mono);
        }
        .model-settings-reset {
          font-size: 10px;
          padding: 4px 8px;
          justify-content: center;
        }
        .model-settings-error {
          font-size: 10px;
          color: var(--accent-red);
        }
      `}</style>
    </div>
  );
}
