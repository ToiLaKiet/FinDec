import React from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  Gauge,
  PauseCircle,
  Play,
  RefreshCw,
  Sparkles,
  Wand2,
} from "lucide-react";
import "./styles.css";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.port === "8000" ? "" : "http://127.0.0.1:8000");

const STOCKS = ["FPT", "GAS", "GMD", "HPG", "MBB", "MWG", "PNJ", "VCB", "VHM", "VNM"];

const ACTION_META = {
  Long: {
    label: "Long",
    tone: "long",
    icon: ArrowUpRight,
    title: "Mở vị thế mua",
  },
  Short: {
    label: "Short",
    tone: "short",
    icon: ArrowDownRight,
    title: "Mở vị thế bán",
  },
  Neutral: {
    label: "Neutral",
    tone: "neutral",
    icon: PauseCircle,
    title: "Đứng ngoài quan sát",
  },
};

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }

  return Number(value).toLocaleString("vi-VN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }

  return `${formatNumber(Number(value) * 100, 2)}%`;
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }

  return new Date(value).toLocaleString("vi-VN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function App() {
  const [ticker, setTicker] = React.useState("FPT");
  const [source, setSource] = React.useState("VCI");
  const [daysBack, setDaysBack] = React.useState(45);
  const [previousAction, setPreviousAction] = React.useState(0);
  const [result, setResult] = React.useState(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  const runDemo = async () => {
    setIsLoading(true);
    setError("");

    const params = new URLSearchParams({
      source,
      days_back: String(daysBack),
      previous_action: String(previousAction),
      interval: "1D",
    });

    try {
      const response = await fetch(`${API_BASE}/api/demo/decision/${ticker}?${params}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Không thể lấy tín hiệu giao dịch.");
      }

      setResult(data);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsLoading(false);
    }
  };

  React.useEffect(() => {
    runDemo();
  }, []);

  const action = result?.action || "Neutral";
  const actionMeta = ACTION_META[action] || ACTION_META.Neutral;
  const ActionIcon = actionMeta.icon;
  const confidence = result?.confidence ?? 0;
  const meterWidth = `${Math.round(confidence * 100)}%`;

  return (
    <main className="app-shell">
      <section className="command-bar">
        <div className="brand-block">
          <div className="brand-mark">
            <Bot size={24} />
          </div>
          <div>
            <p className="eyebrow">SE365 RL Trading</p>
            <h1>Demo ra quyết định giao dịch</h1>
          </div>
        </div>

        <form
          className="controls"
          onSubmit={(event) => {
            event.preventDefault();
            runDemo();
          }}
        >
          <label>
            <span>Mã cổ phiếu</span>
            <select value={ticker} onChange={(event) => setTicker(event.target.value)}>
              {STOCKS.map((stock) => (
                <option key={stock} value={stock}>
                  {stock}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Nguồn</span>
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              <option value="VCI">VCI</option>
              <option value="TCBS">TCBS</option>
            </select>
          </label>

          <label>
            <span>Ngày crawl</span>
            <input
              type="number"
              min="25"
              max="365"
              value={daysBack}
              onChange={(event) => setDaysBack(Number(event.target.value))}
            />
          </label>

          <label>
            <span>Action trước</span>
            <select
              value={previousAction}
              onChange={(event) => setPreviousAction(Number(event.target.value))}
            >
              <option value={0}>Neutral</option>
              <option value={1}>Long</option>
              <option value={-1}>Short</option>
            </select>
          </label>

          <button type="submit" disabled={isLoading}>
            {isLoading ? <RefreshCw className="spin" size={18} /> : <Play size={18} />}
            <span>{isLoading ? "Đang chạy" : "Chạy demo"}</span>
          </button>
        </form>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <section className="dashboard-grid">
        <article className={`decision-surface ${actionMeta.tone}`}>
          <div className="surface-topline">
            <div>
              <p className="eyebrow">Decision</p>
              <h2>{result ? `${result.ticker}: ${actionMeta.title}` : "Đang chờ tín hiệu"}</h2>
            </div>
            <div className="action-token">
              <ActionIcon size={20} />
              <span>{actionMeta.label}</span>
            </div>
          </div>

          <div className="decision-body">
            <div className="radial-score" style={{ "--score-pct": meterWidth }}>
              <div className="radial-inner">
                <span>{result ? `${Math.round(confidence * 100)}%` : "--"}</span>
                <small>confidence</small>
              </div>
            </div>

            <div className="decision-copy">
              <p>{result?.rationale || "Chọn mã cổ phiếu và chạy demo để lấy quyết định mới."}</p>
              <div className="meter">
                <div className="meter-fill" style={{ width: meterWidth }} />
              </div>
              <p className="model-note">
                {result?.model_note || "Luồng demo dùng OHLCV mới nhất và bỏ qua checkpoint đã train."}
              </p>
            </div>
          </div>
        </article>

        <article className="status-panel">
          <PanelHeader icon={Activity} eyebrow="Pipeline" title="Luồng xử lý" />
          <div className="pipeline-list">
            {(result?.pipeline || defaultPipeline()).map((item, index) => (
              <div className="pipeline-item" key={`${item.step}-${index}`}>
                <div className="pipeline-icon">
                  {pipelineIcon(index)}
                </div>
                <div>
                  <strong>{item.step}</strong>
                  <span>{item.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="metrics-grid">
        <MetricCard icon={Gauge} label="Latest close" value={formatNumber(result?.latest_close, 2)} />
        <MetricCard icon={Clock3} label="Latest date" value={formatDateTime(result?.latest_datetime)} compact />
        <MetricCard icon={Database} label="Rows crawled" value={result?.rows ?? "-"} />
        <MetricCard icon={Wand2} label="Observation dim" value={result?.observation_dim ?? "-"} />
      </section>

      <section className="lower-grid">
        <article className="feature-panel">
          <PanelHeader icon={Sparkles} eyebrow="Feature Engineer" title="Tóm tắt tín hiệu" />
          <FeatureTiles summary={result?.feature_summary} score={result?.score} />
        </article>

        <article className="table-panel">
          <PanelHeader icon={BarChart3} eyebrow="Recent OHLCV" title="Dữ liệu mới nhất" />
          <RecentTable rows={result?.recent_rows || []} />
        </article>
      </section>
    </main>
  );
}

function PanelHeader({ icon: Icon, eyebrow, title }) {
  return (
    <div className="panel-header">
      <div className="icon-chip">
        <Icon size={18} />
      </div>
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, compact = false }) {
  return (
    <article className={`metric-card ${compact ? "compact" : ""}`}>
      <Icon size={19} />
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function FeatureTiles({ summary, score }) {
  const rows = [
    ["1-period return", formatPercent(summary?.one_period_return)],
    ["Momentum 5", formatPercent(summary?.momentum_5)],
    ["Momentum 20", formatPercent(summary?.momentum_20)],
    ["Volatility 20", formatPercent(summary?.volatility_20)],
    ["Latest diff", formatNumber(summary?.latest_diff, 3)],
    ["Rule score", formatNumber(score, 2)],
  ];

  return (
    <div className="feature-tiles">
      {rows.map(([label, value]) => (
        <div key={label} className="feature-tile">
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function RecentTable({ rows }) {
  if (!rows.length) {
    return <div className="empty-state">Chưa có dữ liệu OHLCV.</div>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Open</th>
            <th>Close</th>
            <th>Diff</th>
            <th>Close norm</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.datetime}>
              <td>{new Date(row.datetime).toLocaleDateString("vi-VN")}</td>
              <td>{formatNumber(row.Open, 2)}</td>
              <td>{formatNumber(row.Close, 2)}</td>
              <td className={Number(row.diff) >= 0 ? "pos" : "neg"}>{formatNumber(row.diff, 3)}</td>
              <td>{formatNumber(row.close_norm, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function defaultPipeline() {
  return [
    { step: "Crawl OHLCV", detail: "Đang chờ request từ người dùng." },
    { step: "Feature Engineer", detail: "Sẽ tạo diff, time features và normalization." },
    { step: "Skip Model", detail: "Checkpoint RL được bỏ qua trong demo này." },
    { step: "Decision", detail: "Rule demo trả về Long, Neutral hoặc Short." },
  ];
}

function pipelineIcon(index) {
  const icons = [Database, Sparkles, Bot, CheckCircle2];
  const Icon = icons[index] || CheckCircle2;
  return <Icon size={17} />;
}

createRoot(document.getElementById("root")).render(<App />);
