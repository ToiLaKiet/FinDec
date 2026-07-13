from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from stable_baselines3 import A2C, DQN, PPO


ROOT_DIR = Path(__file__).resolve().parent
ITS_SENTARL_DIR = ROOT_DIR / "src" / "RL_Agent" / "its-sentarl"
ITS_SENTARL_APP_DIR = ITS_SENTARL_DIR / "app"
ITS_SENTARL_MODELS_DIR = ITS_SENTARL_APP_DIR / "models"
DEMO_DIR = ROOT_DIR / "demo" / "rl_trading_demo"
DEMO_DIST_DIR = DEMO_DIR / "dist"

PIVOT_WINDOW_SIZE = 20
ACTION_LABELS = {
    0: {"action": "Short", "position": -1},
    1: {"action": "Neutral", "position": 0},
    2: {"action": "Long", "position": 1},
}
MODEL_LOADERS = {
    "a2c": A2C,
    "ppo": PPO,
    "dqn": DQN,
}
POSITION_TO_ACTION_ID = {-1: 0, 0: 1, 1: 2}


if str(ITS_SENTARL_APP_DIR) not in sys.path:
    sys.path.insert(0, str(ITS_SENTARL_APP_DIR))


def fetch_ohlcv_from_vnstock(
    ticker: str,
    days_back: int = 20,
    source: str = "VCI",
    interval: str = "1D",
) -> pd.DataFrame:
    """Fetch recent OHLCV rows from vnstock for one Vietnamese ticker."""
    try:
        from vnstock.api.quote import Quote
    except ImportError as exc:
        raise RuntimeError(
            "vnstock is not installed. Install it with `pip install vnstock`."
        ) from exc

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days_back)

    quote = Quote(symbol=ticker.upper(), source=source)
    df = quote.history(
        symbol=ticker.upper(),
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        interval=interval,
    )

    if df is None or df.empty:
        raise ValueError(
            f"No OHLCV data returned for {ticker.upper()} from "
            f"{start_date.isoformat()} to {end_date.isoformat()}."
        )

    return df


