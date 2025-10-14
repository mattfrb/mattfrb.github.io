#!/usr/bin/env python3
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any

import pandas as pd
import pytz
import yfinance as yf


# -------------------- Config --------------------
SYMBOL = "NQ=F"  # Continuous E-mini Nasdaq 100 futures on Yahoo Finance (delayed)
POINT_VALUE = 20.0  # $ per point

# ORB and trade params (points)
OPENING_RANGE_MINUTES = 15
TRADING_WINDOW_MINUTES = 390  # 6.5 hours * 60
OFFSET_POINTS = 2.0
TRAIL_DISTANCE_POINTS = 15.0
TAKE_PROFIT_POINTS = 20.0
BREAKEVEN_TRIGGER_POINTS = 15.0

# Paths
REPORTS_DIR = os.path.join("opening_range_reports")
SUMMARY_CSV = os.path.join(REPORTS_DIR, "summary_last_10_days.csv")
LATEST_JSON = os.path.join(REPORTS_DIR, "latest.json")
SUMMARY_JSON = os.path.join(REPORTS_DIR, "summary.json")
INTRADAY_JSON = os.path.join(REPORTS_DIR, "intraday_today.json")

ET = pytz.timezone("America/New_York")


@dataclass
class TradeState:
    session_date: str
    trade_executed: bool = False
    trade_open: bool = False
    direction: Optional[str] = None  # "long" or "short"
    entry_time: Optional[str] = None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    watermark_price: Optional[float] = None  # best excursion price in favor
    be_triggered: bool = False
    last_processed_ts: Optional[str] = None  # last candle timestamp processed (ET)


def ensure_dirs():
    os.makedirs(REPORTS_DIR, exist_ok=True)


def today_et(now_et: Optional[datetime] = None) -> datetime:
    return (now_et or datetime.now(ET)).astimezone(ET)


def session_times(d: datetime) -> Dict[str, datetime]:
    # Regular session 9:30–16:00 ET
    session_open = d.replace(hour=9, minute=30, second=0, microsecond=0)
    session_close = d.replace(hour=16, minute=0, second=0, microsecond=0)
    orb_end = session_open + timedelta(minutes=OPENING_RANGE_MINUTES)
    trade_start = orb_end  # 9:45 ET
    trade_end = session_open + timedelta(minutes=TRADING_WINDOW_MINUTES)
    return {
        "open": session_open,
        "orb_end": orb_end,
        "trade_start": trade_start,
        "trade_end": min(trade_end, session_close),
    }


def state_path(d: datetime) -> str:
    return os.path.join(REPORTS_DIR, f"state_{d.strftime('%Y-%m-%d')}.json")


def trade_log_path(d: datetime) -> str:
    return os.path.join(REPORTS_DIR, f"trades_{d.strftime('%Y-%m-%d')}.csv")


def load_state(d: datetime) -> TradeState:
    p = state_path(d)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TradeState(**data)
    return TradeState(session_date=d.strftime("%Y-%m-%d"))


def save_state(st: TradeState, d: datetime) -> None:
    p = state_path(d)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(asdict(st), f, ensure_ascii=False, indent=2)


def fetch_intraday_1m(symbol: str) -> pd.DataFrame:
    # Use 2d to ensure we get today’s data reliably
    df = yf.Ticker(symbol).history(period="2d", interval="1m", auto_adjust=False, actions=False)
    if df.empty:
        return df
    # Localize to UTC then convert to ET
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(ET)
    # Standardize columns
    df = df.rename(columns={c: c.capitalize() for c in df.columns})
    return df[["Open", "High", "Low", "Close", "Volume"]]


def within(dt: datetime, a: datetime, b: datetime) -> bool:
    return a <= dt <= b


def compute_opening_range(df: pd.DataFrame, open_ts: datetime, orb_end: datetime) -> Optional[Dict[str, float]]:
    mask = (df.index >= open_ts) & (df.index < orb_end)
    orb = df.loc[mask]
    if orb.empty:
        return None
    return {
        "high": float(orb["High"].max()),
        "low": float(orb["Low"].min()),
    }


def append_trade_log(d: datetime, row: Dict[str, Any]) -> None:
    p = trade_log_path(d)
    cols = [
        "date", "direction", "entry_time", "entry_price", "exit_time", "exit_price",
        "pnl_points", "pnl_usd", "exit_reason"
    ]
    exists = os.path.exists(p)
    df = pd.DataFrame([row], columns=cols)
    df.to_csv(p, mode="a", header=not exists, index=False)


