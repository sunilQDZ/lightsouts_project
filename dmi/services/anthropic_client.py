import json
import os
import re
import logging
from typing import Dict, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dmi.services.heuristics import similarity_score, clean_for_match, ensure_string

from dmi.core.config import settings
from dmi.services.heuristics import SENTIMENTS, PRIORITIES

import anthropic

logger = logging.getLogger("dmi_api")

_anthropic_client: Optional[anthropic.AsyncAnthropic] = None

def get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    api_key = settings.ANTHROPIC_API_KEY
    if _anthropic_client is None or getattr(_anthropic_client, "api_key", "") != api_key:
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=api_key if api_key else "placeholder"
        )
    return _anthropic_client

async def close_anthropic_client():
    global _anthropic_client
    if _anthropic_client is not None:
        await _anthropic_client.close()
        _anthropic_client = None

CATEGORY_HIERARCHY = {
    "Transaction Failure": [
        "UPI PIN Incorrect", "Bank Server Down", "Limit Exceeded", 
        "VPA Invalid", "Network Timeout", "Bank Offline"
    ],
    "Money Not Credited": [
        "Amount Debited", "Double Deduction", "Refund Delayed", 
        "Stuck Transaction"
    ],
    "Offers & Cashback": [
        "Cashback Not Received", "Cashback Too Low", "Referral Bonus Missing"
    ],
    "Fraud": [
        "Phishing Link", "Unauthorized Transaction", "Fake Customer Care", 
        "Fraudulent Request", "Account Hacked"
    ],
    "Account Blocked": [
        "Account Frozen", "App Locked"
    ],
    "Login Issues": [
        "Verification Failed", "PIN Reset Failed", "Biometric Error"
    ],
    "App Performance": [
        "App Crashing", "Slow Loading", "Scanner Error", 
        "Update Issue", "Blank Screen"
    ],
    "Customer Support": [
        "No Response", "Unhelpful Agent", "Ticket Not Resolved", "Hard To Reach"
    ],
    "General Enquiry": [
        "General Enquiry"
    ],
    "Profile Issue": [
        "Update Failed", "Details Incorrect"
    ],
    "Account Linking": [
        "Linking Failed", "Bank Unlinked"
    ],
    "App Experience": [
        "Language Issue", "Transaction History Issue", "Feature Broken", "Feature Absent", "Confusing UI"
    ],
    "General Feedback": [
        "Positive Feedback", "Vague Complaint"
    ],
    "Generic": [
        "Generic", "Needs Review"
    ]
}

MASTER_CATEGORIES = list(CATEGORY_HIERARCHY.keys())

