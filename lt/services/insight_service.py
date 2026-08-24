import time
import logging
from typing import Dict, List, Optional, Tuple

from lt.services.heuristics import (
    normalize_comment, extract_keywords, detect_category_from_db_text,
    fix_category_from_db,
    should_run_two_step, fix_sentiment_priority_text, handle_positive_feedback,
    MIN_COMMENT_LENGTH, detect_gibberish, calculate_confidence_score,
    is_pure_positive
)
from lt.services.anthropic_client import (
    call_anthropic_llm, MASTER_CATEGORIES
)

logger = logging.getLogger("lt_api")

import os
import json

CACHE_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lt_inference_cache.json")

def load_cache() -> Dict[str, Dict]:
    if os.path.exists(CACHE_FILE_PATH):
        try:
            with open(CACHE_FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
    return {}

def save_cache(cache: Dict[str, Dict]):
    try:
        with open(CACHE_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving cache: {e}")

_INFERENCE_CACHE: Dict[str, Dict] = load_cache()
MAX_CACHE_SIZE = 5000

async def classify_category_two_step(comment: str, categories: List[str], fallback_category: str) -> str:
    pass # Deprecated, removing references

async def generate_insight(comment: str, item_id: str, touchpoint_name: str = "", nps_score: Optional[int] = None) -> Dict:
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
        "status": "auto closed"
    }

    norm_comment = normalize_comment(comment)
    if not norm_comment:
        if raw_comment:
            result["is_gibberish"] = detect_gibberish(raw_comment)
            if result["is_gibberish"] == 1:
                result["observation"] = "The comment does not contain meaningful feedback."
                result["status"] = "open"
            elif len(raw_comment) < MIN_COMMENT_LENGTH:
                result["observation"] = "Comment is too short for meaningful analysis."
                result["is_gibberish"] = 1
                result["status"] = "open"
        else:
            result["observation"] = "No valid comment provided."
            result["is_gibberish"] = 1
            result["status"] = "open"
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
        result["observation"] = "The comment is not related to finance or does not contain meaningful feedback."
        result["recommendations"] = "No action required."
        result["customer_response"] = ""
        result["confidence_score"] = "95%"
        result["status"] = "open"
        return result

    result["is_gibberish"] = local_is_gibberish

    fast_category = detect_category_from_db_text(norm_comment, MASTER_CATEGORIES)
    
    # ------------------- PURE PRAISE BYPASS -------------------
    if is_pure_positive(norm_comment, nps_score):
        logger.info(f"Pure praise detected. Skipping LLM call for ID: {item_id}")
        result["category"] = "Generic"
        result["sub_category"] = "Generic"
        result["sentiment"] = "Positive"
        result["priority"] = "low"
        result["observation"] = "The customer provided positive feedback with no actionable complaints."
        result["recommendations"] = "No action required."
        result["customer_response"] = "Thank you for your valuable feedback! We are glad you had a positive experience."
        result["confidence_score"] = "99%"
        result["status"] = "auto closed"
        return result
    # ----------------------------------------------------------
    
    # ------------------- SEMANTIC LRU CACHE -------------------
    cache_key = f"{touchpoint_name}:{norm_comment.lower().strip()}"
    if cache_key in _INFERENCE_CACHE:
        llm_result = _INFERENCE_CACHE[cache_key]
        logger.info("Cache hit for inference!")
    else:
        llm_result = await call_anthropic_llm(norm_comment)
        if llm_result:
            cat = str(llm_result.get("category", ""))
            sub_cat = str(llm_result.get("sub_category", ""))
            prio = str(llm_result.get("priority", "low"))
            sent = str(llm_result.get("sentiment", "Neutral"))
            is_gib = int(llm_result.get("is_gibberish", 0))
            
            if prio in ["critical", "high"]:
                llm_result["customer_response"] = ""
            elif is_gib == 1:
                llm_result["customer_response"] = "Thank you for your valuable feedback."
            else:
                haiku_resp = str(llm_result.get("customer_response", "")).strip()
                if haiku_resp:
                    llm_result["customer_response"] = haiku_resp
                elif sent == "Positive":
                    llm_result["customer_response"] = "Thank you for your valuable feedback! We are glad you had a positive experience."
                else:
                    llm_result["customer_response"] = "We apologize for the bad experience. We have forwarded your concern to our concerned team."

            if len(_INFERENCE_CACHE) >= MAX_CACHE_SIZE:
                # Naive LRU flush if we exceed memory limits
                _INFERENCE_CACHE.clear()
            _INFERENCE_CACHE[cache_key] = llm_result
            save_cache(_INFERENCE_CACHE)
    # ----------------------------------------------------------

    if llm_result:
        category = str(llm_result.get("category", "")).strip()
        category = fix_category_from_db(category, MASTER_CATEGORIES)

        result["category"] = category
        result["sub_category"] = str(llm_result.get("sub_category", ""))
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
                # If either local logic or LLM says it's gibberish, treat it as gibberish.
                result["is_gibberish"] = max(local_is_gibberish, llm_gibberish)
            except (ValueError, TypeError):
                pass
                
        if result.get("is_gibberish") == 1:
            result["category"] = "Generic"
            result["sub_category"] = "Generic"
            result["sentiment"] = "Neutral"
            result["priority"] = "low"
            result["observation"] = "The comment is not related to finance or does not contain meaningful feedback."
            result["recommendations"] = "No action required."
            result["customer_response"] = ""
            result["confidence_score"] = "95%"
        if result.get("is_gibberish") != 1:
            fixed_sentiment, fixed_priority, fixed_obs, fixed_rec, fixed_resp, fixed_conf = fix_sentiment_priority_text(
                norm_comment, result["sentiment"], result["priority"], result["observation"], 
                result["recommendations"], result["customer_response"], result["confidence_score"],
                result["category"]
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

    # Calculate human-readable status for API response
    priority_val = result.get("priority", "low")
    category_val = result.get("category", "")
    
    if priority_val in ["critical", "high"] or result.get("is_gibberish") == 1:
        result["status"] = "open"
    elif priority_val == "medium" or category_val == "Information Request":
        if category_val in ["Pricing & Charges", "Unwanted Communications"]:
            result["status"] = "auto closed"
        else:
            result["status"] = "semi_autoclosed"
    else:
        result["status"] = "auto closed"

    # The Python heuristic Safety Net validates and forces priority/sentiment overrides if necessary.

    return result

