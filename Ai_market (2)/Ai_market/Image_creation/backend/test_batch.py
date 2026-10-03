"""
Legitimate testing tool: runs the pipeline against a batch of real, varied
prompts and reports actual statistics — how many passed on attempt 1, how
many needed retries, how many exhausted all retries. No fake/forced failures
here; this is honest evidence of how the pipeline behaves in practice.

Run:
  python test_batch.py
"""

from app.graph import run_campaign

TEST_PROMPTS = [
    "Create a Diwali campaign for my coffee shop. Make it warm, premium and festive.",
    "Create a festive promotional poster for a coffee shop celebrating Dussehra.",
    "Create a Christmas campaign for my coffee shop with a cozy, snowy feel.",
    "Create a New Year's Eve promo for my coffee shop, energetic and modern.",
    "Create a Diwali poster showing a coffee cup, a lit diya, marigold flowers, "
    "string lights, a barista in the background, and the text '50% OFF Today' "
    "in bold readable letters — all in one Instagram-ready frame.",
    "Create a monsoon-season campaign for my coffee shop, cozy rainy-day vibes.",
    "Create a Holi campaign for my coffee shop with vibrant colors and playful energy.",
    "Create a minimalist weekday morning promo for my coffee shop, clean and modern.",
]

BUSINESS_PROFILE = {
    "business_name": "Coffee Corner",
    "business_type": "Coffee Shop",
    "brand_tone": "premium and friendly",
}


def run_batch():
    results = []

    for i, prompt in enumerate(TEST_PROMPTS, 1):
        print(f"\n[{i}/{len(TEST_PROMPTS)}] Running: {prompt[:70]}...")
        try:
            final_state = run_campaign(prompt, BUSINESS_PROFILE)
            results.append({
                "prompt": prompt,
                "approved": final_state.get("quality_approved"),
                "score": final_state.get("quality_score"),
                "attempts": final_state.get("retry_count"),
                "issues": final_state.get("quality_issues", []),
            })
            print(f"    -> approved={final_state.get('quality_approved')} "
                  f"score={final_state.get('quality_score')} "
                  f"attempts={final_state.get('retry_count')}")
        except Exception as e:
            results.append({"prompt": prompt, "error": str(e)})
            print(f"    -> ERROR: {e}")

    # summary
    print("\n" + "=" * 60)
    print("BATCH TEST SUMMARY")
    print("=" * 60)

    passed_attempt_1 = sum(1 for r in results if r.get("attempts") == 1 and r.get("approved"))
    passed_with_retry = sum(1 for r in results if r.get("attempts", 0) > 1 and r.get("approved"))
    failed_all_retries = sum(1 for r in results if r.get("approved") is False)
    errored = sum(1 for r in results if "error" in r)

    print(f"Total prompts tested:        {len(TEST_PROMPTS)}")
    print(f"Passed on attempt 1:         {passed_attempt_1}")
    print(f"Passed after retry(ies):     {passed_with_retry}")
    print(f"Failed all retries:          {failed_all_retries}")
    print(f"Errored:                     {errored}")
    print()

    for r in results:
        if "error" in r:
            continue
        status = "PASS" if r["approved"] else "FAIL"
        print(f"[{status}] attempts={r['attempts']} score={r['score']} — {r['prompt'][:60]}")
        if not r["approved"] and r.get("issues"):
            print(f"         issues: {r['issues']}")


if __name__ == "__main__":
    run_batch()
