import ccxt
import pandas as pd
from decimal import Decimal
import logging

class MarketScanner:
    def __init__(self, exchange_id='kraken', sma_period=20):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class()
        self.sma_period = sma_period
        self.logger = logging.getLogger("ExecutiveEngine.Scanner")

    def get_market_signals(self, symbols):
        signals = {}
        for symbol in symbols:
            try:
                # Fetch slightly more data to allow the 14-period ATR to calculate accurately
                limit = self.sma_period + 14 
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=limit)
                
                if not ohlcv:
                    self.logger.warning(f"No data returned for {symbol}")
                    continue

                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # 1. Calculate the SMA
                df['sma'] = df['close'].rolling(window=self.sma_period).mean()
                
                # 2. Calculate the True Range (TR)
                df['prev_close'] = df['close'].shift(1)
                df['tr1'] = df['high'] - df['low']
                df['tr2'] = (df['high'] - df['prev_close']).abs()
                df['tr3'] = (df['low'] - df['prev_close']).abs()
                df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
                
                # 3. Calculate the Average True Range (14-period ATR)
                df['atr'] = df['tr'].rolling(window=14).mean()
                
                latest = df.iloc[-1]
                current_price = Decimal(str(latest['close']))
                current_sma = Decimal(str(latest['sma']))
                current_atr = Decimal(str(latest['atr']))
                
                # 4. Calculate the Volatility Multiplier
                # (ATR as a percentage of the current price)
                atr_pct = (current_atr / current_price) * 100
                
                # Assuming 1.0% hourly movement is "normal baseline volatility"
                # If ATR is 2.5%, the multiplier becomes 2.5
                vol_multiplier = max(Decimal("1.0"), atr_pct) 
                
                is_hunting = current_price > current_sma
                
                signals[symbol] = {
                    'price': current_price.quantize(Decimal("0.01")),
                    'sma': current_sma.quantize(Decimal("0.01")),
                    'atr_pct': atr_pct.quantize(Decimal("0.01")),
                    'vol_multiplier': vol_multiplier.quantize(Decimal("0.01")),
                    'is_hunting': is_hunting
                }
            except Exception as e:
                self.logger.error(f"Error scanning {symbol}: {e}")
                signals[symbol] = {'price': Decimal("0"), 'sma': Decimal("0"), 'atr_pct': Decimal("0"), 'vol_multiplier': Decimal("1"), 'is_hunting': False}
                
        return signals