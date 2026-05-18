import psycopg2

db_params = {
    'dbname': 'cryptobot',
    'user': 'deibbun',
    'password': 'Ps1s&iwo',
    'host': '127.0.0.1',
    'port': '5432'
}

def bootstrap_database():
    print("Booting PostgreSQL Architecture...")
    try:
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()

        # 1. Master Account Balance Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS account_balance (
                account_id INTEGER PRIMARY KEY,
                liquid_usd NUMERIC NOT NULL
            );
        """)

        # Seed the initial $10,009.58 if it doesn't exist
        cur.execute("""
            INSERT INTO account_balance (account_id, liquid_usd) 
            SELECT 1, 10009.58 
            WHERE NOT EXISTS (SELECT 1 FROM account_balance WHERE account_id = 1);
        """)

        # 2. Live Positions Tracker
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol VARCHAR(20) PRIMARY KEY,
                status VARCHAR(20) DEFAULT 'WAITING',
                qty NUMERIC DEFAULT 0.0,
                entry_price NUMERIC DEFAULT 0.0,
                initial_margin_usd NUMERIC DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Insert the three coins we track so the UPDATE commands don't fail
        coins = ['BTC/USD', 'ETH/USD', 'SOL/USD']
        for coin in coins:
            cur.execute("""
                INSERT INTO positions (symbol, status) 
                SELECT %s, 'WAITING' 
                WHERE NOT EXISTS (SELECT 1 FROM positions WHERE symbol = %s);
            """, (coin, coin))

        # 3. Paper Trade Ledger (Receipts)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20),
                side VARCHAR(10),
                price NUMERIC,
                amount NUMERIC,
                total_usd NUMERIC,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 4. Hourly Equity Snapshots
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                available_cash_usd NUMERIC,
                reserved_cash_usd NUMERIC,
                open_positions_value_usd NUMERIC,
                total_net_worth_usd NUMERIC
            );
        """)

        conn.commit()
        print("✅ Database Architecture Built Successfully!")

    except Exception as e:
        print(f"❌ Database Error: {e}")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    bootstrap_database()