const express = require("express");
const dotenv = require("dotenv");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

dotenv.config();

const app = express();

const PORT = process.env.PORT || 3001;

const CANVA_CLIENT_ID = process.env.CANVA_CLIENT_ID;
const CANVA_CLIENT_SECRET = process.env.CANVA_CLIENT_SECRET;
const CANVA_REDIRECT_URI = process.env.CANVA_REDIRECT_URI;

const TOKEN_FILE = path.join(__dirname, "canva_tokens.json");


// ============================================================
// MIDDLEWARE
// ============================================================

app.use(express.json());


// ============================================================
// TEMPORARY OAUTH SESSION STORAGE
// ============================================================

const oauthSessions = new Map();


// ============================================================
// TOKEN STORAGE
// ============================================================

function saveTokens(tokenData) {

    fs.writeFileSync(
        TOKEN_FILE,
        JSON.stringify(tokenData, null, 2),
        "utf8"
    );

    console.log("Canva tokens saved.");
}


function loadTokens() {

    if (!fs.existsSync(TOKEN_FILE)) {
        return null;
    }

    try {

        const data = fs.readFileSync(
            TOKEN_FILE,
            "utf8"
        );

        if (!data.trim()) {
            return null;
        }

        return JSON.parse(data);

    } catch (error) {

        console.error(
            "Could not read token file:",
            error.message
        );

        return null;
    }
}


// ============================================================
// GENERATE PKCE CODE VERIFIER
// ============================================================

function generateCodeVerifier() {

    return crypto
        .randomBytes(64)
        .toString("base64url");
}


// ============================================================
// GENERATE PKCE CODE CHALLENGE
// ============================================================

function generateCodeChallenge(codeVerifier) {

    return crypto
        .createHash("sha256")
        .update(codeVerifier)
        .digest("base64url");
}


// ============================================================
// GENERATE OAUTH STATE
// ============================================================

function generateState() {

    return crypto
        .randomBytes(32)
        .toString("base64url");
}


// ============================================================
// CANVA API HELPER
// ============================================================

async function canvaRequest(
    url,
    options = {},
    accessToken
) {

    const response = await fetch(
        url,
        {
            ...options,

            headers: {
                ...(options.headers || {}),

                "Authorization":
                    `Bearer ${accessToken}`,

                "Content-Type":
                    "application/json"
            }
        }
    );


    const text = await response.text();

    let data;

    try {

        data = JSON.parse(text);

    } catch {

        data = {
            raw: text
        };

    }


    return {
        response,
        data
    };
}


// ============================================================
// REFRESH CANVA ACCESS TOKEN
// ============================================================

async function refreshCanvaToken(refreshToken) {

    console.log(
        "Refreshing Canva access token..."
    );


    const credentials = Buffer
        .from(
            `${CANVA_CLIENT_ID}:${CANVA_CLIENT_SECRET}`
        )
        .toString("base64");


    const body = new URLSearchParams();

    body.append(
        "grant_type",
        "refresh_token"
    );

    body.append(
        "refresh_token",
        refreshToken
    );


    const response = await fetch(
        "https://api.canva.com/rest/v1/oauth/token",
        {
            method: "POST",

            headers: {

                "Authorization":
                    `Basic ${credentials}`,

                "Content-Type":
                    "application/x-www-form-urlencoded"
            },

            body
        }
    );


    const data =
        await response.json();


    if (!response.ok) {

        console.error(
            "Canva refresh token error:",
            data
        );

        throw new Error(
            `Canva token refresh failed: ${JSON.stringify(data)}`
        );
    }


    /*
     * Canva can return a new refresh token.
     * If it doesn't, keep the old one.
     */

    if (!data.refresh_token) {

        data.refresh_token =
            refreshToken;
    }


    saveTokens(data);


    console.log(
        "Canva access token refreshed."
    );


    return data;
}


// ============================================================
// GET VALID CANVA ACCESS TOKEN
// ============================================================

