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


# ---------------------------------------------------------------------------
# Coding-question stream
#
# Tests whether semantic caching works for developer Q&A. Code questions are a
# harder case than support FAQs: a tiny wording change can change the correct
# answer (language, library, sync vs async), so a cache that is too loose will
# serve a WRONG answer.
#
# Each tuple is (query, group, expected) where expected is:
#   "miss"  - first time this intent is seen (populates the cache)
#   "hit"   - paraphrase of a cached intent; should be served from cache
#   "trap"  - looks similar to a cached query but needs a DIFFERENT answer;
#             a correct cache must MISS. A hit here is a false positive.
# ---------------------------------------------------------------------------
CODING_QUERIES: list[tuple[str, str, str]] = [
    # --- reverse a string in Python ---
    ("How do I reverse a string in Python?", "py_reverse_str", "miss"),
    ("What's the easiest way to flip a string around in Python?", "py_reverse_str", "hit"),
    ("Python code to reverse the characters of a string", "py_reverse_str", "hit"),
    ("How do I reverse a string in JavaScript?", "js_reverse_str", "trap"),  # other language
    ("How do I reverse a list in Python?", "py_reverse_list", "trap"),       # other data type

    # --- read a file in Python ---
    ("How do I read a text file line by line in Python?", "py_read_file", "miss"),
    ("Python: iterate over each line of a file", "py_read_file", "hit"),
    ("What's the proper way to open and loop through a file's lines in Python?", "py_read_file", "hit"),
    ("How do I write text to a file in Python?", "py_write_file", "trap"),   # read vs write

    # --- remove duplicates from a list ---
    ("How do I remove duplicates from a list in Python?", "py_dedupe", "miss"),
    ("Best way to get unique items from a Python list", "py_dedupe", "hit"),
    ("Deduplicate a list while keeping the original order in Python", "py_dedupe_ordered", "trap"),  # extra constraint

    # --- SQL ---
    ("Write a SQL query to find the second highest salary", "sql_second_salary", "miss"),
    ("How can I get the 2nd largest salary from an employees table in SQL?", "sql_second_salary", "hit"),
    ("SQL query to find the highest salary per department", "sql_max_by_dept", "trap"),

    # --- git ---
    ("How do I undo my last git commit?", "git_undo_commit", "miss"),
    ("Git: how to revert the most recent commit", "git_undo_commit", "hit"),
    ("I committed by mistake, how do I take it back in git?", "git_undo_commit", "hit"),
    ("How do I undo git add?", "git_unstage", "trap"),                       # different operation

    # --- async / HTTP ---
    ("How do I make an HTTP GET request in Python?", "py_http_get", "miss"),
    ("Python example to call a REST API with GET", "py_http_get", "hit"),
    ("How do I make an async HTTP GET request in Python?", "py_http_get_async", "trap"),  # sync vs async

    # --- unique one-offs ---
    ("Explain the difference between a mutex and a semaphore", "mutex_sem", "miss"),
    ("What does the Rust borrow checker do?", "rust_borrow", "miss"),
]
