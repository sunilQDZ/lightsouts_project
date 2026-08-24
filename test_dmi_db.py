import pymysql
import os
from dotenv import load_dotenv

load_dotenv(override=True)

host = os.getenv("DMI_SURVEY_DB_HOST", "")
if host.startswith("address-"):
    host = host.replace("address-", "")

try:
    conn = pymysql.connect(
        host=host,
        port=int(os.getenv("DMI_SURVEY_DB_PORT", 3306)),
        user=os.getenv("DMI_SURVEY_DB_USER", ""),
        password=os.getenv("DMI_SURVEY_DB_PASSWORD", "").strip('"'),
        db=os.getenv("DMI_SURVEY_DB_NAME", ""),
        cursorclass=pymysql.cursors.DictCursor
    )
    
    with conn.cursor() as cursor:
        print("Checking survey_dynamic_id_1:")
        cursor.execute("DESCRIBE survey_dynamic_id_1")
        for r in cursor.fetchall():
            if 'q' in r['Field'] or 'nps' in r['Field'] or 'id' in r['Field']:
                print(r)
                
        print("\nChecking survey_dynamic_id_2:")
        cursor.execute("DESCRIBE survey_dynamic_id_2")
        for r in cursor.fetchall():
            if 'q' in r['Field'] or 'nps' in r['Field'] or 'id' in r['Field']:
                print(r)
                
    conn.close()
except Exception as e:
    print(f"Failed to connect: {e}")
