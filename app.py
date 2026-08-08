import streamlit as st
import pandas as pd
import requests
import time
import hmac
import hashlib

# Configurazione Pagina Web
st.set_page_config(
    page_title="Bybit Futures Breakout Scanner",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Bybit Futures: Compression & Breakout Scanner")
st.markdown("Scansione in tempo reale dei contratti USDT Perpetual con notifica automatica su Telegram.")

# API Keys
BYBIT_API_KEY = "zKgXLLBfZFC9pBd0w0"
BYBIT_API_SECRET = "nCmAO4UdEKSj3KEIP2G7HIBCLNZISrh2c8h8"

# Parametri Sidebar
st.sidebar.header("⚙️ Parametri Scanner")
LOOKBACK_DAYS = st.sidebar.number_input("Giorni Lateralizzazione (Daily)", value=120, min_value=30, max_value=365)
MAX_RANGE_PCT = st.sidebar.slider("Ampiezza Max Range (%)", min_value=10.0, max_value=50.0, value=35.0, step=1.0)
MIN_VOLUME_M = st.sidebar.number_input("Volume Minimo 24h (Milioni $)", value=5.0, min_value=1.0, step=1.0)
MIN_VOLUME_USDT = MIN_VOLUME_M * 1_000_000

st.sidebar.header("📲 Configurazione Telegram")
ENABLE_TELEGRAM = st.sidebar.checkbox("Attiva Notifiche Telegram", value=False)
TELEGRAM_TOKEN = st.sidebar.text_input("Bot Token Telegram", type="password")
TELEGRAM_CHAT_ID = st.sidebar.text_input("Chat ID Telegram")

BASE_URL = "https://api.bybit.com"

def get_auth_headers(params_str=""):
    timestamp = str(int(time.time() * 1000))
    recv_window = "10000"
    raw_str = timestamp + BYBIT_API_KEY + recv_window + params_str
    signature = hmac.new(
        BYBIT_API_SECRET.encode('utf-8'),
        raw_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return {
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-SIGN": signature,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json"
    }

def send_telegram_message(token, chat_id, text):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

def fetch_bybit_tickers():
    url = f"{BASE_URL}/v5/market/tickers"
    query_params = "category=linear"
    full_url = f"{url}?{query_params}"
    
    headers = get_auth_headers(query_params)
    
    try:
        res = requests.get(full_url, headers=headers, timeout=10)
        data = res.json()
        if data.get("retCode") == 0:
            list_tickers = data.get("result", {}).get("list", [])
            return [t for t in list_tickers if t["symbol"].endswith("USDT")]
        return []
    except Exception:
        return []

def fetch_klines(symbol, limit):
    url = f"{BASE_URL}/v5/market/kline"
    query_params = f"category=linear&symbol={symbol}&interval=D&limit={limit}"
    full_url = f"{url}?{query_params}"
    
    headers = get_auth_headers(query_params)
    
    try:
        res = requests.get(full_url, headers=headers, timeout=10)
        data = res.json()
        if data.get("retCode") == 0:
            raw_klines = data.get("result", {}).get("list", [])
            raw_klines.reverse()
            parsed = []
            for k in raw_klines:
                parsed.append({
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4])
                })
            return parsed
        return []
    except Exception:
        return []

def run_scan():
    status_text = st.empty()
    status_text.text("🔑 Autenticazione API Bybit V5 in corso...")
    
    tickers = fetch_bybit_tickers()
    
    if not tickers:
        st.error("I server di Bybit continuano a rifiutare la connessione dal cloud. Prova a cliccare su 'Manage App' -> 'Reboot' in basso a destra per cambiare IP del server.")
        return pd.DataFrame()

    filtered_tickers = []
    for t in tickers:
        try:
            quote_volume = float(t.get("turnover24h", 0))
            if quote_volume >= MIN_VOLUME_USDT:
                filtered_tickers.append((t["symbol"], quote_volume, float(t.get("lastPrice", 0))))
        except (ValueError, TypeError):
            continue

    results = []
    progress_bar = st.progress(0)
    total = len(filtered_tickers)
    
    if total == 0:
        status_text.empty()
        progress_bar.empty()
        st.warning("Nessuna coppia trovata con il volume minimo specificato.")
        return pd.DataFrame()

    for idx, (symbol, quote_volume, last_price) in enumerate(filtered_tickers):
        status_text.text(f"Analisi grafico {idx+1}/{total}: {symbol}")
        progress_bar.progress((idx + 1) / total)
        
        time.sleep(0.1)
        
        klines = fetch_klines(symbol, LOOKBACK_DAYS + 10)
        if len(klines) < LOOKBACK_DAYS:
            continue
            
        df = pd.DataFrame(klines)
        df_range = df.iloc[-LOOKBACK_DAYS:]
        
        highest_high = df_range['high'].max()
        lowest_low = df_range['low'].min()
        current_close = df['close'].iloc[-1]
        
        if lowest_low <= 0 or (highest_high - lowest_low) <= 0:
            continue

        range_pct = ((highest_high - lowest_low) / lowest_low) * 100
        proximity = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
        
        if range_pct <= MAX_RANGE_PCT:
            res = {
                'Symbol': symbol,
                'Prezzo ($)': current_close,
                'Range Ampiezza (%)': round(range_pct, 2),
                'Prossimità Breakout (%)': round(proximity, 1),
                'Volume 24h (M$)': round(quote_volume / 1_000_000, 2)
            }
            results.append(res)
            
            if ENABLE_TELEGRAM and proximity >= 85.0:
                msg = (
                    f"🚨 *POSSIBILE BREAKOUT IMMINENTE!*\n\n"
                    f"📌 *Coppia:* `{symbol}`\n"
                    f"💰 *Prezzo Attuale:* `{current_close}` $\n"
                    f"📏 *Ampiezza Range {LOOKBACK_DAYS}d:* `{round(range_pct, 2)}%`\n"
                    f"🎯 *Prossimità Resistenza:* `{round(proximity, 1)}%`\n"
                    f"📊 *Volume 24h:* `{round(quote_volume / 1_000_000, 2)} M$`\n\n"
                    f"🔗 [Apri Grafico su Bybit](https://www.bybit.com/trade/usdt/{symbol})"
                )
                send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)

    status_text.empty()
    progress_bar.empty()
    return pd.DataFrame(results)

if st.button("🚀 Avvia Scansione Ora", type="primary"):
    with st.spinner("Scansione del mercato Bybit Futures in corso..."):
        df_results = run_scan()
        if not df_results.empty:
            df_sorted = df_results.sort_values(by=['Prossimità Breakout (%)', 'Range Ampiezza (%)'], ascending=[False, True])
            st.success(f"Scansione completata! Trovate {len(df_sorted)} crypto in accumulazione.")
            st.dataframe(
                df_sorted.style.background_gradient(subset=['Prossimità Breakout (%)'], cmap='Greens'),
                use_container_width=True
            )
