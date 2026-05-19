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
                
                # ---------------------------------------------------------
                # 🚀 NEW: MOMENTUM & BREAKOUT MATH
                # ---------------------------------------------------------
                # 1. Find the highest price of the last 24 hours (excluding the current unclosed hour)
                rolling_24h_high = df['high'].iloc[-25:-1].max()
                
                # 2. Calculate the average volume over the last 24 hours
                avg_24h_volume = df['volume'].iloc[-25:-1].mean()
                current_volume = latest['volume']
                
                # 3. Detect if volume is exploding (e.g., 2.5x higher than normal)
                volume_spike = current_volume > (avg_24h_volume * 2.5)
                #volume_spike = True
                
                # 4. Detect if price is breaking through the 24h ceiling
                is_breaking_out = float(current_price) > rolling_24h_high
                #is_breaking_out = True
                
                # The Ultimate Momentum Trigger: Breaking resistance WITH massive volume
                momentum_ignition = is_breaking_out and volume_spike
                # ---------------------------------------------------------

                # 5. The Whipsaw Defense (Standard SMA Strategy)
                is_hunting = (current_price > current_sma) and (atr_pct > Decimal("0.5"))
                
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
        
    def calculate_pairs_spread(self, leader_symbol='BTC/USD', laggard_symbol='SOL/USD', lookback_hours=24) -> dict:
        """
        Calculates the 24-hour performance gap between two correlated assets.
        Returns the spread data to determine if the 'rubber band' is stretched.
        """
        try:
            # Fetch 24 hours of data for both coins
            leader_ohlcv = self.exchange.fetch_ohlcv(leader_symbol, timeframe='1h', limit=lookback_hours)
            laggard_ohlcv = self.exchange.fetch_ohlcv(laggard_symbol, timeframe='1h', limit=lookback_hours)
            
            if not leader_ohlcv or not laggard_ohlcv:
                return {"status": "ERROR", "reason": "Missing data"}

            # Calculate Leader Returns (e.g., Bitcoin)
            leader_start_price = float(leader_ohlcv[0][1]) # Open price 24h ago
            leader_current_price = float(leader_ohlcv[-1][4]) # Current Close price
            leader_pct_change = ((leader_current_price - leader_start_price) / leader_start_price) * 100

            # Calculate Laggard Returns (e.g., Solana)
            laggard_start_price = float(laggard_ohlcv[0][1])
            laggard_current_price = float(laggard_ohlcv[-1][4])
            laggard_pct_change = ((laggard_current_price - laggard_start_price) / laggard_start_price) * 100

            # Calculate the "Rubber Band" Spread
            # If BTC is up 5% and SOL is down 1%, the spread is 6.0%
            spread = leader_pct_change - laggard_pct_change

            return {
                "status": "SUCCESS",
                "leader": leader_symbol,
                "laggard": laggard_symbol,
                "leader_pct": round(leader_pct_change, 2),
                "laggard_pct": round(laggard_pct_change, 2),
                "spread": round(spread, 2),
                "laggard_current_price": laggard_current_price
            }

        except Exception as e:
            self.logger.error(f"Error calculating pairs spread: {e}")
            return {"status": "ERROR"}