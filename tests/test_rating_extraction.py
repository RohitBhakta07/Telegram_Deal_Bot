import re

# Note: ★ = U+2605, ⭐ = U+2B50 — these are literal Unicode chars
# Using raw strings (r'...') means \u escapes won't work, so we use actual chars

STAR = '\u2605'
STAR2 = '\u2b50'
RUPEE = '\u20b9'

# Pattern 1: Standard — parenthesized count "(1,234 Ratings)" / "(1,234)"
PATTERN_1 = rf'([1-5](?:\.\d{{1,2}})?)\s*(?:{STAR}|{STAR2})?\s*\([^)]*\)'

# Pattern 2: Reviews format — "4.2 Ratings & 234 Reviews"
PATTERN_2 = rf'([1-5](?:\.\d{{1,2}})?)\s*(?:{STAR}|{STAR2})?\s*(?:Ratings?\s*)?(?:&|and)\s*[\d,]+\s*Reviews?'

# Pattern 3: Standalone line — "4.2 ★" on its own line
PATTERN_3 = rf'^([1-5](?:\.\d{{1,2}})?)\s*(?:{STAR}|{STAR2})?$'

# Pattern 4: out of 5 — "4.2 out of 5"
PATTERN_4 = r'([1-5](?:\.\d{1,2})?)\s*out\s*of\s*5'

# Pattern 5: Short star — "4.2★" anywhere
PATTERN_5 = rf'([1-5](?:\.\d{{1,2}})?)\s*[{STAR}{STAR2}]'

# Pattern 6: Bare decimal — standalone number 3-5 with optional decimal
PATTERN_6_BARE = r'(?<!\d)([3-5](?:\.\d{1,2})?)(?!\d)'

# Rating count patterns
RATING_COUNT_PAREN = rf'(?:[1-5]\.\d)\s*(?:{STAR}|{STAR2})?\s*\(\s*([\d,]+)\s*[^)]*\)'
RATING_COUNT_TEXT = r'\b([\d,]+)\s*(?:Ratings?|Reviews?|bought)\b'

# Full production-style pattern list (as used in get_flipkart_deals)
FULL_PATTERNS = [
    (PATTERN_1, 'P1: Standard'),
    (PATTERN_2, 'P2: Reviews'),
    (PATTERN_3, 'P3: Standalone'),
    (PATTERN_4, 'P4: out of 5'),
    (PATTERN_5, 'P5: Short star'),
]

# Production-style list used in scrape_keyword_full
KEYWORD_PATTERNS = [
    PATTERN_1,
    PATTERN_2,
    PATTERN_5,
]


