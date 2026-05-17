import psycopg2
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_CONFIG = {
    'dbname': 'cryptobot',
    'user': 'deibbun',
    'password': 'super_secret_password',
    'host': 'localhost',
    'port': '5432'
}

def build_schema():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        logging.info("Connected to PostgreSQL successfully. Building schema...")

        create_table_query = """
        CREATE TABLE IF NOT EXISTS bot_state (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            tranche_level INT NOT NULL,
            trade_size DECIMAL(18, 8) NOT NULL,
            status VARCHAR(20) NOT NULL,
            entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        cursor.execute(create_table_query)
        conn.commit()
        
        logging.info("Success: 'bot_state' table is ready for execution.")

    except Exception as e:
        logging.error(f"Failed to build schema: {e}")
    finally:
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    build_schema()
