import asyncio
import os
import pymysql
import aiomysql
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

from dmi.services.insight_service import generate_insight
from dmi.services.heuristics import MIN_COMMENT_LENGTH

load_dotenv(override=True)

def parse_response_date(date_val):
    if pd.isnull(date_val):
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(date_val, datetime):
        return date_val.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(date_val, pd.Timestamp):
        return date_val.strftime('%Y-%m-%d %H:%M:%S')
    
    date_str = str(date_val).strip()
    formats = [
        '%d-%m-%Y %I:%M:%S %p', # 02-08-2026 08:49:15 AM
        '%d-%m-%Y %H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%d/%m/%Y %I:%M:%S %p',
        '%d/%m/%Y %H:%M:%S',
        '%Y/%m/%d %H:%M:%S',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
            
    try:
        dt = pd.to_datetime(date_str)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        pass
        
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

from dmi.core.config import settings

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

async def process_database_data(pool):
    print("Connecting to database to fetch latest unanalyzed records dynamically...")
    
    # Auto-ensure loan_application_number column exists in AI_Analyzed and voc_alerts
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            for tbl in ["AI_Analyzed", "voc_alerts"]:
                await cursor.execute(f"SHOW COLUMNS FROM `{tbl}` LIKE 'loan_application_number'")
                col = await cursor.fetchone()
                if not col:
                    try:
                        await cursor.execute(f"ALTER TABLE `{tbl}` ADD COLUMN `loan_application_number` VARCHAR(255) NULL AFTER `mobile`")
                        print(f"Added loan_application_number column to {tbl}")
                    except Exception as e:
                        print(f"Error adding loan_application_number column to {tbl}: {e}")

    survey_ids = [1]  # added in array for future extra surveys
    final_queries = []
    query_params = []
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            for s_id in survey_ids:
                # Fetch questions for this survey to build the dynamic query
                await cursor.execute(
                    "SELECT question_slug, question_type FROM survey_questions WHERE survey_id = %s",
                    (s_id,)
                )
                questions = await cursor.fetchall()
                
                cus_6_slugs = [q['question_slug'] for q in questions if q['question_type'] == 'CUS_6']
                nps_slugs = [q['question_slug'] for q in questions if q['question_type'] in ('CUS_2', 'NPS_2')]
                
                if not cus_6_slugs or not nps_slugs:
                    print(f"Skipping survey {s_id} - missing CUS_6 or NPS columns")
                    continue
                    
                nps_col = nps_slugs[0]
                table_name = f"survey_dynamic_id_{s_id}"
                
                # Check for loan application number column name in the source table
                await cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
                table_cols_raw = await cursor.fetchall()
                table_cols = [c['Field'] for c in table_cols_raw]
                
                if 'loan_application_number' in table_cols:
                    loan_app_expr = "`loan_application_number` AS loan_application_number"
                elif 'loan_application_no' in table_cols:
                    loan_app_expr = "`loan_application_no` AS loan_application_number"
                else:
                    loan_app_expr = "NULL AS loan_application_number"

                sub_queries = []
                for idx, text_col in enumerate(cus_6_slugs):
                    suffix = f"q{idx}"
                    # mapping survey_send_time -> response_datetime, number -> COMPLAINTBY
                    q = f"""
                    SELECT 
                        TRIM(`{text_col}`) AS COMMENTS, 
                        `{nps_col}` AS NPS_SCORE, 
                        '{table_name}' AS TOUCHPOINT, 
                        CONCAT(survey_response_id, '_{suffix}') AS AWBNUMBER,
                        COALESCE(survey_send_time, created_at) AS response_datetime,
                        NULL AS cust_acc_no,
                        NULL AS employee_id,
                        NULL AS PEMPLNAME,
                        CONCAT(survey_response_id, '_{suffix}') AS survey_id,
                        NULL AS EMAILID,
                        number AS COMPLAINTBY,
                        {loan_app_expr}
                    FROM {table_name}
                    WHERE CAST(`{nps_col}` AS SIGNED) <= 6 
                      AND DATE(COALESCE(survey_send_time, created_at)) = CURDATE() - INTERVAL 1 DAY
                      AND `{text_col}` IS NOT NULL 
                      AND LENGTH(TRIM(`{text_col}`)) >= %s
                      AND CONCAT(survey_response_id, '_{suffix}') NOT IN (SELECT survey_response_id FROM AI_Analyzed)
                    """
                    sub_queries.append(q)
                    query_params.append(MIN_COMMENT_LENGTH)
                
                if sub_queries:
                    final_queries.append(" UNION ALL ".join(sub_queries))

            if not final_queries:
                print("No surveys configured or found valid columns.")
                return

            full_query = " UNION ALL ".join(final_queries)
            query = f"SELECT * FROM ({full_query}) AS combined ORDER BY response_datetime DESC"
            
            await cursor.execute(query, tuple(query_params))
            rows = await cursor.fetchall()
            
            if not rows:
                print("No new valid detractor records found to process.")
                return
                
            print(f"Fetched {len(rows)} unanalyzed detractor records from DB.")

    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            # Batch process with a semaphore (max 10 concurrent requests) to leverage Haiku's speed
            semaphore = asyncio.Semaphore(10)

            async def bounded_generate(row, idx_num, total_num):
                async with semaphore:
                    verbatim = str(row.get('COMMENTS', ''))
                    nps_val = int(row['NPS_SCORE']) if row.get('NPS_SCORE') is not None else None
                    touchpoint_name = str(row.get('TOUCHPOINT', 'survey_dynamic_id_dmi'))
                    survey_id = str(row.get('AWBNUMBER', ''))
                    loan_app_num = row.get('loan_application_number')
                    if loan_app_num is not None and str(loan_app_num).lower() != 'nan':
                        loan_app_num = str(loan_app_num).strip()
                    else:
                        loan_app_num = None

                    if not survey_id or survey_id.lower() == 'nan':
                        survey_id = f"gen_id_{idx_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

                    print(f"[{touchpoint_name}] * Analyzing comment {idx_num}/{total_num} (ID: {survey_id})...", flush=True)
                    res = await generate_insight(verbatim, survey_id, touchpoint_name=touchpoint_name, nps_score=nps_val, loan_application_number=loan_app_num)
                    print(f"[{touchpoint_name}] - Finished comment {idx_num}/{total_num} (Priority: {res.get('priority')})!", flush=True)
                    return res, row, survey_id, touchpoint_name, verbatim, nps_val

            tasks = []
            valid_chunk = []
            
            for idx, row in enumerate(rows):
                survey_id = str(row.get('AWBNUMBER', ''))
                if not survey_id or survey_id.lower() == 'nan':
                     survey_id = f"gen_id_{idx}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                     
                tasks.append(bounded_generate(row, len(tasks) + 1, len(rows)))
                valid_chunk.append(row)

            if not tasks:
                print("No new records to process.")
                return

            print(f"Sending {len(tasks)} records to AI Pipeline...")
            results = []
            if tasks:
                print("Running first comment sequentially to build Anthropic Prompt Cache...")
                first_result = await tasks[0]
                results.append(first_result)
                
                if len(tasks) > 1:
                    print(f"Running remaining {len(tasks)-1} comments in parallel...")
                    rest_results = await asyncio.gather(*tasks[1:])
                    results.extend(rest_results)

            # Insert queries for AI_Analyzed and voc_alerts
            insert_ai_analyzed = """
                INSERT INTO AI_Analyzed 
                (survey_response_id, mobile, loan_application_number,
                 customer_verbatim, voc_translated, nps_score, priority, category, sub_category, 
                 sentiment, observations, recommendations, customer_response, confidence_score, 
                 status, is_critical, is_gibberish, is_mailed, response_date, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """

            insert_voc_alerts = """
                INSERT INTO voc_alerts
                (survey_response_id, mobile, loan_application_number,
                 customer_verbatim, voc_translated, nps_score, priority, category, sub_category, 
                 sentiment, observations, recommendations, customer_response, confidence_score, 
                 status, is_critical, is_gibberish, is_mailed, response_date, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, DATE(%s), NOW())
            """

            for result_tuple in results:
                if not result_tuple: continue
                result, row, survey_id, touchpoint_name, verbatim, nps_score = result_tuple
                
                is_critical = 1 if result.get('priority') == 'critical' else 0
                is_gibberish = result.get('is_gibberish', 0)
                cust_resp = result.get('customer_response') or ''
                
                conf_val = str(result.get('confidence_score', '85')).replace('%', '').strip()
                try:
                    conf_score = int(conf_val)
                except ValueError:
                    conf_score = 85
                
                # Status logic: Base on priority and gibberish flag
                priority_val = result.get('priority', 'low')
                if is_gibberish == 1:
                    status_val = '4'  # Auto-Closed (Gibberish)
                elif priority_val in ['critical', 'high']:
                    status_val = '1'  # Open (Agent Callback / Escalation)
                elif priority_val == 'medium' or result.get('category') == 'App Performance':
                    if result.get('category') in ["General Feedback", "General Enquiry", "Customer Support", "App Performance"]:
                        status_val = '4'  # Auto-Closed
                    else:
                        status_val = '5'  # Semi-Autoclosed
                else:
                    status_val = '4'  # Auto-Closed (Low Priority with AI response)
                
                # Get response date
                resp_date = parse_response_date(row.get('response_datetime')).split(' ')[0]

                # Extract additional fields
                def get_str_val(key):
                    val = row.get(key)
                    if val is None or str(val).lower() == 'nan' or not str(val).strip():
                        return None
                    return str(val).strip()

                mobile_val = get_str_val('COMPLAINTBY')
                loan_app_num = get_str_val('loan_application_number')

                payload = (
                    survey_id,
                    mobile_val,
                    loan_app_num,
                    verbatim,
                    result.get('voc_translated', verbatim),
                    nps_score,
                    result.get('priority'),
                    result.get('category'),
                    result.get('sub_category'),
                    result.get('sentiment'),
                    result.get('observation'),
                    result.get('recommendations'),
                    result.get('customer_response'),
                    conf_score,
                    status_val,
                    is_critical,
                    is_gibberish,
                    0, # is_mailed
                    resp_date
                )

                try:
                    await cursor.execute(insert_ai_analyzed, payload)
                except Exception as e:
                    print(f"[{touchpoint_name}] Error inserting AI_Analyzed record for ID {survey_id}: {e}")

                try:
                    await cursor.execute(insert_voc_alerts, payload)
                except Exception as e:
                    print(f"[{touchpoint_name}] Error inserting voc_alerts record for ID {survey_id}: {e}")

            print("Finished processing and inserting DB records.")

async def run_batch_pipeline(target_date=None):
    print("Starting Background Batch VOC Analyzer...")
    
    print("\n--- Step 1: Processing Database Data ---")
    pool = await aiomysql.create_pool(**DB_CONFIG, minsize=1, maxsize=5)
    try:
        await process_database_data(pool)
    except Exception as e:
        print(f"Unhandled error during processing: {e}")
    finally:
        pool.close()
        await pool.wait_closed()
            
    from dmi.services.anthropic_client import close_anthropic_client
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
