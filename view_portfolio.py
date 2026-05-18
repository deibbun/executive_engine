import sys
import json
import psycopg2
from kraken_account_manager import KrakenAccountManager

def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading configuration: {e}")
        sys.exit(1)

def display_local_db_portfolio():
    """
    Fetches and formats local paper trading positions from your PostgreSQL ledger.
    """
    print("=========================================================================")
    print("                        EXECUTIVE ENGINE PORTFOLIO (LOCAL DB)")
    print("=========================================================================")
    print(f"{'SYMBOL':<10} | {'STATUS':<8} | {'QTY':<12} | {'ENTRY':<10} | {'CURRENT':<10} | {'PnL %'}")
    print("-------------------------------------------------------------------------")
    
    # Placeholder layout to mirror your engine's tracked SQL rows
    # In practice, substitute with your active `SELECT * FROM positions` cursor block
    mock_db_positions = [
        {"symbol": "ETH/USD", "status": "OPEN", "qty": 4.5960, "entry": 2177.90, "current": 2182.50, "pnl": "+0.21%"},
        {"symbol": "SOL/USD", "status": "OPEN", "qty": 57.9124, "entry": 86.42, "current": 86.72, "pnl": "+0.35%"},
        {"symbol": "BTC/USD", "status": "FLAT", "qty": 0.0000, "entry": None, "current": None, "pnl": "--"}
    ]
    
    for pos in mock_db_positions:
        entry_str = f"${pos['entry']:.2f}" if pos['entry'] else "--"
        curr_str = f"${pos['current']:.2f}" if pos['current'] else "--"
        print(f"{pos['symbol']:<10} | {pos['status']:<8} | {pos['qty']:<12.4f} | {entry_str:<10} | {curr_str:<10} | {pos['pnl']}")
    print("=========================================================================")

def display_live_exchange_state(config):
    """
    Queries Kraken directly via CCXT to print live balance, open limits, and closures.
    """
    # Instantiate account manager
    manager = KrakenAccountManager(
        api_key=config.get('KRAKEN_API_KEY', ''),
        api_secret=config.get('KRAKEN_API_SECRET', ''),
        live_production=False  # Sandbox verification mode
    )
    
    print("\n=========================================================================")
    print("                        LIVE KRAKEN EXCHANGE STATE")
    print("=========================================================================")
    
    # 1. Fetch Balances
    print("[1] ACTIVE HARDWARE BALANCES:")
    balances = manager.get_balances()
    if not balances:
        print("    No active asset balances found or authentication timed out.")
    else:
        for asset, qty in balances.items():
            print(f"    • {asset:<6}: {qty:.4f}")
            
    # 2. Fetch Open Working Orders
    print("\n[2] CURRENT OPEN WORKING ORDERS:")
    open_orders = manager.get_open_orders()
    if not open_orders:
        print("    No pending open limit orders.")
    else:
        print(f"    {'ID':<10} | {'SIDE':<4} | {'PAIR':<8} | {'PRICE':<10} | {'QTY':<8} | {'STATUS'}")
        for o in open_orders:
            print(f"    {o['id'][:8]:<10} | {o['side']:<4} | {o['symbol']:<8} | ${o['price']:<9.2f} | {o['amount']:<8.2f} | {o['status']}")

    # 3. Fetch Closed Orders
    print("\n[3] RECENT ARCHIVED HISTORICAL ORDERS:")
    closed_orders = manager.get_closed_orders(limit=3)
    if not closed_orders:
        print("    No historical orders found on this profile.")
    else:
        for o in closed_orders:
            print(f"    • [{o['timestamp'].split('T')[0]}] {o['side']:<4} {o['symbol']:<8} -> Filled: {o['filled']:.2f}/{o['amount']:.2f} | Status: {o['status']}")
    print("=========================================================================\n")

if __name__ == "__main__":
    config_data = load_config()
    display_local_db_portfolio()
    display_live_exchange_state(config_data)