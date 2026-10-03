from openai import OpenAI
import json

# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = "YOUR_OPENROUTER_API_KEY_HERE"

MODEL = "apodex/apodex-1.1-mini:free"

# ============================================================
# OPENROUTER CLIENT
# ============================================================

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=API_KEY
)

# ============================================================
# TEST REQUEST
# ============================================================

try:

    print("=" * 60)
    print("Testing OpenRouter API...")
    print("=" * 60)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful AI assistant. "
                    "Answer the user's question clearly and briefly."
                )
            },
            {
                "role": "user",
                "content": "Today morning i went to cricket i an my team got 1st prize and we recieved prize from the andhra pradesh cm with a prize of 100000"
            }
        ],
        max_tokens=300,
        temperature=0.7
    )

    # ========================================================
    # BASIC INFORMATION
    # ========================================================

    print("\n✅ API REQUEST SUCCESSFUL")
    print(f"Model: {response.model}")

    # ========================================================
    # CHECK CHOICES
    # ========================================================

    if not response.choices:

        print("\n❌ No choices returned by the model.")
        print("\nFull response:")
        print(response)

    else:

        message = response.choices[0].message

        print("\n" + "=" * 60)
        print("MESSAGE")
        print("=" * 60)

        print(message)

        # ====================================================
        # FINAL ANSWER
        # ====================================================

        content = message.content

        print("\n" + "=" * 60)
        print("FINAL ANSWER")
        print("=" * 60)

        if content:
            print(content)

        else:
            print("⚠️ message.content is None")

            # Check for additional fields returned by the model
            print("\nAvailable message fields:")

            try:
                message_dict = message.model_dump()

                for key, value in message_dict.items():

                    # Don't print private reasoning content
                    if key in [
                        "reasoning",
                        "reasoning_details"
                    ]:
                        if value:
                            print(f"- {key}: [present but not displayed]")
                    else:
                        print(f"- {key}: {value}")

            except Exception as e:
                print("Could not inspect message:", e)

    # ========================================================
    # USAGE INFORMATION
    # ========================================================

    print("\n" + "=" * 60)
    print("USAGE")
    print("=" * 60)

    if response.usage:
        print("Prompt tokens:",
              getattr(response.usage, "prompt_tokens", None))

        print("Completion tokens:",
              getattr(response.usage, "completion_tokens", None))

        print("Total tokens:",
              getattr(response.usage, "total_tokens", None))

        # Reasoning token information, if available
        completion_details = getattr(
            response.usage,
            "completion_tokens_details",
            None
        )

        if completion_details:

            reasoning_tokens = getattr(
                completion_details,
                "reasoning_tokens",
                None
            )

            if reasoning_tokens is not None:
                print("Reasoning tokens:", reasoning_tokens)

    # ========================================================
    # FINISH
    # ========================================================

    print("\n" + "=" * 60)
    print("TEST COMPLETED")
    print("=" * 60)

except Exception as e:

    print("\n" + "=" * 60)
    print("❌ API REQUEST FAILED")
    print("=" * 60)

    print("Error type:", type(e).__name__)
    print("Error:", e)