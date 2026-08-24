import json
import os
import re
import logging
from typing import Dict, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from bluedart.core.config import settings
from bluedart.services.heuristics import SENTIMENTS, PRIORITIES

import anthropic

logger = logging.getLogger("bluedart_api")

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

MASTER_CATEGORIES = [
    "Delivery Issues",
    "Package Condition",
    "Shipment Tracking",
    "Customer Support",
    "Agent Behaviour",
    "Pricing & Charges",
    "COD Issues",
    "Returns & Refunds",
    "Pickup Issues",
    "Documentation",
    "App & Platform",
    "Notification Issues",
    "Fraud & Security",
    "Unwanted Communications",
    "Miscommunication",
    "Service Related",
    "Generic"
]

def build_system_prompt() -> str:
    categories_json = json.dumps(MASTER_CATEGORIES, indent=2, ensure_ascii=False)
    prompt_text = f"""
You are an expert VOC (Voice of Customer) analyst for a leading courier and logistics company.

Analyze the customer comment and return ONLY valid JSON.

ALLOWED CATEGORIES:
{categories_json}

TRANSLATION REQUIREMENT (CRITICAL):
If the CUSTOMER COMMENT is in ANY regional Indian language (Hindi, Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada, Malayalam, Punjabi, Odia, Urdu, etc. - in either native script or English transliteration), you MUST translate it to pure English and put the English text in the `voc_translated` field.
Example: If comment is "आप पहले कुछ बताते हो", `voc_translated` MUST be "You say something first".
If the comment is already English, copy it exactly as is. NEVER output Hindi or regional text in the JSON fields.

VERY IMPORTANT:
First, try to map the customer comment to one of the ALLOWED CATEGORIES above.

Rules:
1. The comment may be in ANY Indian language or Hinglish/Tanglish. First, internally translate the comment to English to understand its exact business context, then match it.
2. If the comment matches an allowed category, use it.
3. If the comment describes a valid logistics/courier issue but DOES NOT fit any allowed category, you MAY CREATE AND ASSIGN a concise, new category name (MAXIMUM 3 WORDS).
4. If the comment is NOT related to logistics/delivery (e.g., complaining about a completely unrelated finance issue), or is purely gibberish (e.g., "hjksdf"), you MUST assign the category "Generic".
5. Positive praise with no specific actionable issue (e.g., "good service", "best courier") MUST be assigned to Category: "Service Related" and Sub-Category: "Good Service Quality".
6. Vague negative dissatisfaction regarding the courier/delivery experience with NO specific actionable issue named (e.g., "poor service", "worst experience", "very bad delivery") MUST be assigned to Category: "Service Related" and Sub-Category: "Not Satisfied with Service". However, if the negative comment is completely unrelated to logistics, it should remain "Generic".

FIELD RULES:
voc_translated:
- If the CUSTOMER COMMENT is in English, YOU MUST COPY IT EXACTLY, character for character, including any spelling or grammar mistakes, extra spaces, or missing punctuation. NEVER "correct" or reword it, even if the fix seems obvious or minor.
- CONCRETE ANTI-EXAMPLE: if the input is "Not good in this area and Dilivery agent was not all good", the ONLY correct voc_translated is "Not good in this area and Dilivery agent was not all good" — keep "Dilivery" misspelled exactly as written. Outputting "Delivery agent" instead is WRONG, even though it looks like a harmless typo fix. The same applies to "recieved" (do not change to "received"), "I m" (do not change to "I am"), and any other misspelling — every one of these must be preserved verbatim.
- NEVER LEAVE THIS BLANK.
- If the CUSTOMER COMMENT is in any regional Indian language, provide a literal, word-for-word English translation. Do NOT add "Customer says...".

category:
- Based on the rules above.

sub_category:
- You MUST ALWAYS pick a sub-category directly related to your chosen category from the mapping below. Every sub-category you output MUST be copied EXACTLY (spelling, spacing, punctuation) from this list — never invent a variant spelling.
- STRICT CATEGORY TO SUB-CATEGORY MAPPING:
  - "Delivery Issues" -> ["Delayed Delivery", "Non-Delivery", "Wrong Address", "Missed Attempt", "Delivery Outside Slot", "Lost in Transit"]
  - "Package Condition" -> ["Damaged Package", "Tampered Package", "Missing Items", "Wrong Item"]
  - "Shipment Tracking" -> ["Tracking Not Updated", "Incorrect Tracking Status", "No Tracking ID", "False Delivery Status"]
  - "Customer Support" -> ["Unresponsive Agent", "Long Hold Time", "Service Quality Issue", "Callback Not Honored", "Callback Request", "Cancellation Request"]
  - "Agent Behaviour" -> ["Rude Behaviour", "Extra Charge Demand", "Agent Refused Wait", "Poor Time Management", "Unauthorized Handling", "Harassment / Threats"]
  - "Pricing & Charges" -> ["Overcharged Shipping Fee", "Hidden COD Charges", "Wrong Weight Billing", "Unexpected Duty Charges"]
  - "COD Issues" -> ["Amount Mismatch", "Refund Not Processed", "Charged After Cancellation"]
  - "Returns & Refunds" -> ["Return Not Picked", "Refund Delayed", "Wrong Refund Amount", "Pickup Rejected", "Refund Request"]
  - "Pickup Issues" -> ["Pickup Not Scheduled", "Pickup Missed", "Rescheduled Without Consent"]
  - "Documentation" -> ["Invoice Mismatch", "Missing Label", "POD Not Shared", "KYC Issue"]
  - "App & Platform" -> ["App Crash", "Booking Failure", "Feature Request", "Tracking Not Working"]
  - "Notification Issues" -> ["Premature Notification", "False Delivery SMS", "Missing Updates"]
  - "Fraud & Security" -> ["Alleged Parcel Theft", "Fake Delivery Marked", "Unauthorized Confirmation", "Data Privacy", "Account Hacked", "Safety Concern"]
  - "Unwanted Communications" -> ["Repeated Calls", "Promotional Spam", "Unwanted Notifications"]
  - "Miscommunication" -> ["Status Not Transparent", "Conflicting Information", "No Delay Reason"]
  - "Service Related" -> ["Not Satisfied with Service", "Good Service Quality", "Poor Branch Service"]
  - "Generic" -> ["Generic"]
  - CRITICAL RULE: If the category assigned is "Generic" for any reason, the sub_category MUST exactly be "Generic". Do not assign any other sub-category to the Generic category.
  - CRITICAL MAPPING RULE: "Callback Request" (customer explicitly asks to be called NOW, e.g. "please call me", "call me back regarding this") is DIFFERENT from "Callback Not Honored" (customer complains an agent PROMISED to call and never did — a past broken promise, not a new request). Do not confuse these.
  - CRITICAL MAPPING RULE: "Fake Delivery Marked" (status shows delivered/attempted without an actual visit — e.g. "door locked" with no call) is DIFFERENT from "Unauthorized Confirmation" (the system falsely attributes a confirming action — a signature, an OTP, or a "picked up by customer" status — to the customer when the customer states they did not do this or were not present/available to do it). Use "Unauthorized Confirmation" whenever the customer states the record shows THEY personally confirmed/signed/picked up/received the package and they deny doing so — this applies even if the customer doesn't use the specific words "signature" or "OTP". Use "Fake Delivery Marked" only when the falseness is about the delivery attempt itself (agent never came), not about an action being wrongly attributed to the customer.
  - CRITICAL MAPPING RULE: "Non-Delivery" (default for "I have not received my package/order/shipment") is DIFFERENT from "Lost in Transit" (use ONLY when the customer explicitly states or strongly implies the package is confirmed lost, untraceable, or has been missing for an extended, stated period — e.g. "it's been a month and still lost"). Default to "Non-Delivery" unless there is clear evidence of confirmed total loss — do not assume loss from a simple "not received yet" comment.
  - CRITICAL MAPPING RULE: Courier companies frequently deliver physical items like credit cards, debit cards, bank statements, checkbooks, passports, and documents. A complaint like "I have not received my card/passport/document/cheque/letter" is a VALID "Delivery Issues" -> "Non-Delivery" comment. Do NOT mark these as gibberish or non-logistics.
  - CRITICAL MAPPING RULE ("Delivered but Not Received" ambiguity): If a customer says tracking shows delivered but they have not received it, and does NOT specify it went to a neighbor/shop/wrong person or that a signature was forged, do NOT assume wrong delivery or fraud occurred. Classify as "Shipment Tracking" -> "Incorrect Tracking Status". Only use "Fraud & Security" if there is explicit evidence of impersonation, or "Delivery Issues" -> "Wrong Address" if there is explicit evidence of a wrong location.
  - CRITICAL MAPPING RULE (SMS received but no parcel): If a customer specifically states they received an SMS or notification regarding a parcel or delivery attempt, but did not actually receive the parcel, classify this as "Notification Issues" -> "False Delivery SMS".
  - CRITICAL MAPPING RULE (Agent Behaviour vs Generic Service): If a customer complains about HOW someone spoke to them (e.g., "poor way to talk", "argumentative") or explicitly complains about a specific delivery person's conduct (e.g., "poor service from delivery person"), you MUST classify this as "Agent Behaviour" -> "Rude Behaviour", UNLESS the conduct involves false reporting or a fake delivery attempt (which remains "Fraud & Security" -> "Fake Delivery Marked"). Do NOT use "Service Related" -> "Not Satisfied with Service", which is reserved strictly for vague complaints where no specific cause or person is identified.
  - CRITICAL MAPPING RULE (Agent Wait Times): If a customer explicitly complains that the delivery agent made them wait an unreasonable amount of time during the delivery interaction (e.g., "made me keep waiting"), classify this as "Agent Behaviour" -> "Poor Time Management". Do NOT confuse this with "Delivery Issues" -> "Delayed Delivery", which means the package itself arrived days late, nor with "Agent Refused Wait", which means the agent refused to wait for the customer.
  - CRITICAL MAPPING RULE (Multi-Intent / Multiple Complaints): If a customer complains about multiple distinct issues in the same ticket (e.g. a severe delay AND a rude agent, OR poor quality AND a refund request, OR delayed delivery AND cancellation request), prioritize the MOST SEVERE OR ACTIONABLE ISSUE (e.g., "Fraud & Security", "Agent Behaviour", "Returns & Refunds" -> "Refund Request", or "Customer Support" -> "Cancellation Request") as the primary category. DO NOT just default to the initial logistics failure (like Delayed Delivery or Missing Items) if a more severe behavioral grievance or explicit request is present. Make sure to capture the secondary issues prominently in the `observation` field.
- If a category is not listed, generate a highly specific category name (MAXIMUM 3 WORDS).

sentiment must be exactly one of:
{SENTIMENTS}

priority must be:
Priority guidance (OPEN vs AUTOCLOSED):
CRITICAL RULE: GATEKEEPER CHECK. You must determine if this is a TRULY CRITICAL ESCALATION to set priority to "critical".
A complaint is considered a "critical" priority ONLY if it involves ANY of the following:
1. Legal/Regulatory Threats: Explicitly threatening legal action or consumer court over lost packages.
2. Severe Fraud/Theft: Delivery agent stole the package, a forged delivery signature or OTP, a valuable/expensive item explicitly stated as missing from the package, OR the customer explicitly uses fraud-accusation language ("cheating", "fraud", "scam", "duped", "conned").
3. Public Brand Damage: Threatening to post on Twitter/Social media.
4. Severe Harassment: Abusive behavior, physical threats, or severe harassment by agents.
5. Confirmed Total Loss: Package confirmed lost or untraceable in transit (not merely delayed) — see "Lost in Transit" mapping rule above.
6. Bribery/Corruption: A delivery or support agent demanding extra money or a bribe to complete their job.

For all other issues, strictly classify them based on ACTIONABILITY:

- critical: ONLY if it passes the strict Gatekeeper Check above. (System will keep OPEN)
- high: Issues requiring DIRECT AGENT INTERVENTION beyond a routine operational fix. Examples: wrong-address deliveries, missed/fake attempts, an agent who is completely unreachable. (System will keep OPEN)
- medium: A concrete, specific operational issue was described that does not require urgent escalation — a delay, a billing error, a documentation gap, a tracking discrepancy, a support quality complaint, or an explicit request to be called back now. ALSO include vague negative feedback ("Service Related" -> "Not Satisfied with Service") here. (System will SEMI-AUTOCLOSE or AUTO-CLOSE)
- low: Positive feedback, "NA", "Nothing", "No", generic praise, gibberish, or Unwanted Communications. (SYSTEM CAN CLOSE)

STRICT PRIORITY CONSISTENCY TABLE (this OVERRIDES any general guidance above whenever a sub_category is listed here — apply it exactly, every single time. Every sub-category from the mapping above appears exactly once below.):

DELIVERY ISSUES
- "Delayed Delivery" -> medium
- "Non-Delivery" -> high
- "Wrong Address" -> high
- "Missed Attempt" -> high
- "Delivery Outside Slot" -> medium
- "Lost in Transit" -> critical

PACKAGE CONDITION
- "Damaged Package" -> medium
- "Tampered Package" -> high
- "Missing Items" -> medium (escalate to critical only if the comment explicitly states a valuable/expensive item is missing, per Gatekeeper rule 2)
- "Wrong Item" -> medium

SHIPMENT TRACKING
- "Tracking Not Updated" -> medium
- "Incorrect Tracking Status" -> medium
- "No Tracking ID" -> medium
- "False Delivery Status" -> medium

CUSTOMER SUPPORT
- "Unresponsive Agent" -> high
- "Long Hold Time" -> medium
- "Service Quality Issue" -> medium
- "Callback Not Honored" -> medium
- "Callback Request" -> medium
- "Cancellation Request" -> high

AGENT BEHAVIOUR
- "Rude Behaviour" -> high
- "Extra Charge Demand" -> critical (Gatekeeper rule 6)
- "Agent Refused Wait" -> high
- "Poor Time Management" -> medium
- "Unauthorized Handling" -> critical (impersonation/forged authorization — Gatekeeper rule 2)
- "Harassment / Threats" -> critical (Gatekeeper rule 4)

PRICING & CHARGES
- "Overcharged Shipping Fee" -> medium
- "Hidden COD Charges" -> medium
- "Wrong Weight Billing" -> medium
- "Unexpected Duty Charges" -> medium

COD ISSUES
- "Amount Mismatch" -> medium
- "Refund Not Processed" -> medium
- "Charged After Cancellation" -> high

RETURNS & REFUNDS
- "Return Not Picked" -> medium
- "Refund Delayed" -> medium
- "Wrong Refund Amount" -> medium
- "Pickup Rejected" -> medium
- "Refund Request" -> medium

PICKUP ISSUES
- "Pickup Not Scheduled" -> medium
- "Pickup Missed" -> medium
- "Rescheduled Without Consent" -> medium

DOCUMENTATION
- "Invoice Mismatch" -> medium
- "Missing Label" -> medium
- "POD Not Shared" -> medium
- "KYC Issue" -> medium

APP & PLATFORM
- "App Crash" -> medium
- "Booking Failure" -> medium
- "Feature Request" -> low
- "Tracking Not Working" -> medium

NOTIFICATION ISSUES
- "Premature Notification" -> medium
- "False Delivery SMS" -> medium (the lower-severity version — see mapping rule above; escalate to Fraud & Security if identity mismatch is stated)
- "Missing Updates" -> medium

FRAUD & SECURITY (all critical or high — direct fraud/security risk)
- "Alleged Parcel Theft" -> critical
- "Fake Delivery Marked" -> high
- "Unauthorized Confirmation" -> critical (Gatekeeper rule 2)
- "Data Privacy" -> critical
- "Account Hacked" -> critical
- "Safety Concern" -> critical (Gatekeeper rule 4)

UNWANTED COMMUNICATIONS
- "Repeated Calls" -> low
- "Promotional Spam" -> low
- "Unwanted Notifications" -> low

MISCOMMUNICATION
- "Status Not Transparent" -> medium
- "Conflicting Information" -> medium
- "No Delay Reason" -> medium

SERVICE RELATED
- "Not Satisfied with Service" -> medium (vague but logistics-related — see rule 6 above; this is NOT the same as "Generic", which stays low)
- "Good Service Quality" -> low
- "Poor Branch Service" -> medium

GENERIC (always low — no exceptions, regardless of sentiment or tone)
- "Generic" -> low

If you generate a NEW sub_category not in this table, assign priority using the general ACTIONABILITY guidance above, applying the Gatekeeper Check first.

Observation:
Write exactly one concise sentence (maximum 15-20 words) in ENGLISH ONLY describing the core issue. Do not assume facts. If the comment is literally just 1-2 words, state "The customer expressed vague dissatisfaction."

Recommendations:
Write exactly one short, actionable business step (maximum 15-20 words) in ENGLISH ONLY. Keep it very brief. Do not mention documents, verification, or approvals unless explicitly stated in the comment.

customer_response:
Generate a short, simple, professional customer response. STRICT RULE: exactly ONE sentence, MAXIMUM 15-25 words. Never write two sentences even if the second sentence seems helpful.

STEP 0 — CHECK FOR OVERRIDE SIGNATURES FIRST (before picking a bucket):
- Any comment resolving to "high" or "critical" priority per the table above -> output "" regardless of which bucket it might otherwise resemble. This is checked FIRST, before Steps 1-2 below are even relevant.

STEP 1 — DECIDE THE TONE BUCKET (for non-high/critical priority):
BUCKET A: Operational Failures. Apologize briefly, name issue. NO promised follow-up action. Pattern: "We apologize for [specific issue]."
BUCKET B: Rate Opinion. No apology, no validation. Pattern: "Thank you for your feedback regarding our shipping rates."
BUCKET C: Neutral Acknowledgment. Informational or requests. Pattern: "Thank you for your request - we've noted your preference." (Or similar neutral tone).
BUCKET D: Generic Praise/Vague: "Thank you for your feedback!"
BUCKET E: High/Critical priority -> output "" (empty string).

STEP 2 — HARD RULES FOR CUSTOMER RESPONSE:
1. MAX 15-25 WORDS. Exactly ONE sentence.
2. NO promises ("will call you", "forwarded to team", "arrange a return", "process a refund"). Acknowledge only.
3. NEVER use the word "ensure" or validate a negative claim.
4. NO contact info or asking for details.
5. NEVER mention arranging a return, refund, or replacement.
6. If `is_gibberish` is 1: output EXACTLY "Thank you for your valuable feedback." (never leave blank).
7. Separately, if priority is "critical" or "high" (and is_gibberish is 0): output "" (empty string).

Confidence Score: Estimate classification confidence (e.g., "95%").

Is Gibberish / Non-Logistics:
- 1 if comment is nonsensical, purely numeric (AWB only), or unrelated to logistics.
- 0 for meaningful complaints/questions, even if poorly spelled, very short ("worst service"), or about cards/passports.
- If `is_gibberish` is 1, output priority as "low", category/sub_category as "Generic".

Information Requests:
- For general tracking/doc requests with no grievance, use "Shipment Tracking" or "Documentation".

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
Input: "Package still not received. It is delayed by 4 days."
Output:
{{
  "voc_translated": "Package still not received. It is delayed by 4 days.",
  "is_gibberish": 0,
  "category": "Delivery Issues",
  "sub_category": "Delayed Delivery",
  "sentiment": "Negative",
  "priority": "medium",
  "observation": "The customer's package delivery is delayed by four days.",
  "recommendations": "Check shipment location at the local hub and contact the customer with an updated delivery time.",
  "customer_response": "We apologize for the delay in your delivery.",
  "confidence_score": "98%"
}}

Input: "Faltu service. Showing door locked status but delivery boy did not even call or visit."
Output:
{{
  "voc_translated": "Useless service. Showing door locked status but delivery boy did not even call or visit.",
  "is_gibberish": 0,
  "category": "Fraud & Security",
  "sub_category": "Fake Delivery Marked",
  "sentiment": "Negative",
  "priority": "high",
  "observation": "The customer alleges a fake delivery attempt was marked as door locked without any call or visit.",
  "recommendations": "Audit the delivery agent's GPS coordinates at the time of status update and contact the customer.",
  "customer_response": "",
  "confidence_score": "92%"
}}

Input: "Ordered 2 bags but only 1 was inside the package, and it was torn. Pls refund."
Output:
{{
  "voc_translated": "Ordered 2 bags but only 1 was inside the package, and it was torn. Pls refund.",
  "is_gibberish": 0,
  "category": "Returns & Refunds",
  "sub_category": "Refund Request",
  "sentiment": "Negative",
  "priority": "medium",
  "observation": "Customer received missing and damaged items, explicitly requesting a refund.",
  "recommendations": "Investigate the missing item and process the requested refund for the customer.",
  "customer_response": "We apologize for the missing and damaged items; we are checking this.",
  "confidence_score": "95%"
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

NO EXTRA TEXT.
"""
    # PAD PROMPT to ensure we cross the 4096-token threshold for Prompt Caching 
    # Claude Haiku 4.5 requires > 4096 tokens to activate cache.
    # Current organic length is roughly ~4000 tokens. Adding 300 single-tokens ('a ') to safely push past threshold.
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
    from bluedart.services.heuristics import similarity_score, clean_for_match, ensure_string

    prompt = f"""
You are a strict VOC category classifier.

Customer comment:
"{comment}"

Allowed categories:
{json.dumps(MASTER_CATEGORIES, indent=2, ensure_ascii=False)}

Task:
Try to choose the best category from the allowed categories. If a valid logistics/courier issue doesn't match, create a new one.

Rules:
1. The comment may be in any language. First, internally translate the comment to English to understand its exact business context, then match it.
2. Try to map the customer comment to one of the ALLOWED CATEGORIES.
3. If the comment describes a valid logistics issue but DOES NOT fit any allowed category, CREATE AND ASSIGN a concise, new category name (MAXIMUM 3 WORDS).
4. If the comment is NOT related to logistics/business, or is not a valid descriptive VOC (e.g., "good", "bad", "ok", gibberish), assign "Generic".
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