def preprocess_ohlcv_like_training(raw_df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Apply the same schema normalization used by src/RL_Agent/ohlcv_processing.py."""
    df = raw_df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    lower_to_original = {col.lower(): col for col in df.columns}
    time_col = lower_to_original.get("time") or lower_to_original.get("datetime")
    if time_col is None:
        time_col = lower_to_original.get("date") or lower_to_original.get("trading_date")
    if time_col is None:
        raise ValueError("OHLCV data must include a time/datetime/date column.")

    df["datetime"] = pd.to_datetime(df[time_col])
    df["ticker"] = ticker.upper()
    df = df.sort_values(["ticker", "datetime"])

    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    df = df.rename(
        columns={
            lower_to_original[key]: value
            for key, value in rename_map.items()
            if key in lower_to_original
        }
    )

    if "hour_of_day" not in df.columns:
        df["hour_of_day"] = df["datetime"].dt.hour
    if "day_of_week" not in df.columns:
        df["day_of_week"] = df["datetime"].dt.dayofweek
    if "news-count" not in df.columns:
        df["news-count"] = 0
    if "min-sent" not in df.columns:
        df["min-sent"] = 0.0

    required_cols = [
        "datetime",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "hour_of_day",
        "day_of_week",
        "news-count",
        "min-sent",
    ]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"OHLCV data is missing required columns: {missing}")

    df = df[required_cols].copy()
    df = df.sort_values("datetime")

    numeric_cols = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "hour_of_day",
        "day_of_week",
        "news-count",
        "min-sent",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

    return df


def add_inference_features(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror BaseSetup.prep_data() from its-sentarl."""
    prepared = df.copy()
    prepared["diff"] = np.insert(np.diff(prepared["Close"].to_numpy()), 0, 0)
    prepared["hour_of_day_relative"] = prepared["hour_of_day"] / 24
    prepared["day_of_week_relative"] = prepared["day_of_week"] / 7

    close_min = prepared["Close"].min()
    close_max = prepared["Close"].max()
    if close_max == close_min:
        prepared["close_norm"] = 0.0
    else:
        prepared["close_norm"] = (
            2 * (prepared["Close"] - close_min) / (close_max - close_min) - 1
        )

    prepared["news_count_div"] = prepared["news-count"] / 10

    return prepared


def get_strategy_features(stg: str = "vanilla") -> List[Tuple[str, int]]:
    features = [
        ("diff", PIVOT_WINDOW_SIZE),
        ("hour_of_day_relative", PIVOT_WINDOW_SIZE),
    ]
    if stg.lower() == "sentarl":
        features.append(("min-sent", 5))
    return features


def build_observation(
    prepared_df: pd.DataFrame,
    stg: str = "vanilla",
    previous_action: int = 0,
) -> np.ndarray:
    """Build the latest observation vector with StockExchangeEnv ordering."""
    features = get_strategy_features(stg)
    max_window = max(window_size for _, window_size in features)

    if len(prepared_df) < max_window:
        raise ValueError(
            f"Need at least {max_window} OHLCV rows for inference, "
            f"got {len(prepared_df)}. Increase days_back or use intraday data."
        )

    missing = [feature for feature, _ in features if feature not in prepared_df.columns]
    if missing:
        raise ValueError(f"Prepared data is missing model features: {missing}")

    latest_window = prepared_df.tail(max_window)
    state_features = latest_window[[feature for feature, _ in features]].to_numpy()
    inv_state_features = state_features[::-1]
    window_sizes = np.expand_dims([window_size for _, window_size in features], axis=0)
    mask = np.arange(len(inv_state_features))[:, None] < window_sizes
    lookback_window = inv_state_features.T[mask.T]

    return np.append(lookback_window, previous_action).astype(np.float64)


def find_latest_model_path(
    ticker: str,
    algo: str = "a2c",
    stg: str = "vanilla",
    setup: str = "static",
    transaction_cost: str = "0.0025",
    seed: int = 42,
) -> Path:
    ticker = ticker.lower()
    algo = algo.lower()
    stg = stg.lower()
    model_dir = (
        ITS_SENTARL_MODELS_DIR
        / "hour"
        / setup
        / ticker
        / str(transaction_cost)
        / stg
        / f"seed_{seed}"
        / "roll_0"
    )

    if not model_dir.exists():
        raise FileNotFoundError(f"Model directory not found: {model_dir}")

    pattern = f"*asset_{ticker}-stg_{stg}-algo_{algo}-*_steps.zip"
    candidates = list(model_dir.glob(pattern))
    if not candidates:
        raise FileNotFoundError(
            f"No model checkpoint found in {model_dir} with pattern {pattern}"
        )

    def step_number(path: Path) -> int:
        match = re.search(r"_(\d+)_steps\.zip$", path.name)
        return int(match.group(1)) if match else -1

    return max(candidates, key=step_number)


def load_rl_model(model_path: Path, algo: str = "a2c") -> Any:
    algo = algo.lower()
    if algo not in MODEL_LOADERS:
        raise ValueError(f"Unsupported algo `{algo}`. Use one of {list(MODEL_LOADERS)}.")
    return MODEL_LOADERS[algo].load(str(model_path))


def predict_stock_signal(
    ticker: str,
    algo: str = "a2c",
    stg: str = "vanilla",
    days_back: int = 20,
    previous_action: int = 0,
    model_path: Optional[str] = None,
    source: str = "VCI",
    interval: str = "1D",
) -> Dict[str, Any]:
    raw_df = fetch_ohlcv_from_vnstock(
        ticker=ticker,
        days_back=days_back,
        source=source,
        interval=interval,
    )
    ready_df = preprocess_ohlcv_like_training(raw_df, ticker)
    prepared_df = add_inference_features(ready_df)
    observation = build_observation(
        prepared_df,
        stg=stg,
        previous_action=previous_action,
    )

    resolved_model_path = (
        Path(model_path)
        if model_path
        else find_latest_model_path(ticker=ticker, algo=algo, stg=stg)
    )
    model = load_rl_model(resolved_model_path, algo=algo)
    action_raw, _states = model.predict(observation, deterministic=True)
    action_id = int(np.asarray(action_raw).item())
    action_info = ACTION_LABELS.get(
        action_id,
        {"action": str(action_id), "position": action_id},
    )

    latest_row = ready_df.iloc[-1]

    return {
        "ticker": ticker.upper(),
        "model_path": str(resolved_model_path),
        "algo": algo.lower(),
        "stg": stg.lower(),
        "days_back": days_back,
        "rows": int(len(ready_df)),
        "latest_datetime": latest_row["datetime"].isoformat(),
        "latest_close": float(latest_row["Close"]),
        "previous_action": previous_action,
        "action_id": action_id,
        **action_info,
    }


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current / previous) - 1


