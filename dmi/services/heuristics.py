import re
from typing import List, Optional, Dict, Tuple
from difflib import SequenceMatcher

MIN_COMMENT_LENGTH = 23
MAX_COMMENT_LENGTH = 1200

SENTIMENTS = ['Positive', 'Negative', 'Neutral']
PRIORITIES = ['low', 'medium', 'high', 'critical']

# ==============================================================================
# NATIVE INDIAN SCRIPT - MULTILINGUAL SENTIMENT DICTIONARIES
# Covers: Hindi, Tamil, Telugu, Malayalam, Bengali, Gujarati, Kannada, Punjabi
# Uses actual Unicode characters so they match exactly what customers type.
# ==============================================================================

_NATIVE_POSITIVE = {
    # Hindi / Marathi (Devanagari)
    "अच्छा", "बहुत अच्छा", "बहुत बढ़िया", "बढ़िया", "शानदार", "जबरदस्त",
    "लाजवाब", "बेहतरीन", "सुंदर", "खुश", "धन्यवाद", "शुक्रिया",
    "जय हो", "सुपर", "मस्त", "एकदम सही", "एकदम बढ़िया", "उत्कृष्ट",
    "व्यवहार अच्छा", "अच्छा लगा", "सेवा अच्छी",
    # Tamil
    "நல்லது", "நன்று", "நன்றி", "மிக்க நன்றி", "மிகவும் நல்லது",
    "ரோம்ப நல்ல", "சூப்பர்", "அருமை", "சிறப்பு", "திருப்திகரமான",
    # Telugu
    "చాలా మంచిది", "మంచిది", "బావుంది", "సూపర్", "ధన్యవాదాలు",
    # Malayalam
    "നന്ദി", "വളരെ നന്ദി", "നല്ലത്", "സൂപ്പർ", "ഉത്തമം", "സന്തോഷം",
    # Bengali
    "ধন্যবাদ", "ভালো", "অনেক ভালো", "সুন্দর", "চমৎকার", "খুব ভালো",
    # Gujarati
    "ખૂબ સારું", "આભાર", "સરસ", "ઉત્તમ",
    # Kannada
    "ಧನ್ಯವಾದ", "ತುಂಬಾ ಒಳ್ಳೆಯದು", "ಸೂಪರ್", "ಉತ್ತಮ",
    # Punjabi
    "ਬਹੁਤ ਚੰਗਾ", "ਧੰਨਵਾਦ", "ਵਧੀਆ", "ਬਹੁਤ ਵਧੀਆ",
}

_TRANSLITERATED_POSITIVE = {
    "bahut badiya", "bahut badhiya", "badhiya", "badiya",
    "bahut acha", "bahut achha", "bahut accha", "acha", "achha", "accha",
    "shukriya", "dhanyawad", "jai ho", "shandar", "zabardast", "lajawaab",
    "mast", "behtareen", "ekdam sahi", "ekdam badhiya",
    "mikka nandri", "mik nandri", "romba nalla", "nalla", "nanru", "nandri",
    "chala manchidi", "manchidi", "bavundi", "chala bagundi",
    "valare nanni", "nanniyundu",
    "khub bhalo", "tumba olledu", "dhanyavadagalu",
}

_NATIVE_NEGATIVE = {
    # Hindi / Marathi (Devanagari)
    "बहुत बुरा", "खराब", "बुरा", "गलत", "परेशान", "तकलीफ", "परेशानी",
    "धोखा", "धोखाधड़ी", "बेकार", "गंदा", "शिकायत", "समस्या",
    "बहुत देरी", "नाराज", "ठगी", "झूठ", "बहुत ज़्यादा टाइम",
    # Tamil
    "மோசம்", "கஷ்டம்", "பிரச்சனை", "தாமதம்", "புகார்",
    # Telugu
    "చెడు", "సమస్య", "జాప్యం", "మోసం",
    # Malayalam
    "ബുദ്ധിമുട്ട്", "മോശം", "പ്രശ്നം", "ചതി",
    # Bengali
    "খারাপ", "সমস্যা", "দেরি", "প্রতারণা",
    # Gujarati
    "ખરાબ", "સમસ્યા", "ફરિયાદ",
    # Kannada
    "ಕೆಟ್ಟದು", "ಸಮಸ್ಯೆ", "ದೂರು",
    # Punjabi
    "ਮਾੜਾ", "ਸਮੱਸਿਆ",
}