async function getAccessToken() {

    const tokens =
        loadTokens();


    if (!tokens) {

        throw new Error(
            "Canva is not connected. Please visit /auth/canva first."
        );
    }


    /*
     * expires_at is stored by us after OAuth.
     */

    const expiresAt =
        tokens.expires_at || 0;


    const now =
        Date.now();


    /*
     * Refresh 2 minutes before expiry.
     */

    const refreshBuffer =
        2 * 60 * 1000;


    if (
        tokens.access_token &&
        now < (expiresAt - refreshBuffer)
    ) {

        return tokens.access_token;
    }


    if (!tokens.refresh_token) {

        throw new Error(
            "Canva access token expired and no refresh token is available."
        );
    }


    const newTokens =
        await refreshCanvaToken(
            tokens.refresh_token
        );


    return newTokens.access_token;
}


// ============================================================
// HOME
// ============================================================

app.get("/", (req, res) => {

    res.send(`
        <!DOCTYPE html>

        <html>

        <head>

            <title>AI Marketing - Canva</title>

            <style>

                body {
                    font-family: Arial, sans-serif;
                    max-width: 900px;
                    margin: 50px auto;
                    padding: 20px;
                }

                button {
                    padding: 12px 20px;
                    margin: 5px;
                    cursor: pointer;
                }

                a {
                    text-decoration: none;
                }

            </style>

        </head>

        <body>

            <h1>AI Marketing × Canva</h1>

            <p>
                Canva integration backend is running.
            </p>


            <hr>


            <h2>Authentication</h2>

            <a href="/auth/canva">

                <button>
                    Connect Canva
                </button>

            </a>


            <h2>Canva APIs</h2>


            <a href="/canva/profile">

                <button>
                    Get Canva Profile
                </button>

            </a>


            <a href="/canva/brand-templates">

                <button>
                    Get Brand Templates
                </button>

            </a>


            <p>
                Backend:
                http://127.0.0.1:${PORT}
            </p>

        </body>

        </html>
    `);
});


// ============================================================
// START CANVA OAUTH
// ============================================================

app.get(
    "/auth/canva",
    (req, res) => {

        try {

            if (
                !CANVA_CLIENT_ID ||
                !CANVA_CLIENT_SECRET ||
                !CANVA_REDIRECT_URI
            ) {

                return res
                    .status(500)
                    .send(
                        "Canva credentials are missing from .env"
                    );
            }


            const codeVerifier =
                generateCodeVerifier();


            const codeChallenge =
                generateCodeChallenge(
                    codeVerifier
                );


            const state =
                generateState();


            /*
             * Save PKCE information.
             */

            oauthSessions.set(
                state,
                {
                    codeVerifier,

                    createdAt:
                        Date.now()
                }
            );


            /*
             * Automatically remove old OAuth sessions.
             */

            setTimeout(
                () => {

                    oauthSessions.delete(
                        state
                    );

                },
                10 * 60 * 1000
            );


            /*
             * These scopes match the scopes
             * configured in your Canva app.
             */

            const scopes = [

                "app:read",

                "app:write",

                "asset:read",

                "asset:write",

                "brandtemplate:content:read",

                "brandtemplate:meta:read",

                "design:content:read",

                "design:content:write",

                "design:meta:read",

                "profile:read"

            ].join(" ");


            const authorizationURL =
                new URL(
                    "https://www.canva.com/api/oauth/authorize"
                );


            authorizationURL.searchParams.set(
                "code_challenge",
                codeChallenge
            );


            authorizationURL.searchParams.set(
                "code_challenge_method",
                "S256"
            );


            authorizationURL.searchParams.set(
                "client_id",
                CANVA_CLIENT_ID
            );


            authorizationURL.searchParams.set(
                "redirect_uri",
                CANVA_REDIRECT_URI
            );


            authorizationURL.searchParams.set(
                "response_type",
                "code"
            );


            authorizationURL.searchParams.set(
                "scope",
                scopes
            );


            authorizationURL.searchParams.set(
                "state",
                state
            );


            console.log(
                "\nRedirecting to Canva...\n"
            );


            res.redirect(
                authorizationURL.toString()
            );

        } catch (error) {

            console.error(
                error
            );

            res.status(500).send(
                "Could not start Canva OAuth."
            );
        }
    }
);


