import streamlit as st
import ccxt
import pandas as pd
import requests

# Configurazione Pagina Web
st.set_page_config(
    page_title="Bybit Futures Breakout Scanner",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Bybit Futures: Compression & Breakout Scanner")
st.markdown("Scansione in tempo reale dei contratti USDT Perpetual con notifica automatica su Telegram.")

# Parametri Sidebar
st.sidebar.header("⚙️ Parametri Scanner")
LOOKBACK_DAYS = st.sidebar.number_input("Giorni Lateralizzazione (Daily)", value=120, min_value=30, max_value=365)
MAX_RANGE_PCT = st.sidebar.slider("Ampiezza Max Range (%)", min_value=10.0, max_value=50.0, value=35.0, step=1.0)
MIN_VOLUME_M = st.sidebar.number_input("Volume Minimo 24h (Milioni $)", value=3.0, min_value=0.5, step=0.5)
MIN_VOLUME_USDT = MIN_VOLUME_M * 1_000_000

st.sidebar.header("📲 Configurazione Telegram")
ENABLE_TELEGRAM = st.sidebar.checkbox("Attiva Notifiche Telegram", value=False)
TELEGRAM_TOKEN = st.sidebar.text_input("Bot Token Telegram", type="password")
TELEGRAM_CHAT_ID = st.sidebar.text_input("Chat ID Telegram")

def send_telegram_message(token, chat_id, text):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def run_scan():
    exchange = ccxt.bybit({'enableRateLimit': True})
    markets = exchange.load_markets()
    symbols = [
        s for s, m in markets.items() 
        if m.get('linear') and m.get('settle') == 'USDT' and m.get('active')
    ]
    
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    total = len(symbols)
    
    for idx, symbol in enumerate(symbols):
        status_text.text(f"Scansione {idx+1}/{total}: {symbol}")
        progress_bar.progress((idx + 1) / total)
        
        try:
            ticker = exchange.fetch_ticker(symbol)
            quote_volume = ticker.get('quoteVolume', 0) or 0
            if quote_volume < MIN_VOLUME_USDT:
                continue
                
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=LOOKBACK_DAYS + 10)
            if len(ohlcv) < LOOKBACK_DAYS:
                continue
                
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df_range = df.iloc[-LOOKBACK_DAYS:]
            
            highest_high = df_range['high'].max()
            lowest_low = df_range['low'].min()
            current_close = df['close'].iloc[-1]
            
            range_pct = ((highest_high - lowest_low) / lowest_low) * 100
            proximity = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
            
            if range_pct <= MAX_RANGE_PCT:
                try:
                    oi_fetch = exchange.fetch_open_interest(symbol)
                    oi_amount = oi_fetch.get('openInterestAmount', 0) or 0
                    oi_usdt = oi_amount * current_close
                except Exception:
                    oi_usdt = 0
                    
                oi_ratio = (oi_usdt / quote_volume) if quote_volume > 0 else 0
                clean_symbol = symbol.replace(':USDT', '')
                
                res = {
                    'Symbol': clean_symbol,
                    'Prezzo ($)': current_close,
                    'Range Ampiezza (%)': round(range_pct, 2),
                    'Prossimità Breakout (%)': round(proximity, 1),
                    'Volume 24h (M$)': round(quote_volume / 1_000_000, 2),
                    'Open Interest (M$)': round(oi_usdt / 1_000_000, 2),
                    'Ratio OI/Vol': round(oi_ratio, 2)
                }
                results.append(res)
                
                if ENABLE_TELEGRAM and proximity >= 85.0:
                    msg = (
                        f"🚨 *POSSIBILE BREAKOUT IMMINENTE!*\n\n"
                        f"📌 *Coppia:* `{clean_symbol}`\n"
                        f"💰 *Prezzo Attuale:* `{current_close}` $\n"
                        f"📏 *Ampiezza Range {LOOKBACK_DAYS}d:* `{round(range_pct, 2)}%`\n"
                        f"🎯 *Prossimità Resistenza:* `{round(proximity, 1)}%`\n"
                        f"📊 *Volume 24h:* `{round(quote_volume / 1_000_000, 2)} M$`\n"
                        f"🔥 *Open Interest:* `{round(oi_usdt / 1_000_000, 2)} M$`\n\n"
                        f"🔗 [Apri Grafico su Bybit](https://www.bybit.com/trade/usdt/{clean_symbol})"
                    )
                    send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)
                    
        except Exception:
            continue
            
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
        else:
            st.warning("Nessuna crypto trovata con i parametri selezionati.")
