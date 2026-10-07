"""
Run the full agent pipeline from the command line.

Setup:
  ollama pull gemma3:4b
  ollama serve

Run:
  python run.py "Create a Diwali campaign for my coffee shop"
"""

import sys
from app.graph import run_campaign


if __name__ == "__main__":
    if len(sys.argv) < 2:
        prompt = "Create a Diwali marketing campaign for my coffee shop. Make it warm, premium and festive."
        print("No prompt given, using default example.\n")
    else:
        prompt = " ".join(sys.argv[1:])

    business_profile = {
        "business_name": "Coffee Corner",
        "business_type": "Coffee Shop",
        "brand_tone": "premium and friendly",
    }

    print(f"Prompt: {prompt}\n")
    result = run_campaign(prompt, business_profile)

    print("\n--- FINAL STATE ---")
    print(f"Approved: {result.get('quality_approved')}")
    print(f"Score: {result.get('quality_score')}")
    print(f"Attempts used: {result.get('retry_count')}")
    print(f"Image: {result.get('generated_image_path')}")
    print(f"Caption: {result.get('caption')}")
    print(f"Hashtags: {result.get('hashtags')}")
