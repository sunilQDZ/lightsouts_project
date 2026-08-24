import time
import logging
from typing import Dict, List, Optional, Tuple

from dmi.services.heuristics import (
    normalize_comment, extract_keywords, detect_category_from_db_text,
    fix_category_from_db,
    should_run_two_step, fix_sentiment_priority_text, handle_positive_feedback,
    MIN_COMMENT_LENGTH, detect_gibberish, calculate_confidence_score,
    is_pure_positive
)
from dmi.core.database import load_categories_from_db
from dmi.services.anthropic_client import (
    call_anthropic_llm
)
import json
import os

logger = logging.getLogger("dmi_api")

# In-memory exact match cache to save massive LLM compute for repetitive comments
# E.g., caching "Good service", "Worst bank", "No comment"
_INFERENCE_CACHE: Dict[str, Dict] = {}
MAX_CACHE_SIZE = 5000
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dmi_inference_cache.json")

try:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            _INFERENCE_CACHE.update(json.load(f))
except Exception as e:
    logger.error(f"Failed to load cache from file: {e}")

def _save_cache():
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_INFERENCE_CACHE, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save cache to file: {e}")

async def classify_category_two_step(comment: str, categories: List[str], fallback_category: str) -> str:
    pass # Deprecated, removing references

async def generate_insight(comment: str, item_id: str, touchpoint_name: str = "", nps_score: Optional[int] = None, loan_application_number: Optional[str] = None) -> Dict:
    raw_comment = str(comment).strip() if comment else ""
    
    result = {
        "id": item_id,
        "comments": raw_comment,
        "category": "Generic",
        "sub_category": "Generic",
        "sentiment": "Neutral",
        "priority": "low",
        "is_gibberish": 0,
        "observation": "Review required.",
        "recommendations": "Provide an update to the customer.",
        "customer_response": "",
        "confidence_score": "85%",
        "voc_translated": raw_comment,
        "status": "auto closed",
        "loan_application_number": loan_application_number
    }

    norm_comment = normalize_comment(comment)
    if not norm_comment:
        if raw_comment:
            result["is_gibberish"] = detect_gibberish(raw_comment)
            if result["is_gibberish"] == 1:
                result["observation"] = "The comment does not contain meaningful feedback."
                result["status"] = "auto closed"
            elif len(raw_comment) < MIN_COMMENT_LENGTH:
                result["observation"] = "Comment is too short for meaningful analysis."
                result["is_gibberish"] = 1
                result["status"] = "auto closed"
        else:
            result["observation"] = "No valid comment provided."
            result["is_gibberish"] = 1
            result["status"] = "auto closed"
        return result

    result["comments"] = norm_comment
    local_is_gibberish = detect_gibberish(norm_comment)
    
    if local_is_gibberish == 1:
        logger.info(f"Python heuristic detected gibberish. Skipping LLM call for ID: {item_id}")
        result["is_gibberish"] = 1
        result["category"] = "Generic"
        result["sub_category"] = "Generic"
        result["sentiment"] = "Neutral"
        result["priority"] = "low"
        result["observation"] = "The comment does not contain meaningful feedback."
        result["recommendations"] = "No action required."
        result["customer_response"] = "Thank you for your valuable feedback."
        result["confidence_score"] = "95%"
        result["status"] = "auto closed"
        return result

    result["is_gibberish"] = local_is_gibberish

    if is_pure_positive(norm_comment, nps_score):
        logger.info(f"Python heuristic detected purely positive feedback. Skipping LLM call for ID: {item_id}")
        result["category"] = "Generic"
        result["sub_category"] = "Generic"
        result["sentiment"] = "Positive"
        result["priority"] = "low"
        result["observation"] = "The customer shared positive feedback about the service."
        result["recommendations"] = "Continue maintaining good service quality."
        result["customer_response"] = "Thank you for your valuable feedback! We are glad you had a positive experience."
        result["confidence_score"] = "95%"
        result["status"] = "auto closed"
        return result

    categories = await load_categories_from_db()
    fast_category = detect_category_from_db_text(norm_comment, categories)
    
    # ------------------- SEMANTIC LRU CACHE -------------------
    cache_key = f"{touchpoint_name}:{norm_comment.lower().strip()}"
    llm_result = None
    if cache_key in _INFERENCE_CACHE:
        llm_result = _INFERENCE_CACHE[cache_key]
        logger.info("Cache hit for inference!")
    else:
        llm_result = await call_anthropic_llm(norm_comment)
        if llm_result:
            cat = str(llm_result.get("category", "")).strip()
            sub_cat = str(llm_result.get("sub_category", ""))
            prio = str(llm_result.get("priority", "low"))
            sent = str(llm_result.get("sentiment", "Neutral"))
            is_gib = int(llm_result.get("is_gibberish", 0))
            
            if prio in ["critical", "high"]:
                llm_result["customer_response"] = ""
            else:
                haiku_resp = str(llm_result.get("customer_response", "")).strip()
                if haiku_resp:
                    llm_result["customer_response"] = haiku_resp
                elif sent == "Positive":
                    llm_result["customer_response"] = "Thank you for your valuable feedback! We are glad you had a positive experience."
                else:
                    llm_result["customer_response"] = "We apologize for the bad experience. We have forwarded your concern to our concerned team."

            if len(_INFERENCE_CACHE) >= MAX_CACHE_SIZE:
                _INFERENCE_CACHE.clear()
            _INFERENCE_CACHE[cache_key] = llm_result
            _save_cache()
    # ----------------------------------------------------------

    if llm_result:
        category = str(llm_result.get("category", "")).strip()
        category = fix_category_from_db(category, categories)

        result["category"] = category
        result["sub_category"] = str(llm_result.get("sub_category", ""))
        
        # --- POST-PROCESSING LLM FIX FOR GENERIC MISMATCHES ---
        if result["category"] == "Generic" and result["sub_category"] != "Generic":
            if result["sub_category"] in ["Not Satisfied with Service", "Good Service Quality", "Poor Branch Service"]:
                result["category"] = "Service Related"
            else:
                result["sub_category"] = "Generic"
        elif result["category"] == "Service Related" and result["sub_category"] == "Generic":
            result["sub_category"] = "Not Satisfied with Service"
        # ------------------------------------------------------
        result["sentiment"] = str(llm_result.get("sentiment", "Neutral"))
        result["priority"] = str(llm_result.get("priority", "low"))
        result["observation"] = str(llm_result.get("observation", ""))
        result["recommendations"] = str(llm_result.get("recommendations", ""))
        result["customer_response"] = str(llm_result.get("customer_response", ""))
        result["confidence_score"] = str(llm_result.get("confidence_score", "85%"))
        
        vt = str(llm_result.get("voc_translated", "")).strip()
        if vt and vt.lower() != norm_comment.strip().lower():
            result["voc_translated"] = vt
        else:
            result["voc_translated"] = raw_comment
            
        if "is_gibberish" in llm_result:
            try:
                llm_gibberish = int(llm_result.get("is_gibberish"))
                result["is_gibberish"] = max(local_is_gibberish, llm_gibberish)
            except (ValueError, TypeError):
                pass
                
        if result.get("is_gibberish") == 1:
            result["category"] = "Generic"
            result["sub_category"] = "Generic"
            result["sentiment"] = "Neutral"
            result["priority"] = "low"
            result["observation"] = "The comment does not contain meaningful feedback."
            result["recommendations"] = "No action required."
            if not result.get("customer_response"):
                result["customer_response"] = "Thank you for your valuable feedback."
            result["confidence_score"] = "95%"
        if result.get("is_gibberish") != 1:
            fixed_sentiment, fixed_priority, fixed_obs, fixed_rec, fixed_resp, fixed_conf = fix_sentiment_priority_text(
                norm_comment, result["sentiment"], result["priority"], result["observation"], 
                result["recommendations"], result["customer_response"], result["confidence_score"],
                result["category"], result["sub_category"]
            )
            result["sentiment"] = fixed_sentiment
            result["priority"] = fixed_priority
            result["observation"] = fixed_obs
            result["recommendations"] = fixed_rec
            result["customer_response"] = fixed_resp
            result["confidence_score"] = fixed_conf
    else:
        if fast_category:
            result["category"] = fast_category
        else:
            result["category"] = "Generic"

    priority_val = result.get("priority", "low")
    category_val = result.get("category", "")
    
    if result.get("is_gibberish") == 1:
        result["status"] = "auto closed"
    elif priority_val in ["critical", "high"]:
        result["status"] = "open"
    elif priority_val == "medium" or category_val == "App Performance":
        if category_val in ["General Feedback", "General Enquiry", "Customer Support", "App Performance"]:
            result["status"] = "auto closed"
        else:
            result["status"] = "semi_autoclosed"
    else:
        result["status"] = "auto closed"

    return result

