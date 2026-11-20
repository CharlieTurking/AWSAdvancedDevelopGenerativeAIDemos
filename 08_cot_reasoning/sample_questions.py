"""
Sample financial-analysis questions for the reasoning demo (Question 2 scenario).

Includes a mix: a clean multi-step calc, a compounding question (models often
slip here), and one with a deliberately tricky framing that tends to produce
inconsistent reasoning across runs — good for the self-consistency check.
"""

SAMPLE_QUESTIONS: list[str] = [
    # Straightforward margin calc.
    "A product sells for $120 and costs $75 to make. What is the gross margin "
    "percentage?",

    # Compound growth — a classic spot for reasoning slips.
    "An investment of $10,000 grows at 8% per year, compounded annually. What is "
    "its value after 3 years?",

    # Multi-step with a distractor.
    "A company had revenue of $2,000,000 and costs of $1,400,000. It pays 25% "
    "tax on profit. A board member mentions the office has 50 employees. What is "
    "the after-tax profit?",

    # Rate blending — easy to mishandle the weighting.
    "A portfolio is 60% in bonds returning 4% and 40% in stocks returning 10%. "
    "What is the blended annual return?",
]