def _float_or_none(value: Any) -> Optional[float]:
    if pd.isna(value):
        return None
    return float(value)


def derive_rule_based_decision(
    prepared_df: pd.DataFrame,
    previous_action: int = 0,
) -> Dict[str, Any]:
    """Create a demo trading decision without loading a trained model.

    The endpoint still uses the same data and feature engineering pipeline as
    the RL inference code. This rule is only for the interactive demo path.
    """
    if len(prepared_df) < PIVOT_WINDOW_SIZE:
        raise ValueError(
            f"Need at least {PIVOT_WINDOW_SIZE} OHLCV rows for demo inference, "
            f"got {len(prepared_df)}."
        )

    close = prepared_df["Close"].astype(float)
    returns = close.pct_change().dropna()
    latest_close = float(close.iloc[-1])
    previous_close = float(close.iloc[-2])
    close_5 = float(close.iloc[-6]) if len(close) >= 6 else previous_close
    close_20 = float(close.iloc[-PIVOT_WINDOW_SIZE])

    one_period_return = _pct_change(latest_close, previous_close)
    momentum_5 = _pct_change(latest_close, close_5)
    momentum_20 = _pct_change(latest_close, close_20)
    volatility_20 = float(returns.tail(PIVOT_WINDOW_SIZE).std(ddof=0) or 0.0)
    latest_diff = float(prepared_df["diff"].iloc[-1])

    score = 0.0
    score += 1.0 if momentum_5 > 0 else -1.0
    score += 1.0 if momentum_20 > 0 else -1.0
    score += 0.5 if latest_diff > 0 else -0.5

    if volatility_20 > 0.035:
        score *= 0.75
    if previous_action == 1 and score > 0:
        score += 0.25
    elif previous_action == -1 and score < 0:
        score -= 0.25

    if score >= 1.25:
        position = 1
    elif score <= -1.25:
        position = -1
    else:
        position = 0

    action_id = POSITION_TO_ACTION_ID[position]
    action_info = ACTION_LABELS[action_id]
    confidence = min(0.95, 0.45 + (abs(score) / 2.75) * 0.45)

    if position == 1:
        rationale = "Momentum ngắn hạn và 20 phiên đang nghiêng về chiều tăng."
    elif position == -1:
        rationale = "Momentum ngắn hạn và 20 phiên đang nghiêng về chiều giảm."
    else:
        rationale = "Tín hiệu momentum chưa đủ rõ để mở vị thế mới."

    return {
        "action_id": action_id,
        **action_info,
        "confidence": round(confidence, 4),
        "score": round(score, 4),
        "rationale": rationale,
        "feature_summary": {
            "one_period_return": round(one_period_return, 6),
            "momentum_5": round(momentum_5, 6),
            "momentum_20": round(momentum_20, 6),
            "volatility_20": round(volatility_20, 6),
            "latest_diff": round(latest_diff, 6),
            "previous_action": previous_action,
        },
    }


