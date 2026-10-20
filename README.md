# Stratify.ai

Stratify AI is a personalized decision-thinking environment for career
guidance, roadmap generation, blind-spot detection, and realistic
decision-making.

## Accounts

Create an account with a name, password, and unique Stratify username. Usernames
are displayed as `username@stratifyai`; enter either the username or its full
handle when signing in. Usernames are 3–24 characters, use letters, numbers,
dots, underscores, or hyphens, and must begin and end with a letter or number.

Passwords must be 8–128 characters. Account creation immediately signs the user
in; no email address or verification service is required.

Existing accounts are retained when the database adds username support. Their
username is derived from the part of their previous email address before `@`;
if that value is invalid or already in use, a unique `member<ID>` username is
assigned.

## Decision conversations

After onboarding, the home screen is centered on private decision
conversations. New chats begin as in-progress items; use **Save decision** when
you are ready to name the project and mark it complete. Green circles are saved conversations,
red circles are still in progress, and the gold plus circle starts a new chat.
Conversations and messages are stored in the backend SQLite database and are
only available to their owner. You can delete a conversation from its list or
from inside the chat; deletion requires confirmation. Replies use the account's
onboarding answers and thinking profile as context. Details the user explicitly
shares about lasting preferences, background, goals, and constraints are saved
to the profile and can personalize future conversations. Inferred traits and
one-off decision details are not saved as personal memories. Saved context is
visible in the profile screen. User messages are stored even when AI generation
fails. New replies present a structured
decision map with viable paths, trade-offs, assumptions to check, and a
practical next step; when context is insufficient, Stratify asks for the
missing decision-changing detail instead of inventing alternatives. It tracks
what the user has already shared, reflects their stated criteria, and avoids
repeating questions. Existing conversations remain readable.

Configure `GROQ_API_KEY` in the backend environment to enable the primary AI
provider. An optional OpenAI-compatible TokenHarbor fallback can be configured
with `TOKENHARBOR_API_KEY`, `TOKENHARBOR_BASE_URL`, and `TOKENHARBOR_MODEL`.
If Groq and TokenHarbor fail, an optional NVIDIA NIM fallback can be configured
with `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, and `NVIDIA_MODEL`. Keep all provider
keys in the local `backend/.env`; never commit or share them. The fallback
base URLs must use HTTPS and model values must match the provider's model IDs.

## Deploying with Render and Vercel

The repository includes a Render Blueprint (`render.yaml`), a backend
dependency manifest (`backend/requirements.txt`), and Vercel's Vite settings
(`frontend/vercel.json`).

1. In Render, create a Blueprint from this repository and deploy the
   `stratify-api` service. The Blueprint uses the `backend` root directory and
   mounts a persistent disk at `/var/data` for SQLite. Persistent disks require
   Render's Starter (paid) web-service plan; do not remove the disk for a
   production deployment, or account and conversation data can be lost on
   restart or redeploy.
2. In the Render service's environment settings, set `FRONTEND_ORIGINS` to the
   exact Vercel origin, for example `https://your-project.vercel.app` (no path;
   comma-separate origins if needed). Add your `GROQ_API_KEY`. Add the optional
   TokenHarbor and NVIDIA keys and their model IDs if you want those fallbacks.
   Keep keys in the hosting provider's secret environment settings, never in
   source control.
3. In Vercel, import the same repository and set **Root Directory** to
   `frontend`. Add `VITE_API_URL` with the Render service URL, for example
   `https://stratify-api.onrender.com` (no trailing slash), then deploy or
   redeploy so Vite bakes the URL into the frontend build.
4. After both services are live, open the Vercel site, create an account, and
   verify signup, onboarding, chat, and a page refresh. The production frontend
   deliberately refuses to fall back to localhost when `VITE_API_URL` is
   missing.

The Render database starts empty; the ignored local `backend/stratify.db` is
not uploaded or copied to production. Back up the persistent disk before any
database migration or disk change.