def build_system_prompt() -> str:
    categories_json = json.dumps(MASTER_CATEGORIES, indent=2, ensure_ascii=False)
    prompt_text = f"""
You are an expert VOC (Voice of Customer) analyst for DMI Housing Finance.

Analyze the customer comment and return ONLY valid JSON.

ALLOWED CATEGORIES:
{categories_json}

TRANSLATION REQUIREMENT (CRITICAL):
If the CUSTOMER COMMENT is in ANY regional Indian language (Hindi, Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada, Malayalam, Punjabi, Odia, Urdu, etc. - in either native script or English transliteration), you MUST translate it to pure English and put the English text in the `voc_translated` field.
Example: If comment is "mera paisa kat gaya", `voc_translated` MUST be "my money got deducted".
If the comment is already English, copy it exactly as is. NEVER output Hindi or regional text in the JSON fields.

VERY IMPORTANT:
First, try to map the customer comment to one of the ALLOWED CATEGORIES above.

Rules:
1. The comment may be in ANY Indian language or Hinglish/Tanglish. First, internally translate the comment to English to understand its exact business context, then match it.
2. If the comment matches an allowed category, use it.
3. If the comment describes a valid digital payment issue but DOES NOT fit any allowed category, you MAY CREATE AND ASSIGN a concise, new category name (MAXIMUM 3 WORDS).
4. If the comment is NOT related to loans/housing finance (e.g., complaining about a completely unrelated delivery issue), or is purely gibberish (e.g., "hjksdf"), you MUST assign the category "Generic".
5. Positive praise with no specific actionable issue (e.g., "good app", "fast payment") MUST be assigned to Category: "General Feedback" and Sub-Category: "Positive Feedback".
6. Vague negative dissatisfaction regarding the app/service with NO specific actionable issue named (e.g., "worst app", "very bad experience") MUST be assigned to Category: "General Feedback" and Sub-Category: "Vague Complaint". However, if the negative comment is completely unrelated to payments, it should remain "Generic".
7. CRITICAL: Any complaints about missing "Referral" money, "Referral" bonuses, or Cashback MUST be assigned to Category: "Offers & Cashback" and Sub-Category: "Referral Bonus Missing" or "Cashback Missing". Do not map them to "Amount Debited" or "Money Not Credited".

FIELD RULES:
voc_translated:
- If the CUSTOMER COMMENT is in English, YOU MUST COPY IT EXACTLY, character for character, including any spelling or grammar mistakes, extra spaces, or missing punctuation. NEVER "correct" or reword it, even if the fix seems obvious or minor.
- NEVER LEAVE THIS BLANK.
- If the CUSTOMER COMMENT is in any regional Indian language, provide a literal, word-for-word English translation. Do NOT add "Customer says...".

category:
- Based on the rules above.

sub_category:
- You MUST ALWAYS pick a sub-category directly related to your chosen category from the mapping below. Every sub-category you output MUST be copied EXACTLY (spelling, spacing, punctuation) from this list — never invent a variant spelling.
- STRICT CATEGORY TO SUB-CATEGORY MAPPING:
{json.dumps(CATEGORY_HIERARCHY, indent=2, ensure_ascii=False)}
  - CRITICAL RULE: If the category assigned is "Generic" and the comment is neutral/vague, sub_category MUST be "Generic". If the category is "Generic" but the comment is clearly NEGATIVE (a complaint you can't classify), sub_category MUST be "Needs Review" and sentiment MUST be "Negative". NEVER default an unclassifiable negative complaint to Positive.
- If a category is not listed, generate a highly specific category name (MAXIMUM 3 WORDS).

sentiment must be exactly one of:
{SENTIMENTS}

priority must be:
Priority guidance (OPEN vs AUTOCLOSED):
CRITICAL RULE: GATEKEEPER CHECK. You must determine if this is a TRULY CRITICAL ESCALATION to set priority to "critical".
A complaint is considered a "critical" priority ONLY if it involves ANY of the following:
1. Legal/Regulatory Threats: Explicitly threatening legal action, police, or RBI ombudsman.
2. Severe Fraud/Theft: Customer explicitly uses fraud-accusation language ("cheating", "fraud", "scam", "hacked", "unauthorized transaction").
3. Public Brand Damage: Threatening to post on Twitter/Social media.
4. Severe CX Impacting / Churn Intent: User explicitly states they will stop using the app, uninstall, or close their account.
5. Revenue Impacting / High Value: Mentioning a large amount of money stuck or double deduction for a high-value transaction.

For all other issues, strictly classify them based on ACTIONABILITY:

- critical: ONLY if it passes the strict Gatekeeper Check above. (System will keep OPEN)
- high: Issues requiring DIRECT AGENT INTERVENTION beyond a routine operational fix. Examples: persistent money deduction issues, account frozen without reason, an explicit request to be called back now. (System will keep OPEN)
- medium: A concrete, specific operational issue was described that does not require urgent escalation — app crashes, slow loading, PIN Reset Failed, support quality complaint. (System will SEMI-AUTOCLOSE or AUTO-CLOSE)
- low: Positive feedback, "NA", "Nothing", "No", generic praise, gibberish. (SYSTEM CAN CLOSE)

STRICT PRIORITY CONSISTENCY TABLE (NOTE: The Gatekeeper Check above for critical/high ALWAYS overrides this table. For all other cases, apply this exactly, every single time. Every sub-category from the mapping above appears exactly once below.):

TRANSACTION FAILURE
- "UPI PIN Incorrect" -> medium
- "Bank Server Down" -> high
- "Limit Exceeded" -> medium
- "VPA Invalid" -> medium
- "Network Timeout" -> medium
- "Bank Offline" -> high

MONEY NOT CREDITED
- "Amount Debited" -> high
- "Double Deduction" -> high
- "Refund Delayed" -> medium
- "Stuck Transaction" -> high

OFFERS & CASHBACK
- "Cashback Not Received" -> high
- "Cashback Too Low" -> low
- "Referral Bonus Missing" -> low

FRAUD
- "Phishing Link" -> critical
- "Unauthorized Transaction" -> critical
- "Fake Customer Care" -> critical
- "Fraudulent Request" -> critical
- "Account Hacked" -> critical

ACCOUNT BLOCKED
- "Account Frozen" -> high
- "App Locked" -> high

LOGIN ISSUES
- "Verification Failed" -> medium
- "PIN Reset Failed" -> medium
- "Biometric Error" -> medium

APP PERFORMANCE
- "App Crashing" -> medium
- "Slow Loading" -> low
- "Scanner Error" -> medium
- "Update Issue" -> medium
- "Blank Screen" -> medium

CUSTOMER SUPPORT
- "No Response" -> high
- "Unhelpful Agent" -> medium
- "Ticket Not Resolved" -> high
- "Hard To Reach" -> medium

GENERAL ENQUIRY
- "General Enquiry" -> low

PROFILE ISSUE
- "Update Failed" -> medium
- "Details Incorrect" -> medium

ACCOUNT LINKING
- "Linking Failed" -> medium
- "Bank Unlinked" -> high

APP EXPERIENCE
- "Language Issue" -> medium
- "Transaction History Issue" -> medium
- "Feature Broken" -> medium
- "Feature Absent" -> low
- "Confusing UI" -> medium

GENERAL FEEDBACK
- "Positive Feedback" -> low
- "Vague Complaint" -> medium

GENERIC
- "Generic" -> low
- "Needs Review" -> medium

If you generate a NEW sub-category not in this table, assign priority using the general ACTIONABILITY guidance above, applying the Gatekeeper Check first.

Observation:
Write exactly one precise sentence in ENGLISH ONLY describing the core issue. Do not assume facts. If the comment is literally just 1-2 words (e.g., "poor", "bad"), you may state that "The customer expressed dissatisfaction but did not provide specific details."

Recommendations:
Write exactly one concrete, actionable business step in ENGLISH ONLY that directly addresses the specific issue.

customer_response:
Generate a short, simple, professional customer response. STRICT RULE: exactly ONE sentence, MAXIMUM 15-25 words. Never write two sentences even if the second sentence seems helpful.

STEP 0 — CHECK FOR OVERRIDE SIGNATURES FIRST (before picking a bucket):
- Any comment resolving to "high" or "critical" priority per the table above -> output "" regardless of which bucket it might otherwise resemble. This is checked FIRST, before Steps 1-2 below are even relevant.

STEP 1 — DECIDE THE TONE BUCKET (for non-high/critical priority):
BUCKET A: Operational Failures. Apologize briefly, name issue. NO promised follow-up action. Pattern: "We apologize for [specific issue]."
BUCKET B: Rate Opinion. No apology, no validation. Pattern: "Thank you for your feedback regarding our rates."
BUCKET C: Neutral Acknowledgment. Informational or requests. Pattern: "Thank you for your request - we've noted your preference."
BUCKET D: Generic Praise/Vague: "Thank you for your feedback!"
BUCKET E: High/Critical priority -> output "" (empty string).

STEP 2 — HARD RULES FOR CUSTOMER RESPONSE:
1. MAX 15-25 WORDS. Exactly ONE sentence.
2. NO promises ("will call you", "forwarded to team", "process a refund"). Acknowledge only.
3. NEVER use the word "ensure" or validate a negative claim.
4. NO contact info or asking for details.
5. NEVER mention arranging a refund or reversal.
6. If `is_gibberish` is 1: output EXACTLY "Thank you for your valuable feedback." (never leave blank).
7. Separately, if priority is "critical" or "high" (and is_gibberish is 0): output "" (empty string).

Confidence Score: Estimate classification confidence (e.g., "95%").

Is Gibberish / Non-Logistics:
- 1 if comment is nonsensical or unrelated to payments.
- 0 for meaningful complaints/questions, even if poorly spelled, very short ("worst service").
- If `is_gibberish` is 1, output priority as "low", category/sub_category as "Generic".

Return ONLY valid JSON in this exact format:
{{
  "voc_translated": "",
  "is_gibberish": 0,
  "category": "",
  "sub_category": "",
  "sentiment": "",
  "priority": "",
  "observation": "",
  "recommendations": "",
  "customer_response": "",
  "confidence_score": ""
}}

EXAMPLES:
Input: "Money deducted from bank but merchant did not receive."
Output:
{{
  "voc_translated": "Money deducted from bank but merchant did not receive.",
  "is_gibberish": 0,
  "category": "Money Not Credited",
  "sub_category": "Amount Debited",
  "sentiment": "Negative",
  "priority": "high",
  "observation": "The customer's bank account was debited but the merchant did not receive the funds.",
  "recommendations": "Verify the transaction status with the acquiring bank and initiate a reconciliation process.",
  "customer_response": "",
  "confidence_score": "98%"
}}

Input: "Fraud link was clicked and money stolen I will go to police."
Output:
{{
  "voc_translated": "Fraud link was clicked and money stolen I will go to police.",
  "is_gibberish": 0,
  "category": "Fraud",
  "sub_category": "Phishing Link",
  "sentiment": "Negative",
  "priority": "critical",
  "observation": "The customer lost money due to a phishing link and is threatening police action.",
  "recommendations": "Immediately freeze the account and escalate to the fraud investigations team.",
  "customer_response": "",
  "confidence_score": "99%"
}}

Input: "Dear Customer Support"
Output:
{{
  "voc_translated": "Dear Customer Support",
  "is_gibberish": 1,
  "category": "Generic",
  "sub_category": "Generic",
  "sentiment": "Neutral",
  "priority": "low",
  "observation": "The comment is an incomplete greeting with no actual complaint or feedback content.",
  "recommendations": "No action required.",
  "customer_response": "Thank you for your valuable feedback.",
  "confidence_score": "25%"
}}

Input: "My account is frozen without any prior intimation."
Output:
{{
  "voc_translated": "My account is frozen without any prior intimation.",
  "is_gibberish": 0,
  "category": "Account Blocked",
  "sub_category": "Account Frozen",
  "sentiment": "Negative",
  "priority": "high",
  "observation": "The customer's account has been frozen without prior notification.",
  "recommendations": "Investigate the reason for the account freeze and contact the customer to resolve.",
  "customer_response": "",
  "confidence_score": "95%"
}}

Input: "App is crashing constantly when trying to scan."
Output:
{{
  "voc_translated": "App is crashing constantly when trying to scan.",
  "is_gibberish": 0,
  "category": "App Performance",
  "sub_category": "App Crashing",
  "sentiment": "Negative",
  "priority": "medium",
  "observation": "The customer reports the app crashes consistently during scanning.",
  "recommendations": "Log a technical ticket to investigate scanner-related app crashes in the latest build.",
  "customer_response": "We apologize for the app crashing issue.",
  "confidence_score": "94%"
}}

Input: "Very fast payment!"
Output:
{{
  "voc_translated": "Very fast payment!",
  "is_gibberish": 0,
  "category": "General Feedback",
  "sub_category": "Positive Feedback",
  "sentiment": "Positive",
  "priority": "low",
  "observation": "The customer shared positive feedback about the speed of payments.",
  "recommendations": "No action required; log as positive feedback.",
  "customer_response": "Thank you for your kind feedback!",
  "confidence_score": "96%"
}}

NO EXTRA TEXT.
"""
    # PAD PROMPT to ensure we cross the 4096-token threshold for Prompt Caching 
    # Claude Haiku 4.5 requires > 4096 tokens to activate cache.
    # Current organic length is ~3900 tokens. Adding 300 single-tokens ('a ') to safely push past 4100 tokens.
    padding_block = "<padding>\n" + ("a " * 300) + "\n</padding>"
    return prompt_text + "\n" + padding_block