def build_demo_decision(
    ticker: str,
    days_back: int = 45,
    previous_action: int = 0,
    source: str = "VCI",
    interval: str = "1D",
) -> Dict[str, Any]:
    raw_df = fetch_ohlcv_from_vnstock(
        ticker=ticker,
        days_back=days_back,
        source=source,
        interval=interval,
    )
    ready_df = preprocess_ohlcv_like_training(raw_df, ticker)
    prepared_df = add_inference_features(ready_df)
    observation = build_observation(
        prepared_df,
        stg="vanilla",
        previous_action=previous_action,
    )
    decision = derive_rule_based_decision(
        prepared_df,
        previous_action=previous_action,
    )

    latest_row = ready_df.iloc[-1]
    recent_cols = [
        "datetime",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "diff",
        "hour_of_day_relative",
        "close_norm",
    ]
    recent_rows = []
    for row in prepared_df.tail(6)[recent_cols].to_dict(orient="records"):
        row["datetime"] = row["datetime"].isoformat()
        recent_rows.append({key: _float_or_none(value) if key != "datetime" else value for key, value in row.items()})

    return {
        "ticker": ticker.upper(),
        "source": source,
        "interval": interval,
        "days_back": days_back,
        "rows": int(len(ready_df)),
        "latest_datetime": latest_row["datetime"].isoformat(),
        "latest_close": float(latest_row["Close"]),
        "model_used": False,
        "model_note": "Skipped trained RL checkpoint; demo decision uses engineered OHLCV features.",
        "observation_dim": int(observation.shape[0]),
        "pipeline": [
            {
                "step": "Crawl OHLCV",
                "status": "done",
                "detail": f"Fetched {len(ready_df)} rows ending at {latest_row['datetime'].date().isoformat()}.",
            },
            {
                "step": "Feature Engineer",
                "status": "done",
                "detail": "Created diff, hour_of_day_relative, day_of_week_relative, close_norm, news_count_div.",
            },
            {
                "step": "Skip Model",
                "status": "done",
                "detail": "No trained A2C checkpoint was loaded for this demo path.",
            },
            {
                "step": "Decision",
                "status": "done",
                "detail": f"Returned {decision['action']} with confidence {decision['confidence']}.",
            },
        ],
        "recent_rows": recent_rows,
        **decision,
    }


app = Flask(__name__)
CORS(app)


@app.get("/api/health")
def health() -> Any:
    return jsonify({"status": "ok"})


@app.get("/api/ohlcv/<ticker>")
def ohlcv_endpoint(ticker: str) -> Any:
    try:
        days_back = int(request.args.get("days_back", 20))
        raw_df = fetch_ohlcv_from_vnstock(ticker=ticker, days_back=days_back)
        ready_df = preprocess_ohlcv_like_training(raw_df, ticker)
        return jsonify(
            {
                "ticker": ticker.upper(),
                "rows": len(ready_df),
                "data": ready_df.assign(
                    datetime=ready_df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
                ).to_dict(orient="records"),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/rl/signal/<ticker>")
def rl_signal_endpoint(ticker: str) -> Any:
    try:
        result = predict_stock_signal(
            ticker=ticker,
            algo=request.args.get("algo", "a2c"),
            stg=request.args.get("stg", "vanilla"),
            days_back=int(request.args.get("days_back", 20)),
            previous_action=int(request.args.get("previous_action", 0)),
            model_path=request.args.get("model_path"),
            source=request.args.get("source", "VCI"),
            interval=request.args.get("interval", "1D"),
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/demo/decision/<ticker>")
def demo_decision_endpoint(ticker: str) -> Any:
    try:
        result = build_demo_decision(
            ticker=ticker,
            days_back=int(request.args.get("days_back", 45)),
            previous_action=int(request.args.get("previous_action", 0)),
            source=request.args.get("source", "VCI"),
            interval=request.args.get("interval", "1D"),
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/")
@app.get("/demo")
def demo_index() -> Any:
    if (DEMO_DIST_DIR / "index.html").exists():
        return send_from_directory(DEMO_DIST_DIR, "index.html")
    return send_from_directory(DEMO_DIR, "index.html")


@app.get("/demo/<path:filename>")
def demo_asset(filename: str) -> Any:
    if (DEMO_DIST_DIR / filename).exists():
        return send_from_directory(DEMO_DIST_DIR, filename)
    return send_from_directory(DEMO_DIR, filename)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