_TRANSLITERATED_NEGATIVE = {
    "bahut bura", "bura", "galat", "pareshan", "takleef", "pareshani",
    "dhoka", "dhokha", "bekar", "kharab", "ganda", "mosam", "kashdam",
}

_NATIVE_GIBBERISH = {
    "नहीं", "ना", "नही", "कुछ नहीं", "कोई नहीं", "अभी नहीं",   # Hindi
    "இல்லை", "இல்ல", "ஒன்றுமில்லை",  # Tamil
    "లేదు", "ఏమీ లేదు",   # Telugu
    "ഇല്ല", "ഒന്നുമില്ല",  # Malayalam
    "না", "নেই", "কিছু না",  # Bengali
    "નહીં", "કંઈ નહીં",    # Gujarati
    "ಇಲ್ಲ", "ಏನೂ ಇಲ್ಲ",   # Kannada
    "ਨਹੀਂ", "ਕੁਝ ਨਹੀਂ",   # Punjabi
}


def detect_regional_sentiment(comment):
    # type: (str) -> tuple
    """
    Detects positive/negative sentiment from Indian regional language comments.
    Checks native Unicode scripts and transliterated (romanized) forms.
    Returns: (has_positive, has_negative)
    """
    raw = comment.strip()
    raw_lower = raw.lower()
    has_positive = (
        any(word in raw for word in _NATIVE_POSITIVE)
        or any(phrase in raw_lower for phrase in _TRANSLITERATED_POSITIVE)
    )
    has_negative = (
        any(word in raw for word in _NATIVE_NEGATIVE)
        or any(phrase in raw_lower for phrase in _TRANSLITERATED_NEGATIVE)
    )
    return has_positive, has_negative


def is_native_gibberish(comment):
    # type: (str) -> bool
    """Returns True if the comment is a known native-script nothing/no/nil response."""
    stripped = comment.strip()
    return stripped in _NATIVE_GIBBERISH or stripped.lower() in _NATIVE_GIBBERISH


def handle_positive_feedback(comment, category, sentiment, priority, observation, recommendations, customer_response, confidence_score, is_gibberish=0, nps_score=None):
    if not comment:
        return category, sentiment, priority, observation, recommendations, customer_response, confidence_score

    text = comment.lower()
    words = set(re.findall(r'\b\w+\b', text))

    positive_words = {
        "good", "great", "excellent", "best", "satisfied",
        "nice", "happy", "fast", "quick", "helpful", "cooperative",
        "smooth", "easy", "thank", "thanks", "awesome", "amazing",
        "wonderful", "fantastic", "superb", "brilliant", "perfect",
    }

    negative_words = {
        "bad", "poor", "issue", "problem", "delay", "failed",
        "rejected", "rude", "abusive", "unprofessional", "hidden",
        "charges", "never", "complaint",
        "pending", "unacceptable", "shocked"
    }

    has_positive = bool(words.intersection(positive_words))
    has_negative = bool(words.intersection(negative_words))

    reg_pos, reg_neg = detect_regional_sentiment(comment)
    has_positive = has_positive or reg_pos
    has_negative = has_negative or reg_neg

    # ---- Fix 5: If gibberish → force Neutral, low priority, Generic category ----
    if is_gibberish == 1:
        category = "Generic"
        sentiment = "Neutral"
        priority = "low"
        observation = "The comment does not contain meaningful feedback."
        recommendations = "No action required."
        customer_response = "Thank you for your response."
        confidence_score = "95%"
        return category, sentiment, priority, observation, recommendations, customer_response, confidence_score

    # ---- Fix 6: NPS Detractor Protection ----
    # If NPS <= 6 and negative complaint signals exist, NEVER treat as Positive
    comp_triggers = ["failed", "pending", "declined", "stuck", "deducted", "not credited", "stolen", "fraud", "scam", "blocked"]
    if nps_score is not None and nps_score <= 6 and (has_negative or any(t in text or t in comment for t in comp_triggers)):
        has_positive = False
        has_negative = True
        sentiment = "Negative"

    # If NPS >= 9 and no clear negative keywords, treat as Positive
    if nps_score is not None and nps_score >= 9 and not has_negative:
        has_positive = True

    if has_positive and not has_negative:
        category = "Generic"
        sentiment = "Positive"
        priority = "low"
        observation = "The customer shared positive feedback about the service."
        recommendations = "Continue maintaining good service quality."
        customer_response = "Thank you for your valuable feedback! We are glad you had a positive experience."
        confidence_score = "95%"

    return category, sentiment, priority, observation, recommendations, customer_response, confidence_score