def build_user_prompt(comment: str) -> str:
    return f"""
CUSTOMER COMMENT:
"{comment}"
"""

def parse_llm_json(raw_text: str) -> Optional[Dict]:
    if not raw_text or not isinstance(raw_text, str):
        return None

    raw_text = raw_text.strip()
    raw_text = re.sub(r"```(?:json)?\s*|\s*```", "", raw_text)

    try:
        result = json.loads(raw_text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1

    if start != -1 and end > start:
        try:
            result = json.loads(raw_text[start:end])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    return None

def _estimate_max_tokens(comment: str) -> int:
    comment_tokens = max(len(comment) // 4, 0)
    return min(max(400, comment_tokens * 2 + 300), 2000)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=1, max=10),
    retry=retry_if_exception_type((anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError)),
    reraise=True
)
async def call_anthropic_llm(comment: str, prompt_override: Optional[str] = None, max_tokens: Optional[int] = None) -> Optional[Dict]:
    client = get_anthropic_client()
    system_prompt = prompt_override if prompt_override else build_system_prompt()
    user_prompt = build_user_prompt(comment) if not prompt_override else f'"{comment}"'
    
    resolved_max_tokens = max_tokens if max_tokens is not None else _estimate_max_tokens(comment)
    
    response = await client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=resolved_max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": "1h"}
            }
        ],
        messages=[
            {"role": "user", "content": user_prompt}
        ]
    )

    if hasattr(response, 'usage') and response.usage:
        usage = response.usage
        input_t = getattr(usage, 'input_tokens', 0)
        output_t = getattr(usage, 'output_tokens', 0)
        cache_creation_t = getattr(usage, 'cache_creation_input_tokens', 0)
        cache_read_t = getattr(usage, 'cache_read_input_tokens', 0)
        print(f"TOKEN USAGE -> Input: {input_t} | Output: {output_t} | Cache Write: {cache_creation_t} | Cache Read: {cache_read_t}")

    result_text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            result_text = block.text
            break
        elif hasattr(block, "text"):
            result_text = block.text

    result = parse_llm_json(result_text)
    if result and isinstance(result, dict):
        return result
    return None

