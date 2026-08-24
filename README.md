# Centralized Lightsouts API - Complete Architecture & Logic Guide

The **Centralized Lightsouts API** is an automated Voice of Customer (VOC) analysis and ticketing engine. It aggregates feedback from different business domains (Blue Dart, L&T, NPCI, and DMI), analyzes it using AI (Anthropic Claude), and automatically assigns priority, categories, and routing statuses based on predefined business heuristics.

---

## 📂 1. Project Structure & Modules

The repository is divided into self-contained modules to keep the logic for different departments/clients isolated, yet run them under a single unified FastAPI application.

*   `main.py`: The central FastAPI entry point. It registers routers for all modules (`/bluedart`, `/lt`, `/npci`) and runs the `uvicorn` server.
*   `/bluedart/` - Logic specific to Blue Dart (Logistics / Delivery feedback).
*   `/lt/` - Logic specific to L&T (Larsen & Toubro).
*   `/npci/` - Logic specific to NPCI (National Payments Corporation of India).
*   `/dmi/` - Logic specific to DMI Finance.

**Inside each module:**
*   `api/routes.py`: Defines the FastAPI endpoints for that specific domain.
*   `core/database.py`: Asynchronous database connection pooling (using `aiomysql`) and DB queries.
*   `services/batch_processor.py`: The ETL background script that pulls unanalyzed data, runs it through the AI, and pushes it back.
*   `services/insight_service.py`: The core AI inference pipeline (combines Python heuristics + Anthropic API).
*   `export_today.py` (or `export_today_results.py`): Standalone scripts to export the day's processed AI data into Excel or CSV format for reporting.

---

## 🧠 2. The Core Logic: AI Inference Pipeline

The most critical part of this system is how it processes customer feedback (verbatims) efficiently without overspending on LLM API tokens. This happens inside `insight_service.py` via the `generate_insight()` function.

### Step 2.1: Pre-Processing & Heuristics (Python)
Before a comment is sent to the AI, it passes through fast Python-based heuristics:
1.  **Length & Validity Check**: If the comment is empty or less than a minimum length (`MIN_COMMENT_LENGTH`), it is immediately flagged as **Gibberish**.
2.  **Gibberish Detection**: Uses regex and character analysis to detect spam or keyboard-mashing (e.g., "asdfghj").
3.  **Pure Positive Filter**: If the NPS score is high and the text matches known positive keywords (e.g., "Good service", "Excellent"), it bypasses the LLM completely, sets sentiment to "Positive", and generates a predefined thank-you response.

### Step 2.2: Semantic LRU Cache
If the comment requires AI analysis, the system first checks a **local JSON cache** (e.g., `bluedart_inference_cache.json`).
*   **Why?** Customers often leave identical feedback like "Delivery delayed" or "Bad behavior".
*   If an exact match is found in the cache, the system reuses the previous AI analysis, saving time and money.
*   The cache holds up to `5,000` entries (managed dynamically).

### Step 2.3: Anthropic Claude LLM
If no cache hit occurs, the comment is sent to **Anthropic Claude**. The LLM is instructed to extract:
*   **Priority:** Critical, High, Medium, Low.
*   **Category & Sub-Category:** E.g., "Shipment Tracking", "Pricing & Charges".
*   **Sentiment:** Positive, Negative, Neutral.
*   **Observations & Recommendations:** Internal notes for the agent.
*   **Customer Response:** A drafted reply to the customer (only generated for non-critical/high issues, as critical issues require human-drafted replies).

### Step 2.4: Post-Processing & Normalization
Once the LLM returns data, the system applies fallback corrections:
*   **Category Fixing:** Validates the AI's category against the actual categories in the MySQL database.
*   **Mismatch Correction:** If the AI outputs Category="Generic" but Sub-Category="Poor Branch Service", the Python logic overrides the Category to "Service Related".

---

## 🚦 3. Ticket Status Mapping & Auto-Resolution

After the insight is generated, the system maps the result to a **Status Code** so the frontend CRM or ticketing system knows how to handle it.

| Priority / Condition | Status Value | Meaning |
| :--- | :---: | :--- |
| **Gibberish** (Flags=1) | `4` / `auto closed` | Immediately closed. No action needed. |
| **Purely Positive** | `4` / `auto closed` | Closed automatically with a Thank You note. |
| **Low Priority** | `4` / `auto closed` | Closed automatically with an AI-generated response. |
| **Specific Categories** | `4` / `auto closed` | Specific issues like "Pricing & Charges" or "Documentation" are auto-closed based on business rules. |
| **Medium Priority** | `5` / `semi_autoclosed`| Requires slight oversight but is mostly resolved. |
| **Critical / High Priority** | `1` / `open` | Requires an immediate **Agent Callback** or escalation. No auto-response is sent. |

---

## 🗄️ 4. Database Flow (ETL)

The daily background script (`run_batch_pipeline` in `batch_processor.py`) performs the following Database operations:

1.  **Extract:** Queries the raw response table (e.g., `tp10_response_part`) for records from the previous day (`CURDATE() - INTERVAL 1 DAY`) where `NPS_SCORE <= 6` (Detractors). It explicitly filters out IDs that are already present in the `AI_Analyzed` table.
2.  **Transform:** Uses `asyncio.Semaphore(10)` to process up to 10 comments concurrently through the `insight_service` pipeline described above.
3.  **Load:** Inserts the final insights into two tables:
    *   `AI_Analyzed`: The master table containing all historical AI feedback analysis.
    *   `voc_alerts`: A mirrored table used to trigger immediate alerts/notifications in the CRM dashboard.

---

## 🌐 5. API Endpoints

The API is accessible via `http://127.0.0.1:8000`. The Swagger UI is at `/docs`.

*   `GET /` - Root health check. Confirms the centralized API is online.
*   `GET /{module}/health` - Checks the specific module's configuration (e.g., Anthropic model version).
*   `POST /{module}/start-daily-analysis` - Triggers the `run_batch_pipeline` for that module in a FastApi `BackgroundTask`. (Requires API Key).
*   `POST /{module}/clear-cache` - Deletes the module's `inference_cache.json` and purges Python `__pycache__`. Use this to force the AI to re-evaluate common comments after you update the prompt or business rules.
*   `GET /{module}/logs` - Returns the last 1000 lines of the respective module's log file (e.g., `bluedart_app.log`).

---

## 📊 6. Daily Data Export

Each module contains an `export_today.py` (or similar) script.
*   **Purpose:** Queries the `AI_Analyzed` table for all records processed **today** (`DATE(created_at) = CURDATE()`).
*   **Output:** Generates a timestamped `.xlsx` (Excel) or `.csv` file in the module directory (e.g., `npci_processed_data_YYYYMMDD_HHMMSS.xlsx`).
*   **Usage:** Run these scripts manually via `python npci/export_today.py` to generate ad-hoc reports for stakeholders.
