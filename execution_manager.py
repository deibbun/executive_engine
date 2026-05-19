import psycopg2
from decimal import Decimal
import logging
from datetime import datetime

logger = logging.getLogger("ExecutiveEngine.RiskManager")

# ==========================================
# STANDALONE GOVERNOR FUNCTIONS
# ==========================================

def calculate_tranche_orders(symbol: str, liquid_cash: float, current_price: float, vol_multiplier: float, risk_pct: float = 0.02) -> dict:
    """
    Calculates a dynamic 3-part limit order ladder.
    Multiplies base drop thresholds by live market volatility (ATR).
    """
    allocations = [0.30, 0.30, 0.40] 
    base_drops = [0.0, 3.0, 6.0]     

    KRAKEN_MIN_USD = 2.00
    
    total_target_usd = liquid_cash * risk_pct
    
    if total_target_usd < (KRAKEN_MIN_USD * 3):
        return {"status": "REJECTED", "reason": "Insufficient funds to split into 3 tranches."}
        
    orders = []
    
    for i in range(3):
        dynamic_drop_pct = base_drops[i] * vol_multiplier
        target_price = current_price * (1 - (dynamic_drop_pct / 100))
        tranche_usd = total_target_usd * allocations[i]
        qty = tranche_usd / target_price
        
        orders.append({
            "tranche_level": i + 1,
            "target_price": round(target_price, 2),
            "drop_pct": round(dynamic_drop_pct, 2),
            "usd_size": round(tranche_usd, 2),
            "qty": round(qty, 6)
        })
        
    return {
        "status": "APPROVED",
        "total_usd": round(total_target_usd, 2),
        "orders": orders
    }

def record_equity_snapshot(db_conn, liquid_cash: float, current_prices: dict, strategy_id: str = 'master') -> float:
    """
    Calculates the live portfolio net worth and saves an immutable
    timestamped row to the equity_snapshots ledger, ISOLATED by strategy.
    """
    cursor = db_conn.cursor()
    try:
        # 🛡️ STRATEGY ISOLATION: Fetch only the assets THIS strategy is holding
        cursor.execute("SELECT symbol, qty FROM positions WHERE status = 'OPEN' AND strategy_id = %s;", (strategy_id,))
        open_positions = cursor.fetchall()
        
        open_positions_value_usd = 0.0
        
        for symbol, qty in open_positions:
            live_price = current_prices.get(symbol, 0.0)
            open_positions_value_usd += float(qty) * float(live_price)
            
        total_net_worth_usd = float(liquid_cash) + open_positions_value_usd
        
        # 🛡️ STRATEGY ISOLATION: Insert the snapshot explicitly tagged for this bot
        insert_query = """
            INSERT INTO equity_snapshots
            (strategy_id, available_cash_usd, reserved_cash_usd, open_positions_value_usd, total_net_worth_usd)
            VALUES (%s, %s, %s, %s, %s);
        """
        cursor.execute(insert_query, (strategy_id, liquid_cash, 0.0, open_positions_value_usd, total_net_worth_usd))
        db_conn.commit()
            
        return total_net_worth_usd
            
    except Exception as e:
        db_conn.rollback()
        print(f"Database error while recording equity snapshot for {strategy_id}:  {e}")
        return 0.0
    finally:
        cursor.close()

# ==========================================
# MAIN EXECUTION CLASS
# ==========================================

class ExecutionManager:
    # 🛡️ STRATEGY ISOLATION: Accept strategy_id on initialization
    def __init__(self, db_config=None, strategy_id='master'):
        self.strategy_id = strategy_id
        self.logger = logging.getLogger(f"ExecutiveEngine.Execution.{self.strategy_id.upper()}")
        
        self.db_params = db_config or {
            'dbname': 'cryptobot',
            'user': 'deibbun',
            'password': 'Ps1s&iwo',
            'host': '127.0.0.1',
            'port': '5432'
        }

    def execute_paper_order(self, symbol, side, price, amount):
        """Simulates an exchange execution and logs it into PostgreSQL."""
        try:
            f_price = float(price)
            f_amount = float(amount)
            total_usd = f_price * f_amount
            
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            # 🛡️ STRATEGY ISOLATION: Tag the receipt
            query = """
                INSERT INTO paper_trades (symbol, strategy_id, side, price, amount, total_usd)
                VALUES (%s, %s, %s, %s, %s, %s);
            """
            cur.execute(query, (symbol, self.strategy_id, side, f_price, f_amount, float(total_usd)))
            conn.commit()
            
            self.logger.info(f"[PAPER TRADE] Successfully executed {side} for {f_amount:.6f} {symbol} at ${f_price:.2f} (Total: ${total_usd:.2f})")
            
            cur.close()
            conn.close()
            return True
            
        except Exception as e:
            self.logger.error(f"Database error tracking paper trade: {e}")
            return False

    def is_already_holding(self, symbol):
        """Checks if our last recorded action for this symbol AND strategy was a BUY."""
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            query = """
                SELECT side FROM paper_trades 
                WHERE symbol = %s AND strategy_id = %s
                ORDER BY timestamp DESC LIMIT 1;
            """
            cur.execute(query, (symbol, self.strategy_id))
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
        """Retrieves the exact amount bought in the last trade by THIS specific bot."""
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            query = """
                SELECT amount FROM paper_trades 
                WHERE symbol = %s AND side = 'BUY' AND strategy_id = %s
                ORDER BY timestamp DESC LIMIT 1;
            """
            cur.execute(query, (symbol, self.strategy_id))
            result = cur.fetchone()
            
            cur.close()
            conn.close()
            
            if result:
                return Decimal(str(result[0]))
            return Decimal('0')
            
        except Exception as e:
            self.logger.error(f"Error fetching position amount: {e}")
            return Decimal('0')
            
    def enforce_time_stops(self, live_prices: dict, max_hold_hours: int = 72):
        """
        Scans for open positions older than the allowed holding period belonging to THIS bot.
        """
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()

            query = """
                SELECT symbol, qty, entry_price 
                FROM positions 
                WHERE status = 'OPEN' AND strategy_id = %s
                AND last_updated < NOW() - INTERVAL '%s hours';
            """
            cur.execute(query, (self.strategy_id, max_hold_hours))
            stale_positions = cur.fetchall()

            if not stale_positions:
                return  

            for pos in stale_positions:
                symbol, qty, entry_price = pos
                current_price = live_prices.get(symbol)

                if not current_price:
                    continue

                total_value = float(qty) * float(current_price)
                
                self.logger.warning(f"⏳ [TIME STOP] {symbol} held for > {max_hold_hours} hrs. Liquidating to free capital.")

                self.execute_paper_order(symbol, 'SELL', float(current_price), float(qty))

                cur.execute("""
                    UPDATE positions 
                    SET status = 'WAITING', qty = 0, entry_price = 0, initial_margin_usd = 0 
                    WHERE symbol = %s AND strategy_id = %s;
                """, (symbol, self.strategy_id))

                cur.execute("""
                    UPDATE account_balance 
                    SET liquid_usd = liquid_usd + %s 
                    WHERE account_id = 1;
                """, (total_value,))

            conn.commit()
            
        except Exception as e:
            self.logger.error(f"Error enforcing time stops: {e}")
        finally:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()