async def classify_category_only_with_llm(comment: str) -> Optional[str]:

    prompt = f"""
You are a strict VOC category classifier.

Customer comment:
"{comment}"

Allowed categories:
{json.dumps(MASTER_CATEGORIES, indent=2, ensure_ascii=False)}

Task:
Try to choose the best category from the allowed categories. If a valid digital payment issue doesn't match, create a new one.

Rules:
1. The comment may be in any language. First, internally translate the comment to English to understand its exact business context, then match it.
2. Try to map the customer comment to one of the ALLOWED CATEGORIES.
3. If the comment describes a valid digital payment issue but DOES NOT fit any allowed category, CREATE AND ASSIGN a concise, new category name (MAXIMUM 3 WORDS).
4. If the comment is NOT related to payments/business, or is not a valid descriptive VOC (e.g., "good", "bad", "ok", gibberish), assign "Generic".
5. Positive praise with no issue should be Generic.
6. Return ONLY valid JSON.

Format:
{{
  "category": ""
}}
"""
    try:
        result = await call_anthropic_llm(comment, prompt_override=prompt, max_tokens=150)
        if result and isinstance(result, dict):
            category = ensure_string(result.get("category", ""))
            for db_category in MASTER_CATEGORIES:
                if clean_for_match(db_category) == clean_for_match(category):
                    return db_category
            best_category = ""
            best_score = 0.0
            for db_category in MASTER_CATEGORIES:
                score = similarity_score(category, db_category)
                if score > best_score:
                    best_score = score
                    best_category = db_category
            if best_category and best_score >= 0.75:
                return best_category
    except Exception as e:
        logger.warning(f"Category-only classification failed: {str(e)[:80]}")
    return None