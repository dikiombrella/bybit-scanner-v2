import ccxt
import pandas as pd
import numpy as np
import time

def run_bybit_advanced_scanner():
    print("Connessione alle API Futures di Bybit in corso...\n")
    exchange = ccxt.bybit({'enableRateLimit': True})
    
    # Carica i mercati Futures USDT (Linear)
    markets = exchange.load_markets()
    symbols = [
        s for s, m in markets.items() 
        if m.get('linear') and m.get('settle') == 'USDT' and m.get('active')
    ]
    
    # ---------------- PARAMETRI DI FILTRO ----------------
    LOOKBACK_DAYS = 120       # Candele Daily per la lateralizzazione (es. 4 mesi)
    MAX_RANGE_PCT = 35.0      # Ampiezza massima del canale di compressione (%)
    MIN_24H_VOLUME_USDT = 3_000_000  # Volume minimo 24h per evitare illiquidità
    # ----------------------------------------------------
    
    results = []
    print(f"Scansione di {len(symbols)} coppie Futures USDT su Bybit...")
    print(f"Filtri attivi: Volume 24h > ${MIN_24H_VOLUME_USDT:,.0f} | Range Max <= {MAX_RANGE_PCT}%\n")
    
    for idx, symbol in enumerate(symbols, 1):
        try:
            # 1. Recupera i dati del Ticker per verificare il Volume 24h
            ticker = exchange.fetch_ticker(symbol)
            quote_volume_24h = ticker.get('quoteVolume', 0)
            
            # Scarta se non supera il volume minimo richiesto
            if quote_volume_24h is None or quote_volume_24h < MIN_24H_VOLUME_USDT:
                continue
                
            # 2. Recupera lo storico candele Daily (OHLCV)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=LOOKBACK_DAYS + 10)
            if len(ohlcv) < LOOKBACK_DAYS:
                continue
            
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df_range = df.iloc[-LOOKBACK_DAYS:]
            
            highest_high = df_range['high'].max()
            lowest_low = df_range['low'].min()
            current_close = df['close'].iloc[-1]
            
            # Calcolo ampiezza range %
            range_pct = ((highest_high - lowest_low) / lowest_low) * 100
            
            # Prossimità al breakout (0% sui minimi, 100% sui massimi)
            breakout_proximity = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
            
            # 3. Filtra la lateralizzazione
            if range_pct <= MAX_RANGE_PCT:
                # 4. Recupera l'Open Interest (OI)
                oi_data = None
                try:
                    oi_fetch = exchange.fetch_open_interest(symbol)
                    oi_value = oi_fetch.get('openInterestAmount', 0)
                    # Converti in USDT stima (OI contratti * prezzo attuale)
                    oi_usdt = oi_value * current_close if oi_value else 0
                except Exception:
                    oi_usdt = 0
                
                # Calcola il ratio OI su Volume 24h
                oi_to_vol_ratio = (oi_usdt / quote_volume_24h) if quote_volume_24h > 0 else 0
                
                results.append({
                    'Symbol': symbol.replace(':USDT', ''),
                    'Prezzo': current_close,
                    'Range_%': round(range_pct, 2),
                    'Prossimita_Breakout_%': round(breakout_proximity, 1),
                    'Vol_24h_M$': round(quote_volume_24h / 1_000_000, 2),
                    'OI_M$': round(oi_usdt / 1_000_000, 2),
                    'Ratio_OI/Vol': round(oi_to_vol_ratio, 2)
                })
                
        except Exception:
            continue

    # --- STAMPA DEL REPORT FINALIZZATO ---
    if results:
        res_df = pd.DataFrame(results)
        # Ordina per prossimità al breakout (decrescente) e poi per range più stretto
        res_df = res_df.sort_values(by=['Prossimita_Breakout_%', 'Range_%'], ascending=[False, True])
        
        print("\n" + "="*80)
        print("=== CANDIDATI LONG BYBIT FUTURES (ACCUMULAZIONE + HIGH OI) ===")
        print("="*80)
        print(res_df.to_string(index=False))
        print("="*80)
        print("\nNote operative sui risultati:")
        print("- Prossimita_Breakout_% > 80%: Il prezzo è vicino alla resistenza del range.")
        print("- Ratio_OI/Vol alto (> 0.5): Indica un'elevata presenza di posizioni aperte sul derivato rispetto ai volumi correnti.")
    else:
        print("Nessuna coppia trovata che rispetta i criteri di volume, OI e lateralizzazione.")

if __name__ == "__main__":
    run_bybit_advanced_scanner()