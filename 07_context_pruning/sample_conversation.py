"""
A canned 16-turn customer-support conversation that matches the Module 7,
Question 1 scenario: a long session where the user, at the end, references an
issue raised much earlier. Nothing is pinned by the user — the system detects on
its own that turn 2 (the order number) and turn 5 (the refund promise) are
important and keeps them, even though they fall outside a short sliding window.
"""

from pruning import Turn

# The final query deliberately refers back to turn 2 (order number) and turn 5
# (the refund promise), both outside a 5-turn window.
FINAL_QUERY = (
    "Can you confirm the refund for the damaged item on my original order will "
    "go to the card I used, and remind me what order number that was?"
)

CONVERSATION: list[Turn] = [
    Turn(1, "Hi, I need help with a recent order.",
         "Of course — I'd be happy to help. What seems to be the problem?"),
    Turn(2, "My order number is ORD-48213 and one of the items arrived damaged.",
         "Thanks. I see order ORD-48213 with a damaged item on it. I'm sorry about that."),
    Turn(3, "It was the ceramic mug set, the box was crushed.",
         "Got it — the ceramic mug set arrived with a crushed box. I've noted the damage."),
    Turn(4, "Do I need to send photos?",
         "A quick photo helps but isn't required for items marked fragile like this one."),
    Turn(5, "Okay. What are my options?",
         "You can get a full refund to your original payment method, or a free replacement shipped today."),
    Turn(6, "How long does a replacement take?",
         "A replacement typically arrives in 3-5 business days with free expedited shipping."),
    Turn(7, "And a refund?",
         "Refunds post to your original card in 5-7 business days after we receive the return."),
    Turn(8, "Do I have to pay return shipping?",
         "No — we'll email you a prepaid return label at no cost to you."),
    Turn(9, "By the way, my app keeps logging me out.",
         "That's usually a stale session token. Updating to the latest app version fixes it."),
    Turn(10, "I'm on the latest version already.",
         "Then clearing the app cache and signing back in should resolve the logout loop."),
    Turn(11, "Okay that worked, thanks.",
         "Great, glad that's sorted. Anything else on the app side?"),
    Turn(12, "No, the app is fine now.",
         "Perfect. Back to your order whenever you're ready."),
    Turn(13, "Can I change my shipping address for future orders?",
         "Yes — update it under Account > Addresses, and set it as your default."),
    Turn(14, "Done. Do loyalty points apply to replacements?",
         "Replacements don't earn new points, but your original purchase points remain intact."),
    Turn(15, "Good to know.",
         "Happy to help. Is there anything else I can do for you today?"),
    Turn(16, "Actually yes, one more thing about the damaged item.",
         "Sure — what would you like to know about the damaged item?"),
]