// ============================================================
// CANVA OAUTH CALLBACK
// ============================================================

app.get(
    "/oauth/redirect",
    async (req, res) => {

        try {

            const {
                code,
                state,
                error,
                error_description
            } = req.query;


            /*
             * User rejected authorization.
             */

            if (error) {

                return res
                    .status(400)
                    .send(`
                        <h2>Canva Authorization Failed</h2>

                        <p>
                            ${error}
                        </p>

                        <p>
                            ${error_description || ""}
                        </p>
                    `);
            }


            /*
             * Verify authorization code.
             */

            if (!code) {

                return res
                    .status(400)
                    .send(
                        "Authorization code was not received."
                    );
            }


            /*
             * Verify OAuth state.
             */

            if (!state) {

                return res
                    .status(400)
                    .send(
                        "OAuth state was not received."
                    );
            }


            const session =
                oauthSessions.get(
                    state
                );


            if (!session) {

                return res
                    .status(400)
                    .send(
                        "Invalid or expired OAuth state."
                    );
            }


            const codeVerifier =
                session.codeVerifier;


            /*
             * State should only be used once.
             */

            oauthSessions.delete(
                state
            );


            /*
             * Client authentication.
             */

            const credentials =
                Buffer
                    .from(
                        `${CANVA_CLIENT_ID}:${CANVA_CLIENT_SECRET}`
                    )
                    .toString("base64");


            const body =
                new URLSearchParams();


            body.append(
                "grant_type",
                "authorization_code"
            );


            body.append(
                "code",
                code
            );


            body.append(
                "code_verifier",
                codeVerifier
            );


            body.append(
                "redirect_uri",
                CANVA_REDIRECT_URI
            );


            /*
             * Exchange authorization code
             * for access + refresh token.
             */

            const tokenResponse =
                await fetch(
                    "https://api.canva.com/rest/v1/oauth/token",
                    {
                        method: "POST",

                        headers: {

                            "Authorization":
                                `Basic ${credentials}`,

                            "Content-Type":
                                "application/x-www-form-urlencoded"
                        },

                        body
                    }
                );


            const tokenData =
                await tokenResponse.json();


            if (!tokenResponse.ok) {

                console.error(
                    "Canva token error:",
                    tokenData
                );


                return res
                    .status(
                        tokenResponse.status
                    )
                    .send(`
                        <h2>
                            Canva Token Exchange Failed
                        </h2>

                        <pre>
${JSON.stringify(
    tokenData,
    null,
    2
)}
                        </pre>
                    `);
            }


            /*
             * Calculate expiry timestamp.
             */

            const expiresIn =
                Number(
                    tokenData.expires_in || 14400
                );


            tokenData.expires_at =
                Date.now() +
                expiresIn * 1000;


            /*
             * Save tokens.
             */

            saveTokens(
                tokenData
            );


            console.log(
                "\nCanva OAuth successful!"
            );


            console.log(
                "Token type:",
                tokenData.token_type
            );


            console.log(
                "Expires in:",
                tokenData.expires_in,
                "seconds"
            );


            console.log(
                "Granted scopes:",
                tokenData.scope
            );


            /*
             * Never display the actual token.
             */

            res.send(`
                <!DOCTYPE html>

                <html>

                <head>

                    <title>
                        Canva Connected
                    </title>

                    <style>

                        body {
                            font-family: Arial;
                            max-width: 700px;
                            margin: 80px auto;
                            text-align: center;
                        }

                        .success {
                            font-size: 22px;
                            color: green;
                        }

                    </style>

                </head>

                <body>

                    <h1>
                        Canva Connected Successfully! ✅
                    </h1>

                    <p>
                        Your AI Marketing application
                        is authorized to use Canva.
                    </p>

                    <p>
                        <strong>
                            Token type:
                        </strong>

                        ${tokenData.token_type}
                    </p>

                    <p>
                        <strong>
                            Expires in:
                        </strong>

                        ${tokenData.expires_in}
                        seconds
                    </p>

                    <p>
                        <strong>
                            Granted scopes:
                        </strong>

                        ${tokenData.scope || ""}
                    </p>

                    <hr>

                    <p class="success">
                        Tokens saved securely on the backend.
                    </p>

                    <br>

                    <a href="/">
                        Back to AI Marketing
                    </a>

                </body>

                </html>
            `);

        } catch (error) {

            console.error(
                "OAuth callback error:",
                error
            );


            res.status(500).send(
                "Internal server error during Canva OAuth."
            );
        }
    }
);