def is_pure_positive(comment: str, nps_score: Optional[int] = None) -> bool:
    """Returns True if the comment is purely positive with no negative signals."""
    if not comment:
        return False
        
    text = comment.lower()
    words = set(re.findall(r'\b\w+\b', text))

    positive_words = {
        "good", "great", "excellent", "best", "satisfied",
        "nice", "happy", "fast", "quick", "helpful", "cooperative",
        "smooth", "easy", "thank", "thanks", "awesome", "amazing",
        "wonderful", "fantastic", "superb", "brilliant", "perfect",
    }

    negative_words = {
        "bad", "poor", "issue", "problem", "delay", "failed",
        "rejected", "rude", "abusive", "unprofessional", "hidden",
        "charges", "never", "complaint",
        "pending", "unacceptable", "shocked"
    }

    has_positive = bool(words.intersection(positive_words))
    has_negative = bool(words.intersection(negative_words))

    reg_pos, reg_neg = detect_regional_sentiment(comment)
    has_positive = has_positive or reg_pos
    has_negative = has_negative or reg_neg

    comp_triggers = ["failed", "pending", "declined", "stuck", "deducted", "not credited", "stolen", "fraud", "scam", "blocked"]
    if nps_score is not None and nps_score <= 6 and (has_negative or any(t in text or t in comment for t in comp_triggers)):
        return False
        
    if any(neg_phrase in text for neg_phrase in ["not good", "not happy", "not satisfied", "not clear", "not so good", "not best", "not a best", "not the best", "not great", "not nice"]):
        return False

    if nps_score is not None and nps_score >= 9 and not has_negative:
        return True

    return has_positive and not has_negative


