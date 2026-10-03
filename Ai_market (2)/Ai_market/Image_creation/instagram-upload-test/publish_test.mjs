import "dotenv/config";
import { readFile } from "node:fs/promises";
import { basename } from "node:path";

const ACCESS_TOKEN = process.env.INSTAGRAM_ACCESS_TOKEN;
const CLOUDINARY_CLOUD_NAME = process.env.CLOUDINARY_CLOUD_NAME;
const CLOUDINARY_UPLOAD_PRESET = process.env.CLOUDINARY_UPLOAD_PRESET;

const IMAGE_PATH = process.env.IMAGE_PATH;

const CAPTION = "Test post from my AI Marketing Agent 🚀";

if (!ACCESS_TOKEN) {
    throw new Error("INSTAGRAM_ACCESS_TOKEN is missing");
}

console.log("Using Instagram account from access token");
console.log("Token loaded:", !!ACCESS_TOKEN);

if (!IMAGE_PATH) throw new Error("IMAGE_PATH is missing in .env");
if (!CLOUDINARY_CLOUD_NAME) throw new Error("CLOUDINARY_CLOUD_NAME is missing in .env");
if (!CLOUDINARY_UPLOAD_PRESET) throw new Error("CLOUDINARY_UPLOAD_PRESET is missing in .env");

console.log("Uploading local image and generating a public URL...");
const imageBytes = await readFile(IMAGE_PATH);
const form = new FormData();
form.append("file", new Blob([imageBytes]), basename(IMAGE_PATH));
form.append("upload_preset", CLOUDINARY_UPLOAD_PRESET);
const uploadResponse = await fetch(`https://api.cloudinary.com/v1_1/${CLOUDINARY_CLOUD_NAME}/image/upload`, { method: "POST", body: form });
const uploadData = await uploadResponse.json();
const originalImageUrl = uploadData?.secure_url;
// Normalize to a universally supported Instagram square JPEG.
const IMAGE_URL = originalImageUrl?.replace(
    "/image/upload/",
    "/image/upload/c_fill,w_1080,h_1080,ar_1:1,g_auto,f_jpg/"
);
if (!uploadResponse.ok || !IMAGE_URL) {
    throw new Error(`Image upload failed: ${JSON.stringify(uploadData)}`);
}
console.log("Image URL created:", IMAGE_URL);

//
// STEP 1: Create media container
//

console.log("\n1️⃣ Creating Instagram media container...");

const createUrl =
    `https://graph.instagram.com/me/media` +
    `?image_url=${encodeURIComponent(IMAGE_URL)}` +
    `&caption=${encodeURIComponent(CAPTION)}` +
    `&access_token=${encodeURIComponent(ACCESS_TOKEN)}`;

const createResponse = await fetch(createUrl, {
    method: "POST"
});

const createData = await createResponse.json();

console.log("HTTP Status:", createResponse.status);
console.log("Response:");
console.log(JSON.stringify(createData, null, 2));

if (!createResponse.ok || !createData.id) {
    console.error("\n❌ Media container creation failed.");
    process.exit(1);
}

const creationId = createData.id;

console.log("\n✅ Media container created:");
console.log(creationId);

console.log("Waiting for Instagram to finish processing...");
let status = "IN_PROGRESS";
for (let attempt = 1; attempt <= 30; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    const statusUrl =
        `https://graph.instagram.com/${creationId}` +
        `?fields=status_code,status&access_token=${encodeURIComponent(ACCESS_TOKEN)}`;
    const statusResponse = await fetch(statusUrl);
    const statusData = await statusResponse.json();
    status = statusData.status_code || statusData.status;
    console.log(`Processing status: ${status}`);
    if (status === "FINISHED") break;
    if (status === "ERROR" || status === "EXPIRED") {
        throw new Error(`Instagram media processing failed: ${JSON.stringify(statusData)}`);
    }
}
if (status !== "FINISHED") throw new Error("Instagram media processing timed out after 60 seconds");

//
// STEP 2: Publish container
//

console.log("\n2️⃣ Publishing Instagram post...");

const publishUrl =
    `https://graph.instagram.com/me/media_publish` +
    `?creation_id=${encodeURIComponent(creationId)}` +
    `&access_token=${encodeURIComponent(ACCESS_TOKEN)}`;

const publishResponse = await fetch(publishUrl, {
    method: "POST"
});

const publishData = await publishResponse.json();

console.log("HTTP Status:", publishResponse.status);
console.log("Response:");
console.log(JSON.stringify(publishData, null, 2));

if (!publishResponse.ok || !publishData.id) {
    console.error("\n❌ Publishing failed.");
    process.exit(1);
}

console.log("\n🎉 Instagram post published successfully!");
console.log("Post ID:", publishData.id);
