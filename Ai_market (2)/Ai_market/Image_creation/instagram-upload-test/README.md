# One-off Instagram upload test

This folder is deliberately separate from the marketing application. It publishes exactly one image using the Instagram Graph API and prints the resulting media ID.

## Setup

1. Copy `.env.example` to `.env`.
2. Put the Instagram access token in `INSTAGRAM_ACCESS_TOKEN` and confirm `INSTAGRAM_USER_ID`.
3. Set `IMAGE_PATH` to the local image path. The script uploads it to a temporary public HTTPS URL, then Meta fetches it. Alternatively set `IMAGE_URL` if you already have a public URL.

## Run

```powershell
node .\publish_test.mjs
```

The script first creates an image media container and then immediately publishes it. Run it only when the selected image and caption are final.

Secrets in `.env` are ignored by Git. Do not put real tokens into `.env.example` or send them in chat.

The temporary image URL is public while it exists. Use this only for a test image and avoid sensitive/private photos.
