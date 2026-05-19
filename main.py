import time
import logging
import psycopg2
import argparse
from decimal import Decimal
from datetime import datetime

from state_reconciler import StateReconciler
from funding_manager import FundingManager
from market_scanner import MarketScanner 
from execution_manager import ExecutionManager, calculate_tranche_orders, record_equity_snapshot

last_snapshot_hour = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def run_engine(strategy_id):
    global last_snapshot_hour
    
    # Custom logger so your terminal output clearly shows which bot is running
    logger = logging.getLogger(f"Engine.{strategy_id.upper()}")
    
    try:
        db_conn = psycopg2.connect(dbname="cryptobot")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return

    reconciler = StateReconciler()
    funding = FundingManager()
    scanner = MarketScanner(exchange_id='kraken', sma_period=20) 
    
    # NOTE: You will need to update ExecutionManager to accept strategy_id as well!
    executor = ExecutionManager(strategy_id=strategy_id) 
    
    # 🎯 Isolate target symbols based on the running strategy
    if strategy_id == 'btc_pure':
        target_symbols = ['BTC/USD']
    elif strategy_id == 'eth_pure':
        target_symbols = ['ETH/USD']
    elif strategy_id == 'sol_pure':
        target_symbols = ['SOL/USD']
    else:
        target_symbols = ['BTC/USD', 'ETH/USD', 'SOL/USD']

    logger.info(f"[{strategy_id.upper()}] Started. Monitoring: {target_symbols}")

    while True:
        try:
            total_balance = reconciler.get_total_balance()
            
            # 🛡️ Get the absolute total of all locked funds to protect the master balance
            total_global_reserved = reconciler.get_all_global_reserved()
            
            current_time = datetime.now()
            
            logger.info("Scanning Kraken for live SMA signals...")
            active_signals = scanner.get_market_signals(target_symbols)

            allocations = funding.allocate(total_balance, total_global_reserved, active_signals, strategy_id=strategy_id)
            
            # Get just this strategy's isolated liquid pool for logging
            strategy_pool = funding.get_strategy_pool(total_balance, total_global_reserved, strategy_id)
            
            logger.info(f"--- Cycle Update ---")
            logger.info(f"Isolated Strategy Pool: ${strategy_pool}")
            
            # 🛡️ RISK DIAL: Fetch drawdown isolated to THIS strategy
            current_risk_pct = funding.calculate_drawdown_governor(db_conn, strategy_id=strategy_id, base_risk=0.02, floor_risk=0.005)
            logger.info(f"[RISK CONTROL] Active Sizing Profile: {current_risk_pct * 100:.2f}% risk per asset allocation.")
            
            # 📊 PAIRS TRADING (Only the Master bot executes this)
            if strategy_id == 'master':
                leader = 'BTC/USD'
                laggards = ['ETH/USD', 'SOL/USD']
                
                for laggard in laggards:
                    spread_data = scanner.calculate_pairs_spread(leader, laggard, lookback_hours=24)
                    
                    if spread_data['status'] == 'SUCCESS':
                        gap = spread_data['spread']
                        if gap >= 4.0:
                            logger.warning(f"🚨 [ARBITRAGE ALERT] 24H Gap is {gap}%! Forcing {laggard} into HUNTING mode.")
                            active_signals[laggard]['is_hunting'] = True
                            
                # Recalculate allocations if arbitrage triggered
                allocations = funding.allocate(total_balance, total_global_reserved, active_signals, strategy_id=strategy_id)
            
            live_prices = {sym: data['price'] for sym, data in active_signals.items()}
            
            # 🧹 TIME-BASED EXITS
            executor.enforce_time_stops(live_prices, max_hold_hours=72)
            
            # COMPREHENSIVE EXECUTION LOOP
            for symbol in target_symbols:
                usd_allocation = allocations.get(symbol, Decimal('0'))
                is_holding = executor.is_already_holding(symbol)
                
                current_price = active_signals[symbol]['price']
                sma = active_signals[symbol]['sma']
                position_status = "HUNTING" if active_signals[symbol]['is_hunting'] else "WAITING"
                
                if active_signals[symbol]['is_hunting'] and position_status == 'WAITING':
                    liquid_cash = float(strategy_pool) 
                    
                    # 🚀 PATH A: THE MOMENTUM BREAKOUT
                    if active_signals[symbol].get('momentum_ignition'):
                        logger.warning(f"🚨 [MOMENTUM IGNITION] Breakout on {symbol}! Executing market buy.")
                        
                        target_usd = liquid_cash * current_risk_pct
                        qty = target_usd / float(current_price)
                        
                        try:
                            cursor = db_conn.cursor()
                            # 🛡️ FIX: Added strategy_id to the WHERE clause
                            cursor.execute("""
                                UPDATE positions 
                                SET status = 'OPEN', qty = %s, entry_price = %s, 
                                    initial_margin_usd = %s, last_updated = CURRENT_TIMESTAMP
                                WHERE symbol = %s AND strategy_id = %s;
                            """, (qty, current_price, target_usd, symbol, strategy_id))
                            
                            cursor.execute("""
                                UPDATE account_balance 
                                SET liquid_usd = liquid_usd - %s 
                                WHERE account_id = 1;
                            """, (target_usd,))
                            
                            db_conn.commit()
                            executor.execute_paper_order(symbol, 'BUY', current_price, qty)
                        except Exception as e:
                            db_conn.rollback()
                        finally:
                            cursor.close()

                    # 📉 PATH B: STANDARD VOLATILITY TRANCHES
                    else:
                        vol_mult = float(active_signals[symbol]['vol_multiplier'])
                        order_plan = calculate_tranche_orders(symbol, liquid_cash, float(current_price), vol_mult, risk_pct=current_risk_pct)
                        
                        if order_plan['status'] == 'APPROVED':
                            t1 = order_plan['orders'][0]
                            target_qty = t1['qty']
                            total_cost = t1['usd_size']
                            
                            try:
                                cursor = db_conn.cursor()
                                # 🛡️ FIX: Added strategy_id to the WHERE clause
                                cursor.execute("""
                                    UPDATE positions 
                                    SET status = 'OPEN', qty = %s, entry_price = %s, 
                                        initial_margin_usd = %s, last_updated = CURRENT_TIMESTAMP
                                    WHERE symbol = %s AND strategy_id = %s;
                                """, (target_qty, current_price, total_cost, symbol, strategy_id))
                                
                                cursor.execute("""
                                    UPDATE account_balance 
                                    SET liquid_usd = liquid_usd - %s 
                                    WHERE account_id = 1;
                                """, (total_cost,))
                                
                                db_conn.commit()
                                success = executor.execute_paper_order(symbol, 'BUY', current_price, target_qty)
                                
                            except Exception as e:
                                db_conn.rollback()
                            finally:
                                cursor.close()
                
                elif usd_allocation == 0 and is_holding:
                    hold_amount = executor.get_current_position_amount(symbol)
                    if hold_amount > 0:
                        executor.execute_paper_order(symbol, 'SELL', current_price, hold_amount)
                
            # SNAPSHOT LOGIC
            if last_snapshot_hour != current_time.hour:
                live_prices = {sym: active_signals[sym]['price'] for sym in target_symbols}
                # Ensure equity snapshots are tracked by strategy
                net_worth = record_equity_snapshot(db_conn, float(strategy_pool), live_prices, strategy_id=strategy_id)
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
    # 🛠️ This allows you to pass the strategy from the command line!
    parser = argparse.ArgumentParser(description="Launch a specific Crypto Trading Strategy.")
    parser.add_argument('--strategy', type=str, required=True, choices=['master', 'btc_pure', 'eth_pure', 'sol_pure'], 
                        help="Which bot to run")
    
    args = parser.parse_args()
    
    run_engine(args.strategy)