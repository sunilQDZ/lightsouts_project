import asyncio
import os
import pymysql
import aiomysql
from dotenv import load_dotenv

from lt.services.insight_service import generate_insight
from lt.core.database import init_db_pool, close_db_pool
from lt.services.heuristics import MIN_COMMENT_LENGTH

load_dotenv(override=True)

TOUCHPOINTS = {
    "survey_dynamic_id_1": "Two Wheeler Loan",
    "survey_dynamic_id_8": "Personal Loan",
    "survey_dynamic_id_4": "Home Loan",
    "survey_dynamic_id_5": "Farm Loan",
    "survey_dynamic_id_6": "SME Loan",
    "survey_dynamic_id_7": "Micro Loan"
}
from lt.core.config import settings

DB_CONFIG = {
    "host": settings.DB_HOST,
    "port": settings.DB_PORT,
    "user": settings.DB_USER,
    "password": settings.DB_PASS,
    "db": settings.DB_NAME,
    "charset": "utf8mb4",
    "cursorclass": aiomysql.DictCursor,
    "autocommit": True,
    "pool_recycle": 1800,
    "connect_timeout": 10,
}

async def get_dynamic_columns(cursor, table_name):
    """
    Dynamically finds the NPS column (contains 'likely') 
    and Comment columns (contains 'suggestion' or 'reason')
    """
    await cursor.execute(f"SHOW COLUMNS FROM {table_name};")
    columns = await cursor.fetchall()
    
    nps_col = None
    comment_cols = []
    
    for row in columns:
        field = row['Field'].lower()
        if 'likely' in field or 'nps' in field:
            nps_col = row['Field']
            
        if 'suggestion' in field:
            if 'text' in row['Type'].lower() or 'varchar' in row['Type'].lower():
                comment_cols.append(row['Field'])
                
    return nps_col, comment_cols

