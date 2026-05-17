import time
import logging
from decimal import Decimal
from state_reconciler import StateReconciler
from funding_manager import FundingManager
from market_scanner import MarketScanner 
from execution_manager import ExecutionManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ExecutiveEngine")

def run_engine():
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
            
            logger.info("Scanning Kraken for live SMA signals...")
            active_signals = scanner.get_market_signals(target_symbols)

            allocations = funding.allocate(total_balance, reserved_dict, active_signals)
            liquid_pool = funding.get_liquid_pool(total_balance, reserved_dict)
            
            logger.info(f"--- Cycle Update ---")
            logger.info(f"Liquid Pool: ${liquid_pool}")
            
            for symbol, data in active_signals.items():
                status = "HUNTING" if data['is_hunting'] else "WAITING"
                logger.info(f"[{symbol}] Price: ${data['price']} | SMA: ${data['sma']} | {status}")
                
            # COMPREHENSIVE EXECUTION LOOP (ENTRIES & EXITS)
            for symbol in target_symbols:
                usd_allocation = allocations.get(symbol, Decimal('0'))
                is_holding = executor.is_already_holding(symbol)
                current_price = active_signals[symbol]['price']
                
                # Case 1: Strategy wants to buy, and we don't have a position yet
                if usd_allocation > 0 and not is_holding:
                    target_amount = usd_allocation / current_price
                    logger.info(f" > Signal Triggered! Sending BUY allocation for {symbol}...")
                    executor.execute_paper_order(symbol, 'BUY', current_price, target_amount)
                
                # Case 2: Strategy drops allocation to 0, but we are still holding the asset
                elif usd_allocation == 0 and is_holding:
                    hold_amount = executor.get_current_position_amount(symbol)
                    if hold_amount > 0:
                        logger.info(f" > Exit Signal Triggered! Sending SELL order to liquidate {symbol}...")
                        executor.execute_paper_order(symbol, 'SELL', current_price, hold_amount)
                
                # Case 3: Standing holding state
                elif usd_allocation > 0 and is_holding:
                    logger.info(f" > {symbol}: Strategy active & Position open. Holding trend.")

            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("Engine shutting down gracefully...")
            break
        except Exception as e:
            logger.error(f"Critical Engine Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_engine()