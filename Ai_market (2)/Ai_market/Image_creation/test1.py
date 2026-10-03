import requests
import json
import time


# ============================================================
# KIE API CONFIGURATION
# ============================================================

API_KEY = "3b757a12f53fdacfed0ecb36bb104117".strip()

BASE_URL = "https://api.kie.ai"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


# ============================================================
# PROMPT
# ============================================================

prompt = """
Create a social media post for participation of proRITHM in IMC 2026,
starting from 7th to 10th October 2026. Please reach us to see the live
demo of our product in action.
"""


# ============================================================
# IMAGE GENERATION PAYLOAD
# ============================================================

payload = {
    "model": "qwen2-1/text-to-image",

    "input": {
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "resolution": "1K",
        "output_format": "png"
    }
}


# ============================================================
# STEP 1: CREATE IMAGE GENERATION TASK
# ============================================================

print("=" * 60)
print("CREATING proRITHM IMC 2026 SOCIAL MEDIA POST")
print("=" * 60)

response = requests.post(
    f"{BASE_URL}/api/v1/jobs/createTask",
    headers=headers,
    json=payload,
    timeout=60
)

print("\nHTTP Status:", response.status_code)


# ============================================================
# PARSE RESPONSE
# ============================================================

try:
    result = response.json()

except Exception:
    print("\n❌ KIE API returned an invalid response")
    print(response.text)
    exit()


print("\nAPI Response:")
print(json.dumps(result, indent=2))


# ============================================================
# STEP 2: CHECK TASK CREATION
# ============================================================

if response.status_code != 200:

    print("\n❌ Failed to create image-generation task")
    print(response.text)

    exit()


if result.get("code") != 200:

    print("\n❌ KIE API returned an error")
    print(result.get("msg"))

    exit()


# ============================================================
# GET TASK ID
# ============================================================

task_id = result["data"]["taskId"]


print("\n" + "=" * 60)
print("✅ IMAGE GENERATION TASK CREATED")
print("=" * 60)

print("\nTask ID:")
print(task_id)


# ============================================================
# STEP 3: CHECK IMAGE GENERATION STATUS
# ============================================================

status_url = f"{BASE_URL}/api/v1/jobs/recordInfo"

status_headers = {
    "Authorization": f"Bearer {API_KEY}"
}


print("\n" + "=" * 60)
print("WAITING FOR IMAGE GENERATION")
print("=" * 60)


max_attempts = 100
attempt = 0


while attempt < max_attempts:

    attempt += 1

    print(
        f"\nChecking generation status "
        f"({attempt}/{max_attempts})..."
    )


    try:

        response = requests.get(
            status_url,
            headers=status_headers,
            params={
                "taskId": task_id
            },
            timeout=60
        )

    except requests.RequestException as e:

        print("\n❌ Failed to check task status")
        print(e)

        time.sleep(3)
        continue


    # ========================================================
    # CHECK HTTP STATUS
    # ========================================================

    if response.status_code != 200:

        print("\n❌ Failed to check task status")

        print(
            "HTTP Status:",
            response.status_code
        )

        print(
            "Response:",
            response.text
        )

        time.sleep(3)
        continue


    # ========================================================
    # PARSE STATUS RESPONSE
    # ========================================================

    try:

        result = response.json()

    except Exception:

        print("\n❌ Invalid JSON response")
        print(response.text)

        time.sleep(3)
        continue


    data = result.get("data", {})

    state = data.get("state")

    success_flag = data.get("successFlag")


    print("\nCurrent State:", state)
    print("Success Flag:", success_flag)


    # ========================================================
    # IMAGE STILL GENERATING
    # ========================================================

    if (
        success_flag == 0
        or state in [
            "waiting",
            "queuing",
            "generating"
        ]
    ):

        print("⏳ Image is still generating...")

        time.sleep(3)

        continue


    # ========================================================
    # IMAGE SUCCESSFULLY GENERATED
    # ========================================================

    elif (
        success_flag == 1
        or state == "success"
    ):

        print("\n" + "=" * 60)
        print("✅ IMAGE GENERATED SUCCESSFULLY")
        print("=" * 60)


        # ----------------------------------------------------
        # GET IMAGE URL
        # ----------------------------------------------------

        image_urls = (
            data
            .get("response", {})
            .get("resultUrls", [])
        )


        if not image_urls:

            print(
                "\n❌ Image was generated but "
                "no image URL was returned."
            )

            print("\nFull response:")

            print(
                json.dumps(
                    data,
                    indent=2
                )
            )

            break


        image_url = image_urls[0]


        print("\nImage URL:")
        print(image_url)


        # ====================================================
        # STEP 4: DOWNLOAD IMAGE
        # ====================================================

        print("\n" + "=" * 60)
        print("DOWNLOADING IMAGE")
        print("=" * 60)


        try:

            image_response = requests.get(
                image_url,
                timeout=120
            )

        except requests.RequestException as e:

            print("\n❌ Failed to download image")
            print(e)

            break


        # ====================================================
        # SAVE IMAGE
        # ====================================================

        if image_response.status_code == 200:

            filename = "proRITHM_IMC_2026.png"


            with open(
                filename,
                "wb"
            ) as file:

                file.write(
                    image_response.content
                )


            print("\n" + "=" * 60)
            print("✅ IMAGE DOWNLOADED SUCCESSFULLY")
            print("=" * 60)

            print("\nFile:")
            print(filename)

            print("\nImage URL:")
            print(image_url)

            print("\nCredits consumed:")
            print(
                data.get(
                    "creditsConsumed"
                )
            )


        else:

            print("\n❌ Failed to download image")

            print(
                "Download HTTP Status:",
                image_response.status_code
            )


        break


    # ========================================================
    # IMAGE GENERATION FAILED
    # ========================================================

    elif (
        success_flag == 2
        or state == "failed"
    ):

        print("\n" + "=" * 60)
        print("❌ IMAGE GENERATION FAILED")
        print("=" * 60)

        print("\nError:")

        print(
            data.get("failMsg")
            or data.get("errorMessage")
            or "Unknown error"
        )

        print("\nFull response:")

        print(
            json.dumps(
                data,
                indent=2
            )
        )

        break


    # ========================================================
    # UNKNOWN STATUS
    # ========================================================

    else:

        print("\n⚠️ Unknown task status")

        print(
            json.dumps(
                result,
                indent=2
            )
        )

        time.sleep(3)


# ============================================================
# TIMEOUT
# ============================================================

else:

    print("\n" + "=" * 60)
    print("❌ IMAGE GENERATION TIMED OUT")
    print("=" * 60)

    print(
        f"\nThe task was checked "
        f"{max_attempts} times."
    )

    print("\nTask ID:", task_id)