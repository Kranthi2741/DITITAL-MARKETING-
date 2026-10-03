from google import genai

# Put your API key here
API_KEY = "YOUR_GEMINI_API_KEY_HERE"

# Create client
client = genai.Client(api_key=API_KEY)

# Test Gemini 3.8 Flash
try:
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents="Hello Gemini! Tell me in one sentence that you are working."
    )

    print("✅ API KEY IS WORKING")
    print("Model: gemini-3.8-flash")
    print("Response:")
    print(response.text)

except Exception as e:
    print("❌ API CALL FAILED")
    print("Error:")
    print(e)