def update_summary(row: Dict[str, Any]) -> None:
    # Maintain last 10 days
    cols = [
        "date", "direction", "entry_time", "entry_price", "exit_time", "exit_price",
        "pnl_points", "pnl_usd", "win"
    ]
    new_df = pd.DataFrame([
        {
            "date": row["date"],
            "direction": row["direction"],
            "entry_time": row["entry_time"],
            "entry_price": row["entry_price"],
            "exit_time": row["exit_time"],
            "exit_price": row["exit_price"],
            "pnl_points": row["pnl_points"],
            "pnl_usd": row["pnl_usd"],
            "win": 1 if row["pnl_points"] > 0 else 0,
        }
    ], columns=cols)

    if os.path.exists(SUMMARY_CSV):
        try:
            cur = pd.read_csv(SUMMARY_CSV)
        except Exception:
            cur = pd.DataFrame(columns=cols)
        cur = pd.concat([cur, new_df], ignore_index=True)
    else:
        cur = new_df

    # Keep only last 10 days by date
    cur = cur.sort_values("date").drop_duplicates("date", keep="last")
    if len(cur) > 10:
        cur = cur.tail(10)
    cur.to_csv(SUMMARY_CSV, index=False)

    # Also write JSON summary for the UI
    summary = {
        "last_10": cur.to_dict(orient="records"),
        "winrate": float(cur["win"].mean()) if len(cur) else None,
        "total_pnl_points": float(cur["pnl_points"].sum()) if len(cur) else 0.0,
        "total_pnl_usd": float(cur["pnl_usd"].sum()) if len(cur) else 0.0,
    }
    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def write_latest(payload: Dict[str, Any]) -> None:
    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main():
    ensure_dirs()
    now = today_et()
    times = session_times(now)

    # Guard: only run on weekdays
    if now.weekday() > 4:
        write_latest({
            "status": "inactive",
            "reason": "weekend",
            "now_et": now.isoformat(),
        })
        return

    # Load data
    df = fetch_intraday_1m(SYMBOL)
    if df.empty:
        write_latest({
            "status": "error",
            "reason": "no_data",
            "now_et": now.isoformat(),
        })
        return

    # Filter to today only
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_df = df[df.index >= today_start]
    st = load_state(now)

    # Compute opening range
    orb = compute_opening_range(today_df, times["open"], times["orb_end"])
    if orb is None:
        # before/during ORB window
        write_latest({
            "status": "pre_orb",
            "now_et": now.isoformat(),
            "session_date": now.strftime('%Y-%m-%d'),
            "session_open": times["open"].isoformat(),
            "orb_end": times["orb_end"].isoformat(),
        })
        save_state(st, now)
        return

    orb_high = orb["high"]
    orb_low = orb["low"]
    long_level = orb_high + OFFSET_POINTS
    short_level = orb_low - OFFSET_POINTS

    # Build candles we need to process from last_processed_ts to now
    process_mask = today_df.index >= times["open"]
    if st.last_processed_ts:
        try:
            last_ts = datetime.fromisoformat(st.last_processed_ts)
            if last_ts.tzinfo is None:
                last_ts = ET.localize(last_ts)
            else:
                last_ts = last_ts.astimezone(ET)
            process_mask = today_df.index > last_ts
        except Exception:
            # Fallback: process from session open
            process_mask = today_df.index >= times["open"]
    candles = today_df.loc[process_mask]

    # Iterate candles in chronological order
    for ts, row in candles.iterrows():
        # Only manage entries/exits during trading window
        in_window = within(ts, times["trade_start"], times["trade_end"]) or (st.trade_open and ts <= times["trade_end"])
        if not in_window:
            st.last_processed_ts = ts.isoformat()
            continue

        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])

        # Entry logic
        if not st.trade_open and not st.trade_executed and ts >= times["trade_start"]:
            if h >= long_level:
                # Long entry at candle close
                st.trade_open = True
                st.trade_executed = True
                st.direction = "long"
                st.entry_time = ts.isoformat()
                st.entry_price = c
                st.watermark_price = c  # best favorable price so far
                st.stop_price = max(c - TRAIL_DISTANCE_POINTS, float('-inf'))
                st.be_triggered = False
            elif l <= short_level:
                # Short entry at candle close
                st.trade_open = True
                st.trade_executed = True
                st.direction = "short"
                st.entry_time = ts.isoformat()
                st.entry_price = c
                st.watermark_price = c
                st.stop_price = min(c + TRAIL_DISTANCE_POINTS, float('inf'))
                st.be_triggered = False

        # Manage open trade
        if st.trade_open:
            direction = st.direction
            entry = float(st.entry_price)
            # Update watermark and trailing stop
            if direction == "long":
                # Update watermark on favorable move
                if h > st.watermark_price:
                    st.watermark_price = h
                # Trailing logic
                new_trail = st.watermark_price - TRAIL_DISTANCE_POINTS
                st.stop_price = max(st.stop_price, new_trail)
                # Break-even trigger
                if not st.be_triggered and (st.watermark_price - entry) >= BREAKEVEN_TRIGGER_POINTS:
                    st.stop_price = max(st.stop_price, entry)
                    st.be_triggered = True
                # Exit checks (TP first, then stop)
                tp_price = entry + TAKE_PROFIT_POINTS
                exit_reason = None
                exit_price = None
                if h >= tp_price:
                    exit_price = tp_price
                    exit_reason = "TP"
                elif l <= st.stop_price:
                    exit_price = st.stop_price
                    exit_reason = "TrailingStop"
                elif ts >= times["trade_end"]:
                    exit_price = c
                    exit_reason = "EOD"

                if exit_reason:
                    pnl_points = (exit_price - entry)
                    pnl_usd = pnl_points * POINT_VALUE
                    row_out = {
                        "date": st.session_date,
                        "direction": direction,
                        "entry_time": st.entry_time,
                        "entry_price": round(entry, 2),
                        "exit_time": ts.isoformat(),
                        "exit_price": round(float(exit_price), 2),
                        "pnl_points": round(float(pnl_points), 2),
                        "pnl_usd": round(float(pnl_usd), 2),
                        "exit_reason": exit_reason,
                    }
                    append_trade_log(now, row_out)
                    update_summary(row_out)
                    st.trade_open = False
                    st.direction = None

            elif direction == "short":
                if l < st.watermark_price:
                    st.watermark_price = l
                new_trail = st.watermark_price + TRAIL_DISTANCE_POINTS
                st.stop_price = min(st.stop_price, new_trail)
                if not st.be_triggered and (entry - st.watermark_price) >= BREAKEVEN_TRIGGER_POINTS:
                    st.stop_price = min(st.stop_price, entry)
                    st.be_triggered = True
                tp_price = entry - TAKE_PROFIT_POINTS
                exit_reason = None
                exit_price = None
                if l <= tp_price:
                    exit_price = tp_price
                    exit_reason = "TP"
                elif h >= st.stop_price:
                    exit_price = st.stop_price
                    exit_reason = "TrailingStop"
                elif ts >= times["trade_end"]:
                    exit_price = c
                    exit_reason = "EOD"

                if exit_reason:
                    pnl_points = (entry - exit_price)
                    pnl_usd = pnl_points * POINT_VALUE
                    row_out = {
                        "date": st.session_date,
                        "direction": direction,
                        "entry_time": st.entry_time,
                        "entry_price": round(entry, 2),
                        "exit_time": ts.isoformat(),
                        "exit_price": round(float(exit_price), 2),
                        "pnl_points": round(float(pnl_points), 2),
                        "pnl_usd": round(float(pnl_usd), 2),
                        "exit_reason": exit_reason,
                    }
                    append_trade_log(now, row_out)
                    update_summary(row_out)
                    st.trade_open = False
                    st.direction = None

        st.last_processed_ts = ts.isoformat()

    # Build latest.json snapshot
    latest: Dict[str, Any] = {
        "status": "active",
        "now_et": now.isoformat(),
        "session_date": now.strftime('%Y-%m-%d'),
        "session_open": times["open"].isoformat(),
        "orb_end": times["orb_end"].isoformat(),
        "trade_window_end": times["trade_end"].isoformat(),
        "opening_range": {
            "high": round(orb_high, 2),
            "low": round(orb_low, 2),
            "long_level": round(long_level, 2),
            "short_level": round(short_level, 2),
        },
        "params": {
            "OFFSET_POINTS": OFFSET_POINTS,
            "TRAIL_DISTANCE_POINTS": TRAIL_DISTANCE_POINTS,
            "TAKE_PROFIT_POINTS": TAKE_PROFIT_POINTS,
            "BREAKEVEN_TRIGGER_POINTS": BREAKEVEN_TRIGGER_POINTS,
            "POINT_VALUE": POINT_VALUE,
        },
    }

    if st.trade_open:
        # Unrealized PnL using last close
        last_close = float(today_df.iloc[-1]["Close"]) if not today_df.empty else float("nan")
        if st.direction == "long":
            pnl_points = last_close - float(st.entry_price)
        else:
            pnl_points = float(st.entry_price) - last_close
        latest["trade"] = {
            "open": True,
            "direction": st.direction,
            "entry_time": st.entry_time,
            "entry_price": round(float(st.entry_price), 2),
            "stop_price": round(float(st.stop_price), 2) if st.stop_price is not None else None,
            "watermark_price": round(float(st.watermark_price), 2) if st.watermark_price is not None else None,
            "be_triggered": st.be_triggered,
            "unrealized_pnl_points": round(float(pnl_points), 2),
            "unrealized_pnl_usd": round(float(pnl_points * POINT_VALUE), 2),
        }
    else:
        latest["trade"] = {"open": False, "trade_executed": st.trade_executed}

    # Attach last 10 summary if present
    if os.path.exists(SUMMARY_JSON):
        with open(SUMMARY_JSON, "r", encoding="utf-8") as f:
            latest["summary"] = json.load(f)

    write_latest(latest)
    save_state(st, now)

    # Write intraday candles for today's session (for frontend chart)
    try:
        mask = (today_df.index >= times["open"]) & (today_df.index <= min(now, times["trade_end"]))
        view = today_df.loc[mask]
        candles = []
        for ts, r in view.iterrows():
            candles.append({
                "t": ts.isoformat(),
                "o": round(float(r["Open"]), 2),
                "h": round(float(r["High"]), 2),
                "l": round(float(r["Low"]), 2),
                "c": round(float(r["Close"]), 2),
            })
        payload = {
            "symbol": SYMBOL,
            "date": now.strftime('%Y-%m-%d'),
            "session_open": times["open"].isoformat(),
            "session_close": times["trade_end"].isoformat(),
            "candles": candles,
        }
        with open(INTRADAY_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        # best-effort; ignore chart export errors
        pass


if __name__ == "__main__":
    main()
