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
