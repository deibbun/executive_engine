import time
import logging
import psycopg2
from decimal import Decimal
from datetime import datetime

from state_reconciler import StateReconciler
from funding_manager import FundingManager
from market_scanner import MarketScanner 
from execution_manager import ExecutionManager, calculate_tranche_orders, record_equity_snapshot

# Typo fixed here
last_snapshot_hour = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ExecutiveEngine")

def run_engine():
    global last_snapshot_hour
    
    # Establish master database connection for the engine
    try:
        db_conn = psycopg2.connect(dbname="cryptobot")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return

    reconciler = StateReconciler()
    funding = FundingManager()
    scanner = MarketScanner(exchange_id='kraken', sma_period=20) 
    executor = ExecutionManager()
    
    target_symbols = ['BTC/USD', 'ETH/USD', 'SOL/USD']
    logger.info("Executive Engine Started. Monitoring live markets with Paper Execution & Exit Logic...")

    while True:
        try:
            total_balance = reconciler.get_total_balance()
            reserved_dict = reconciler.get_reserved_funds()
            current_time = datetime.now()
            
            logger.info("Scanning Kraken for live SMA signals...")
            active_signals = scanner.get_market_signals(target_symbols)

            allocations = funding.allocate(total_balance, reserved_dict, active_signals)
            liquid_pool = funding.get_liquid_pool(total_balance, reserved_dict)
            
            logger.info(f"--- Cycle Update ---")
            logger.info(f"Liquid Pool: ${liquid_pool}")
            
            # Create a quick dictionary of the live prices for our sweepers
            live_prices = {sym: data['price'] for sym, data in active_signals.items()}
            
            # 🧹  TIME-BASED EXITS:  Sweep for dead capital before making new buys
            executor.enforce_time_stops(live_prices, max_hold_hours=72)
            #executor.enforce_time_stops(live_prices, max_hold_hours=0)
            
            for symbol, data in active_signals.items():
                status = "HUNTING" if data['is_hunting'] else "WAITING"
                logger.info(f"[{symbol}] Price: ${data['price']} | SMA: ${data['sma']} | Vol Multiplier: {data['vol_multiplier']}x | {status}")
                
            # COMPREHENSIVE EXECUTION LOOP (ENTRIES & EXITS)
            for symbol in target_symbols:
                usd_allocation = allocations.get(symbol, Decimal('0'))
                is_holding = executor.is_already_holding(symbol)
                
                # FIX: We must define these variables inside this loop before we use them!
                current_price = active_signals[symbol]['price']
                sma = active_signals[symbol]['sma']
                position_status = "HUNTING" if active_signals[symbol]['is_hunting'] else "WAITING"
                
                # Case 1: Strategy wants to buy, and we don't have a position yet
                if current_price > sma and position_status == 'WAITING':
                    logger.info(f"  > Signal Triggered! Calculating Volatility-Adjusted Tranches for {symbol}...")
                    
                    liquid_cash = float(liquid_pool) 
                    
                    # 1. Pass the live volatility multiplier into the math!
                    vol_mult = float(active_signals[symbol]['vol_multiplier'])
                    order_plan = calculate_tranche_orders(symbol, liquid_cash, current_price, vol_mult, risk_pct=0.02)
                    
                    if order_plan['status'] == 'APPROVED':
                        # Extract Tranche 1 (The immediate Market Buy)
                        t1 = order_plan['orders'][0]
                        target_qty = t1['qty']
                        total_cost = t1['usd_size']
                        
                        try:
                            cursor = db_conn.cursor()
                            
                            # Execute Tranche 1 into the database
                            cursor.execute("""
                                UPDATE positions 
                                SET status = 'OPEN', qty = %s, entry_price = %s, 
                                    initial_margin_usd = %s, last_updated = CURRENT_TIMESTAMP
                                WHERE symbol = %s;
                            """, (target_qty, current_price, total_cost, symbol))
                            
                            cursor.execute("""
                                UPDATE account_balance 
                                SET liquid_usd = liquid_usd - %s 
                                WHERE account_id = 1;
                            """, (total_cost,))
                            
                            db_conn.commit()
                            logger.info(f"  [TRANCHE 1 EXECUTED] Bought {target_qty} {symbol} at ${current_price:,.2f} (Cost: ${total_cost:,.2f})")
                            
                            # Log the dynamic pending limit orders for Tranche 2 and 3
                            t2 = order_plan['orders'][1]
                            t3 = order_plan['orders'][2]
                            logger.info(f"  [PENDING LIMIT] Tranche 2 mapped at ${t2['target_price']:,.2f} (-{t2['drop_pct']}%)")
                            logger.info(f"  [PENDING LIMIT] Tranche 3 mapped at ${t3['target_price']:,.2f} (-{t3['drop_pct']}%)")
                            
                        except Exception as e:
                            db_conn.rollback()
                            logger.error(f"  [DB ERROR] Failed to lock in paper trade for {symbol}: {e}")
                        finally:
                            cursor.close()
            
                    else:
                        logger.info(f"  [RISK MANAGER] Buy aborted for {symbol}: {order_plan.get('reason')}")
                
                # Case 2: Strategy drops allocation to 0, but we are still holding the asset
                elif usd_allocation == 0 and is_holding:
                    hold_amount = executor.get_current_position_amount(symbol)
                    if hold_amount > 0:
                        logger.info(f" > Exit Signal Triggered! Sending SELL order to liquidate {symbol}...")
                        executor.execute_paper_order(symbol, 'SELL', current_price, hold_amount)
                
                # Case 3: Standing holding state
                elif usd_allocation > 0 and is_holding:
                    logger.info(f" > {symbol}: Strategy active & Position open. Holding trend.")
                    
            # SNAPSHOT LOGIC
            if last_snapshot_hour != current_time.hour:
                # Create a simple dictionary of current prices for the snapshot function
                live_prices = {sym: active_signals[sym]['price'] for sym in target_symbols}
                
                net_worth = record_equity_snapshot(db_conn, float(liquid_pool), live_prices)
                
                if net_worth > 0:
                    logger.info(f"\n[🕒 HOURLY LEDGER] Snapshot secured.  Total Network Equity:  ${net_worth:,.2f}\n")
                    
                last_snapshot_hour = current_time.hour

            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("Engine shutting down gracefully...")
            db_conn.close()
            break
        except Exception as e:
            logger.error(f"Critical Engine Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_engine()