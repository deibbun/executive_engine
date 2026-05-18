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
    # 1. Base rules from your config.json roadmap
    allocations = [0.30, 0.30, 0.40] # 30%, 30%, 40% capital split
    base_drops = [0.0, 3.0, 6.0]     # 0%, 3%, 6% drops

    KRAKEN_MIN_USD = 2.00
    
    # 2. Total money we are allowing this specific coin to use
    total_target_usd = liquid_cash * risk_pct
    
    if total_target_usd < (KRAKEN_MIN_USD * 3):
        return {"status": "REJECTED", "reason": "Insufficient funds to split into 3 tranches."}
        
    orders = []
    
    # 3. Calculate the exact math for all 3 bullets
    for i in range(3):
        # 🔥 THE MAGIC: Multiply the required price drop by the live volatility!
        dynamic_drop_pct = base_drops[i] * vol_multiplier
        
        # Calculate the exact target price where the limit order should sit
        target_price = current_price * (1 - (dynamic_drop_pct / 100))
        
        # Calculate how much cash this specific bullet gets
        tranche_usd = total_target_usd * allocations[i]
        
        # Calculate exact token quantity
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

def record_equity_snapshot(db_conn, liquid_cash: float, current_prices: dict) -> float:
    """
    Calculates the live portfolio net worth and saves an immutable
    timestamped row to the equity_snapshots ledger.
    """
    cursor = db_conn.cursor()
    try:
        # 1. Fetch only the assets we are currently holding
        cursor.execute("SELECT symbol, qty FROM positions WHERE status = 'OPEN';")
        open_positions = cursor.fetchall()
        
        open_positions_value_usd = 0.0
        
        # 2. Calculate the exact live USD value of all held crypto tokens
        for symbol, qty in open_positions:
            live_price = current_prices.get(symbol, 0.0)
            open_positions_value_usd += float(qty) * float(live_price)
            
        # 3. Calculate absolute institutional net worth
        total_net_worth_usd = float(liquid_cash) + open_positions_value_usd
        
        # 4. Insert the master metrics into the snapshot ledger
        insert_query = """
            INSERT INTO equity_snapshots
            (available_cash_usd, reserved_cash_usd, open_positions_value_usd, total_net_worth_usd)
            VALUES (%s, %s, %s, %s);
        """
        cursor.execute(insert_query, (liquid_cash, 0.0, open_positions_value_usd, total_net_worth_usd))
        db_conn.commit()
            
        return total_net_worth_usd
            
    except Exception as e:
        db_conn.rollback()
        print(f"Database error while recording equity snapshot:  {e}")
        return 0.0
    finally:
        cursor.close()

# ==========================================
# MAIN EXECUTION CLASS
# ==========================================

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
            
    def enforce_time_stops(self, live_prices: dict, max_hold_hours: int = 72):
        """
        Scans for open positions older than the allowed holding period.
        If found, liquidates them at the current market price to free up capital drag.
        """
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()

            # Find positions older than our max_hold_hours threshold
            query = """
                SELECT symbol, qty, entry_price 
                FROM positions 
                WHERE status = 'OPEN' 
                AND last_updated < NOW() - INTERVAL '%s hours';
            """
            cur.execute(query, (max_hold_hours,))
            stale_positions = cur.fetchall()

            if not stale_positions:
                return  # No stale positions found, exit silently

            for pos in stale_positions:
                symbol, qty, entry_price = pos
                current_price = live_prices.get(symbol)

                if not current_price:
                    continue

                total_value = float(qty) * float(current_price)
                
                self.logger.warning(f"⏳ [TIME STOP] {symbol} held for > {max_hold_hours} hrs. Liquidating to free capital.")

                # 1. Log the paper trade sell to keep our receipts accurate
                self.execute_paper_order(symbol, 'SELL', float(current_price), float(qty))

                # 2. Wipe the position from the active board
                cur.execute("""
                    UPDATE positions 
                    SET status = 'WAITING', qty = 0, entry_price = 0, initial_margin_usd = 0 
                    WHERE symbol = %s;
                """, (symbol,))

                # 3. Inject the salvaged funds back into the master liquid pool
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