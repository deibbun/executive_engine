import psycopg2
from decimal import Decimal
import logging

class ExecutionManager:
    def __init__(self, db_config=None):
        self.logger = logging.getLogger("ExecutiveEngine.Execution")
        # Updated dbname to 'cryptobot'
        self.db_params = db_config or {
            'dbname': 'cryptobot',
            'user': 'deibbun',
            'password': 'Ps1s&iwo',
            'host': '127.0.0.1',
            'port': '5432'
        }

    def execute_paper_order(self, symbol, side, price, amount):
        """Simulates an exchange execution and logs it into PostgreSQL."""
        total_usd = price * amount
        
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            query = """
                INSERT INTO paper_trades (symbol, side, price, amount, total_usd)
                VALUES (%s, %s, %s, %s, %s);
            """
            cur.execute(query, (symbol, side, float(price), float(amount), float(total_usd)))
            conn.commit()
            
            self.logger.info(f"[PAPER TRADE] Successfully executed {side} for {amount:.6f} {symbol} at ${price:.2f} (Total: ${total_usd:.2f})")
            
            cur.close()
            conn.close()
            return True
            
        except Exception as e:
            self.logger.error(f"Database error tracking paper trade: {e}")
            return False

    def is_already_holding(self, symbol):
        """Checks if our last recorded action for this symbol was a BUY."""
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            query = """
                SELECT side FROM paper_trades 
                WHERE symbol = %s 
                ORDER BY timestamp DESC LIMIT 1;
            """
            cur.execute(query, (symbol,))
            result = cur.fetchone()
            
            cur.close()
            conn.close()
            
            if result and result[0] == 'BUY':
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking position state: {e}")
            return False

    def get_current_position_amount(self, symbol):
        """Retrieves the exact amount bought in the last trade so we can liquidate it entirely."""
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            query = """
                SELECT amount FROM paper_trades 
                WHERE symbol = %s AND side = 'BUY'
                ORDER BY timestamp DESC LIMIT 1;
            """
            cur.execute(query, (symbol,))
            result = cur.fetchone()
            
            cur.close()
            conn.close()
            
            if result:
                return Decimal(str(result[0]))
            return Decimal('0')
            
        except Exception as e:
            self.logger.error(f"Error fetching position amount: {e}")
            return Decimal('0')