def _try_patterns(flat_text, patterns):
    for pattern, name in patterns:
        m = re.search(pattern, flat_text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _try_bare_decimal(flat_text):
    clean = re.sub(rf'{RUPEE}\s*[\d,]+', '', flat_text)
    clean = re.sub(r'\d+\s*%', '', clean)
    m = re.search(PATTERN_6_BARE, clean)
    return m.group(1) if m else None


# ========== Pattern 1: Standard Format ==========

def test_p1_with_decimal_and_star():
    text = f"4.2{STAR} (1,234 Ratings)"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result == "4.2"


def test_p1_no_decimal():
    text = "4 (1,234 Ratings)"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result == "4"


def test_p1_two_decimals():
    text = "4.20 (1,234 Ratings)"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result == "4.20"


def test_p1_no_star():
    text = "4.2 (1,234 Ratings)"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result == "4.2"


def test_p1_rating_5():
    text = "5.0 (10,000 Ratings)"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result == "5.0"


def test_p1_rating_3():
    text = "3 (500 Ratings)"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result == "3"


def test_p1_no_false_match():
    """Should NOT match '1' from '1,234 Ratings' standalone."""
    text = "1,234 Ratings"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result is None


def test_p1_real_card_context():
    text = f"Some Product 4.2{STAR} (1,234 Ratings) \u20b91,299"
    result = _try_patterns(text, [(PATTERN_1, 'P1')])
    assert result == "4.2"


# ========== Pattern 2: Reviews Format ==========

def test_p2_standard():
    text = "4.2 Ratings & 234 Reviews"
    result = _try_patterns(text, [(PATTERN_2, 'P2')])
    assert result == "4.2"


def test_p2_no_decimal():
    text = "4 Ratings & 234 Reviews"
    result = _try_patterns(text, [(PATTERN_2, 'P2')])
    assert result == "4"


# ========== Pattern 3: Standalone Line ==========

def test_p3_standard():
    text = f"4.2 {STAR}"
    result = _try_patterns(text, [(PATTERN_3, 'P3')])
    assert result == "4.2"


def test_p3_no_decimal():
    text = f"4{STAR}"
    result = _try_patterns(text, [(PATTERN_3, 'P3')])
    assert result == "4"


# ========== Pattern 4: out of 5 ==========

def test_p4_standard():
    text = "4.2 out of 5"
    result = _try_patterns(text, [(PATTERN_4, 'P4')])
    assert result == "4.2"


def test_p4_no_decimal():
    text = "4 out of 5"
    result = _try_patterns(text, [(PATTERN_4, 'P4')])
    assert result == "4"


# ========== Pattern 5: Short Star ==========

def test_p5_standard():
    text = f"4.2{STAR}"
    result = _try_patterns(text, [(PATTERN_5, 'P5')])
    assert result == "4.2"


def test_p5_no_decimal():
    text = f"4{STAR}"
    result = _try_patterns(text, [(PATTERN_5, 'P5')])
    assert result == "4"


def test_p5_catches_inline_count():
    """Pattern 5 catches '4.2*' even when there's inline text."""
    text = f"4.2{STAR} 1,234 Ratings"
    result = _try_patterns(text, [(PATTERN_5, 'P5')])
    assert result == "4.2"


def test_p5_no_false_match():
    text = "1,234 Ratings"
    result = _try_patterns(text, [(PATTERN_5, 'P5')])
    assert result is None


# ========== Pattern 6: Bare Decimal ==========

def test_p6_standard():
    text = f"Price {RUPEE}1,299 4.2 {STAR} Rating"
    result = _try_bare_decimal(text)
    assert result == "4.2"


def test_p6_no_decimal():
    text = f"Price {RUPEE}1,299 4 {STAR} Rating"
    result = _try_bare_decimal(text)
    assert result == "4"


def test_p6_ignores_price_and_pct():
    text = f"{RUPEE}1,299 {RUPEE}999 70% off"
    result = _try_bare_decimal(text)
    assert result is None


def test_p6_catches_no_star_inline():
    """Bare decimal catches '4.2' when no star present."""
    text = "4.2 1,234 Ratings"
    result = _try_bare_decimal(text)
    assert result == "4.2"


# ========== Rating Count ==========

def test_count_from_parentheses():
    text = f"4.2{STAR} (1,234 Ratings)"
    m = re.search(RATING_COUNT_PAREN, text)
    assert m is not None
    assert int(m.group(1).replace(',', '')) == 1234


def test_count_from_text():
    text = "Some product text 500 Ratings & 100 Reviews"
    m = re.search(RATING_COUNT_TEXT, text, re.IGNORECASE)
    assert m is not None
    assert int(m.group(1).replace(',', '')) == 500


# ========== Full Flow Simulations ==========

def test_fetch_deals_style_extraction():
    """Simulate get_flipkart_deals extraction flow."""
    card_text_lines = [
        "Noise ColorFit Pulse Grand Smartwatch",
        f"4.2{STAR}",
        "(1,234 Ratings)",
        f"{RUPEE}1,299",
        f"{RUPEE}3,999",
        "67% off",
    ]
    flat_text = " ".join(card_text_lines)
    extracted = None

    for pattern, _ in FULL_PATTERNS:
        m = re.search(pattern, flat_text, re.IGNORECASE)
        if m:
            extracted = m.group(1)
            break

    if not extracted:
        clean = re.sub(rf'{RUPEE}\s*[\d,]+', '', flat_text)
        clean = re.sub(r'\d+\s*%', '', clean)
        m = re.search(PATTERN_6_BARE, clean)
        if m:
            extracted = m.group(1)

    assert extracted == "4.2"


def test_keyword_full_style_extraction():
    """Simulate scrape_keyword_full extraction flow."""
    card_text_lines = [
        "Noise ColorFit Pulse Grand Smartwatch",
        f"4.2{STAR}",
        "(1,234 Ratings)",
        f"{RUPEE}1,299",
        f"{RUPEE}3,999",
        "67% off",
    ]
    flat_text = " ".join(card_text_lines)
    lines = card_text_lines
    extracted = None

    for pat in KEYWORD_PATTERNS:
        m = re.search(pat, flat_text, re.IGNORECASE)
        if m:
            extracted = m.group(1)
            break

    if not extracted:
        for line in lines:
            m = re.search(PATTERN_3, line.strip())
            if m:
                extracted = m.group(1)
                break

    if not extracted:
        clean = re.sub(rf'{RUPEE}\s*[\d,]+', '', flat_text)
        clean = re.sub(r'\d+\s*%', '', clean)
        m = re.search(PATTERN_6_BARE, clean)
        if m:
            extracted = m.group(1)

    assert extracted == "4.2"


def test_first_rating_extracted():
    """When multiple ratings exist, the first one (leftmost) is correct."""
    text = f"4.5{STAR} (500 bought in past month) 4.2{STAR} Rating"
    result = _try_patterns(text, FULL_PATTERNS)
    assert result == "4.5"


def test_all_variants():
    variants = [
        (f"4.2{STAR} (1,234 Ratings)", "4.2"),
        (f"4.2{STAR}\n(1,234 Ratings)", "4.2"),
        ("4.2 (1,234)", "4.2"),
        ("4 (1,234)", "4"),
        (f"4.5{STAR}", "4.5"),
        (f"4{STAR}", "4"),
        ("3.8 out of 5", "3.8"),
        ("4 out of 5", "4"),
        (f"5.0{STAR} (50,000 Ratings)", "5.0"),
        (f"4.2{STAR} 1,234 Ratings", "4.2"),  # no parens → P5 catches
        ("4.2 1,234 Ratings", "4.2"),           # no star → P6 catches
    ]
    for text, expected in variants:
        result = _try_patterns(text, FULL_PATTERNS)
        if result is None:
            clean = re.sub(rf'{RUPEE}\s*[\d,]+', '', text)
            clean = re.sub(r'\d+\s*%', '', clean)
            m = re.search(PATTERN_6_BARE, clean)
            if m:
                result = m.group(1)
        assert result == expected, f"Failed for '{text}': expected {expected}, got {result}"
