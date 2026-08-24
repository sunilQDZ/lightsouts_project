# Deployment Guide

Simple and quick steps to deploy and run the Centralized Lightsouts API.

---

## 1. Setup Environment
Create virtual environment and install required packages:

```bash
# Create and activate virtual environment
python -m venv venv

# On Windows:
venv\Scripts\activate

# On Linux/macOS:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

---

## 2. Configure Environment (`.env`)
Create a `.env` file in the root directory with your DB credentials and API keys:

```env
API_TOKEN=your_secret_api_token_here
DMI_API_TOKEN=your_secret_api_token_here
BLUEDART_API_TOKEN=your_secret_api_token_here
LT_API_TOKEN=your_secret_api_token_here
NPCI_API_TOKEN=your_secret_api_token_here
```

---

## 3. Run the Application

Start the API server:
```bash
python main.py
```
*Or using uvicorn:*
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 4. Accessing the API & Documentation

- **Base URL**: `http://localhost:8000`
- **Swagger Documentation**: `http://localhost:8000/docs?api_key=<YOUR_API_TOKEN>`
- **API Key Header for Requests**: `X-API-Key: <YOUR_API_TOKEN>`

---

## 5. Triggering Daily Batch Analysis

Run batch analysis via API or direct script:

```bash
# Example API Call
curl -X POST "http://localhost:8000/dmi/start-daily-analysis" -H "X-API-Key: <YOUR_API_TOKEN>"

# Or run module scripts directly
python dmi/run_daily_batch.py
python bluedart/run_daily_batch.py
python lt/run_daily_batch.py
python npci/run_daily_batch.py
```
