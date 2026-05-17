import psycopg2
import ccxt
from decimal import Decimal

DB_CONFIG = {
    'dbname': 'cryptobot',
    'user': 'deibbun',
    'password': 'Ps1s&iwo',
    'host': '127.0.0.1',
    'port': '5432'
}

def get_portfolio_status():
    exchange = ccxt.kraken()
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Get the unique list of symbols we've traded
        cur.execute("SELECT DISTINCT symbol FROM paper_trades;")
        symbols = [row[0] for row in cur.fetchall()]
        
        if not symbols:
            print("\n====================================================")
            print("         EXECUTIVE ENGINE PORTFOLIO REPORT          ")
            print("====================================================")
            print(" No paper trades recorded yet. Status: 100% Cash.")
            print("====================================================\n")
            return

        print("\n=========================================================================")
        print("                       EXECUTIVE ENGINE PORTFOLIO                        ")
        print("=========================================================================")
        print(f"{'SYMBOL':<10} | {'STATUS':<8} | {'QTY':<12} | {'ENTRY':<10} | {'CURRENT':<10} | {'PnL %':<8}")
        print("-" * 73)

        for symbol in symbols:
            # Get the absolute latest trade for this token
            cur.execute("""
                SELECT side, price, amount FROM paper_trades 
                WHERE symbol = %s 
                ORDER BY timestamp DESC LIMIT 1;
            """, (symbol,))
            last_trade = cur.fetchone()
            
            if not last_trade:
                continue
                
            side, entry_price, amount = last_trade
            
            if side == 'BUY':
                # Position is OPEN. Fetch live market price to calculate performance
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['close']
                
                pnl_pct = ((current_price - float(entry_price)) / float(entry_price)) * 100
                
                print(f"{symbol:<10} | OPEN     | {amount:<12.4f} | ${float(entry_price):<9.2f} | ${current_price:<9.2f} | {pnl_pct:+.2f}%")
            else:
                # Position is CLOSED
                print(f"{symbol:<10} | FLAT     | {'0.0000':<12} | {'--':<10} | {'--':<10} | --")

        print("=========================================================================\n")
        
        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error compiling portfolio report: {e}")

if __name__ == "__main__":
    get_portfolio_status()