def detect_gibberish(text: str) -> int:
    import re
    # FIRST VALIDATION: Less than 3 characters is automatically gibberish
    if not text or len(text.strip()) < 3:
        return 1
    if is_native_gibberish(text):
        return 1
    
    text_lower = text.lower().strip()
    
    words = text_lower.split()
    
    # 1. Check for common unwanted test strings and single 1-word non-descriptive responses
    unwanted_words = ["n/a", "na", "nil", "nill", "none", "nothing", "test", "testing", "xxx", "000", "no", "nope", "nahi"]
    single_generic_words = [
        "ok", "okay", "yes", "no"
    ]
    if len(words) <= 3 and any(w in unwanted_words for w in words):
        return 1
    if len(words) == 1 and words[0] in single_generic_words:
        return 1
    if text_lower in unwanted_words or text_lower.replace(".", "") in unwanted_words or text_lower in single_generic_words:
        return 1

    # 2. Check for numeric characters
    numeric_chars = sum(1 for c in text_lower if c.isdigit())
    if len(text_lower) > 0 and (numeric_chars / len(text_lower)) > 0.5:
        return 1
    numeric_only = re.sub(r'[\s\W_]', '', text_lower)
    if not numeric_only or numeric_only.isdigit():
        return 1
    
    # 3. Check for high density of special characters (excluding common punctuation)
    special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace() and c not in ".,!?-/:;()")
    if len(text) > 0 and (special_chars / len(text)) > 0.4:
        return 1
    
    # 4. Check for alphanumeric character repetition (e.g. aaaaa, 11111 - NOT punctuation like ..... or !!!!!)
    if re.search(r'([a-zA-Z0-9])\1{4,}', text_lower):
        return 1
        
    # 5. Check for keyboard mashing
    mashing = ['asdf', 'qwer', 'zxcv', 'hjkl', 'tyui', 'ghjk', 'vbnm']
    if any(m in text_lower for m in mashing):
        return 1
        
    # 6. Check for long Latin alphabetic words lacking vowels (ONLY for English/Latin text)
    has_non_ascii = any(ord(c) > 127 for c in text)
    if not has_non_ascii:
        vowel_regex = re.compile(r'[aeiouy]')
        clean_alpha_words = re.sub(r'[^a-z]', ' ', text_lower).split()
        non_vowel_long_words = sum(
            1 for w in clean_alpha_words
            if len(w) >= 5 and not vowel_regex.search(w)
        )
        if non_vowel_long_words > 0:
            return 1

        if len(clean_alpha_words) == 1 and len(clean_alpha_words[0]) <= 5 and not vowel_regex.search(clean_alpha_words[0]):
            return 1
        
    return 0

def redact_pii(text: str) -> str:
    """
    Redacts sensitive Personally Identifiable Information (PII) from the text.
    Masks emails, phone numbers, and potential account numbers.
    """
    if not text:
        return text

    # Redact Emails
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[EMAIL]', text)
    
    # Redact 10-digit Phone Numbers (Indian format matching or generic 10 digits)
    text = re.sub(r'\b(?:\+91[\-\s]?)?[6-9]\d{9}\b|\b\d{10}\b', '[PHONE]', text)
    
    # Redact Tracking/AWB Numbers (numeric sequences 8 digits or longer)
    text = re.sub(r'\b\d{8,}\b', '[TRACKING_NUMBER]', text)
    
    return text

def normalize_text(text: str) -> str:
    text = text.lower()

    contractions = {
        "couldn’t": "couldnt", "couldn't": "couldnt",
        "didn’t": "didnt", "didn't": "didnt",
        "don’t": "dont", "don't": "dont",
        "doesn’t": "doesnt", "doesn't": "doesnt",
        "can’t": "cant", "can't": "cant",
        "won’t": "wont", "won't": "wont",
        "isn’t": "isnt", "isn't": "isnt",
        "aren’t": "arent", "aren't": "arent",
        "wasn’t": "wasnt", "wasn't": "wasnt",
        "weren’t": "werent", "weren't": "werent",
    }

    for old, new in contractions.items():
        text = text.replace(old, new)

    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def normalize_comment(comment: str) -> Optional[str]:
    if not comment or not isinstance(comment, str):
        return None

    comment = comment.strip()

    if len(comment) < MIN_COMMENT_LENGTH:
        return None

    if len(comment) > MAX_COMMENT_LENGTH:
        comment = comment[:MAX_COMMENT_LENGTH]

    # Redact PII before returning the normalized string
    comment = redact_pii(comment)

    comment = "".join(c for c in comment if c.isprintable() or c in "\n\t")

    return comment if comment else None