// ============================================================
// GET CANVA PROFILE
// ============================================================

app.get(
    "/canva/profile",
    async (req, res) => {

        try {

            const accessToken =
                await getAccessToken();


            const {
                response,
                data
            } = await canvaRequest(
                "https://api.canva.com/rest/v1/users/me/profile",
                {
                    method: "GET"
                },
                accessToken
            );


            if (!response.ok) {

                return res
                    .status(response.status)
                    .json(data);
            }


            res.json(data);

        } catch (error) {

            console.error(
                error
            );


            res.status(500).json({
                error:
                    error.message
            });
        }
    }
);


// ============================================================
// LIST BRAND TEMPLATES
// ============================================================

app.get(
    "/canva/brand-templates",
    async (req, res) => {

        try {

            const accessToken =
                await getAccessToken();


            /*
             * Optional query:
             *
             * /canva/brand-templates?query=coffee
             */

            const query =
                req.query.query || "";


            const limit =
                req.query.limit || "100";


            /*
             * dataset=non_empty means:
             *
             * return templates that have
             * autofillable data fields.
             */

            const url =
                new URL(
                    "https://api.canva.com/rest/v1/brand-templates"
                );


            url.searchParams.set(
                "limit",
                limit
            );


            url.searchParams.set(
                "dataset",
                "non_empty"
            );


            if (query) {

                url.searchParams.set(
                    "query",
                    query
                );
            }


            const {
                response,
                data
            } = await canvaRequest(
                url.toString(),
                {
                    method: "GET"
                },
                accessToken
            );


            if (!response.ok) {

                return res
                    .status(response.status)
                    .json(data);
            }


            res.json(data);

        } catch (error) {

            console.error(
                "Brand template error:",
                error
            );


            res.status(500).json({
                error:
                    error.message
            });
        }
    }
);


// ============================================================
// GET BRAND TEMPLATE DATASET
// ============================================================

app.get(
    "/canva/brand-templates/:brandTemplateId/dataset",
    async (req, res) => {

        try {

            const {
                brandTemplateId
            } = req.params;


            if (!brandTemplateId) {

                return res
                    .status(400)
                    .json({
                        error:
                            "brandTemplateId is required"
                    });
            }


            const accessToken =
                await getAccessToken();


            const url =
                `https://api.canva.com/rest/v1/brand-templates/${encodeURIComponent(
                    brandTemplateId
                )}/dataset`;


            const {
                response,
                data
            } = await canvaRequest(
                url,
                {
                    method: "GET"
                },
                accessToken
            );


            if (!response.ok) {

                return res
                    .status(response.status)
                    .json(data);
            }


            res.json(data);

        } catch (error) {

            console.error(
                "Dataset error:",
                error
            );


            res.status(500).json({
                error:
                    error.message
            });
        }
    }
);


// ============================================================
// GET BRAND TEMPLATE METADATA
// ============================================================