async def process_touchpoint(pool, table_name, touchpoint_name, target_date=None):
    print(f"\n[{touchpoint_name}] Starting processing for {table_name} (Date: {target_date or 'Yesterday'})...")
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            # 1. Verify table exists
            await cursor.execute("SHOW TABLES LIKE %s;", (table_name,))
            if not await cursor.fetchone():
                print(f"[{touchpoint_name}] Table {table_name} does not exist. Skipping.")
                return
                
            # 2. Get dynamic columns
            nps_col, comment_cols = await get_dynamic_columns(cursor, table_name)
            
            if not nps_col:
                print(f"[{touchpoint_name}] Could not find NPS column (no 'likely' or 'nps' in name). Skipping.")
                return
                
            if not comment_cols:
                print(f"[{touchpoint_name}] Could not find any Verbatim comment columns. Skipping.")
                return
                
            print(f"[{touchpoint_name}] Found NPS column: {nps_col}")
            print(f"[{touchpoint_name}] Found Comment columns: {comment_cols}")
            
            # 3. Fetch Detractors for specific date or yesterday
            # Using CONCAT_WS to join multiple verbatim columns if they exist
            concat_expr = f"CONCAT_WS('. ', {', '.join(comment_cols)})"
            
            date_filter = f"DATE('{target_date}')" if target_date else "CURDATE() - INTERVAL 1 DAY"
            
            query = f"""
                SELECT id, survey_response_id, created_at as response_date, {nps_col} as nps_score, {concat_expr} as verbatim
                FROM {table_name}
                WHERE DATE(created_at) = {date_filter}
                  AND {concat_expr} IS NOT NULL 
                  AND LENGTH(TRIM({concat_expr})) >= {MIN_COMMENT_LENGTH}
                  AND {nps_col} <= 6
            """
            try:
                await cursor.execute(query)
                rows = await cursor.fetchall()
            except Exception as e:
                print(f"[{touchpoint_name}] Error querying data: {e}")
                return
                
            if not rows:
                print(f"[{touchpoint_name}] No valid comments found for yesterday.")
                return
                
            print(f"[{touchpoint_name}] Found {len(rows)} comments. Sending to AI Pipeline...")
            
            # 4. Process with AI
            # Batch process with a semaphore (max 10 concurrent requests) to avoid overwhelming the Anthropic API
            semaphore = asyncio.Semaphore(10)
            
            async def bounded_generate(row, idx_num, total_num):
                async with semaphore:
                    verbatim = row['verbatim']
                    nps_val = int(row['nps_score']) if row['nps_score'] else None
                    print(f"[{touchpoint_name}] * Analyzing comment {idx_num}/{total_num} (ID: {row['survey_response_id']})...", flush=True)
                    res = await generate_insight(verbatim, str(row['id']), touchpoint_name=touchpoint_name, nps_score=nps_val)
                    print(f"[{touchpoint_name}] - Finished comment {idx_num}/{total_num} (Priority: {res.get('priority')})!", flush=True)
                    return res

            chunk_size = 20
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i + chunk_size]
                
                tasks = []
                valid_chunk = []
                
                for idx, row in enumerate(chunk):
                    # Check if already processed in AI_Analyzed
                    await cursor.execute(
                        "SELECT id FROM AI_Analyzed WHERE survey_response_id = %s", 
                        (row['survey_response_id'],)
                    )
                    if await cursor.fetchone():
                        print(f"[{touchpoint_name}] Alert for {row['survey_response_id']} already exists in AI_Analyzed. Skipping.", flush=True)
                        continue
                        
                    verbatim = row['verbatim']
                    if verbatim and len(verbatim.strip()) >= MIN_COMMENT_LENGTH:
                        tasks.append(bounded_generate(row, len(tasks) + 1, len(chunk)))
                        valid_chunk.append(row)
                    else:
                        print(f"[{touchpoint_name}] Skipping empty comment for {row['survey_response_id']}", flush=True)
                        
                if not tasks:
                    continue
                        
                # Execute batch concurrently under semaphore control
                results = []
                if tasks:
                    print(f"[{touchpoint_name}] Running first comment sequentially to build Anthropic Prompt Cache...")
                    first_result = await tasks[0]
                    results.append(first_result)
                    
                    if len(tasks) > 1:
                        print(f"[{touchpoint_name}] Running remaining {len(tasks)-1} comments in parallel...")
                        rest_results = await asyncio.gather(*tasks[1:])
                        results.extend(rest_results)
                
                # Insert queries for AI_Analyzed and voc_alerts
                insert_ai_analyzed = """
                    INSERT INTO AI_Analyzed 
                    (survey_response_id, touchpoint, verbatim, voc_translated, nps_score, 
                     priority, category, sub_category, sentiment, observation, recommendations, 
                     customer_response, confidence_score, status, is_critical, is_gibberish, 
                     response_date, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """

                insert_voc_alerts = """
                    INSERT INTO voc_alerts
                    (survey_response_id, touchpoint, customer_verbatim, voc_translated, nps_score, 
                     priority, category, sub_category, sentiment, observations, recommendations, 
                     customer_response, confidence_score, status, is_critical, is_gibberish, 
                     is_mailed, response_date, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, DATE(%s), NOW())
                """
                
                for idx, result in enumerate(results):
                    if not result: continue
                    
                    row = valid_chunk[idx]
                    is_critical = 1 if result.get('priority') == 'critical' else 0
                    is_gibberish = result.get('is_gibberish', 0)
                    semi_autoclosed = result.get('semi_autoclosed', 0)
                    cust_resp = result.get('customer_response') or ''
                    # Status logic: Base on priority instead of customer_response length
                    priority_val = result.get('priority', 'low')
                    
                    if priority_val in ['critical', 'high'] or is_gibberish == 1:
                        status_val = '1'  # Open (Agent Callback / Gibberish for manual review)
                    elif priority_val == 'medium' or result.get('category') == 'Information Request':
                        if result.get('category') in ["Pricing & Charges", "Unwanted Communications"]:
                            status_val = '4'  # Auto-Closed
                        else:
                            status_val = '5'  # Semi-Autoclosed
                    else:
                        status_val = '4'  # Auto-Closed (Low Priority with AI response)
                    
                    try:
                        await cursor.execute(insert_ai_analyzed, (
                            row['survey_response_id'],
                            touchpoint_name,
                            row['verbatim'],
                            result.get('voc_translated'),
                            row['nps_score'],
                            result.get('priority'),
                            result.get('category'),
                            result.get('sub_category'),
                            result.get('sentiment'),
                            result.get('observation'),
                            result.get('recommendations'),
                            result.get('customer_response'),
                            result.get('confidence_score'),
                            status_val,
                            is_critical,
                            is_gibberish,
                            row['response_date']
                        ))
                    except Exception as e:
                        print(f"[{touchpoint_name}] Error inserting AI_Analyzed record for ID {row['survey_response_id']}: {e}")

                    try:
                        await cursor.execute(insert_voc_alerts, (
                            row['survey_response_id'],
                            touchpoint_name,
                            row['verbatim'],
                            result.get('voc_translated'),
                            row['nps_score'],
                            result.get('priority'),
                            result.get('category'),
                            result.get('sub_category'),
                            result.get('sentiment'),
                            result.get('observation'),
                            result.get('recommendations'),
                            result.get('customer_response'),
                            result.get('confidence_score'),
                            status_val,
                            is_critical,
                            is_gibberish,
                            0,
                            row['response_date']
                        ))
                    except Exception as e:
                        print(f"[{touchpoint_name}] Error inserting voc_alerts record for ID {row['survey_response_id']}: {e}")
                        
            print(f"[{touchpoint_name}] Finished processing and inserting records.")
            return

async def run_batch_pipeline(target_date=None):
    print(f"Starting Background Batch VOC Analyzer... (Target Date: {target_date or 'Yesterday'})")
    
    for table_name, touchpoint_name in TOUCHPOINTS.items():
        pool = await aiomysql.create_pool(**DB_CONFIG, minsize=1, maxsize=5)
        try:
            await process_touchpoint(pool, table_name, touchpoint_name, target_date=target_date)
        except Exception as e:
            print(f"[{touchpoint_name}] Unhandled error: {e}")
        finally:
            pool.close()
            await pool.wait_closed()
            
    from lt.services.anthropic_client import close_anthropic_client
    try:
        await close_anthropic_client()
    except Exception:
        pass
        
    print("\nBatch analysis complete! All data stored in AI_Analyzed and voc_alerts.")

if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_batch_pipeline())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