def extract_keywords(comment: str) -> str:
    if not comment or not comment.strip():
        return "issue"

    text = normalize_text(comment)

    stop_words = {
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", 
        "yourself", "yourselves", "he", "him", "his", "himself", "she", "her", "hers", 
        "herself", "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
        "what", "which", "who", "whom", "this", "that", "these", "those", "am", "is", "are", 
        "was", "were", "be", "been", "being", "have", "has", "had", "having", "do", "does", 
        "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because", "as", "until", 
        "while", "of", "at", "by", "for", "with", "about", "against", "between", "into", 
        "through", "during", "before", "after", "above", "below", "to", "from", "up", "down", 
        "in", "out", "on", "off", "over", "under", "again", "further", "then", "once", "here", 
        "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", 
        "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", 
        "than", "too", "very", "s", "t", "can", "will", "just", "don", "should", "now",
        "please", "thank", "thanks", "sorry", "honestly", "felt", "seemed", "like", "feel",
        "continuing", "first", "yet", "would", "could", "make", "made", "get", "got", "give", 
        "gave", "take", "took", "say", "said", "tell", "told", "ask", "asked", "want", "wanted",
        "need", "needed", "try", "tried", "use", "used", "go", "went", "come", "came", "see", 
        "saw", "look", "looked", "find", "found", "think", "thought", "know", "knew", "let",
        "put", "keep", "kept", "show", "showed", "pay", "paid", "call", "called", "send", "sent",
        "click", "clicked", "open", "opened", "close", "closed", "start", "started", "stop", "stopped",
        "immediately", "really", "quite", "already", "also", "always", "still", "even", "much", "many",
        "today", "yesterday", "tomorrow", "day", "days", "month", "months", "year", "years", "time"
    }

    raw_words = text.split()
    
    valid_flags = []
    for w in raw_words:
        valid_flags.append(len(w) >= 3 and w not in stop_words and not w.isdigit())
        
    phrases = []
    used_indices = set()
    
    for i in range(len(raw_words) - 1):
        if valid_flags[i] and valid_flags[i+1]:
            phrases.append(f"{raw_words[i]} {raw_words[i+1]}")
            used_indices.add(i)
            used_indices.add(i+1)
            
    for i in range(len(raw_words)):
        if valid_flags[i] and i not in used_indices:
            phrases.append(raw_words[i])
            
    seen = set()
    unique_phrases = []
    for p in phrases:
        if p not in seen:
            seen.add(p)
            unique_phrases.append(p)
            
    return ", ".join(unique_phrases[:4]) if unique_phrases else "issue"


def ensure_string(value):
    if value is None:
        return ""

    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)

    if not isinstance(value, str):
        return str(value)

    return value.strip()


