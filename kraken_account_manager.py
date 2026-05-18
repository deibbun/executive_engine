import ccxt
import logging

logger = logging.getLogger("ExecutiveEngine.KrakenAccount")

class KrakenAccountManager:
    def __init__(self, api_key: str, api_secret: str, live_production: bool = False):
        """
        Initializes the private Kraken API interface via CCXT.
        """
        exchange_options = {
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,  # Essential to prevent Kraken from banning your Pi's IP
        }
        
        self.exchange = ccxt.kraken(exchange_options)
        self.live_production = live_production
        
        # NOTE: Kraken Spot does not support a native CCXT sandbox URL.
        # We handle paper trading locally via PostgreSQL instead of an exchange testnet.

    def get_balances(self) -> dict:
        """
        Fetches active asset balances. Cleans out zero-balances 
        so your terminal display stays uncluttered.
        """
        try:
            raw_balance = self.exchange.fetch_balance()
            # CCXT unifies the response structure into the 'total' sub-dictionary
            active_balances = {
                asset: total_qty 
                for asset, total_qty in raw_balance.get('total', {}).items() 
                if total_qty > 0
            }
            return active_balances
        except ccxt.AuthenticationError:
            logger.error("Kraken Authentication Failed. Double-check your API key and secret.")
            return {}
        except ccxt.NetworkError as e:
            logger.error(f"Network timeout reaching Kraken API: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error pulling balances: {e}")
            return {}

    def get_open_orders(self, symbol: str = None) -> list:
        """
        Retrieves all currently active/unfilled working limit orders.
        Optionally filter by a single pair like 'BTC/USD'.
        """
        try:
            open_orders = self.exchange.fetch_open_orders(symbol=symbol)
            return self._parse_orders(open_orders)
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            return []

    def get_closed_orders(self, symbol: str = None, limit: int = 10) -> list:
        """
        Retrieves the historical record of filled or canceled orders.
        """
        try:
            closed_orders = self.exchange.fetch_closed_orders(symbol=symbol, limit=limit)
            return self._parse_orders(closed_orders)
        except Exception as e:
            logger.error(f"Error fetching closed orders: {e}")
            return []

    def _parse_orders(self, ccxt_orders_list: list) -> list:
        """
        Helper method to strip down heavy CCXT dictionary payloads 
        into streamlined maps for quick display or DB entry.
        """
        parsed_list = []
        for o in ccxt_orders_list:
            parsed_list.append({
                'id': o.get('id'),
                'timestamp': o.get('datetime'),
                'symbol': o.get('symbol'),
                'type': o.get('type'),
                'side': o.get('side').upper(),
                'price': o.get('price'),
                'amount': o.get('amount'),
                'filled': o.get('filled'),
                'status': o.get('status').upper()
            })
        return parsed_list