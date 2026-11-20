# Demo A — Adapter layer: legacy COBOL → JSON → Bedrock - slide 10

> AWS *Advanced Development with Generative AI* · **Module 10**, slides 9 & 10
> (and the **correct answer to Question 1**, option B)

Question 1 scenario: Amazon Bedrock needs real-time access to customer data
stored in a legacy mainframe's **COBOL copybook** format, and the mainframe
wasn't built for modern APIs. The correct pattern is an **API facade with a data
-transformation layer** (COBOL → JSON), plus authentication and error handling —
the slide-9 adapter responsibilities.

This local Streamlit app runs that adapter end to end:

```
raw fixed-width record → authenticate → parse/transform → JSON → Bedrock → content
```

- **Data transformation (slide 10):** parses a fixed-width COBOL `CUSTOMER-RECORD`
  copybook (PIC X text, PIC 9 integers, PIC 9(7)V99 implied-decimal money) into a
  typed JSON object.
- **Authentication (slide 9):** an API-key check gates the adapter.
- **Error handling (slide 9):** a toggle injects a truncated record so you can see
  the adapter catch and surface a typed `AdapterError` instead of crashing.

## Run

```bash
cd ~/AdvDevGenAI/10_adapter_layer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

- **Simulate (default, no AWS):** emits a canned personalized message and shows the
  prompt the adapter would send.
- **Live Bedrock:** turn *Simulate* off to generate the message with Claude.

Prerequisites for live mode: AWS credentials, Bedrock model access, and
`bedrock:InvokeModel` permission. No AWS resources are created; nothing to tear down.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (record editor → JSON → content) |
| `adapter.py` | Copybook layout, fixed-width parser, auth, prompt builder |
| `bedrock_client.py` | `Converse` wrapper |

## Note

The copybook parser models the common fixed-width ASCII case with implied
decimals. Real mainframe data may be EBCDIC-encoded with packed-decimal (COMP-3)
fields; a production adapter would add a decoding step. The teaching point — a
transformation layer between legacy formats and the AI API — is the same.