def clean_for_match(value: str) -> str:
    value = ensure_string(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def split_clean_words(value: str) -> List[str]:
    ignore_words = {
        "issue", "issues", "related", "category", "sub", "the", "a", "an",
        "of", "in", "on", "for", "to", "and", "or"
    }

    return [
        word for word in clean_for_match(value).split()
        if word and word not in ignore_words
    ]


def similarity_score(a: str, b: str) -> float:
    a_clean = clean_for_match(a)
    b_clean = clean_for_match(b)

    if not a_clean or not b_clean:
        return 0.0

    if a_clean == b_clean:
        return 1.0

    if a_clean in b_clean or b_clean in a_clean:
        return 0.90

    a_words = set(split_clean_words(a_clean))
    b_words = set(split_clean_words(b_clean))

    common_words = a_words.intersection(b_words)
    word_score = len(common_words) / max(len(a_words), len(b_words), 1)

    sequence_score = SequenceMatcher(None, a_clean, b_clean).ratio()

    token_scores = []
    for aw in a_words:
        for bw in b_words:
            token_scores.append(SequenceMatcher(None, aw, bw).ratio())

    token_score = max(token_scores) if token_scores else 0.0

    return max(word_score, sequence_score, token_score)


def comment_match_score(comment: str, label: str) -> float:
    comment_words = split_clean_words(comment)
    label_words = split_clean_words(label)

    if not comment_words or not label_words:
        return 0.0

    matched = 0

    for label_word in label_words:
        for comment_word in comment_words:
            if label_word == comment_word:
                matched += 1
                break

            if SequenceMatcher(None, label_word, comment_word).ratio() >= 0.72:
                matched += 1
                break

    score = matched / max(len(label_words), 1)

    if clean_for_match(label) in clean_for_match(comment):
        score = max(score, 1.0)

    return score


def detect_category_from_db_text(
    comment: str,
    categories: List[str]
) -> Optional[str]:

    best_category = ""
    best_score = 0.0

    for db_category in categories:
        if db_category == "Generic":
            continue

        category_score = comment_match_score(comment, db_category)

        if category_score > best_score:
            best_score = category_score
            best_category = db_category

    if best_category and best_score >= 0.45:
        return best_category

    return None


def fix_category_from_db(
    category: str,
    categories: List[str]
) -> str:

    category = ensure_string(category)

    if not category:
        return "Generic"

    category_clean = clean_for_match(category)

    for db_category in categories:
        if clean_for_match(db_category) == category_clean:
            return db_category

    fixed_category = ""
    best_category_score = 0.0

    for db_category in categories:
        score = similarity_score(category, db_category)

        if score > best_category_score:
            best_category_score = score
            fixed_category = db_category

    if best_category_score < 0.55:
        # If the LLM generated a custom category, keep it instead of forcing to Generic.
        fixed_category = category.strip()

    if fixed_category:
        return fixed_category

    return "Generic"


def should_run_two_step(
    category: str,
    fast_category: Optional[str]
) -> bool:

    if not category or category == "Generic":
        return True

    # Trust the LLM if it gave a specific category (either mapped or newly created)
    return False


def fix_sentiment_priority_text(
    comment: str,
    sentiment: str,
    priority: str,
    observation: str,
    recommendations: str,
    customer_response: str,
    confidence_score: str,
    category: str = "",
    sub_category: str = ""
) -> Tuple[str, str, str, str, str, str]:

    sentiment = ensure_string(sentiment)
    priority = ensure_string(priority).lower()
    observation = ensure_string(observation)
    recommendations = ensure_string(recommendations)
    customer_response = ensure_string(customer_response)
    confidence_score = ensure_string(confidence_score)

    text = normalize_text(comment)
    raw_lower = comment.lower().strip()

    # ---- Fix 4: Remove leaked prompt instruction phrases ----
    LEAKED_PROMPT_PHRASES = [
        "one precise sentence", "- one precise sentence", "-one precise sentence-",
        "one proper actionable business step", "actionable business step",
        "based only on the customer comment", "do not assume extra facts",
    ]
    obs_lower = observation.lower().strip() if observation else ""
    for phrase in LEAKED_PROMPT_PHRASES:
        if obs_lower == phrase or obs_lower.strip("-").strip() == phrase.strip("-").strip():
            observation = ""
            break
    rec_lower = recommendations.lower().strip() if recommendations else ""
    for phrase in LEAKED_PROMPT_PHRASES:
        if rec_lower == phrase or rec_lower.strip("-").strip() == phrase.strip("-").strip():
            recommendations = ""
            break

    # ---- Fix 3: Normalize confidence_score to "XX%" format ----
    if confidence_score:
        cs_clean = ensure_string(confidence_score).replace("%", "").strip()
        try:
            cs_int = int(float(cs_clean))
            confidence_score = f"{cs_int}%"
        except (ValueError, TypeError):
            confidence_score = "85%"
    else:
        confidence_score = "85%"

    positive_words = [
        "good", "great", "excellent", "nice", "best", "happy",
        "satisfied", "like", "love", "helpful", "quick", "fast",
        "smooth", "easy", "thank", "thanks", "awesome", "amazing",
        "wonderful", "fantastic", "superb", "brilliant", "perfect",
    ]

    negative_words = [
        "bad", "poor", "worst", "wrong", "worse", "pathetic", "terrible", "awful",
        "rude", "abusive", "unprofessional", "fake", "fraud", "scam", "cheating",
        "delay", "delayed", "late", "pending", "rejected", "failed", "unacceptable",
        "high", "expensive", "fee", "fees", "cost", "charges", "extra", "hidden",
        "disappointed", "upset", "angry", "frustrated", "useless",
        "zyada", "jyada", "kuch", "aur", "paresan", "dikkat", "kharab", "bekar",
        "ganda", "mosam", "kashdam", "galat", "pareshan", "takleef", "pareshani",
        "dhoka", "dhokha"
    ]

    negative_signals = [
        "delay", "not informed", "no one", "no information", "without information",
        "not updated", "no update", "issue", "problem", "complaint",
        "rude", "abusive", "unprofessional", "rejected", "failed",
        "hidden charges", "not clear", "no clarity", "without prior",
        "too much", "pending", "unacceptable", "shocked", "never",
        "transaction failed", "money deducted", "not credited", "account blocked",
        "payment stuck", "unauthorized", "fraud", "cheating", "declined"
    ]

    text_words = set(text.split())

    has_positive = any(word in text_words for word in positive_words)
    has_negative = any(word in text_words for word in negative_words) or any(signal in text for signal in negative_signals)
    
    if any(neg_phrase in text for neg_phrase in ["not good", "not happy", "not satisfied", "not clear", "not so good", "not best", "not a best", "not the best", "not great", "not nice"]):
        has_positive = False

    reg_pos, reg_neg = detect_regional_sentiment(comment)
    has_positive = has_positive or reg_pos
    has_negative = has_negative or reg_neg

    import re
    callback_signals = ["please call", "call me", "callback", "call karne", "call karo", "call kijiye", "call lagata", "call back", "call karlo", "contact me"]
    has_callback = any(re.search(r'\b' + re.escape(sig) + r'\b', text, re.IGNORECASE) for sig in callback_signals)

    churn_signals = ["uninstall", "delete", "stop using", "close account", "closing account"]
    has_churn = any(re.search(r'\b' + re.escape(sig) + r'\b', text, re.IGNORECASE) for sig in churn_signals)

    # REMOVED DANGEROUS REGEX OVERRIDES:
    # We now fully trust the Anthropic Prompt's strict Priority Consistency Table 
    # to accurately assign critical and high priorities based on contextual understanding.
    
    # We also fully trust the Anthropic Prompt's intelligent Sentiment assignment, 
    # so we no longer blindly override sentiment to Negative just because a keyword exists.

    if has_callback and priority not in ["high", "critical"]:
        priority = "high"

    if has_churn:
        priority = "critical"

    # Only safely format the priority and sentiment strings
    if priority:
        priority = str(priority).strip().lower()

    if sentiment:
        sentiment = str(sentiment).strip().title()

    if sentiment not in SENTIMENTS:
        sentiment = "Neutral"

    if priority not in PRIORITIES:
        priority = "low"

    if not observation or not observation.strip():
        observation = "The customer shared feedback that requires review."

    if not recommendations or not recommendations.strip():
        recommendations = "Review the customer's concern and provide a clear update with the next action."

    if priority in ["critical", "high"]:
        customer_response = ""
    elif not customer_response or not customer_response.strip():
        if sentiment == "Positive":
            customer_response = "Thank you for your valuable feedback! We are glad you had a positive experience."
        else:
            customer_response = "We apologize for the bad experience. We have forwarded your concern to our concerned team."

    return sentiment, priority, observation, recommendations, customer_response, confidence_score

def calculate_confidence_score(comment: str, category: str, is_gibberish: int, sentiment: str) -> str:
    if is_gibberish == 1:
        return "95%"
        
    if sentiment == "Positive":
        return "95%"
        
    if category == "Generic":
        return "85%"
        
    score = comment_match_score(comment, category)
    
    if score >= 0.8:
        return "95%"
    elif score >= 0.5:
        return "85%"
    elif score >= 0.3:
        return "75%"
    else:
        return "65%"
