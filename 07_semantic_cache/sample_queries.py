"""
Sample query stream for the semantic-cache demo.

Mirrors the Module 7 scenario (slides 38-39, Question 2): users ask the SAME
intent with different wording. Exact-match caching misses all the paraphrases;
semantic caching serves them from the first cached answer.

Each tuple is (query, intent_group). Queries in the same group should resolve to
one cached answer under semantic caching.
"""

# Ordered to mimic real support traffic: a few common intents, each asked many
# times with different wording, interleaved with a couple of unique one-offs.
# The first query of each intent is a cache miss (it populates the cache); every
# later paraphrase of that intent should be a semantic hit. With this repeat-heavy
# mix the semantic hit rate lands in the slide's 60-80% band.
SAMPLE_QUERIES: list[tuple[str, str]] = [
    # --- password reset (the slide's own example) ---
    ("How do I reset my password?", "password_reset"),              # miss (first)
    ("What's the process for changing my login credentials?", "password_reset"),  # hit
    ("I forgot my password, how can I set a new one?", "password_reset"),          # hit
    ("How can I update my sign-in details?", "password_reset"),     # hit
    ("I need to recover my login password", "password_reset"),      # hit

    # --- order tracking ---
    ("Where is my order?", "order_tracking"),                       # miss (first)
    ("How do I track my shipment?", "order_tracking"),              # hit
    ("Can I see the delivery status of my package?", "order_tracking"),  # hit
    ("How do I find my parcel's tracking status?", "order_tracking"),    # hit

    # --- refund ---
    ("How do I request a refund?", "refund"),                       # miss (first)
    ("What is the process to get my money back?", "refund"),        # hit
    ("How can I claim a refund for my order?", "refund"),           # hit

    # --- unique one-offs — should stay misses ---
    ("Do you ship internationally?", "shipping_intl"),              # miss (one-off)
    ("What are your business hours?", "hours"),                     # miss (one-off)
]