app.get(
    "/canva/brand-templates/:brandTemplateId",
    async (req, res) => {

        try {

            const {
                brandTemplateId
            } = req.params;


            const accessToken =
                await getAccessToken();


            const url =
                `https://api.canva.com/rest/v1/brand-templates/${encodeURIComponent(
                    brandTemplateId
                )}`;


            const {
                response,
                data
            } = await canvaRequest(
                url,
                {
                    method: "GET"
                },
                accessToken
            );


            if (!response.ok) {

                return res
                    .status(response.status)
                    .json(data);
            }


            res.json(data);

        } catch (error) {

            console.error(
                "Brand template metadata error:",
                error
            );


            res.status(500).json({
                error:
                    error.message
            });
        }
    }
);


// ============================================================
// CREATE AUTOFILL JOB
// ============================================================

app.post(
    "/canva/autofill",
    async (req, res) => {

        try {

            const {
                brand_template_id,
                data
            } = req.body;


            if (!brand_template_id) {

                return res
                    .status(400)
                    .json({
                        error:
                            "brand_template_id is required"
                    });
            }


            if (!data) {

                return res
                    .status(400)
                    .json({
                        error:
                            "data is required"
                    });
            }


            const accessToken =
                await getAccessToken();


            /*
             * Canva Autofill API
             */

            const requestBody = {

                type:
                    "create_from_brand_template",

                brand_template_id:
                    brand_template_id,

                data:
                    data
            };


            const {
                response,
                data: result
            } = await canvaRequest(
                "https://api.canva.com/rest/v1/autofills",
                {
                    method: "POST",

                    body:
                        JSON.stringify(
                            requestBody
                        )
                },
                accessToken
            );


            if (!response.ok) {

                return res
                    .status(response.status)
                    .json(result);
            }


            res.json(result);

        } catch (error) {

            console.error(
                "Autofill error:",
                error
            );


            res.status(500).json({
                error:
                    error.message
            });
        }
    }
);


// ============================================================
// GET AUTOFILL JOB
// ============================================================

app.get(
    "/canva/autofill/:jobId",
    async (req, res) => {

        try {

            const {
                jobId
            } = req.params;


            const accessToken =
                await getAccessToken();


            const url =
                `https://api.canva.com/rest/v1/autofills/${encodeURIComponent(
                    jobId
                )}`;


            const {
                response,
                data
            } = await canvaRequest(
                url,
                {
                    method: "GET"
                },
                accessToken
            );


            if (!response.ok) {

                return res
                    .status(response.status)
                    .json(data);
            }


            res.json(data);

        } catch (error) {

            console.error(
                "Autofill job error:",
                error
            );


            res.status(500).json({
                error:
                    error.message
            });
        }
    }
);


// ============================================================
// TOKEN STATUS
// ============================================================

app.get(
    "/canva/status",
    (req, res) => {

        const tokens =
            loadTokens();


        if (!tokens) {

            return res.json({
                connected:
                    false
            });
        }


        const expiresAt =
            tokens.expires_at || null;


        const remaining =
            expiresAt
                ? Math.max(
                    0,
                    expiresAt -
                    Date.now()
                )
                : null;


        res.json({

            connected:
                true,

            token_type:
                tokens.token_type || null,

            expires_at:
                expiresAt,

            expires_in_ms:
                remaining,

            scope:
                tokens.scope || null,

            has_refresh_token:
                Boolean(
                    tokens.refresh_token
                )

        });
    }
);


// ============================================================
// START SERVER
// ============================================================

app.listen(
    PORT,
    "127.0.0.1",
    () => {

        console.log("");
        console.log(
            "======================================"
        );

        console.log(
            "AI MARKETING CANVA BACKEND"
        );

        console.log(
            "======================================"
        );

        console.log("");

        console.log(
            `Server: http://127.0.0.1:${PORT}`
        );

        console.log(
            `OAuth:  http://127.0.0.1:${PORT}/auth/canva`
        );

        console.log(
            `Templates: http://127.0.0.1:${PORT}/canva/brand-templates`
        );

        console.log("");

    }
);