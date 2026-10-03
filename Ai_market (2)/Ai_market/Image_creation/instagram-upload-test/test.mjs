import "dotenv/config";

const token = process.env.INSTAGRAM_ACCESS_TOKEN;

console.log("Token loaded:", !!token);
console.log("Token length:", token?.length);
console.log("Token starts with:", token?.slice(0, 5));

if (!token) {
    console.error("❌ Token was not loaded");
    process.exit(1);
}

const url =
    `https://graph.instagram.com/me` +
    `?fields=user_id,username` +
    `&access_token=${encodeURIComponent(token)}`;

const response = await fetch(url);

console.log("\nHTTP Status:", response.status);

const data = await response.json();

console.log("Response:");
console.log(JSON.stringify(data, null, 2));