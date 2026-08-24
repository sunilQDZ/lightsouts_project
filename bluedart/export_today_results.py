import pandas as pd
import pymysql
from datetime import datetime
import os

# Add the parent directory to sys.path so we can import the 'bluedart' package
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bluedart.core.config import settings

def export_today_data():
    print("Connecting to database...")
    try:
        connection = pymysql.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASS,
            database=settings.DB_NAME,
            charset='utf8mb4'
        )
        
        query = """
            SELECT * FROM AI_Analyzed 
            WHERE DATE(created_at) = CURDATE()
        """
        
        print("Fetching today's analyzed records...")
        df = pd.read_sql(query, connection)
        
        if df.empty:
            print("No records found for today.")
            return
            
        filename = f"bluedart_analyzed_today_{datetime.now().strftime('%Y%m%d')}.csv"
        df.to_csv(filename, index=False)
        print(f"Successfully exported {len(df)} records to {filename}")
        print("You can open this CSV file directly in Microsoft Excel.")
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'connection' in locals() and connection.open:
            connection.close()

if __name__ == "__main__":
    export_today_data()
