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
                limit = self.sma_period + 5 
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=limit)
                
                if not ohlcv:
                    self.logger.warning(f"No data returned for {symbol}")
                    continue

                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['sma'] = df['close'].rolling(window=self.sma_period).mean()
                
                latest = df.iloc[-1]
                current_price = Decimal(str(latest['close']))
                current_sma = Decimal(str(latest['sma']))
                is_hunting = current_price > current_sma
                
                signals[symbol] = {
                    'price': current_price.quantize(Decimal("0.01")),
                    'sma': current_sma.quantize(Decimal("0.01")),
                    'is_hunting': is_hunting
                }
            except Exception as e:
                self.logger.error(f"Error scanning {symbol}: {e}")
                signals[symbol] = {'price': Decimal("0"), 'sma': Decimal("0"), 'is_hunting': False}
        return signals