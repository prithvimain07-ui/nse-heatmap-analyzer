import json
import pickle
import time
import base64
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import csv
import io
import sqlite3

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="F&O Stocks HeatMap",
    layout="wide"
)

# =========================================================
# AUTO REFRESH - 15 MINUTES WITH LIVE COUNTDOWN
# =========================================================

REFRESH_INTERVAL = 15 * 60  # 15 minutes
CACHE_TTL = 14 * 60

refresh_count = st_autorefresh(
    interval=REFRESH_INTERVAL * 1000,
    limit=None,
    key="data_refresh",
)

if "last_refresh_time" not in st.session_state:
    st.session_state.last_refresh_time = int(time.time())
if "last_autorefresh_count" not in st.session_state:
    st.session_state.last_autorefresh_count = refresh_count

if refresh_count != st.session_state.last_autorefresh_count:
    st.session_state.last_autorefresh_count = refresh_count
    st.session_state.last_refresh_time = int(time.time())
    st.toast("\u2705 LATEST DATA FETCHED SUCCESSFULLY")

def show_refresh_timer():
    last_ts = int(st.session_state.last_refresh_time)
    next_ts = last_ts + REFRESH_INTERVAL
    last_dt = datetime.fromtimestamp(last_ts)
    next_dt = datetime.fromtimestamp(next_ts)
    timer_html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        html, body {{ overflow: hidden; }}
        body {{
          margin: 0;
          background: transparent;
          font-family: system-ui, -apple-system, Segoe UI, sans-serif;
          color: #d4d7de;
        }}
        .box {{
          background: #334762;
          color: #7fb2ff;
          padding: 14px 16px;
          border-radius: 6px;
          line-height: 1.8;
          font-weight: 600;
        }}
        .cycle {{ margin-top: 14px; font-size: 14px; }}
        .track {{
          height: 8px;
          background: #111218;
          border-radius: 99px;
          overflow: hidden;
          margin-top: 8px;
        }}
        .bar {{
          height: 100%;
          width: 0%;
          background: #ff6961;
          border-radius: 99px;
          transition: width 0.25s linear;
        }}
        .done {{
          display: none;
          margin-top: 10px;
          color: #9df59d;
          font-weight: 700;
          font-size: 13px;
        }}
      </style>
    </head>
    <body>
      <div class="box">
        <div>Next refresh in: <span id="countdown">--:--</span></div>
        <div style="margin-top:12px;">Last refreshed: {last_dt.strftime('%H:%M:%S')}</div>
        <div style="margin-top:12px;">Next refresh at: {next_dt.strftime('%H:%M:%S')}</div>
      </div>
      <div class="cycle">Refresh cycle: <span id="cycle_pct">0</span>%</div>
      <div class="track"><div id="cycle_bar" class="bar"></div></div>
      <div id="done" class="done">LATEST DATA FETCHED SUCCESSFULLY</div>
      <script>
        const lastTs = {last_ts} * 1000;
        const nextTs = {next_ts} * 1000;
        const intervalMs = {REFRESH_INTERVAL} * 1000;
        function tick() {{
          const now = Date.now();
          const remaining = Math.max(0, Math.floor((nextTs - now) / 1000));
          const mins = Math.floor(remaining / 60).toString().padStart(2, '0');
          const secs = (remaining % 60).toString().padStart(2, '0');
          const elapsed = Math.min(intervalMs, Math.max(0, now - lastTs));
          const pct = Math.min(100, Math.floor((elapsed / intervalMs) * 100));
          document.getElementById('countdown').textContent = `${{mins}}:${{secs}}`;
          document.getElementById('cycle_pct').textContent = pct;
          document.getElementById('cycle_bar').style.width = pct + '%';
          document.getElementById('done').style.display = remaining === 0 ? 'block' : 'none';
        }}
        tick();
        setInterval(tick, 1000);
      </script>
    </body>
    </html>
    """
    timer_src = "data:text/html;base64," + base64.b64encode(timer_html.encode("utf-8")).decode("ascii")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### \U0001F552 Auto-Refresh Timer")
    with st.sidebar:
        if hasattr(st, "iframe"):
            st.iframe(timer_src, height=210)
        else:
            import streamlit.components.v1 as components
            components.html(timer_html, height=210, scrolling=False)
    st.sidebar.markdown("---")

# =========================================================
# CONFIG
# =========================================================

START_DATE = "2022-01-01"
FULL_HISTORY_PERIOD = "max"
FULL_HISTORY_START_DATE = "1990-01-01"

SECTOR_CSV_PATHS = [
    Path(__file__).with_name("Basic RS Setup.csv"),
    Path.home() / "OneDrive" / "Desktop" / "Basic RS Setup.csv",
    Path.home() / "Desktop" / "Basic RS Setup.csv",
]

NSE_UNIVERSE_CSV_PATHS = [
    Path(__file__).with_name("nse universe.csv"),
    Path(__file__).with_name("nse_universe.csv"),
    Path.home() / "OneDrive" / "Desktop" / "nse universe.csv",
    Path.home() / "OneDrive" / "Desktop" / "nse_universe.csv",
    Path.home() / "Desktop" / "nse universe.csv",
    Path.home() / "Desktop" / "nse_universe.csv",
]

TICKER_CACHE_PATH = Path(__file__).with_name("ticker_cache.json")
MARKET_CACHE_PATH = Path(__file__).with_name("market_data_cache.pkl")
MARKET_CACHE_META_PATH = Path(__file__).with_name("market_data_cache_meta.json")
CACHE_SCHEMA_VERSION = 8
UPDATE_WINDOW_DAYS = 14
# FIX: Use a shorter stale threshold so local cache is used aggressively
STALE_CACHE_SECONDS = REFRESH_INTERVAL - 30
TODAY_REFRESH_PERIOD = "1d"
MARKET_DATA_DIR = Path(__file__).with_name("market_data_store")
HISTORICAL_DATA_DIR = MARKET_DATA_DIR / "historical_till_yesterday"
TODAY_DATA_DIR = MARKET_DATA_DIR / "today_live_15min"
HISTORICAL_CLOSE_CSV = HISTORICAL_DATA_DIR / "close.csv"
HISTORICAL_HIGH_CSV = HISTORICAL_DATA_DIR / "high.csv"
HISTORICAL_LOW_CSV = HISTORICAL_DATA_DIR / "low.csv"
TODAY_CLOSE_CSV = TODAY_DATA_DIR / "close_today.csv"
TODAY_HIGH_CSV = TODAY_DATA_DIR / "high_today.csv"
TODAY_LOW_CSV = TODAY_DATA_DIR / "low_today.csv"
CSV_MARKET_META_PATH = MARKET_DATA_DIR / "market_data_meta.json"
MARKET_SQLITE_PATH = MARKET_DATA_DIR / "market_data.sqlite"
MIN_NSE_INDEX_HISTORY_ROWS = 45
PRICE_CACHE_BACKEND = "sqlite"

CSV_SYMBOL_ALIASES = {
    "LTM": "LTM",
}

def to_yahoo_ticker(raw: str) -> str:
    t = str(raw).strip()
    if not t:
        return t
    if t.startswith("^") or t.endswith(".NS") or t.endswith(".BO") or t.endswith(".BSE"):
        return t
    return f"{t}.NS"

EXCLUDED_SYMBOLS = {"KISSHT", "SANGHIIND", "GSPL"}

MANUAL_STOCK_DATA_OVERRIDES = {
    "TORNTPOWER": {"Sector": "Power",               "Industry": "Power Generation & Distribution"},
    "ADANIPOWER": {"Sector": "Power",               "Industry": "Power Generation & Distribution"},
    "HUDCO":      {"Sector": "Financial Services",   "Industry": "Housing Finance"},
    "IRCTC":      {"Sector": "Consumer Services",    "Industry": "Travel Support Services"},
    "TATATECH":   {"Sector": "Information Technology","Industry": "IT Enabled Services"},
    "PPLPHARMA":  {"Sector": "Healthcare",            "Industry": "Pharmaceuticals"},
    "SYNGENE":    {"Sector": "Healthcare",            "Industry": "Biotechnology"},
}

KNOWN_TICKER_OVERRIDES = {
    "BAJAJ-AUTO"  : "BAJAJ-AUTO",
    "M&M"         : "M%26M",
    "ETERNAL"     : "ETERNAL",
    "TMPV"        : "TMPV",
    "PREMIERENE"  : "PREMIERENE",
    "SAMMAANCAP"  : "SAMMAANCAP",
    "PGEL"        : "PGEL",
    "INOXWIND"    : "INOXWIND",
    "SWIGGY"      : "SWIGGY",
    "PAYTM"       : "PAYTM",
    "NYKAA"       : "NYKAA",
    "POLICYBZR"   : "POLICYBZR",
    "DELHIVERY"   : "DELHIVERY",
    "ZOMATO"      : "ETERNAL",
    "NEPHROPLUS"  : "NEPHROPLUS.NS",
    "NACLIND"     : "NACLIND.NS",
    "MUNJALSHOW"  : "MUNJALSHOW.NS",
    "MODISONLTD"  : "MODISONLTD.NS",
    "MODIS"       : "MODIS.NS",
    "MMTC"        : "MMTC.NS",
    "MIDWESTLTD"  : "MIDWESTLTD.NS",
    "MANYAVAR"    : "MANYAVAR.NS",
    "MANINFRA"    : "MANINFRA.NS",
    "MAMATA"      : "MAMATA.NS",
    "MAHLIFE"     : "MAHLIFE.NS",
    "KSHINTL"     : "KSHINTL.NS",
    "KKCL"        : "KKCL.NS",
    "KELLTONTEC"  : "KELLTONTEC.NS",
}

ALL_STOCKS = [
    "NATIONALUM","ASHOKLEY","MCX","SHRIRAMFIN","VEDL","ABCAPITAL",
    "AUBANK","BHARATFORG","RBLBANK","SBIN","LTF","FEDERALBNK",
    "BANKINDIA","APLAPOLLO","CUMMINSIND","EICHERMOT","IDEA",
    "LAURUSLABS","POWERINDIA","INDIANB","UNIONBANK","CANBK",
    "HINDZINC","MOTHERSON","TATASTEEL","HINDALCO","MFSL",
    "INDUSTOWER","TVSMOTOR","MANAPPURAM","MUTHOOTFIN","SAIL",
    "GLENMARK","BEL","JINDALSTEL","NYKAA","TORNTPHARM",
    "BANKBARODA","KEI","IOC","AXISBANK","IDFCFIRSTB",
    "ADANIENSOL","LT","ASTRAL","FORTIS","BPCL","AMBER",
    "POLYCAB","PNB","TITAN","SBILIFE","JSWSTEEL","OIL",
    "TORNTPOWER","DELHIVERY","ADANIPORTS","ADANIPOWER","NMDC","ONGC",
    "PAYTM","VOLTAS","BAJAJ-AUTO","HDFCAMC","BSE",
    "SAMMAANCAP","GMRAIRPORT","BRITANNIA","LUPIN","HEROMOTOCO",
    "NTPC","BAJFINANCE","BANDHANBNK","ABB","COALINDIA",
    "BLUESTARCO","INDUSINDBK","UPL","MARICO","PHOENIXLTD",
    "CHOLAFIN","HINDPETRO","SOLARINDS","ULTRACEMCO","UNOMINDA",
    "ICICIPRULI","GRASIM","APOLLOHOSP","NESTLEIND","360ONE",
    "DRREDDY","BHEL","PFC","MARUTI","POWERGRID","SONACOMS",
    "PETRONET","M&M","TATACONSUM","BIOCON","BOSCHLTD",
    "BHARTIARTL","DALBHARAT","CGPOWER","GODREJCP","SIEMENS",
    "BAJAJFINSV","YESBANK","ICICIGI","ICICIBANK","KOTAKBANK",
    "SUPREMEIND","WAAREEENER","HDFCLIFE","ALKEM","DIVISLAB",
    "LICI","SUNPHARMA","AUROPHARMA","PIDILITIND","RELIANCE",
    "UNITDSPR","ADANIGREEN","DABUR","KFINTECH","ETERNAL",
    "PRESTIGE","TECHM","ZYDUSLIFE","NUVAMA","TATAPOWER",
    "CAMS","HDFCBANK","JSWENERGY","VBL","HAL",
    "PNBHOUSING","PGEL","SRF","ANGELONE","HINDUNILVR",
    "MAXHEALTH","AMBUJACEM","GAIL","DMART","ASIANPAINT",
    "RECLTD","HAVELLS","SBICARD","CONCOR","COLPAL",
    "NBCC","NHPC","LICHSGFIN","SHREECEM","JIOFIN",
    "ADANIENT","LTM","PATANJALI","PERSISTENT","INDHOTEL",
    "BAJAJHLDNG","OBEROIRLTY","CDSL","MPHASIS","HUDCO",
    "HCLTECH","INDIGO","CIPLA","BDL","IRFC",
    "INFY","RVNL","EXIDEIND","GODREJPROP","MANKIND",
    "SWIGGY","CROMPTON","PIIND","MAZDOCK","IRCTC",
    "LODHA","TATATECH","TATAELXSI","DLF","POLICYBZR",
    "PPLPHARMA","TRENT","TIINDIA","JUBLFOOD","WIPRO",
    "TCS","IEX","IREDA","COFORGE","KALYANKJIL",
    "ITC","SUZLON","OFSS","PAGEIND","NAUKRI",
    "TMPV","PREMIERENE","DIXON","KAYNES","KPITTECH",
    "SYNGENE","INOXWIND",
]

# =========================================================
# NIFTY INDEX CONSTITUENT LISTS
# =========================================================

NIFTY_INDICES = {
    "Nifty 50": [
        "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK",
        "BAJAJ-AUTO","BAJFINANCE","BAJAJFINSV","BHARTIARTL","BPCL",
        "BRITANNIA","CIPLA","COALINDIA","DIVISLAB","DRREDDY",
        "EICHERMOT","GRASIM","HCLTECH","HDFCBANK","HDFCLIFE",
        "HEROMOTOCO","HINDALCO","HINDUNILVR","ICICIBANK","INDUSINDBK",
        "INFY","ITC","JSWSTEEL","KOTAKBANK","LT",
        "LTM","M&M","MARUTI","NESTLEIND","NTPC",
        "ONGC","POWERGRID","RELIANCE","SBILIFE","SBIN",
        "SHRIRAMFIN","SUNPHARMA","TATACONSUM","TATASTEEL",
        "TCS","TECHM","TITAN","ULTRACEMCO","WIPRO","ETERNAL",
    ],
    "Nifty 100": [
        "ADANIENT","ADANIPORTS","ADANIENSOL","APOLLOHOSP","ASIANPAINT",
        "AXISBANK","BAJAJ-AUTO","BAJFINANCE","BAJAJFINSV","BHARTIARTL",
        "BPCL","BRITANNIA","CIPLA","COALINDIA","COLPAL",
        "DIVISLAB","DLF","DRREDDY","EICHERMOT","ETERNAL",
        "GAIL","GODREJCP","GRASIM","HCLTECH","HDFCAMC",
        "HDFCBANK","HDFCLIFE","HEROMOTOCO","HINDALCO","HINDPETRO",
        "HINDUNILVR","ICICIBANK","ICICIGI","ICICIPRULI","INDUSINDBK",
        "INFY","IOC","ITC","JSWSTEEL","KOTAKBANK",
        "LICI","LT","LTM","LUPIN","M&M",
        "MARICO","MARUTI","NESTLEIND","NTPC","ONGC",
        "PAGEIND","PIDILITIND","POWERGRID","RELIANCE","SBICARD",
        "SBILIFE","SBIN","SHRIRAMFIN","SIEMENS","SUNPHARMA",
        "TATACONSUM","TATASTEEL","TCS","TECHM","TITAN",
        "TORNTPHARM","TRENT","ULTRACEMCO","WIPRO","ZYDUSLIFE",
        "ABB","AMBUJACEM","BEL","CGPOWER","CHOLAFIN",
        "CUMMINSIND","DABUR","DMART","GODREJPROP","HAVELLS",
        "INDHOTEL","INDUSTOWER","JIOFIN","LODHA","MAXHEALTH",
        "MUTHOOTFIN","NAUKRI","NHPC","OBEROIRLTY","PERSISTENT",
        "PFC","PHOENIXLTD","PRESTIGE","RECLTD","SHREECEM",
        "TATAPOWER","TVSMOTOR","VEDL","VBL","BAJAJHLDNG",
    ],
    "Nifty 200": [
        "ADANIENT","ADANIPORTS","ADANIENSOL","ADANIGREEN","APOLLOHOSP",
        "ASIANPAINT","AUBANK","AXISBANK","BAJAJ-AUTO","BAJFINANCE",
        "BAJAJFINSV","BAJAJHLDNG","BANDHANBNK","BANKBARODA","BANKINDIA",
        "BHARATFORG","BHARTIARTL","BHEL","BIOCON","BLUESTARCO",
        "BOSCHLTD","BPCL","BRITANNIA","BSE","CAMS","CANBK",
        "CDSL","CGPOWER","CHOLAFIN","CIPLA","COALINDIA",
        "COFORGE","COLPAL","CONCOR","CROMPTON","CUMMINSIND",
        "DABUR","DALBHARAT","DELHIVERY","DIVISLAB","DLF",
        "DMART","DRREDDY","EICHERMOT","ETERNAL","EXIDEIND",
        "FEDERALBNK","FORTIS","GAIL","GLENMARK","GODREJCP",
        "GODREJPROP","GRASIM","HAVELLS","HCLTECH","HDFCAMC",
        "HDFCBANK","HDFCLIFE","HEROMOTOCO","HINDALCO","HINDPETRO",
        "HINDZINC","HINDUNILVR","HUDCO","ICICIBANK","ICICIGI",
        "ICICIPRULI","IDEA","IDFCFIRSTB","INDIANB","INDHOTEL",
        "INDIGO","INDUSINDBK","INDUSTOWER","INFY","IOC",
        "IRCTC","IRFC","ITC","JIOFIN","JINDALSTEL",
        "JSWENERGY","JSWSTEEL","JUBLFOOD","KALYANKJIL","KAYNES",
        "KEI","KFINTECH","KOTAKBANK","KPITTECH","LAURUSLABS",
        "LT","LTM","LICI","LICHSGFIN","LODHA","LUPIN",
        "M&M","MANKIND","MANAPPURAM","MARICO","MARUTI",
        "MAXHEALTH","MCX","MFSL","MOTHERSON","MPHASIS",
        "MUTHOOTFIN","NAUKRI","NBCC","NESTLEIND","NHPC",
        "NMDC","NTPC","NUVAMA","NYKAA","OBEROIRLTY",
        "OFSS","OIL","ONGC","PAGEIND","PATANJALI",
        "PAYTM","PERSISTENT","PETRONET","PFC","PHOENIXLTD",
        "PIDILITIND","PIIND","PNBHOUSING","PNB","POLICYBZR",
        "POLYCAB","POWERGRID","POWERINDIA","PRESTIGE","RECLTD",
        "RELIANCE","RBLBANK","RVNL","SAIL","SAMMAANCAP",
        "SBICARD","SBILIFE","SBIN","SHREECEM","SHRIRAMFIN",
        "SIEMENS","SOLARINDS","SONACOMS","SRF","SUNPHARMA",
        "SUPREMEIND","SUZLON","TATACONSUM","TATASTEEL","TATAELXSI",
        "TATAPOWER","TATATECH","TCS","TECHM","TIINDIA",
        "TITAN","TORNTPHARM","TORNTPOWER","TRENT","TVSMOTOR",
        "ULTRACEMCO","UNIONBANK","UNITDSPR","UPL","VBL",
        "VEDL","VOLTAS","WAAREEENER","WIPRO","YESBANK","ZYDUSLIFE",
    ],
    "Nifty 500": [
        "ADANIENT","ADANIPORTS","ADANIENSOL","ADANIGREEN","ABCAPITAL",
        "APLAPOLLO","AMBER","ANGELONE","APOLLOHOSP","ASIANPAINT",
        "ASTRAL","AUBANK","AXISBANK","BAJAJ-AUTO","BAJFINANCE",
        "BAJAJFINSV","BAJAJHLDNG","BANDHANBNK","BANKBARODA","BANKINDIA",
        "BDL","BEL","BHARATFORG","BHARTIARTL","BHEL","BIOCON",
        "BLUESTARCO","BOSCHLTD","BPCL","BRITANNIA","BSE","CAMS",
        "CANBK","CDSL","CGPOWER","CHOLAFIN","CIPLA","COALINDIA",
        "COFORGE","COLPAL","CONCOR","CROMPTON","CUMMINSIND","DABUR",
        "DALBHARAT","DELHIVERY","DIVISLAB","DIXON","DLF","DMART",
        "DRREDDY","EICHERMOT","ETERNAL","EXIDEIND","FEDERALBNK",
        "FORTIS","GAIL","GLENMARK","GMRAIRPORT","GODREJCP",
        "GODREJPROP","GRASIM","HAL","HAVELLS","HCLTECH","HDFCAMC",
        "HDFCBANK","HDFCLIFE","HEROMOTOCO","HINDALCO","HINDPETRO",
        "HINDZINC","HINDUNILVR","HUDCO","ICICIBANK","ICICIGI",
        "ICICIPRULI","IDEA","IDFCFIRSTB","IEX","INDIANB","INDHOTEL",
        "INDIGO","INDUSINDBK","INDUSTOWER","INFY","INOXWIND","IOC",
        "IRCTC","IREDA","IRFC","ITC","JIOFIN","JINDALSTEL",
        "JSWENERGY","JSWSTEEL","JUBLFOOD","KALYANKJIL","KAYNES",
        "KEI","KFINTECH","KOTAKBANK","KPITTECH","LAURUSLABS",
        "LT","LTM","LTF","LICI","LICHSGFIN","LODHA","LUPIN",
        "M&M","MAZDOCK","MANKIND","MANAPPURAM","MARICO","MARUTI",
        "MAXHEALTH","MCX","MFSL","MOTHERSON","MPHASIS","MUTHOOTFIN",
        "NATIONALUM","NAUKRI","NBCC","NESTLEIND","NHPC","NMDC",
        "NTPC","NUVAMA","NYKAA","OBEROIRLTY","OFSS","OIL","ONGC",
        "PAGEIND","PATANJALI","PAYTM","PERSISTENT","PETRONET","PFC",
        "PHOENIXLTD","PIDILITIND","PIIND","PNBHOUSING","PGEL","PNB",
        "POLICYBZR","POLYCAB","POWERGRID","POWERINDIA","PREMIERENE",
        "PRESTIGE","RECLTD","RELIANCE","RBLBANK","RVNL","SAIL",
        "SAMMAANCAP","SBICARD","SBILIFE","SBIN","SHREECEM","SHRIRAMFIN",
        "SIEMENS","SOLARINDS","SONACOMS","SRF","SUNPHARMA","SUPREMEIND",
        "SUZLON","SWIGGY","SYNGENE","TATACONSUM","TATASTEEL",
        "TATAELXSI","TATAPOWER","TATATECH","TCS","TECHM","TIINDIA",
        "TITAN","TMPV","TORNTPHARM","TORNTPOWER","TRENT","TVSMOTOR",
        "ULTRACEMCO","UNIONBANK","UNITDSPR","UPL","VBL","VEDL",
        "VOLTAS","WAAREEENER","WIPRO","YESBANK","ZYDUSLIFE","360ONE",
        "PPLPHARMA","ASHOKLEY","NATIONALUM","EXIDEIND","COFORGE",
    ],
    "Nifty Midcap 50": [
        "AUBANK","APLAPOLLO","ABCAPITAL","AMBER","ANGELONE","ASTRAL",
        "BANDHANBNK","BDL","BSE","CAMS","CDSL","CHOLAFIN","COFORGE",
        "CROMPTON","DIXON","FEDERALBNK","GODREJPROP","GMRAIRPORT",
        "HAL","HUDCO","IDFCFIRSTB","INDHOTEL","IRCTC","IREDA",
        "JIOFIN","KALYANKJIL","KAYNES","KEI","KFINTECH","KPITTECH",
        "LTF","LICHSGFIN","LODHA","MAZDOCK","MFSL","MUTHOOTFIN",
        "NUVAMA","NYKAA","OBEROIRLTY","PATANJALI","PAYTM","PERSISTENT",
        "PHOENIXLTD","POLICYBZR","PRESTIGE","RBLBANK","RVNL",
        "SAMMAANCAP","SOLARINDS","TATATECH",
    ],
    "Nifty Midcap 100": [
        "AUBANK","APLAPOLLO","ABCAPITAL","AMBER","ANGELONE","ASTRAL",
        "BANDHANBNK","BDL","BHARATFORG","BSE","CAMS","CDSL","CHOLAFIN",
        "COFORGE","CONCOR","CROMPTON","DALBHARAT","DELHIVERY","DIXON",
        "EXIDEIND","FEDERALBNK","GMRAIRPORT","GODREJPROP","HAL",
        "HAVELLS","HUDCO","IDFCFIRSTB","IEX","INDHOTEL","IRCTC",
        "IREDA","IRFC","JIOFIN","JUBLFOOD","KALYANKJIL","KAYNES",
        "KEI","KFINTECH","KPITTECH","LTF","LAURUSLABS","LICHSGFIN",
        "LODHA","MANAPPURAM","MAZDOCK","MFSL","MOTHERSON","MUTHOOTFIN",
        "NATIONALUM","NUVAMA","NYKAA","OBEROIRLTY","PATANJALI","PAYTM",
        "PERSISTENT","PHOENIXLTD","PIIND","PNBHOUSING","POLICYBZR",
        "POLYCAB","PREMIERENE","PRESTIGE","RBLBANK","RECLTD","RVNL",
        "SAIL","SAMMAANCAP","SOLARINDS","SONACOMS","SRF","SUPREMEIND",
        "SUZLON","SYNGENE","TATAELXSI","TATATECH","TIINDIA","TORNTPOWER",
        "TRENT","UNITDSPR","VBL","VOLTAS","WAAREEENER","ZYDUSLIFE",
        "360ONE","ASHOKLEY","BANKBARODA","BLUESTARCO","CGPOWER",
        "GLENMARK","INOXWIND","MCX","NMDC",
    ],
    "Nifty Smallcap 100": [
        "AARTIIND","ABSLAMC","AEGISLOG","APLLTD","APTUS","BSOFT",
        "CANFINHOME","CARTRADE","CESC","CLEAN","CMSINFO","DATAPATTNS",
        "DELHIVERY","EDELWEISS","ELGIEQUIP","EMAMILTD","EPIGRAL",
        "ERIS","ESABINDIA","FIVESTAR","GESHIP","GRINDWELL","GUJGASLTD",
        "HAPPSTMNDS","HFCL","IDFC","IIFL","INTELLECT","IRCON",
        "IXIGO","JBCHEPHARM","JKCEMENT","JKLAKSHMI","JYOTHYLAB",
        "KEC","KRBL","LATENTVIEW","LEMONTREE","LXCHEM","MAHLOG",
        "MAPMYINDIA","MEDANTA","METROBRAND","METROPOLIS","MOLDTKPAC",
        "MTAR","NATCOPHARM","NAVINFLUOR","NETWORK18","ORIENTELEC",
        "ORIENTCEM","POLYMED","PRINCEPIPE","RADICO","RAINBOW",
        "RATEGAIN","RATNAMANI","RITES","ROUTE","SAFARI","SAPPHIRE",
        "SEQUENT","SHOPERSTOP","SKIPPER","SONATSOFTW","SPANDANA",
        "STLTECH","SUDARSCHEM","SUMICHEM","SUNTECK","SUVENPHAR",
        "TANLA","TATAINVEST","TEAMLEASE","TECHNOELEC","THYROCARE",
        "TITAGARH","TRIVENI","UJJIVANSFB","UNIPARTS","UTIAMC",
        "VAIBHAVGBL","VGUARD","VINDHYATEL",
    ],
    "Nifty IT": [
        "COFORGE","HCLTECH","INFY","KPITTECH","LTM",
        "MPHASIS","OFSS","PERSISTENT","TCS","TECHM","WIPRO",
    ],
    "Nifty Bank": [
        "AUBANK","AXISBANK","BANDHANBNK","FEDERALBNK","HDFCBANK",
        "ICICIBANK","IDFCFIRSTB","INDUSINDBK","KOTAKBANK","PNB",
        "RBLBANK","SBIN",
    ],
    "Nifty FMCG": [
        "BRITANNIA","COLPAL","DABUR","GODREJCP","HINDUNILVR",
        "ITC","MARICO","NESTLEIND","TATACONSUM","UNITDSPR","VBL",
    ],
    "Nifty Auto": [
        "ASHOKLEY","BAJAJ-AUTO","BHARATFORG","EICHERMOT","HEROMOTOCO",
        "M&M","MARUTI","MOTHERSON","SONACOMS","TVSMOTOR",
        "TIINDIA","UNOMINDA",
    ],
    "Nifty Pharma": [
        "ALKEM","AUROPHARMA","BIOCON","CIPLA","DIVISLAB",
        "DRREDDY","GLENMARK","LAURUSLABS","LUPIN","MANKIND",
        "SUNPHARMA","TORNTPHARM","ZYDUSLIFE",
    ],
    "Nifty Financial Services": [
        "ABCAPITAL","AXISBANK","BAJFINANCE","BAJAJFINSV","CHOLAFIN",
        "HDFCAMC","HDFCBANK","HDFCLIFE","ICICIBANK","ICICIGI",
        "ICICIPRULI","JIOFIN","KOTAKBANK","LTF","LICI",
        "MFSL","MUTHOOTFIN","PFC","RECLTD","SBICARD",
        "SBILIFE","SBIN","SHRIRAMFIN",
    ],
    "Nifty Capital Goods": [
        "ABB","BEL","BHEL","BDL","CGPOWER","CUMMINSIND",
        "HAVELLS","HAL","KAYNES","KEI","MAZDOCK",
        "POWERINDIA","SIEMENS","TIINDIA","VOLTAS",
    ],
    "Nifty Metal": [
        "ADANIENT","APLAPOLLO","HINDALCO","HINDZINC","JINDALSTEL",
        "JSWSTEEL","NATIONALUM","NMDC","SAIL","TATASTEEL","VEDL",
    ],
    "Nifty Energy": [
        "ADANIENSOL","ADANIGREEN","BPCL","COALINDIA","GAIL",
        "HINDPETRO","IOC","JSWENERGY","NHPC","NTPC","OIL",
        "ONGC","PETRONET","POWERGRID","TATAPOWER","TORNTPOWER",
        "SUZLON","WAAREEENER",
    ],
    "Nifty Realty": [
        "DLF","GODREJPROP","LODHA","OBEROIRLTY","PHOENIXLTD",
        "PRESTIGE",
    ],
    "Nifty PSU Bank": [
        "BANKBARODA","BANKINDIA","CANBK","INDIANB","PNB",
        "SBIN","UNIONBANK",
    ],
    "Nifty Infrastructure": [
        "ADANIPORTS","BHEL","CONCOR","GMRAIRPORT","LT",
        "NBCC","NTPC","POWERGRID","RVNL",
    ],
    "Nifty Consumption": [
        "BRITANNIA","COLPAL","DABUR","DMART","GODREJCP","HINDUNILVR",
        "INDHOTEL","ITC","JUBLFOOD","KALYANKJIL","MARICO","NESTLEIND",
        "PAGEIND","TATACONSUM","TITAN","TRENT","UNITDSPR","VBL",
    ],
    "Nifty Healthcare": [
        "ALKEM","APOLLOHOSP","AUROPHARMA","BIOCON","CIPLA","DIVISLAB",
        "DRREDDY","FORTIS","GLENMARK","LAURUSLABS","LUPIN","MANKIND",
        "MAXHEALTH","SYNGENE","SUNPHARMA","TORNTPHARM","ZYDUSLIFE","PPLPHARMA",
    ],
}

# =========================================================
# NSE INDICES BASKET
# =========================================================

NSE_INDEX_BASKET = [
    "NIFTY",
    "BANKNIFTY",
    "CNXIT",
    "CNX500",
    "CNXFINANCE",
    "CNXPHARMA",
    "CNXAUTO",
    "CNXMETAL",
    "CNXFMCG",
    "CNXPSUBANK",
    "CNXENERGY",
    "CNXREALTY",
    "NIFTYPVTBANK",
    "CNXINFRA",
    "NIFTYMIDCAP50",
    "NIFTY_HEALTHCARE",
    "NIFTY_OIL_AND_GAS",
    "CNXMEDIA",
    "CNXPSE",
    "NIFTY_CONSUMPTION",
    "CNXCOMMOD",
    "NIFTY_CAPITAL_MARKETS",
    "CNXSERVICE",
    "NIFTY_CHEMICALS",
    "CPSE",
    "NIFTY_INDIA_MANUFACTURING",
    "NIFTY_INDIA_DIGITAL",
    "NIFTY_INDIA_TOURISM",
    "NIFTY_IPO",
    "NIFTY_HOUSING",
]

NIFTY_CONSTITUENT_CSV_FILES = {
    "Nifty 50": "ind_nifty50list.csv",
    "Nifty 100": "ind_nifty100list.csv",
    "Nifty 200": "ind_nifty200list.csv",
    "Nifty 500": "ind_nifty500list.csv",
    "Nifty Midcap 50": "ind_niftymidcap50list.csv",
    "Nifty Midcap 100": "ind_niftymidcap100list.csv",
    "Nifty Smallcap 100": "ind_niftysmallcap100list.csv",
    "Nifty IT": "ind_niftyitlist.csv",
    "Nifty Bank": "ind_niftybanklist.csv",
    "Nifty FMCG": "ind_niftyfmcglist.csv",
    "Nifty Auto": "ind_niftyautolist.csv",
    "Nifty Pharma": "ind_niftypharmalist.csv",
    "Nifty Financial Services": "ind_niftyfinancelist.csv",
    "Nifty Capital Goods": "ind_niftycapitalgoodslist.csv",
    "Nifty Metal": "ind_niftymetallist.csv",
    "Nifty Energy": "ind_niftyenergylist.csv",
    "Nifty Realty": "ind_niftyrealtylist.csv",
    "Nifty PSU Bank": "ind_niftypsubanklist.csv",
    "Nifty Infrastructure": "ind_niftyinfralist.csv",
    "Nifty Consumption": "ind_niftyconsumptionlist.csv",
    "Nifty Healthcare": "ind_niftyhealthcarelist.csv",
}

# FIX: Force NSE-fallback-only for indices that Yahoo doesn't reliably serve
NSE_INDEX_TICKER_OVERRIDES = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "CNXIT": "^CNXIT",
    "CNX500": "^CRSLDX",
    "CNXFINANCE": "NIFTY_FIN_SERVICE.NS",
    "CNXPHARMA": "^CNXPHARMA",
    "CNXAUTO": "^CNXAUTO",
    "CNXMETAL": "^CNXMETAL",
    "CNXFMCG": "^CNXFMCG",
    "CNXPSUBANK": "^CNXPSUBANK",
    "CNXENERGY": "^CNXENERGY",
    "CNXREALTY": "^CNXREALTY",
    "NIFTYPVTBANK": "NIFTY_PVT_BANK.NS",
    "CNXINFRA": "^CNXINFRA",
    "NIFTYMIDCAP50": "^NSEMDCP50",
    # FIX: These don't work reliably on Yahoo — force NSE fallback path
    "NIFTY_HEALTHCARE": "__NSE_FALLBACK__",
    "NIFTY_OIL_AND_GAS": "__NSE_FALLBACK__",
    "NIFTY_CAPITAL_MARKETS": "__NSE_FALLBACK__",
    "NIFTY_CHEMICALS": "__NSE_FALLBACK__",
    "CPSE": "__NSE_FALLBACK__",
    "NIFTY_IPO": "__NSE_FALLBACK__",
    "NIFTY_HOUSING": "__NSE_FALLBACK__",
    "NIFTY_INDIA_MANUFACTURING": "__NSE_FALLBACK__",
    "NIFTY_INDIA_DIGITAL": "__NSE_FALLBACK__",
    "NIFTY_INDIA_TOURISM": "__NSE_FALLBACK__",
    "CNXMEDIA": "^CNXMEDIA",
    "CNXPSE": "^CNXPSE",
    "NIFTY_CONSUMPTION": "^CNXCONSUM",
    "CNXCOMMOD": "^CNXCMDT",
    "CNXSERVICE": "^CNXSERVICE",
}

NSE_INDEX_HIST_NAMES = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "CNXIT": "NIFTY IT",
    "CNX500": "NIFTY 500",
    "CNXFINANCE": "NIFTY FINANCIAL SERVICES",
    "CNXPHARMA": "NIFTY PHARMA",
    "CNXAUTO": "NIFTY AUTO",
    "CNXMETAL": "NIFTY METAL",
    "CNXFMCG": "NIFTY FMCG",
    "CNXPSUBANK": "NIFTY PSU BANK",
    "CNXENERGY": "NIFTY ENERGY",
    "CNXREALTY": "NIFTY REALTY",
    "NIFTYPVTBANK": "NIFTY PRIVATE BANK",
    "CNXINFRA": "NIFTY INFRASTRUCTURE",
    "NIFTYMIDCAP50": "NIFTY MIDCAP 50",
    "NIFTY_HEALTHCARE": "Nifty Healthcare Index",
    "NIFTY_OIL_AND_GAS": "Nifty Oil & Gas",
    "CNXMEDIA": "NIFTY MEDIA",
    "CNXPSE": "NIFTY PSE",
    "NIFTY_CONSUMPTION": "NIFTY CONSUMPTION",
    "CNXCOMMOD": "NIFTY COMMODITIES",
    "NIFTY_CAPITAL_MARKETS": "Nifty Capital Markets",
    "CNXSERVICE": "NIFTY SERVICES SECTOR",
    "NIFTY_CHEMICALS": "Nifty Chemicals",
    "CPSE": "Nifty CPSE",
    "NIFTY_INDIA_MANUFACTURING": "NIFTY INDIA MANUFACTURING",
    "NIFTY_INDIA_DIGITAL": "NIFTY INDIA DIGITAL",
    "NIFTY_INDIA_TOURISM": "NIFTY INDIA TOURISM",
    "NIFTY_IPO": "Nifty IPO",
    "NIFTY_HOUSING": "Nifty Housing",
}

NSE_FALLBACK_INDEX_NAMES = NSE_INDEX_HIST_NAMES.copy()
NSE_ARCHIVE_INDEX_SYMBOLS = set(NSE_INDEX_HIST_NAMES.keys())

NSE_INDEX_GROUPS = {
    "NIFTY": ("Broad Market", "Benchmark"),
    "BANKNIFTY": ("Financials", "Banking"),
    "CNXIT": ("Sectoral", "Information Technology"),
    "CNX500": ("Broad Market", "Large Broad Market"),
    "CNXFINANCE": ("Financials", "Financial Services"),
    "CNXPHARMA": ("Sectoral", "Pharmaceuticals"),
    "CNXAUTO": ("Sectoral", "Automobiles"),
    "CNXMETAL": ("Sectoral", "Metals"),
    "CNXFMCG": ("Sectoral", "Fast Moving Consumer Goods"),
    "CNXPSUBANK": ("Financials", "Public Sector Banks"),
    "CNXENERGY": ("Sectoral", "Energy"),
    "CNXREALTY": ("Sectoral", "Realty"),
    "NIFTYPVTBANK": ("Financials", "Private Banks"),
    "CNXINFRA": ("Sectoral", "Infrastructure"),
    "NIFTYMIDCAP50": ("Broad Market", "Midcap 50"),
    "NIFTY_HEALTHCARE": ("Sectoral", "Healthcare"),
    "NIFTY_OIL_AND_GAS": ("Sectoral", "Oil & Gas"),
    "CNXMEDIA": ("Sectoral", "Media"),
    "CNXPSE": ("Sectoral", "Public Sector Enterprises"),
    "NIFTY_CONSUMPTION": ("Sectoral", "Consumption"),
    "CNXCOMMOD": ("Sectoral", "Commodities"),
    "NIFTY_CAPITAL_MARKETS": ("Sectoral", "Capital Markets"),
    "CNXSERVICE": ("Sectoral", "Services"),
    "NIFTY_CHEMICALS": ("Sectoral", "Chemicals"),
    "CPSE": ("Thematic", "CPSE"),
    "NIFTY_INDIA_MANUFACTURING": ("Thematic", "India Manufacturing"),
    "NIFTY_INDIA_DIGITAL": ("Thematic", "India Digital"),
    "NIFTY_INDIA_TOURISM": ("Thematic", "India Tourism"),
    "NIFTY_IPO": ("Thematic", "IPO"),
    "NIFTY_HOUSING": ("Thematic", "Housing"),
}

# =========================================================
# FAST TICKER RESOLVER
# =========================================================

def resolve_all_tickers(symbols_tuple):
    symbols = list(symbols_tuple)
    resolved = {}
    for s in symbols:
        if s in NSE_INDEX_TICKER_OVERRIDES:
            ticker = NSE_INDEX_TICKER_OVERRIDES[s]
            if ticker != "__NSE_FALLBACK__":
                resolved[s] = ticker
            # Skip __NSE_FALLBACK__ — handled by download_nse_fallback_indices
        elif s == "LTM":
            resolved[s] = "LTM"
        else:
            resolved[s] = KNOWN_TICKER_OVERRIDES.get(s, quote(s, safe="-_.^"))
    return resolved

# =========================================================
# SECTOR + INDUSTRY MAPPING
# =========================================================

def load_stock_data_from_csv():
    csv_path = next((p for p in SECTOR_CSV_PATHS if p.exists()), None)
    csv_mapping = {}

    if csv_path is not None:
        sector_df = pd.read_csv(csv_path)
        sector_df.columns = [str(c).strip() for c in sector_df.columns]
        required = {"Stock Name", "Sector", "Basic Industry"}
        missing = required - set(sector_df.columns)
        if missing:
            st.error("Sector CSV missing columns: " + ", ".join(sorted(missing)))
            st.stop()

        sector_df["Stock Name"] = (
            sector_df["Stock Name"].astype(str).str.strip().str.upper()
            .replace(CSV_SYMBOL_ALIASES)
        )
        sector_df = sector_df[~sector_df["Stock Name"].isin(EXCLUDED_SYMBOLS)]
        sector_df["Sector"] = sector_df["Sector"].astype(str).str.strip()
        sector_df["Basic Industry"] = sector_df["Basic Industry"].astype(str).str.strip()

        csv_mapping = {
            row["Stock Name"]: {"Sector": row["Sector"], "Industry": row["Basic Industry"]}
            for _, row in sector_df.iterrows()
            if row["Stock Name"] and row["Stock Name"] != "NAN"
        }

    csv_mapping.update(MANUAL_STOCK_DATA_OVERRIDES)

    stock_data = {
        s: csv_mapping.get(s, {"Sector": "Others", "Industry": "Others"})
        for s in ALL_STOCKS
        if s not in EXCLUDED_SYMBOLS
    }
    return stock_data, csv_path

def load_nse_universe():
    nse_path = next((p for p in NSE_UNIVERSE_CSV_PATHS if p.exists()), None)
    if nse_path is None:
        return None, None
    df = pd.read_csv(nse_path)
    df.columns = [str(c).strip() for c in df.columns]
    df["Stock Name"] = (
        df["Stock Name"].astype(str).str.strip().str.upper()
        .replace(CSV_SYMBOL_ALIASES)
    )
    df = df[~df["Stock Name"].isin(EXCLUDED_SYMBOLS)]
    return df, nse_path

STOCK_DATA, STOCK_DATA_SOURCE = load_stock_data_from_csv()
NSE_DF, NSE_CSV_SOURCE = load_nse_universe()

# =========================================================
# HELPERS
# =========================================================

def yahoo_symbol(s, ticker_map=None):
    if ticker_map and s in ticker_map:
        return to_yahoo_ticker(ticker_map[s])
    return to_yahoo_ticker(quote(s, safe='-_.^'))


def _safe_last(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return np.nan
    return float(s.iloc[-1])


def _safe_return(series: pd.Series, periods: int):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 2:
        return np.nan
    actual_periods = min(periods, len(s) - 1)
    prev = s.iloc[-1 - actual_periods]
    if prev == 0 or pd.isna(prev):
        return np.nan
    return float((s.iloc[-1] / prev - 1) * 100)


def _safe_high(series: pd.Series, window: int = 252):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return np.nan
    return float(s.tail(min(window, len(s))).max())


def _safe_low(series: pd.Series, window: int = 252):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return np.nan
    return float(s.tail(min(window, len(s))).min())


def _has_enough_index_history(close_df: pd.DataFrame, symbol: str, min_rows: int = MIN_NSE_INDEX_HISTORY_ROWS) -> bool:
    if close_df is None or close_df.empty or symbol not in close_df.columns:
        return False
    series = pd.to_numeric(close_df[symbol], errors="coerce").dropna()
    if len(series) < min_rows:
        return False
    try:
        monthly_points = series.resample("ME").last().dropna()
        return len(monthly_points) >= 2
    except Exception:
        return False


def _normalize_symbol(raw: str) -> str:
    symbol = str(raw).strip().upper()
    if not symbol:
        return symbol
    symbol = symbol.replace(".NS", "").replace(".BO", "")
    return CSV_SYMBOL_ALIASES.get(symbol, symbol)


def _is_real_symbol(symbol: str) -> bool:
    s = str(symbol).strip().upper()
    if not s:
        return False
    if s.startswith("DUMMY") or "DUMMY" in s:
        return False
    return s not in EXCLUDED_SYMBOLS


def _nse_universe_top_symbols(limit: int):
    if NSE_DF is None or NSE_DF.empty or "Stock Name" not in NSE_DF.columns:
        return []
    df = NSE_DF.copy()
    df["Stock Name"] = df["Stock Name"].map(_normalize_symbol)
    df = df[df["Stock Name"].map(_is_real_symbol)]
    if "Market Cap" in df.columns:
        market_cap = (
            df["Market Cap"]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("Cr", "", regex=False)
            .str.replace("₹", "", regex=False)
            .str.strip()
        )
        df["_MarketCapNum"] = pd.to_numeric(market_cap, errors="coerce")
        df = df.sort_values("_MarketCapNum", ascending=False, na_position="last")
    symbols = [s for s in dict.fromkeys(df["Stock Name"].dropna().tolist()) if _is_real_symbol(s)]
    return symbols[:limit]


NIFTY_EXPECTED_COUNTS = {
    "Nifty 50": 50,
    "Nifty 100": 100,
    "Nifty 200": 200,
    "Nifty 500": 500,
}


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_nifty_index_constituents(index_name: str):
    fallback = list(dict.fromkeys(NIFTY_INDICES.get(index_name, [])))
    fallback = [s for s in fallback if _is_real_symbol(s)]
    csv_file = NIFTY_CONSTITUENT_CSV_FILES.get(index_name)
    if not csv_file:
        return fallback, "manual fallback"

    url = f"https://www.niftyindices.com/IndexConstituent/{csv_file}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Referer": "https://www.niftyindices.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200 or not resp.text.strip():
            return fallback, "manual fallback"
        df = pd.read_csv(io.StringIO(resp.text))
        symbol_col = next((c for c in df.columns if str(c).strip().lower() == "symbol"), None)
        if symbol_col is None:
            symbol_col = next((c for c in df.columns if "symbol" in str(c).lower()), None)
        if symbol_col is None:
            return fallback, "manual fallback"
        symbols = [_normalize_symbol(s) for s in df[symbol_col].dropna().tolist()]
        symbols = [s for s in dict.fromkeys(symbols) if _is_real_symbol(s)]
        expected = NIFTY_EXPECTED_COUNTS.get(index_name)
        if expected and len(symbols) < int(expected * 0.9):
            nse_symbols = _nse_universe_top_symbols(expected)
            if len(nse_symbols) >= int(expected * 0.9):
                return nse_symbols, "local NSE universe top market-cap fallback"
        return (symbols or fallback), "official Nifty Indices CSV"
    except Exception:
        expected = NIFTY_EXPECTED_COUNTS.get(index_name)
        if expected:
            nse_symbols = _nse_universe_top_symbols(expected)
            if len(nse_symbols) >= int(expected * 0.9):
                return nse_symbols, "local NSE universe top market-cap fallback"
        return fallback, "manual fallback"


def _composite(close_df):
    if close_df is None or close_df.empty:
        return pd.Series(dtype=float)
    close_df = close_df.apply(pd.to_numeric, errors="coerce")

    def _series_return(series: pd.Series, periods: int):
        s = pd.to_numeric(series, errors="coerce").dropna()
        if len(s) < 2:
            return np.nan
        lookback = min(periods, len(s) - 1)
        base = s.iloc[-lookback - 1]
        if pd.isna(base) or base == 0:
            return np.nan
        return (s.iloc[-1] / base - 1) * 100

    scores = {}
    for symbol in close_df.columns:
        s = close_df[symbol]
        r3 = _series_return(s, 63)
        r6 = _series_return(s, 126)
        r9 = _series_return(s, 189)
        r12 = _series_return(s, 252)

        if pd.isna(r3):
            r3 = _series_return(s, 21)
        if pd.isna(r6):
            r6 = r3
        if pd.isna(r9):
            r9 = r6
        if pd.isna(r12):
            r12 = r9

        if not pd.isna(r3):
            scores[symbol] = r3 * 0.4 + r6 * 0.2 + r9 * 0.2 + r12 * 0.2

    return pd.Series(scores, dtype=float)


def compute_yearly_returns_from_listing(close_df: pd.DataFrame) -> pd.DataFrame:
    if close_df is None or close_df.empty:
        return pd.DataFrame()

    cf = close_df.apply(pd.to_numeric, errors="coerce").sort_index()
    yearly_last = cf.resample("YE").last()
    yearly_returns = yearly_last.pct_change() * 100

    for symbol in cf.columns:
        series = cf[symbol].dropna()
        if series.empty:
            continue
        first_year = series.index[0].year
        first_year_rows = yearly_returns.index[yearly_returns.index.year == first_year]
        if len(first_year_rows) == 0:
            continue
        year_end_idx = first_year_rows[0]
        year_end = yearly_last.at[year_end_idx, symbol] if symbol in yearly_last.columns else np.nan
        first_price = series.iloc[0]
        if pd.notna(year_end) and pd.notna(first_price) and first_price != 0:
            yearly_returns.at[year_end_idx, symbol] = (year_end / first_price - 1) * 100

    return yearly_returns


def build_history_availability_notes(close_df: pd.DataFrame, symbols: list) -> pd.DataFrame:
    rows = []
    if close_df is None:
        close_df = pd.DataFrame()

    for symbol in symbols:
        if symbol not in close_df.columns:
            rows.append({
                "Symbol": symbol,
                "First Available Date": "-",
                "Reason": "No historical prices downloaded; ticker may be unresolved or unavailable.",
            })
            continue

        series = pd.to_numeric(close_df[symbol], errors="coerce").dropna()
        if series.empty:
            rows.append({
                "Symbol": symbol,
                "First Available Date": "-",
                "Reason": "Yahoo Finance returned the ticker but no usable historical close prices.",
            })
            continue

        first_date = series.index.min()
        rows.append({
            "Symbol": symbol,
            "First Available Date": first_date.strftime("%Y-%m-%d"),
            "Reason": f"History starts on {first_date.strftime('%Y-%m-%d')}.",
        })

    return pd.DataFrame(rows)


def compute_rs_vs_nifty50(close_df, nifty_close):
    stock_raw = _composite(close_df)
    if stock_raw.empty:
        return pd.Series(dtype="Int64")

    if nifty_close is None:
        return pd.Series(50, index=stock_raw.index, dtype="Int64")

    nifty_series = pd.to_numeric(nifty_close, errors="coerce").dropna()
    if nifty_series.empty:
        return pd.Series(50, index=stock_raw.index, dtype="Int64")

    nifty_raw = _composite(nifty_series.to_frame("NSEI"))
    if nifty_raw.empty:
        return pd.Series(50, index=stock_raw.index, dtype="Int64")

    relative = stock_raw.copy()
    ranks = relative.rank(pct=True) * 99
    return ranks.fillna(50).clip(1, 99).round(0).astype("Int64")


def compute_rs_vs_benchmark(close_df, benchmark_close):
    return compute_rs_vs_nifty50(close_df, benchmark_close)


def compute_rs_sectoral(close_df, sector_map):
    raw = _composite(close_df)
    if raw.empty:
        return pd.Series(dtype="Int64")

    sectors = pd.Series(sector_map)
    result = pd.Series(50, index=raw.index, dtype="Float64")

    for sec in sectors.dropna().unique():
        members = [m for m in sectors[sectors == sec].index if m in raw.index]
        if not members:
            continue
        if len(members) == 1:
            result.loc[members] = 50
            continue
        ranked = raw[members].rank(pct=True, method="average") * 99
        result.loc[members] = ranked.clip(1, 99)

    return result.fillna(50).round(0).astype("Int64")


def _extract_price_frame(raw, field, batch, yahoo_to_orig):
    if raw is None or raw.empty:
        return pd.DataFrame()

    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if field not in raw.columns.get_level_values(0):
                return pd.DataFrame()
            df = raw[field]
        else:
            if field not in raw.columns:
                return pd.DataFrame()
            df = raw[field]
    except Exception:
        return pd.DataFrame()

    if isinstance(df, pd.Series):
        yt = batch[0]
        orig = yahoo_to_orig.get(yt, yt.replace(".NS", ""))
        df = df.to_frame(name=orig)
    else:
        rename_map = {yt: yahoo_to_orig.get(yt, yt.replace(".NS", "")) for yt in df.columns}
        df = df.rename(columns=rename_map)

    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def _download_raw_batch(batch, start=None, period=None):
    for attempt in range(2):
        try:
            kwargs = dict(
                tickers=batch,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if period is not None:
                kwargs["period"] = period
            else:
                kwargs["start"] = start or START_DATE
            raw = yf.download(**kwargs)
            if raw is not None and not raw.empty:
                return raw
        except Exception:
            pass
        if period == FULL_HISTORY_PERIOD:
            try:
                raw = yf.download(
                    tickers=batch,
                    start=start or FULL_HISTORY_START_DATE,
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                if raw is not None and not raw.empty:
                    return raw
            except Exception:
                pass
        time.sleep(0.6 * (attempt + 1))
    return pd.DataFrame()


def _today_floor() -> pd.Timestamp:
    return pd.Timestamp(datetime.now().date())


def _read_market_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()].sort_index()
        df = df.loc[:, ~df.columns.duplicated()]
        return df.apply(pd.to_numeric, errors="coerce")
    except Exception:
        return pd.DataFrame()


def _write_market_csv(df: pd.DataFrame, path: Path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = _dedupe_columns(df)
        out.to_csv(path, index_label="Date")
    except Exception:
        pass


def _split_history_and_today(df: pd.DataFrame) -> tuple:
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    cleaned = _dedupe_columns(df)
    today = _today_floor()
    normalized = pd.to_datetime(cleaned.index).normalize()
    history = cleaned.loc[normalized < today]
    today_df = cleaned.loc[normalized >= today]
    return history, today_df


def _load_csv_market_payload():
    """
    FIX: Load historical + today data from local CSVs.
    This is the primary fast path — uses your local files directly.
    """
    close_hist = _read_market_csv(HISTORICAL_CLOSE_CSV)
    high_hist = _read_market_csv(HISTORICAL_HIGH_CSV)
    low_hist = _read_market_csv(HISTORICAL_LOW_CSV)
    close_today = _read_market_csv(TODAY_CLOSE_CSV)
    high_today = _read_market_csv(TODAY_HIGH_CSV)
    low_today = _read_market_csv(TODAY_LOW_CSV)

    # Check if any data was loaded at all
    if close_hist.empty and close_today.empty:
        return None

    close_hist_old, close_today_current = _split_history_and_today(_merge_time_series_frames(close_hist, close_today))
    high_hist_old, high_today_current = _split_history_and_today(_merge_time_series_frames(high_hist, high_today))
    low_hist_old, low_today_current = _split_history_and_today(_merge_time_series_frames(low_hist, low_today))

    if not close_hist_old.empty:
        _write_market_csv(close_hist_old, HISTORICAL_CLOSE_CSV)
    if not high_hist_old.empty:
        _write_market_csv(high_hist_old, HISTORICAL_HIGH_CSV)
    if not low_hist_old.empty:
        _write_market_csv(low_hist_old, HISTORICAL_LOW_CSV)
    _write_market_csv(close_today_current, TODAY_CLOSE_CSV)
    _write_market_csv(high_today_current, TODAY_HIGH_CSV)
    _write_market_csv(low_today_current, TODAY_LOW_CSV)

    close_df = _merge_time_series_frames(close_hist_old, close_today_current)
    high_df = _merge_time_series_frames(high_hist_old, high_today_current)
    low_df = _merge_time_series_frames(low_hist_old, low_today_current)

    if close_df.empty and high_df.empty and low_df.empty:
        return None

    try:
        with open(CSV_MARKET_META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}

    return {
        "schema_version": int(meta.get("schema_version", CACHE_SCHEMA_VERSION)),
        "updated_at": int(meta.get("updated_at", 0)),
        "close": close_df,
        "high": high_df,
        "low": low_df,
        "ticker_map": meta.get("ticker_map", {}),
    }


def _save_csv_market_payload(payload: dict):
    close_df = payload.get("close", pd.DataFrame())
    high_df = payload.get("high", pd.DataFrame())
    low_df = payload.get("low", pd.DataFrame())

    close_hist, close_today = _split_history_and_today(close_df)
    high_hist, high_today = _split_history_and_today(high_df)
    low_hist, low_today = _split_history_and_today(low_df)

    _write_market_csv(close_hist, HISTORICAL_CLOSE_CSV)
    _write_market_csv(high_hist, HISTORICAL_HIGH_CSV)
    _write_market_csv(low_hist, HISTORICAL_LOW_CSV)
    _write_market_csv(close_today, TODAY_CLOSE_CSV)
    _write_market_csv(high_today, TODAY_HIGH_CSV)
    _write_market_csv(low_today, TODAY_LOW_CSV)

    try:
        MARKET_DATA_DIR.mkdir(parents=True, exist_ok=True)
        meta = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "updated_at": int(time.time()),
            "history_saved_till": (_today_floor() - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "today_live_date": _today_floor().strftime("%Y-%m-%d"),
            "symbols": len(close_df.columns) if isinstance(close_df, pd.DataFrame) else 0,
            "ticker_map": payload.get("ticker_map", {}),
        }
        with open(CSV_MARKET_META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f)
    except Exception:
        pass


def _init_market_sqlite():
    MARKET_DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MARKET_SQLITE_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            close REAL,
            high REAL,
            low REAL,
            updated_at INTEGER,
            PRIMARY KEY (date, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_symbol_date ON prices(symbol, date)")
    conn.commit()
    return conn


def _load_sqlite_market_payload(symbols=None):
    if not MARKET_SQLITE_PATH.exists():
        return None
    symbols = list(dict.fromkeys(symbols or []))
    try:
        conn = _init_market_sqlite()
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            query = f"SELECT date, symbol, close, high, low FROM prices WHERE symbol IN ({placeholders})"
            df = pd.read_sql_query(query, conn, params=symbols, parse_dates=["date"])
        else:
            df = pd.read_sql_query("SELECT date, symbol, close, high, low FROM prices", conn, parse_dates=["date"])
        meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
        conn.close()
    except Exception:
        return None

    if df.empty:
        return None

    def _pivot(field):
        out = df.pivot_table(index="date", columns="symbol", values=field, aggfunc="last")
        out.index = pd.to_datetime(out.index)
        out = out.sort_index()
        out = out.dropna(axis=1, how="all")
        return out

    meta = {k: v for k, v in meta_rows}
    try:
        ticker_map = json.loads(meta.get("ticker_map", "{}"))
    except Exception:
        ticker_map = {}

    return {
        "schema_version": int(meta.get("schema_version", CACHE_SCHEMA_VERSION)),
        "updated_at": int(meta.get("updated_at", 0)),
        "close": _pivot("close"),
        "high": _pivot("high"),
        "low": _pivot("low"),
        "ticker_map": ticker_map,
    }


# FIX: Remove dropna=True — not supported in pandas 2.x new stack implementation
def _save_sqlite_market_payload(payload: dict):
    close_df = _dedupe_columns(payload.get("close", pd.DataFrame()))
    high_df = _dedupe_columns(payload.get("high", pd.DataFrame()))
    low_df = _dedupe_columns(payload.get("low", pd.DataFrame()))

    parts = []
    for field, frame in (("close", close_df), ("high", high_df), ("low", low_df)):
        if frame is None or frame.empty:
            continue
        # FIX: Remove dropna=True — pandas 2.x no longer accepts this argument
        long = frame.stack().rename(field).reset_index()
        long.columns = ["date", "symbol", field]
        parts.append(long)

    if not parts:
        return

    try:
        merged = parts[0]
        for part in parts[1:]:
            merged = merged.merge(part, on=["date", "symbol"], how="outer")
        for field in ("close", "high", "low"):
            if field not in merged.columns:
                merged[field] = None
        merged = merged.dropna(subset=["close", "high", "low"], how="all")
        if merged.empty:
            return
        merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
        merged["updated_at"] = int(time.time())
        merged = merged.replace({np.nan: None})

        conn = _init_market_sqlite()
        conn.executemany("""
            INSERT INTO prices(date, symbol, close, high, low, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, symbol) DO UPDATE SET
                close=excluded.close,
                high=excluded.high,
                low=excluded.low,
                updated_at=excluded.updated_at
        """, merged[["date", "symbol", "close", "high", "low", "updated_at"]].itertuples(index=False, name=None))
        meta = {
            "schema_version": str(CACHE_SCHEMA_VERSION),
            "updated_at": str(int(time.time())),
            "ticker_map": json.dumps(payload.get("ticker_map", {})),
        }
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            list(meta.items()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # Don't crash the app if sqlite save fails
        pass


def load_market_cache(symbols=None):
    """
    Market prices are SQLite-first. If SQLite is missing, callers bootstrap
    it by downloading historical data from Yahoo/NSE instead of reading the
    old large CSV price cache.
    """
    sqlite_payload = _load_sqlite_market_payload(symbols=symbols)
    if sqlite_payload is not None:
        return sqlite_payload
    return None


def save_market_cache(payload: dict):
    _save_sqlite_market_payload(payload)


def _merge_time_series_frames(old_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    if old_df is None or old_df.empty:
        return new_df.copy() if new_df is not None else pd.DataFrame()
    if new_df is None or new_df.empty:
        return old_df.copy()

    old = old_df.copy()
    new = new_df.copy()
    old.index = pd.to_datetime(old.index)
    new.index = pd.to_datetime(new.index)
    old = old.sort_index().loc[:, ~old.columns.duplicated()]
    new = new.sort_index().loc[:, ~new.columns.duplicated()]

    merged = old.combine_first(new)
    merged.update(new)
    return merged.sort_index().loc[:, ~merged.columns.duplicated()]


def _subset_market_payload(payload: dict, symbols: list) -> tuple:
    close_df = payload.get("close", pd.DataFrame()).copy()
    high_df = payload.get("high", pd.DataFrame()).copy()
    low_df = payload.get("low", pd.DataFrame()).copy()
    ticker_map = payload.get("ticker_map", {}).copy()

    wanted = [s for s in symbols if s in close_df.columns]
    if wanted:
        close_df = close_df[wanted]
        if not high_df.empty:
            high_df = high_df[[c for c in wanted if c in high_df.columns]]
        if not low_df.empty:
            low_df = low_df[[c for c in wanted if c in low_df.columns]]
    else:
        close_df = pd.DataFrame(index=close_df.index)
        high_df = pd.DataFrame(index=high_df.index) if not high_df.empty else pd.DataFrame()
        low_df = pd.DataFrame(index=low_df.index) if not low_df.empty else pd.DataFrame()

    ticker_map = {s: ticker_map.get(s, s) for s in symbols}
    return close_df, high_df, low_df, ticker_map


def _fresh_enough(payload: dict) -> bool:
    try:
        updated_at = int(payload.get("updated_at", 0))
        return (int(time.time()) - updated_at) < STALE_CACHE_SECONDS
    except Exception:
        return False


def _dedupe_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.loc[:, ~df.columns.duplicated()]
    return df


def _finalize_market_frames(close_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame):
    close_df = _dedupe_columns(close_df)
    high_df = _dedupe_columns(high_df)
    low_df = _dedupe_columns(low_df)

    for name, frame in (("close", close_df), ("high", high_df), ("low", low_df)):
        if frame is not None and not frame.empty:
            frame = frame.dropna(axis=1, how="all")
            if name == "close":
                close_df = frame
            elif name == "high":
                high_df = frame
            else:
                low_df = frame

    return close_df, high_df, low_df


def _symbols_with_usable_close(close_df: pd.DataFrame, symbols: list) -> list:
    if close_df is None or close_df.empty:
        return []
    usable = []
    for symbol in symbols:
        if symbol not in close_df.columns:
            continue
        series = pd.to_numeric(close_df[symbol], errors="coerce").dropna()
        if not series.empty:
            usable.append(symbol)
    return usable


def _payload_has_usable_symbols(payload: dict, symbols: list) -> bool:
    close_df = payload.get("close", pd.DataFrame())
    return set(symbols).issubset(set(_symbols_with_usable_close(close_df, symbols)))


def _should_have_today_data() -> bool:
    now = pd.Timestamp.now(tz="Asia/Kolkata")
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    return now >= market_open


def _payload_has_today_data(payload: dict, symbols: list) -> bool:
    if not _should_have_today_data():
        return True
    close_df = payload.get("close", pd.DataFrame())
    if close_df is None or close_df.empty:
        return False
    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
    frame = close_df.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce").tz_localize(None)
    frame = frame[frame.index.normalize() == today]
    if frame.empty:
        return False
    usable_today = set(_symbols_with_usable_close(frame, symbols))
    return set(symbols).issubset(usable_today)


BATCH_SIZE = 180


def _fetch_batches(symbols: list, yahoo_to_orig: dict, start=None, period=None, show_progress=True):
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    orig_to_yahoo = {v: k for k, v in yahoo_to_orig.items()}
    yahoo_tickers = []
    for orig in symbols:
        yt = orig_to_yahoo.get(orig)
        if yt is None:
            yt = to_yahoo_ticker(orig)
        yahoo_tickers.append(yt)

    batches = [yahoo_tickers[i:i + BATCH_SIZE] for i in range(0, len(yahoo_tickers), BATCH_SIZE)]
    close_parts = []
    high_parts = []
    low_parts = []

    progress_bar = st.progress(0, text="Downloading market data\u2026") if show_progress else None
    total = max(len(batches), 1)

    for idx, batch in enumerate(batches):
        if progress_bar is not None:
            progress_bar.progress((idx + 1) / total, text=f"Downloading batch {idx + 1}/{total} ({len(batch)} stocks)\u2026")

        raw = _download_raw_batch(batch, start=start, period=period)
        if raw.empty:
            for yt in batch:
                orig = yahoo_to_orig.get(yt, yt.replace(".NS", ""))
                c, h, l = _download_single(yt, orig, start=start, period=period)
                if not c.empty: close_parts.append(c)
                if not h.empty: high_parts.append(h)
                if not l.empty: low_parts.append(l)
            continue

        c = _extract_price_frame(raw, "Close", batch, yahoo_to_orig)
        h = _extract_price_frame(raw, "High", batch, yahoo_to_orig)
        l = _extract_price_frame(raw, "Low", batch, yahoo_to_orig)

        if not c.empty: close_parts.append(c)
        if not h.empty: high_parts.append(h)
        if not l.empty: low_parts.append(l)

        loaded = set(c.columns) if not c.empty else set()
        missing = [yt for yt in batch if yahoo_to_orig.get(yt, yt.replace(".NS", "")) not in loaded]
        for yt in missing:
            orig = yahoo_to_orig.get(yt, yt.replace(".NS", ""))
            c2, h2, l2 = _download_single(yt, orig, start=start, period=period)
            if not c2.empty: close_parts.append(c2)
            if not h2.empty: high_parts.append(h2)
            if not l2.empty: low_parts.append(l2)

    if progress_bar is not None:
        progress_bar.empty()

    def _merge(parts):
        if not parts:
            return pd.DataFrame()
        cleaned = []
        for part in parts:
            if part is None or part.empty:
                continue
            part = part.copy()
            part.index = pd.to_datetime(part.index)
            part = part.sort_index()
            if not part.index.is_unique:
                part = part[~part.index.duplicated(keep="last")]
            part = part.loc[:, ~part.columns.duplicated()]
            cleaned.append(part)
        if not cleaned:
            return pd.DataFrame()
        merged = pd.concat(cleaned, axis=1, sort=False)
        merged.index = pd.to_datetime(merged.index)
        merged = merged.sort_index()
        if not merged.index.is_unique:
            merged = merged[~merged.index.duplicated(keep="last")]
        merged = merged.loc[:, ~merged.columns.duplicated()]
        return merged

    return _merge(close_parts), _merge(high_parts), _merge(low_parts)


def _download_single(yt, orig, start=None, period=None):
    for attempt in range(2):
        try:
            if orig == "LTM" or to_yahoo_ticker(yt) == "LTM.NS":
                hist_kwargs = {
                    "auto_adjust": True,
                    "actions": False,
                }
                if period is not None:
                    hist_kwargs["period"] = period
                else:
                    hist_kwargs["start"] = start or FULL_HISTORY_START_DATE
                raw = yf.Ticker("LTM.NS").history(**hist_kwargs)
                if raw is None or raw.empty:
                    raise ValueError("empty")
                raw.index = pd.to_datetime(raw.index)
                close = raw[["Close"]].rename(columns={"Close": orig}) if "Close" in raw.columns else pd.DataFrame()
                high = raw[["High"]].rename(columns={"High": orig}) if "High" in raw.columns else pd.DataFrame()
                low = raw[["Low"]].rename(columns={"Low": orig}) if "Low" in raw.columns else pd.DataFrame()
                return close, high, low

            kwargs = dict(
                tickers=[yt],
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if period is not None:
                kwargs["period"] = period
            else:
                kwargs["start"] = start or START_DATE
            raw = yf.download(**kwargs)
            if (raw is None or raw.empty) and period == FULL_HISTORY_PERIOD:
                kwargs.pop("period", None)
                kwargs["start"] = start or FULL_HISTORY_START_DATE
                raw = yf.download(**kwargs)
            if raw is None or raw.empty:
                raise ValueError("empty")

            result = {}
            for field in ["Close", "High", "Low"]:
                df = _extract_price_frame(raw, field, [yt], {yt: orig})
                if not df.empty:
                    result[field] = df

            if result:
                return result.get("Close", pd.DataFrame()), result.get("High", pd.DataFrame()), result.get("Low", pd.DataFrame())
        except Exception:
            pass
        time.sleep(0.5 * (attempt + 1))

    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def download_with_resolved_tickers(symbols):
    """
    SQLite-first market data flow:
    - If SQLite already has fresh usable rows, read from SQLite.
    - If SQLite is missing/incomplete, fetch historical data from Yahoo/NSE.
    - Save fetched data into SQLite, then return the SQLite-shaped payload.
    """
    symbols = list(dict.fromkeys(symbols))
    ticker_map = resolve_all_tickers(tuple(symbols))

    # Step 1: Try SQLite cache only.
    payload = load_market_cache(symbols)
    if payload is not None and int(payload.get("schema_version", 0)) != CACHE_SCHEMA_VERSION:
        payload = None

    # Step 2: If cache is fresh and has usable close data for all symbols, return immediately
    if payload is not None:
        if (
            _payload_has_usable_symbols(payload, symbols)
            and _payload_has_today_data(payload, symbols)
            and _fresh_enough(payload)
        ):
            return _subset_market_payload(payload, symbols)

    # Step 3: Identify what's missing from local cache
    base_close = pd.DataFrame()
    base_high = pd.DataFrame()
    base_low = pd.DataFrame()
    base_ticker_map = ticker_map.copy()

    if payload is not None:
        base_close = payload.get("close", pd.DataFrame()).copy()
        base_high = payload.get("high", pd.DataFrame()).copy()
        base_low = payload.get("low", pd.DataFrame()).copy()
        base_ticker_map.update(payload.get("ticker_map", {}))
        base_ticker_map.update(ticker_map)

    usable_cached = set(_symbols_with_usable_close(base_close, symbols))

    # FIX: Only skip Yahoo tickers for NSE fallback symbols
    yahoo_symbols = [
        s for s in symbols
        if NSE_INDEX_TICKER_OVERRIDES.get(s) != "__NSE_FALLBACK__"
    ]
    missing_full = [s for s in yahoo_symbols if s not in usable_cached]
    recent_only = [s for s in yahoo_symbols if s in usable_cached]

    close_parts = []
    high_parts = []
    low_parts = []

    # Download full history only for truly missing symbols
    if missing_full:
        close_m, high_m, low_m = _fetch_batches(
            missing_full,
            {to_yahoo_ticker(ticker_map.get(s, s)): s for s in missing_full},
            start=FULL_HISTORY_START_DATE,
            period=None,
            show_progress=True,
        )
        if not close_m.empty:
            close_parts.append(close_m)
        if not high_m.empty:
            high_parts.append(high_m)
        if not low_m.empty:
            low_parts.append(low_m)

    # Refresh only today's candle for cached symbols (fast path)
    if recent_only:
        recent_map = {to_yahoo_ticker(ticker_map.get(s, s)): s for s in recent_only}
        close_r, high_r, low_r = _fetch_batches(
            recent_only,
            recent_map,
            period=TODAY_REFRESH_PERIOD,
            show_progress=bool(not missing_full),
        )
        if not close_r.empty:
            close_parts.append(close_r)
        if not high_r.empty:
            high_parts.append(high_r)
        if not low_r.empty:
            low_parts.append(low_r)

    # Merge with base cache
    close_df = base_close
    high_df = base_high
    low_df = base_low

    for part in close_parts:
        close_df = _merge_time_series_frames(close_df, part)
    for part in high_parts:
        high_df = _merge_time_series_frames(high_df, part)
    for part in low_parts:
        low_df = _merge_time_series_frames(low_df, part)

    close_df, high_df, low_df = _finalize_market_frames(close_df, high_df, low_df)
    available_after_fetch = set(_symbols_with_usable_close(close_df, symbols))
    if payload is not None and missing_full:
        still_missing = [s for s in missing_full if s not in available_after_fetch]
        if still_missing:
            fallback_close, fallback_high, fallback_low = _subset_market_payload(payload, still_missing)[:3]
            close_df = _merge_time_series_frames(close_df, fallback_close)
            high_df = _merge_time_series_frames(high_df, fallback_high)
            low_df = _merge_time_series_frames(low_df, fallback_low)
            close_df, high_df, low_df = _finalize_market_frames(close_df, high_df, low_df)

    updated_payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "updated_at": int(time.time()),
        "close": close_df,
        "high": high_df,
        "low": low_df,
        "ticker_map": base_ticker_map,
    }
    save_market_cache(updated_payload)

    return _subset_market_payload(updated_payload, symbols)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def download_nse_fallback_indices(symbols_tuple):
    """
    FIX: Download NSE indices via NSE's historical index endpoints.
    All problematic indices (NIFTY_HEALTHCARE, NIFTY_OIL_AND_GAS, etc.)
    now route exclusively through this path.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _session():
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://www.nseindia.com/",
            "Origin": "https://www.nseindia.com",
        })
        try:
            session.get("https://www.nseindia.com", timeout=5)
        except Exception:
            pass
        return session

    def _candidate_names(name: str):
        if not name:
            return []
        base = " ".join(str(name).strip().split())
        candidates = [base]
        # Add uppercase variant
        candidates.append(base.upper())
        # Add title case
        candidates.append(base.title())
        if " & " in base:
            candidates.append(base.replace(" & ", " AND "))
            candidates.append(base.upper().replace(" & ", " AND "))
        if " AND " in base:
            candidates.append(base.replace(" AND ", " & "))
        if "SECTOR" in base.upper() and "SECTORS" not in base.upper():
            candidates.append(base.upper().replace("SECTOR", "SECTORS"))
        # Remove duplicates while preserving order
        out, seen = [], set()
        for item in candidates:
            item = " ".join(str(item).split())
            if item and item not in seen:
                seen.add(item)
                out.append(item)
        return out

    def _extract_ohlc_df(df: pd.DataFrame, sym: str):
        if df is None or df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

        def _pick_col(candidates):
            cols = list(df.columns)
            for cand in candidates:
                if cand is None:
                    continue
                c_low = cand.lower()
                for col in cols:
                    col_low = col.lower()
                    if c_low == col_low or c_low in col_low:
                        return col
            return None

        date_col = _pick_col(["date", "historicaldate", "ch_timestamp", "timestamp", "trade_date", "tradedate"])
        high_col = _pick_col(["high_index_val", "eod_high_index_val", "high"])
        low_col = _pick_col(["low_index_val", "eod_low_index_val", "low"])
        close_col = _pick_col(["close_index_val", "eod_close_index_val", "close"])

        if date_col is None:
            date_col = next((c for c in df.columns if "date" in c.lower() or "timestamp" in c.lower()), None)

        if date_col is None or close_col is None:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors="coerce")
        df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
        if not df.index.is_unique:
            df = df[~df.index.duplicated(keep="last")]

        def _make_frame(col_name):
            if col_name is None or col_name not in df.columns:
                return pd.DataFrame()
            s = pd.to_numeric(
                df[col_name].astype(str).str.replace(",", "", regex=False).str.replace("-", "", regex=False),
                errors="coerce",
            )
            s = s.dropna()
            if s.empty:
                return pd.DataFrame()
            s = s.groupby(level=0).last().sort_index()
            return s.rename(sym).to_frame()

        return _make_frame(close_col), _make_frame(high_col), _make_frame(low_col)

    def _fetch_official(session, index_name, from_date, to_date):
        url = "https://www.nseindia.com/api/historical/indicesHistory"
        try:
            resp = session.get(
                url,
                params={"indexType": index_name, "from": from_date, "to": to_date},
                timeout=10,
            )
            if resp.status_code != 200:
                return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

            payload = resp.json()
            records = None
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                for key in ("indexCloseOnlineRecords", "records", "data"):
                    if data.get(key):
                        records = data.get(key)
                        break
            elif isinstance(data, list):
                records = data

            if records is None and isinstance(payload, dict):
                for key in ("indexCloseOnlineRecords", "records", "data"):
                    if payload.get(key):
                        records = payload.get(key)
                        break

            if records is None:
                return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

            if isinstance(records, dict):
                records = [records]

            df = pd.DataFrame.from_records(records)
            return _extract_ohlc_df(df, index_name)
        except Exception:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def _fetch_legacy(session, index_name, from_date, to_date):
        url = "https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": "https://www.niftyindices.com",
            "Referer": "https://www.niftyindices.com/reports/historical-data",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }

        payload_variants = [
            {"name": index_name, "startDate": from_date, "endDate": to_date},
            {"cinfo": json.dumps({"name": index_name, "startDate": from_date, "endDate": to_date, "indexName": index_name})},
        ]

        for payload in payload_variants:
            try:
                resp = session.post(url, headers=headers, data=json.dumps(payload), timeout=12)
                if resp.status_code != 200:
                    continue
                j = resp.json()
                raw = j.get("d") if isinstance(j, dict) else None
                if not raw:
                    continue
                rows = json.loads(raw)
                df = pd.DataFrame.from_records(rows)
                c, h, l = _extract_ohlc_df(df, index_name)
                if not c.empty:
                    return c, h, l
            except Exception:
                continue
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # FIX: Accept ALL symbols that are in NSE_FALLBACK_INDEX_NAMES,
    # not just those failing _has_enough_index_history
    symbols = [s for s in symbols_tuple if s in NSE_FALLBACK_INDEX_NAMES]
    if not symbols:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    full_history_start = datetime.strptime(FULL_HISTORY_START_DATE, "%Y-%m-%d")
    from_date_official = full_history_start.strftime("%d-%m-%Y")
    to_date_official = datetime.today().strftime("%d-%m-%Y")
    from_date_legacy = full_history_start.strftime("%d-%b-%Y")
    to_date_legacy = datetime.today().strftime("%d-%b-%Y")

    def _fetch_one(sym: str):
        index_name = NSE_FALLBACK_INDEX_NAMES[sym]
        session = _session()

        for candidate in _candidate_names(index_name):
            c, h, l = _fetch_official(session, candidate, from_date_official, to_date_official)
            if not c.empty:
                c = c.rename(columns={c.columns[0]: sym})
                if not h.empty:
                    h = h.rename(columns={h.columns[0]: sym})
                if not l.empty:
                    l = l.rename(columns={l.columns[0]: sym})
                return c, h, l

        for candidate in _candidate_names(index_name):
            c, h, l = _fetch_legacy(session, candidate, from_date_legacy, to_date_legacy)
            if not c.empty:
                c = c.rename(columns={c.columns[0]: sym})
                if not h.empty:
                    h = h.rename(columns={h.columns[0]: sym})
                if not l.empty:
                    l = l.rename(columns={l.columns[0]: sym})
                return c, h, l

        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    close_parts = []
    high_parts = []
    low_parts = []

    max_workers = min(4, len(symbols))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            c, h, l = future.result()
            if not c.empty:
                close_parts.append(c)
            if not h.empty:
                high_parts.append(h)
            if not l.empty:
                low_parts.append(l)

    def _merge(parts):
        if not parts:
            return pd.DataFrame()
        cleaned = []
        for part in parts:
            if part is None or part.empty:
                continue
            part = part.copy()
            part.index = pd.to_datetime(part.index)
            part = part.sort_index()
            if not part.index.is_unique:
                part = part[~part.index.duplicated(keep="last")]
            part = part.loc[:, ~part.columns.duplicated()]
            cleaned.append(part)
        if not cleaned:
            return pd.DataFrame()
        merged = pd.concat(cleaned, axis=1, sort=False)
        merged.index = pd.to_datetime(merged.index)
        merged = merged.sort_index()
        if not merged.index.is_unique:
            merged = merged[~merged.index.duplicated(keep="last")]
        merged = merged.loc[:, ~merged.columns.duplicated()]
        return merged

    return _merge(close_parts), _merge(high_parts), _merge(low_parts)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def download_nse_archive_indices(symbols_tuple):
    """Fill Yahoo one-bar index tickers from NSE daily index close archives."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import date, timedelta
    import re

    symbols = [s for s in symbols_tuple if s in NSE_INDEX_HIST_NAMES]
    if not symbols:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def _norm(value):
        return re.sub(r"[^A-Z0-9]+", "", str(value).upper())

    name_to_symbol = {}
    for sym in symbols:
        base = NSE_INDEX_HIST_NAMES[sym]
        candidates = {base, base.upper(), base.title()}
        if not str(base).upper().endswith(" INDEX"):
            candidates.add(f"{base} Index")
            candidates.add(f"{base} INDEX")
        if " & " in str(base):
            candidates.add(str(base).replace(" & ", " AND "))
        if " AND " in str(base):
            candidates.add(str(base).replace(" AND ", " & "))
        for candidate in candidates:
            name_to_symbol[_norm(candidate)] = sym

    today = datetime.today().date()
    start = datetime.strptime(FULL_HISTORY_START_DATE, "%Y-%m-%d").date()
    recent_start = max(start, today - timedelta(days=370))

    wanted_dates = set()
    d = recent_start
    while d <= today:
        if d.weekday() < 5:
            wanted_dates.add(d)
        d += timedelta(days=1)

    month_cursor = date(start.year, start.month, 1)
    while month_cursor <= today:
        if month_cursor.month == 12:
            next_month = date(month_cursor.year + 1, 1, 1)
        else:
            next_month = date(month_cursor.year, month_cursor.month + 1, 1)
        month_end = next_month - timedelta(days=1)
        for offset in range(0, 8):
            candidate = month_end - timedelta(days=offset)
            if start <= candidate <= today and candidate.weekday() < 5:
                wanted_dates.add(candidate)
        month_cursor = next_month

    headers = {"User-Agent": "Mozilla/5.0"}

    def _fetch_day(day):
        url = f"https://archives.nseindia.com/content/indices/ind_close_all_{day.strftime('%d%m%Y')}.csv"
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200 or not resp.text.lstrip().startswith("Index Name"):
                return []
            rows = []
            for row in csv.DictReader(io.StringIO(resp.text)):
                sym = name_to_symbol.get(_norm(row.get("Index Name", "")))
                if not sym:
                    continue
                row_date = pd.to_datetime(row.get("Index Date") or day, dayfirst=True, errors="coerce")
                if pd.isna(row_date):
                    row_date = pd.Timestamp(day)

                def _num(col):
                    return pd.to_numeric(str(row.get(col, "")).replace(",", ""), errors="coerce")

                rows.append((row_date, sym, _num("Closing Index Value"), _num("High Index Value"), _num("Low Index Value")))
            return rows
        except Exception:
            return []

    records = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(_fetch_day, day) for day in sorted(wanted_dates)]
        for future in as_completed(futures):
            records.extend(future.result())

    if not records:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    close = {}
    high = {}
    low = {}
    for row_date, sym, close_val, high_val, low_val in records:
        if not pd.isna(close_val):
            close.setdefault(sym, {})[row_date] = float(close_val)
        if not pd.isna(high_val):
            high.setdefault(sym, {})[row_date] = float(high_val)
        if not pd.isna(low_val):
            low.setdefault(sym, {})[row_date] = float(low_val)

    def _frame(data):
        if not data:
            return pd.DataFrame()
        frame = pd.DataFrame({sym: pd.Series(values) for sym, values in data.items()})
        frame.index = pd.to_datetime(frame.index)
        return frame.sort_index()

    return _frame(close), _frame(high), _frame(low)


@st.cache_data(ttl=3600, show_spinner=False)
def download_nifty50():
    raw = yf.download(
        tickers=[to_yahoo_ticker("^NSEI")],
        period="3y",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close.index = pd.to_datetime(close.index)
        return close.sort_index()
    close.index = pd.to_datetime(close.index)
    return close.squeeze()


@st.cache_data(ttl=3600, show_spinner=False)
def download_benchmark_close(symbol):
    raw = yf.download(
        tickers=[to_yahoo_ticker(symbol)],
        start=FULL_HISTORY_START_DATE,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close.index = pd.to_datetime(close.index)
        return close.sort_index()
    close.index = pd.to_datetime(close.index)
    return close.squeeze()


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def fetch_recent_corporate_actions(symbols_tuple, ticker_items_tuple, lookback_days=365):
    ticker_map = dict(ticker_items_tuple)
    cutoff = pd.Timestamp(datetime.now().date() - pd.Timedelta(days=lookback_days))
    rows = []

    for symbol in symbols_tuple:
        try:
            yt = to_yahoo_ticker(ticker_map.get(symbol, symbol))
            actions = yf.Ticker(yt).actions
            if actions is None or actions.empty:
                continue
            actions = actions.copy()
            actions.index = pd.to_datetime(actions.index).tz_localize(None)
            actions = actions[actions.index >= cutoff]
            if actions.empty:
                continue

            for action_date, row in actions.iterrows():
                dividend = float(row.get("Dividends", 0) or 0)
                split = float(row.get("Stock Splits", 0) or 0)
                action_types = []
                if dividend:
                    action_types.append("Dividend")
                if split:
                    action_types.append("Split/Bonus")
                if not action_types:
                    continue
                rows.append({
                    "Symbol": symbol,
                    "Yahoo Ticker": yt,
                    "Date": action_date.strftime("%Y-%m-%d"),
                    "Corporate Action": ", ".join(action_types),
                    "Dividend": dividend if dividend else np.nan,
                    "Split/Bonus Ratio": split if split else np.nan,
                    "Price Handling": "Adjusted prices used in heatmaps/returns",
                })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(columns=[
            "Symbol", "Yahoo Ticker", "Date", "Corporate Action",
            "Dividend", "Split/Bonus Ratio", "Price Handling",
        ])
    return pd.DataFrame(rows).sort_values(["Date", "Symbol"], ascending=[False, True])

# =========================================================
# METRICS + DISPLAY
# =========================================================

def build_metrics(close_df, symbols, sector_fn, industry_fn, market_cap_fn=None, high_df=None, low_df=None):
    symbols = _symbols_with_usable_close(close_df, symbols)
    m = pd.DataFrame(index=symbols)
    m.index.name = "Symbol"
    m["Sector"] = pd.Series(m.index.map(sector_fn), index=m.index).fillna("Others").replace({None: "Others", "None": "Others", "": "Others"})
    m["Industry"] = pd.Series(m.index.map(industry_fn), index=m.index).fillna("Others").replace({None: "Others", "None": "Others", "": "Others"})

    if market_cap_fn:
        m["Market Cap (Cr)"] = pd.Series(pd.to_numeric(m.index.map(market_cap_fn), errors="coerce"), index=m.index).fillna(0)

    cf = close_df.reindex(columns=symbols).apply(pd.to_numeric, errors="coerce")
    cf = cf.sort_index()

    m["LTP"] = cf.apply(_safe_last)
    m["1D Return"] = cf.apply(lambda s: _safe_return(s, 1))
    m["1W Return"] = cf.apply(lambda s: _safe_return(s, 5))
    m["1M Return"] = cf.apply(lambda s: _safe_return(s, 21))
    m["3M Return"] = cf.apply(lambda s: _safe_return(s, 63))
    m["6M Return"] = cf.apply(lambda s: _safe_return(s, 126))
    m["1Y Return"] = cf.apply(lambda s: _safe_return(s, 252))

    if high_df is not None and not high_df.empty:
        high_df = high_df.reindex(columns=symbols).apply(pd.to_numeric, errors="coerce")
        m["52W High"] = high_df.apply(lambda s: _safe_high(s, 252))
    else:
        m["52W High"] = cf.apply(lambda s: _safe_high(s, 252))

    if low_df is not None and not low_df.empty:
        low_df = low_df.reindex(columns=symbols).apply(pd.to_numeric, errors="coerce")
        m["52W Low"] = low_df.apply(lambda s: _safe_low(s, 252))
    else:
        m["52W Low"] = cf.apply(lambda s: _safe_low(s, 252))

    m["% from 52W High"] = np.where(
        m["52W High"].notna() & (m["52W High"] != 0),
        (m["LTP"] - m["52W High"]) / m["52W High"] * 100,
        np.nan,
    )
    numeric_cols = m.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        if col in ("LTP", "52W High", "52W Low"):
            m[col] = m[col].fillna(0)
        else:
            m[col] = m[col].fillna(0)
    return m


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def refresh_nse_universe_recent_window(symbols_tuple, ticker_items_tuple):
    symbols = list(dict.fromkeys(symbols_tuple))
    ticker_map = dict(ticker_items_tuple)
    if not symbols:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    recent_map = {to_yahoo_ticker(ticker_map.get(s, s)): s for s in symbols}
    return _fetch_batches(
        symbols,
        recent_map,
        period="10d",
        show_progress=False,
    )


def clean_nse_universe_price_outliers(close_df, high_df=None, low_df=None):
    def _clean_frame(frame, reference=None):
        if frame is None or frame.empty:
            return pd.DataFrame()
        out = frame.copy()
        out.index = pd.to_datetime(out.index, errors="coerce")
        out = out[~out.index.isna()].sort_index()
        out = out.apply(pd.to_numeric, errors="coerce")
        ref = reference if reference is not None and not reference.empty else out
        ref = ref.reindex(index=out.index, columns=out.columns).apply(pd.to_numeric, errors="coerce")
        for symbol in out.columns:
            s = pd.to_numeric(ref[symbol], errors="coerce")
            median = s.rolling(63, min_periods=10).median().ffill().bfill()
            if median.dropna().empty:
                continue
            bad = (out[symbol] < median * 0.35) | (out[symbol] > median * 2.85)
            out.loc[bad, symbol] = np.nan
        return out

    close_clean = _clean_frame(close_df)
    high_clean = _clean_frame(high_df, close_clean)
    low_clean = _clean_frame(low_df, close_clean)
    return close_clean, high_clean, low_clean


def show_dashboard_metrics(metrics):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stocks", len(metrics))
    c2.metric("Positive Today", int((metrics["1D Return"] > 0).sum()))
    c3.metric("Negative Today", int((metrics["1D Return"] < 0).sum()))
    c4.metric("Average 1D Return", f"{metrics['1D Return'].mean():.2f}%")


def style_metrics(metrics):
    base_cols = ["1D Return", "1W Return", "1M Return", "3M Return", "6M Return", "1Y Return"]
    grad_cols = [c for c in base_cols if c in metrics.columns]
    fmt = {
        "LTP": "{:.2f}",
        "1D Return": "{:.2f}",
        "1W Return": "{:.2f}",
        "1M Return": "{:.2f}",
        "3M Return": "{:.2f}",
        "6M Return": "{:.2f}",
        "1Y Return": "{:.2f}",
        "52W High": "{:.2f}",
        "52W Low": "{:.2f}",
        "% from 52W High": "{:.2f}",
    }
    if "Market Cap (Cr)" in metrics.columns:
        fmt["Market Cap (Cr)"] = "{:.0f}"

    styled = (
        metrics.style
        .format(fmt, na_rep="-")
        .background_gradient(cmap="RdYlGn", subset=grad_cols)
        .background_gradient(cmap="RdYlGn_r", subset=["% from 52W High"])
    )

    rs_cols = [c for c in ["RS vs Nifty50", "RS vs CNX500", "RS Sectoral"] if c in metrics.columns]
    if rs_cols:
        styled = styled.background_gradient(cmap="RdYlGn", subset=rs_cols)
    return styled


MAX_STYLED_HEATMAP_CELLS = 250_000


def show_heatmap_dataframe(frame: pd.DataFrame, height=900):
    frame = frame.replace({None: np.nan, "None": np.nan})
    if frame.size > MAX_STYLED_HEATMAP_CELLS:
        st.caption(
            f"Showing {frame.shape[0]:,} rows x {frame.shape[1]:,} columns without color styling "
            "because it is larger than Pandas Styler's render limit."
        )
        st.dataframe(frame.round(2), width="stretch", height=height)
        return

    st.dataframe(
        frame.style
        .format("{:.2f}", na_rep="-")
        .background_gradient(cmap="RdYlGn", axis=None, vmin=-20, vmax=20),
        width="stretch",
        height=height,
    )


def show_missing_heatmap_values_notice(hmap: pd.DataFrame, close_df: pd.DataFrame = None):
    missing = hmap.isna()
    if not missing.any().any():
        return

    rows = []
    for symbol in hmap.index[missing.any(axis=1)]:
        first_date = "-"
        reason = "No previous period/source close was available for the blank cells."
        if close_df is not None and symbol in close_df.columns:
            series = pd.to_numeric(close_df[symbol], errors="coerce").dropna()
            if not series.empty:
                first_date = series.index.min().strftime("%Y-%m-%d")
                reason = (
                    f"Available source history starts on {first_date}; blank cells occur before enough "
                    "monthly/yearly history exists to calculate a return."
                )
        rows.append({
            "Symbol": symbol,
            "First Available Date": first_date,
            "Reason": reason,
        })

    if rows:
        with st.expander("Missing / None Value Notes", expanded=False):
            st.caption("Blank cells mean return cannot be calculated because the prior comparison period is missing from the data source.")
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=min(420, 38 * len(rows) + 42))


def show_heatmap_section(metrics, monthly_returns, yearly_returns, heatmap_type, label="", close_df=None):
    if monthly_returns.empty and yearly_returns.empty:
        st.info("Not enough historical data to build the heatmap.")
        return

    if heatmap_type == "Monthly":
        if monthly_returns.empty:
            st.info("Monthly data is not available yet.")
            return
        years = sorted(monthly_returns.index.year.unique(), reverse=True)
        selected_year = st.selectbox("Select Year", years, index=0)
        hdata = monthly_returns[monthly_returns.index.year == selected_year]
        valid = [s for s in metrics.index if s in hdata.columns]
        hmap = hdata.T.loc[valid].iloc[:, ::-1]
        hmap.columns = [x.strftime("%b") for x in hmap.columns]
    else:
        if yearly_returns.empty:
            st.info("Yearly data is not available yet.")
            return
        valid = [s for s in metrics.index if s in yearly_returns.columns]
        hmap = yearly_returns.T.loc[valid].iloc[:, ::-1]
        hmap.columns = [x.strftime("%Y") for x in hmap.columns]

    hmap = hmap.dropna(how="all")
    hmap = hmap.apply(pd.to_numeric, errors="coerce")

    st.subheader(f"{heatmap_type} Heatmap{' - ' + label if label else ''}")
    show_heatmap_dataframe(hmap, height=900)
    show_missing_heatmap_values_notice(hmap, close_df)

    if heatmap_type == "Yearly":
        notes = build_history_availability_notes(close_df, list(metrics.index))
        if not notes.empty:
            with st.expander("Yearly Data Availability Notes", expanded=False):
                st.dataframe(notes, width="stretch", hide_index=True, height=min(420, 38 * len(notes) + 42))

    with st.expander("Full Historical Heatmap"):
        if heatmap_type == "Monthly":
            fh = monthly_returns.T.loc[[s for s in metrics.index if s in monthly_returns.columns]].iloc[:, ::-1]
            fh.columns = [x.strftime("%Y-%m") for x in fh.columns]
        else:
            fh = yearly_returns.T.loc[[s for s in metrics.index if s in yearly_returns.columns]].iloc[:, ::-1]
            fh.columns = [x.strftime("%Y") for x in fh.columns]
        fh = fh.dropna(how="all").apply(pd.to_numeric, errors="coerce")
        show_heatmap_dataframe(fh, height=900)
        if heatmap_type == "Yearly":
            notes = build_history_availability_notes(close_df, [s for s in metrics.index if s in fh.index])
            if not notes.empty:
                st.caption("Blank yearly cells mean no close price existed before that symbol/index started trading.")
                st.dataframe(notes, width="stretch", hide_index=True, height=min(420, 38 * len(notes) + 42))


def show_ticker_diagnostics(ticker_map, close_df, all_requested):
    with st.sidebar.expander("\U0001F50D Ticker Resolution Report", expanded=False):
        resolved_correctly = []
        remapped = []
        still_missing = []
        usable_symbols = set(_symbols_with_usable_close(close_df, all_requested))

        for orig in all_requested:
            resolved = ticker_map.get(orig, orig)
            in_data = orig in usable_symbols

            if not in_data:
                still_missing.append(orig)
            elif resolved != orig:
                remapped.append((orig, resolved))
            else:
                resolved_correctly.append(orig)

        st.write(f"\u2705 **Working:** {len(resolved_correctly)}")
        st.write(f"\U0001F504 **Remapped:** {len(remapped)}")
        st.write(f"\u274C **Still Missing:** {len(still_missing)}")

        if remapped:
            st.write("**Remapped Tickers:**")
            for orig, res in remapped:
                st.write(f"  `{orig}` \u2192 `{res}`")

        if still_missing:
            st.write("**Still Missing (no data):**")
            for s in still_missing:
                st.write(f"  `{s}`")


def show_recent_corporate_actions(symbols, ticker_map, label):
    with st.expander(f"Recent Corporate Actions - {label}", expanded=False):
        st.caption(
            "Shows Yahoo Finance corporate actions from the last 1 year. "
            "Heatmaps and returns use adjusted prices, so splits/bonus/dividend adjustments are already reflected where Yahoo provides them."
        )
        actions = fetch_recent_corporate_actions(tuple(symbols), tuple(sorted(ticker_map.items())))
        if actions.empty:
            st.info("No recent dividend/split/bonus records found from Yahoo Finance for this selection.")
        else:
            st.dataframe(actions, width="stretch", hide_index=True, height=min(520, 38 * len(actions) + 42))

# =========================================================
# TITLE + MODE SELECTOR
# =========================================================

st.sidebar.header("Filters")

mode = st.sidebar.radio(
    "Universe",
    ["F&O Stocks", "Nifty Indices", "NSE Indices", "NSE Universe"],
    index=0,
)

PAGE_TITLES = {
    "F&O Stocks": "F&O Stocks HeatMap",
    "Nifty Indices": "Nifty Index Stocks HeatMap",
    "NSE Indices": "NSE Indices HeatMap",
    "NSE Universe": "NSE Universe Stocks HeatMap",
}

st.title(PAGE_TITLES.get(mode, "Stocks HeatMap"))

show_refresh_timer()

# =========================================================
# MODE 1 - F&O STOCKS
# =========================================================

if mode == "F&O Stocks":
    if STOCK_DATA_SOURCE is not None:
        st.sidebar.caption(f"Sector source: {STOCK_DATA_SOURCE.name}")
    else:
        st.sidebar.warning("Sector CSV not found. Using fallback mappings.")

    search_stock = st.sidebar.text_input("Search Stock")

    sector_list = sorted({STOCK_DATA[s]["Sector"] for s in ALL_STOCKS})
    industry_list = sorted({STOCK_DATA[s]["Industry"] for s in ALL_STOCKS})

    selected_sectors = st.sidebar.multiselect("Sector Filter", sector_list, default=[])
    selected_industries = st.sidebar.multiselect("Industry Filter", industry_list, default=[])
    heatmap_type = st.sidebar.radio("Heatmap Type", ["Monthly", "Yearly"])

    with st.spinner("Loading market data from SQLite, or building it from Yahoo Finance if missing..."):
        close_df, high_df, low_df, ticker_map = download_with_resolved_tickers(ALL_STOCKS)

    if close_df.empty:
        st.error("No market data downloaded.")
        st.stop()

    show_ticker_diagnostics(ticker_map, close_df, ALL_STOCKS)

    monthly_returns = close_df.resample("ME").last().pct_change() * 100
    yearly_returns = compute_yearly_returns_from_listing(close_df)

    symbols = [s for s in ALL_STOCKS if s in close_df.columns]
    if selected_sectors:
        symbols = [s for s in symbols if STOCK_DATA[s]["Sector"] in selected_sectors]
    if selected_industries:
        symbols = [s for s in symbols if STOCK_DATA[s]["Industry"] in selected_industries]
    if search_stock:
        symbols = [s for s in symbols if search_stock.lower() in s.lower()]

    if not symbols:
        st.warning("No stocks match filters.")
        st.stop()

    top_n = len(symbols) if len(symbols) <= 1 else st.sidebar.slider("Rows To Show", 1, len(symbols), len(symbols))

    metrics = build_metrics(
        close_df, symbols,
        sector_fn=lambda s: STOCK_DATA.get(s, {}).get("Sector", "Others"),
        industry_fn=lambda s: STOCK_DATA.get(s, {}).get("Industry", "Others"),
        high_df=high_df, low_df=low_df,
    )
    metrics = metrics.sort_values("1D Return", ascending=False).head(top_n)

    show_dashboard_metrics(metrics)
    st.subheader("Live Stock Metrics - F&O Stocks")
    st.dataframe(style_metrics(metrics), width="stretch", height=800)

    show_heatmap_section(
        metrics,
        monthly_returns[[s for s in symbols if s in monthly_returns.columns]],
        yearly_returns[[s for s in symbols if s in yearly_returns.columns]],
        heatmap_type,
        label="F&O Stocks",
        close_df=close_df,
    )

    csv = metrics.to_csv().encode("utf-8")
    st.download_button("Download CSV Report", data=csv, file_name="fo_stocks_report.csv", mime="text/csv")

# =========================================================
# MODE 2 - NIFTY INDICES
# =========================================================

elif mode == "Nifty Indices":
    selected_index = st.sidebar.selectbox("Select Nifty Index", list(NIFTY_INDICES.keys()), index=0)
    index_stocks, constituent_source = load_nifty_index_constituents(selected_index)
    st.sidebar.caption(f"Stocks in index: {len(index_stocks)}")
    st.sidebar.caption(f"Constituents: {constituent_source}")

    if STOCK_DATA_SOURCE is not None:
        st.sidebar.caption(f"Sector source: {STOCK_DATA_SOURCE.name}")

    search_stock = st.sidebar.text_input("Search Stock")

    def _sector(s):
        return STOCK_DATA.get(s, {}).get("Sector", "Others")

    def _industry(s):
        return STOCK_DATA.get(s, {}).get("Industry", "Others")

    sector_list = sorted({_sector(s) for s in index_stocks})
    industry_list = sorted({_industry(s) for s in index_stocks})

    selected_sectors = st.sidebar.multiselect("Sector Filter", sector_list, default=[])
    selected_industries = st.sidebar.multiselect("Industry Filter", industry_list, default=[])
    heatmap_type = st.sidebar.radio("Heatmap Type", ["Monthly", "Yearly"])

    with st.spinner("Loading market data from SQLite, or building it from Yahoo Finance if missing..."):
        close_df, high_df, low_df, ticker_map = download_with_resolved_tickers(index_stocks)

    if close_df.empty:
        st.error("No market data downloaded.")
        st.stop()

    show_ticker_diagnostics(ticker_map, close_df, index_stocks)

    monthly_returns = close_df.resample("ME").last().pct_change() * 100
    yearly_returns = compute_yearly_returns_from_listing(close_df)

    symbols = [s for s in index_stocks if s in close_df.columns]
    if selected_sectors:
        symbols = [s for s in symbols if _sector(s) in selected_sectors]
    if selected_industries:
        symbols = [s for s in symbols if _industry(s) in selected_industries]
    if search_stock:
        symbols = [s for s in symbols if search_stock.lower() in s.lower()]
    if not symbols:
        st.warning("No stocks match filters.")
        st.stop()

    top_n_default = len(symbols)
    top_n = len(symbols) if len(symbols) <= 1 else st.sidebar.slider(
        "Rows To Show",
        1,
        len(symbols),
        top_n_default,
        key=f"rows_to_show_{selected_index.replace(' ', '_').lower()}",
    )

    metrics = build_metrics(
        close_df, symbols, _sector, _industry,
        high_df=high_df, low_df=low_df
    )
    metrics = metrics.sort_values("1D Return", ascending=False).head(top_n)

    show_dashboard_metrics(metrics)
    st.subheader(f"Live Stock Metrics - {selected_index}")
    st.dataframe(style_metrics(metrics), width="stretch", height=800)
    show_recent_corporate_actions(symbols, ticker_map, selected_index)

    show_heatmap_section(
        metrics,
        monthly_returns[[s for s in symbols if s in monthly_returns.columns]],
        yearly_returns[[s for s in symbols if s in yearly_returns.columns]],
        heatmap_type,
        label=selected_index,
        close_df=close_df,
    )

    csv = metrics.to_csv().encode("utf-8")
    st.download_button(
        "Download CSV Report",
        data=csv,
        file_name=f"nifty_{selected_index.replace(' ','_')}.csv",
        mime="text/csv"
    )

# =========================================================
# MODE 3 - NSE INDICES
# =========================================================

elif mode == "NSE Indices":
    st.sidebar.caption(f"Index basket size: {len(NSE_INDEX_BASKET)}")
    search_index = st.sidebar.text_input("Search Index")

    index_groups = sorted({NSE_INDEX_GROUPS.get(s, ("Indices", "Indices"))[0] for s in NSE_INDEX_BASKET})
    selected_groups = st.sidebar.multiselect("Index Group Filter", index_groups, default=[])
    heatmap_type = st.sidebar.radio("Heatmap Type", ["Monthly", "Yearly"])

    def _group(s):
        return NSE_INDEX_GROUPS.get(s, ("Indices", "Indices"))[0]

    def _family(s):
        return NSE_INDEX_GROUPS.get(s, ("Indices", "Indices"))[1]

    index_stocks = list(dict.fromkeys(NSE_INDEX_BASKET))

    with st.spinner("Loading index data..."):
        # FIX: Separate Yahoo-served indices from NSE-fallback-only indices
        yahoo_index_stocks = [
            s for s in index_stocks
            if NSE_INDEX_TICKER_OVERRIDES.get(s) != "__NSE_FALLBACK__"
        ]
        nse_fallback_stocks = [
            s for s in index_stocks
            if NSE_INDEX_TICKER_OVERRIDES.get(s) == "__NSE_FALLBACK__"
        ]

        # Download Yahoo-served indices
        close_df, high_df, low_df, ticker_map = download_with_resolved_tickers(yahoo_index_stocks)
        nifty50_close = download_nifty50()

        # FIX: Always fetch NSE fallback indices via NSE API (not conditional on _has_enough_index_history)
        if nse_fallback_stocks:
            with st.spinner(f"Fetching {len(nse_fallback_stocks)} indices from NSE India..."):
                fb_close, fb_high, fb_low = download_nse_fallback_indices(tuple(nse_fallback_stocks))
                if not fb_close.empty:
                    close_df = _merge_time_series_frames(close_df, fb_close)
                    for s in fb_close.columns:
                        ticker_map[s] = s
                if not fb_high.empty:
                    high_df = _merge_time_series_frames(high_df, fb_high)
                if not fb_low.empty:
                    low_df = _merge_time_series_frames(low_df, fb_low)

        # Also fetch archive data for all indices (fills gaps in Yahoo data)
        archive_symbols = tuple(s for s in index_stocks if s in NSE_ARCHIVE_INDEX_SYMBOLS)
        if archive_symbols:
            ar_close, ar_high, ar_low = download_nse_archive_indices(archive_symbols)
            if not ar_close.empty:
                close_df = _merge_time_series_frames(close_df, ar_close)
                for s in ar_close.columns:
                    if s not in ticker_map:
                        ticker_map[s] = s
            if not ar_high.empty:
                high_df = _merge_time_series_frames(high_df, ar_high)
            if not ar_low.empty:
                low_df = _merge_time_series_frames(low_df, ar_low)

        close_df, high_df, low_df = _finalize_market_frames(close_df, high_df, low_df)
        save_market_cache({
            "schema_version": CACHE_SCHEMA_VERSION,
            "updated_at": int(time.time()),
            "close": close_df,
            "high": high_df,
            "low": low_df,
            "ticker_map": ticker_map,
        })

    if close_df.empty:
        st.error("No market data downloaded.")
        st.stop()

    show_ticker_diagnostics(ticker_map, close_df, index_stocks)

    monthly_returns = close_df.resample("ME").last().pct_change() * 100
    yearly_returns = compute_yearly_returns_from_listing(close_df)

    symbols = [s for s in index_stocks if s in close_df.columns]
    if selected_groups:
        symbols = [s for s in symbols if _group(s) in selected_groups]
    if search_index:
        symbols = [s for s in symbols if search_index.lower() in s.lower()]

    if not symbols:
        st.warning("No indices match filters.")
        st.stop()

    top_n = len(symbols) if len(symbols) <= 1 else st.sidebar.slider("Rows To Show", 1, len(symbols), len(symbols))

    metrics = build_metrics(
        close_df, symbols,
        sector_fn=_group,
        industry_fn=_family,
        high_df=high_df, low_df=low_df,
    )

    if "CNX500" in close_df.columns and not close_df["CNX500"].dropna().empty:
        cnx500_close = close_df["CNX500"]
    else:
        cnx500_close = download_benchmark_close(NSE_INDEX_TICKER_OVERRIDES.get("CNX500", "^CRSLDX"))

    if not close_df.empty:
        avail_for_rs = [s for s in symbols if s in close_df.columns]
        if avail_for_rs:
            rs_cnx500 = compute_rs_vs_benchmark(close_df[avail_for_rs], cnx500_close)
            metrics["RS vs CNX500"] = rs_cnx500.reindex(metrics.index).fillna(50).astype("Int64")
        else:
            metrics["RS vs CNX500"] = 50
    else:
        metrics["RS vs CNX500"] = 50

    metrics = metrics.sort_values("1D Return", ascending=False).head(top_n)

    show_dashboard_metrics(metrics)
    st.subheader("Live Index Metrics - NSE Indices")
    st.dataframe(style_metrics(metrics), width="stretch", height=800)

    show_heatmap_section(
        metrics,
        monthly_returns[[s for s in symbols if s in monthly_returns.columns]],
        yearly_returns[[s for s in symbols if s in yearly_returns.columns]],
        heatmap_type,
        label="NSE Indices",
        close_df=close_df,
    )

    csv = metrics.to_csv().encode("utf-8")
    st.download_button("Download CSV Report", data=csv, file_name="nse_indices_report.csv", mime="text/csv")

# =========================================================
# MODE 4 - NSE UNIVERSE
# =========================================================

else:
    if NSE_DF is None:
        st.error(
            "nse_universe.csv not found. Place it in the same folder as the app "
            "or on your Desktop (OneDrive\\Desktop or Desktop)."
        )
        st.stop()

    if NSE_CSV_SOURCE is not None:
        st.sidebar.caption(f"NSE Universe: {NSE_CSV_SOURCE.name}")

    search_stock = st.sidebar.text_input("Search Stock")

    nse_sector_list = sorted(NSE_DF["Sector"].dropna().unique())
    nse_industry_list = sorted(NSE_DF["Basic Industry"].dropna().unique())

    selected_sectors = st.sidebar.multiselect("Sector Filter", nse_sector_list, default=[])
    selected_industries = st.sidebar.multiselect("Industry Filter", nse_industry_list, default=[])
    heatmap_type = st.sidebar.radio("Heatmap Type", ["Monthly", "Yearly"])

    nse_filtered = NSE_DF.copy()
    nse_filtered = nse_filtered[~nse_filtered["Stock Name"].isin(EXCLUDED_SYMBOLS)]
    if selected_sectors:
        nse_filtered = nse_filtered[nse_filtered["Sector"].isin(selected_sectors)]
    if selected_industries:
        nse_filtered = nse_filtered[nse_filtered["Basic Industry"].isin(selected_industries)]
    if search_stock:
        nse_filtered = nse_filtered[nse_filtered["Stock Name"].str.lower().str.contains(search_stock.lower())]

    if nse_filtered.empty:
        st.warning("No stocks match filters.")
        st.stop()

    symbols_to_fetch = [s for s in nse_filtered["Stock Name"].tolist() if s not in EXCLUDED_SYMBOLS]
    top_n = len(symbols_to_fetch) if len(symbols_to_fetch) <= 1 else st.sidebar.slider(
        "Rows To Show", 1, len(symbols_to_fetch), min(200, len(symbols_to_fetch))
    )

    with st.spinner("Loading NSE Universe data from SQLite, or building it from Yahoo Finance if missing..."):
        close_df, high_df, low_df, ticker_map = download_with_resolved_tickers(symbols_to_fetch)
        nifty50_close = download_nifty50()

    if close_df.empty:
        st.error("No market data downloaded.")
        st.stop()

    recent_close, recent_high, recent_low = refresh_nse_universe_recent_window(
        tuple(symbols_to_fetch),
        tuple(sorted(ticker_map.items())),
    )
    if not recent_close.empty:
        close_df = _merge_time_series_frames(close_df, recent_close)
    if not recent_high.empty:
        high_df = _merge_time_series_frames(high_df, recent_high)
    if not recent_low.empty:
        low_df = _merge_time_series_frames(low_df, recent_low)
    close_df, high_df, low_df = clean_nse_universe_price_outliers(close_df, high_df, low_df)

    show_ticker_diagnostics(ticker_map, close_df, symbols_to_fetch)

    monthly_returns = close_df.resample("ME").last().pct_change() * 100
    yearly_returns = compute_yearly_returns_from_listing(close_df)

    nse_lookup = nse_filtered.set_index("Stock Name")
    available = [s for s in symbols_to_fetch if s in close_df.columns]

    metrics = build_metrics(
        close_df, available,
        sector_fn=lambda s: nse_lookup.loc[s, "Sector"] if s in nse_lookup.index else "Others",
        industry_fn=lambda s: nse_lookup.loc[s, "Basic Industry"] if s in nse_lookup.index else "Others",
        market_cap_fn=lambda s: nse_lookup.loc[s, "Market Cap"] if s in nse_lookup.index else np.nan,
        high_df=high_df, low_df=low_df,
    )

    if not nifty50_close.empty and not close_df.empty:
        avail_for_rs = [s for s in available if s in close_df.columns]
        if avail_for_rs:
            rs_nifty = compute_rs_vs_nifty50(close_df[avail_for_rs], nifty50_close)
            metrics["RS vs Nifty50"] = rs_nifty.reindex(metrics.index).fillna(50).astype("Int64")
        else:
            metrics["RS vs Nifty50"] = 50
    else:
        metrics["RS vs Nifty50"] = 50

    if not close_df.empty:
        avail_for_rs = [s for s in available if s in close_df.columns]
        if avail_for_rs:
            sec_map = {s: metrics.loc[s, "Sector"] for s in avail_for_rs if s in metrics.index}
            rs_sect = compute_rs_sectoral(close_df[avail_for_rs], sec_map)
            metrics["RS Sectoral"] = rs_sect.reindex(metrics.index).fillna(50).astype("Int64")
        else:
            metrics["RS Sectoral"] = 50
    else:
        metrics["RS Sectoral"] = 50

    metrics = metrics.sort_values("1D Return", ascending=False).head(top_n)

    show_dashboard_metrics(metrics)
    st.subheader("Live Stock Metrics - NSE Universe")
    st.dataframe(style_metrics(metrics), width="stretch", height=800)

    show_heatmap_section(
        metrics,
        monthly_returns[[s for s in available if s in monthly_returns.columns]],
        yearly_returns[[s for s in available if s in yearly_returns.columns]],
        heatmap_type,
        label="NSE Universe",
        close_df=close_df,
    )

    csv = metrics.to_csv().encode("utf-8")
    st.download_button("Download CSV Report", data=csv, file_name="nse_universe_report.csv", mime="text/csv")

# =========================================================
# FOOTER
# =========================================================

st.caption(
    "Data sourced live from Yahoo Finance + NSE India. "
    "Historical data loaded from local disk cache for speed. "
    "Only today's live candle is fetched from Yahoo on each refresh. "
    "NSE-only indices (Healthcare, Oil & Gas, Chemicals, CPSE, IPO, Housing, etc.) "
    "are fetched directly from NSE India API. "
    "Auto-refresh runs every 15 minutes."
)
