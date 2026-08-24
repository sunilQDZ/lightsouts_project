import asyncio
import sys
import os
import io

# Add the parent directory to sys.path so we can import the 'lt' package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from lt.services.batch_processor import run_batch_pipeline

if __name__ == "__main__":
    # Ensure stdout handles UTF-8 correctly
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        print("Initializing Daily Batch Process...")
        loop.run_until_complete(run_batch_pipeline())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
