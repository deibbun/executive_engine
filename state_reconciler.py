import json
import psycopg2
from psycopg2.extras import RealDictCursor
from decimal import Decimal
import logging

# Database credentials (matching your setup script)
DB_CONFIG = {
    'dbname': 'cryptobot',
    'user': 'deibbun',
    'password': 'Ps1s&iwo',
    'host': '127.0.0.1',
    'port': '5432'
}

class StateReconciler:
    def __init__(self, config_path='wallet.json'):
        self.config_path = config_path
        self.logger = logging.getLogger("ExecutiveEngine.Reconciler")
        
    def get_total_balance(self):
        """Reads the total USD balance directly from the PostgreSQL master account table."""
        conn = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            
            # Fetch the live cash pool from the database
            cursor.execute("SELECT liquid_usd FROM account_balance WHERE account_id = 1;")
            result = cursor.fetchone()
            
            cursor.close()
            
            if result:
                return Decimal(str(result[0]))
            return Decimal("0.00")
            
        except Exception as e:
            self.logger.error(f"Database error reading balance: {e}")
            return Decimal("0.00")
        finally:
            if conn:
                conn.close()

    def get_reserved_funds(self):
        """
        Calculates locked USD for pending T2 and T3 tranches 
        based on active 'HOLDING' positions in PostgreSQL.
        """
        reserved = {
            'BTC/USD': Decimal("0.00"),
            'ETH/USD': Decimal("0.00"),
            'SOL/USD': Decimal("0.00")
        }
        
        conn = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            # RealDictCursor keeps your row['column_name'] syntax working perfectly
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("SELECT symbol, tranche_level, trade_size FROM bot_state WHERE status = 'HOLDING'")
            rows = cursor.fetchall()
            
            for row in rows:
                symbol = row['symbol']
                
                # Normalize 'BTCUSD' to 'BTC/USD' for CCXT compatibility
                if symbol.endswith('USD') and '/' not in symbol:
                    symbol = f"{symbol[:-3]}/USD"
                
                tranche_level = int(row['tranche_level'])
                current_size = Decimal(str(row['trade_size']))
                
                if tranche_level == 1:
                    reserved_usd = (current_size / Decimal("0.30")) * Decimal("0.70")
                    reserved[symbol] = reserved_usd.quantize(Decimal("0.01"))
                elif tranche_level == 2:
                    reserved_usd = (current_size / Decimal("0.60")) * Decimal("0.40")
                    reserved[symbol] = reserved_usd.quantize(Decimal("0.01"))

            cursor.close()
        except Exception as e:
            self.logger.error(f"Database error in Reconciler: {e}")
        finally:
            if conn:
                conn.close()
                
        return reserved
