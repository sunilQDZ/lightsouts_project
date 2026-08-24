import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from datetime import datetime
import pandas as pd
import pymysql
from npci.core.config import settings

def export_today_data():
    conn = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASS,
        db=settings.DB_NAME,
        charset='utf8mb4'
    )
    
    query = """
    SELECT *
    FROM AI_Analyzed
    WHERE DATE(created_at) = CURDATE()
      AND (survey_response_id LIKE '%_q3' OR survey_response_id LIKE '%_q6' OR survey_response_id LIKE 'gen_id_%')
    """
    
    print("Fetching today's processed NPCI data from AI_Analyzed...")
    df = pd.read_sql(query, conn)
    conn.close()
    
    if df.empty:
        print("No NPCI data processed today found in the database.")
        return
        
    filename = f"npci_processed_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join(os.path.dirname(__file__), filename)
    df.to_excel(filepath, index=False)
    print(f"Data exported successfully to: {filepath}")

if __name__ == '__main__':
    export_today_data()
