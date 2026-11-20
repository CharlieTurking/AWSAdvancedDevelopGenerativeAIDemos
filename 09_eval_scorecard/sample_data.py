"""
Sample questions + reference answers for the evaluation demo, plus canned
offline responses so the demo runs without Bedrock.
"""

SAMPLES: dict[str, dict] = {
    "What is Amazon Bedrock?": {
        "reference": (
            "Amazon Bedrock is a fully managed AWS service that provides access to "
            "foundation models from multiple providers through a single API, for "
            "building generative AI applications."
        ),
        # Canned responses for two "models" in offline mode.
        "offline": {
            "Model A": (
                "Amazon Bedrock is a fully managed service that offers foundation "
                "models from several providers via one API to build generative AI apps."
            ),
            "Model B": (
                "Bedrock is an AWS thing for AI. It does machine learning and you can "
                "use it to train models from scratch on your own GPUs."
            ),
        },
    },
    "How do I calculate gross margin percentage?": {
        "reference": (
            "Gross margin percentage = (revenue - cost of goods sold) / revenue, "
            "expressed as a percentage."
        ),
        "offline": {
            "Model A": (
                "Gross margin % = (revenue - COGS) / revenue x 100. For example, "
                "$120 price and $75 cost gives (120-75)/120 = 37.5%."
            ),
            "Model B": (
                "You subtract cost from price. So 120 minus 75 is 45 dollars of margin."
            ),
        },
    },
}

DEFAULT_MODELS = ["Model A", "Model B"]
