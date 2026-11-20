"""
Sample questions, references, and answer pairs for the LLM-judge demo, plus
offline canned judge behavior.
"""

SAMPLES: dict[str, dict] = {
    "What is the capital of Australia?": {
        "reference": "The capital of Australia is Canberra.",
        "answer_a": "The capital of Australia is Canberra, located in the ACT.",
        "answer_b": "The capital of Australia is Sydney, its largest city.",
    },
    "Explain what a vector embedding is.": {
        "reference": (
            "A vector embedding is a numeric representation of text (or other data) "
            "in a high-dimensional space, where semantically similar items are close "
            "together."
        ),
        "answer_a": (
            "An embedding maps text to a point in a high-dimensional vector space so "
            "that similar meanings sit near each other, enabling similarity search."
        ),
        "answer_b": (
            "An embedding is when you compress a file to make it smaller for storage."
        ),
    },
}
