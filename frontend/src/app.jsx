import { useEffect, useRef, useState } from "react";
import Welcome from "./pages/welcome";
import "./App.css";

const API_URL = (
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

const TOKEN_KEY = "stratify_access_token";

async function apiRequest(path, { token, ...options } = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((issue) => issue.msg).join(" ")
      : data.detail;
    const error = new Error(
      typeof detail === "string" && detail
        ? detail
        : "Something went wrong. Please try again."
    );

    error.status = response.status;
    throw error;
  }

  return data;
}

function DecisionMap({
  analysis,
  messageId,
  onNextStep,
  onSubmitFollowUp,
  busy,
}) {
  const [answerDraft, setAnswerDraft] = useState("");
  const [answering, setAnswering] = useState(false);
  const paths = Array.isArray(analysis.paths) ? analysis.paths : [];
  const knownFacts = Array.isArray(analysis.known_facts)
    ? analysis.known_facts
    : [];
  const decisionCriteria = Array.isArray(analysis.decision_criteria)
    ? analysis.decision_criteria
    : [];
  const criticalUnknowns = Array.isArray(analysis.critical_unknowns)
    ? analysis.critical_unknowns
    : [];
  const tradeoffs = Array.isArray(analysis.tradeoffs)
    ? analysis.tradeoffs
    : [];
  const blindSpots = Array.isArray(analysis.blind_spots)
    ? analysis.blind_spots
    : [];

  async function submitFollowUp(event) {
    event.preventDefault();
    const answer = answerDraft.trim();
    if (!answer || busy || answering) {
      return;
    }

    setAnswering(true);
    const sent = await onSubmitFollowUp(messageId, answer);
    if (sent) {
      setAnswerDraft("");
    }
    setAnswering(false);
  }

  return (
    <section
      className={`decision-map ${analysis.follow_up
        ? analysis.follow_up_answer
          ? "has-answered-question"
          : "has-pending-question"
        : ""}`}
      aria-label="Decision map"
    >
      <p className="decision-map-stage">
        {analysis.stage === "clarify"
          ? "CLARIFYING BEFORE COMPARING"
          : "DECISION MAP"}
      </p>
      {analysis.decision_frame && (
        <h2 className="decision-map-frame">{analysis.decision_frame}</h2>
      )}
      <p className="decision-map-summary">{analysis.summary}</p>

      {(knownFacts.length > 0 ||
        decisionCriteria.length > 0 ||
        criticalUnknowns.length > 0) && (
        <div className="decision-map-lenses">
          {knownFacts.length > 0 && (
            <section aria-labelledby="decision-known-title">
              <h3 id="decision-known-title">What you’ve told me</h3>
              <ul>
                {knownFacts.map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
            </section>
          )}
          {decisionCriteria.length > 0 && (
            <section aria-labelledby="decision-criteria-title">
              <h3 id="decision-criteria-title">What matters to you</h3>
              <ul>
                {decisionCriteria.map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
            </section>
          )}
          {criticalUnknowns.length > 0 && (
            <section aria-labelledby="decision-unknown-title">
              <h3 id="decision-unknown-title">What could change the choice</h3>
              <ul>
                {criticalUnknowns.map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {paths.length > 0 ? (
        <div className="decision-flow">
          <div className="decision-flow-origin">
            <span>THE SITUATION</span>
            <strong>Possible paths</strong>
          </div>
          <div className="decision-flow-paths">
            {paths.map((path, index) => (
              <article className="decision-path" key={`${path.name}-${index}`}>
                <span className="decision-path-index">
                  PATH {String(index + 1).padStart(2, "0")}
                </span>
                <h3>{path.name}</h3>
                {path.upside && (
                  <div>
                    <span className="decision-detail-label">UPSIDE</span>
                    <p>{path.upside}</p>
                  </div>
                )}
                {path.downside && (
                  <div>
                    <span className="decision-detail-label">COST TO WEIGH</span>
                    <p>{path.downside}</p>
                  </div>
                )}
                {path.fit && (
                  <div>
                    <span className="decision-detail-label">MAY FIT IF</span>
                    <p>{path.fit}</p>
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>
      ) : (
        <div className="decision-map-open-question">
          <span>BEFORE COMPARING PATHS</span>
          <p>There is still useful context to uncover.</p>
        </div>
      )}

      {(tradeoffs.length > 0 || blindSpots.length > 0) && (
        <div className="decision-map-lenses">
          {tradeoffs.length > 0 && (
            <section aria-labelledby="decision-tradeoffs-title">
              <h3 id="decision-tradeoffs-title">Tensions to weigh</h3>
              <ul>
                {tradeoffs.map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
            </section>
          )}
          {blindSpots.length > 0 && (
            <section aria-labelledby="decision-blindspots-title">
              <h3 id="decision-blindspots-title">Worth checking</h3>
              <ul>
                {blindSpots.map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      <div className="decision-map-next">
        <span>ONE USEFUL NEXT STEP</span>
        <p>{analysis.next_step}</p>
        <button
          type="button"
          className="decision-next-step-button"
          onClick={() => onNextStep(analysis.next_step)}
          disabled={busy}
        >
          {busy ? "Sending…" : "Do this next ↗"}
        </button>
      </div>
      {analysis.follow_up && (
        <section
          className={`decision-map-question ${
            analysis.follow_up_answer ? "answered" : "pending"
          }`}
          aria-labelledby={`follow-up-${messageId}`}
        >
          <span>
            {analysis.follow_up_answer
              ? "ANSWER RECEIVED"
              : analysis.stage === "clarify"
                ? "YOUR ANSWER NEEDED TO CONTINUE"
                : "OPTIONAL QUESTION TO REFINE THIS"}
          </span>
          <h3 id={`follow-up-${messageId}`}>{analysis.follow_up}</h3>
          {analysis.follow_up_answer ? (
            <p className="decision-follow-up-answer">
              {analysis.follow_up_answer}
            </p>
          ) : (
            <form
              className="decision-follow-up-form"
              onSubmit={submitFollowUp}
            >
              <textarea
                aria-label="Answer Stratify's question"
                placeholder="Write your answer here…"
                rows={2}
                maxLength={5000}
                value={answerDraft}
                onChange={(event) => setAnswerDraft(event.target.value)}
                disabled={busy || answering}
                required
              />
              <button
                type="submit"
                disabled={busy || answering || !answerDraft.trim()}
              >
                {answering ? "Sending…" : "Submit answer ↗"}
              </button>
            </form>
          )}
        </section>
      )}
    </section>
  );
}

function ConversationDialog({
  saving,
  deleting,
  title,
  error,
  busy,
  onTitleChange,
  onCancel,
  onSubmit,
}) {
  if (!saving && !deleting) {
    return null;
  }

  return (
    <div className="conversation-dialog-backdrop">
      <form
        className="conversation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="conversation-dialog-title"
        onSubmit={onSubmit}
      >
        <p className="app-eyebrow">
          {saving ? "KEEP THIS DECISION" : "CONVERSATION MANAGEMENT"}
        </p>
        <h2 id="conversation-dialog-title">
          {saving ? "Name this decision" : "Delete this decision?"}
        </h2>
        {saving ? (
          <>
            <p>
              Give this project a name that will be easy to find in your
              conversations.
            </p>
            <label htmlFor="decision-project-name">Decision name</label>
            <input
              id="decision-project-name"
              autoFocus
              type="text"
              value={title}
              onChange={(event) => onTitleChange(event.target.value)}
              maxLength={80}
              required
            />
          </>
        ) : (
          <p>
            “{deleting.title}” and its messages will be permanently removed.
            This can’t be undone.
          </p>
        )}
        {error && <p className="app-error" role="alert">{error}</p>}
        <div className="conversation-dialog-actions">
          <button
            className="conversation-dialog-cancel"
            type="button"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            className={deleting ? "conversation-dialog-delete" : "finish-chat-button"}
            type="submit"
            disabled={busy || (saving && !title.trim())}
          >
            {busy
              ? "Please wait…"
              : saving
                ? "Name & save"
                : "Delete decision"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function App() {
  const [screen, setScreen] = useState("welcome");
  const [authMode, setAuthMode] = useState("signup");
  const [token, setToken] = useState(
    () => localStorage.getItem(TOKEN_KEY) || ""
  );
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [question, setQuestion] = useState(null);
  const [answer, setAnswer] = useState("");
  const [progress, setProgress] = useState({
    completed_questions: 0,
    total_questions: 12,
    completion_percent: 0,
  });
  const [profile, setProfile] = useState(null);
  const [user, setUser] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [chatDraft, setChatDraft] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [decisionTitleDraft, setDecisionTitleDraft] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [homeError, setHomeError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const chatEndRef = useRef(null);

  useEffect(() => {
    if (screen === "chat") {
      chatEndRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "end",
      });
    }
  }, [screen, messages, chatBusy]);

  function resetMessages() {
    setError("");
  }

  function syncProgress(response) {
    const nextProgress = response?.progress;
    if (
      nextProgress &&
      Number.isFinite(nextProgress.completed_questions) &&
      Number.isFinite(nextProgress.total_questions) &&
      Number.isFinite(nextProgress.completion_percent)
    ) {
      setProgress(nextProgress);
    }
  }

  async function loadHome(accessToken) {
    const [currentUser, onboarding, chatList] = await Promise.all([
      apiRequest("/auth/me", { token: accessToken }),
      apiRequest("/onboarding/profile", { token: accessToken }),
      apiRequest("/chat/conversations", { token: accessToken }),
    ]);
    setUser(currentUser);
    setProfile(onboarding.profile || {});
    setConversations(chatList.conversations || []);
    setActiveConversation(null);
    setMessages([]);
    setHomeError("");
    setScreen("home");
  }

  async function startOnboarding(accessToken) {
    setBusy(true);
    resetMessages();

    try {
      const result = await apiRequest("/onboarding/start", {
        method: "POST",
        token: accessToken,
      });

      setSessionId(result.session_id);
      setQuestion(result.question);
      setAnswer("");
      syncProgress(result);
      setScreen("onboarding");
    } catch (err) {
      setScreen("auth");
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function enterApp(accessToken = token) {
    setBusy(true);
    resetMessages();

    try {
      const result = await apiRequest("/onboarding/profile", {
        token: accessToken,
      });

      const latestSession = result.sessions?.[0];

      if (
        latestSession &&
        ["in_progress", "active"].includes(latestSession.status)
      ) {
        const id = latestSession.session_id;
        setSessionId(id);

        const next = await apiRequest(
          `/onboarding/next?session_id=${encodeURIComponent(id)}`,
          { token: accessToken }
        );

        if (next.status === "complete") {
          await loadHome(accessToken);
        } else {
          setQuestion(next.question);
          setAnswer("");
          syncProgress(next);
          setScreen("onboarding");
        }
      } else if (
        latestSession &&
        ["completed", "complete"].includes(latestSession.status)
      ) {
        await loadHome(accessToken);
      } else {
        setScreen("onboarding");
        await startOnboarding(accessToken);
      }
    } catch (err) {
      if (err.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        setToken("");
        setScreen("auth");
        setError("Please sign in again to continue.");
      } else {
        setScreen("auth");
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleAuth(event) {
    event.preventDefault();
    resetMessages();
    setBusy(true);

    try {
      const result = await apiRequest(
        authMode === "signup" ? "/auth/signup" : "/auth/login",
        {
          method: "POST",
          body: JSON.stringify({
            username: `${username.trim()}@stratifyai`,
            ...(authMode === "signup" ? { name: name.trim() } : {}),
            password,
          }),
        }
      );

      localStorage.setItem(TOKEN_KEY, result.access_token);
      setToken(result.access_token);
      setPassword("");

      if (authMode === "signup") {
        await startOnboarding(result.access_token);
      } else {
        await enterApp(result.access_token);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer(event) {
    event.preventDefault();

    if (!question || !answer.trim()) {
      return;
    }

    setBusy(true);
    resetMessages();

    try {
      let result;

      try {
        result = await apiRequest("/onboarding/answer", {
          method: "POST",
          token,
          body: JSON.stringify({
            session_id: sessionId,
            question_id: question.id,
            answer: answer.trim(),
          }),
        });
      } catch (err) {
        // The backend may save an answer before AI generation fails.
        if (err.status !== 502) {
          throw err;
        }

        result = await apiRequest(
          `/onboarding/next?session_id=${encodeURIComponent(sessionId)}`,
          { token }
        );
      }

      if (result.status === "complete") {
        syncProgress(result);
        await loadHome(token);
        return;
      }

      syncProgress(result);
      if (result.question) {
        setQuestion(result.question);
        setAnswer("");
      } else {
        const next = await apiRequest(
          `/onboarding/next?session_id=${encodeURIComponent(sessionId)}`,
          { token }
        );

        if (next.status === "complete") {
          await loadHome(token);
        } else {
          syncProgress(next);
          setQuestion(next.question);
          setAnswer("");
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleWelcomeEnter() {
    resetMessages();

    if (token) {
      setScreen("checking");
      await enterApp();
    } else {
      setScreen("auth");
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setSessionId("");
    setQuestion(null);
    setProgress({
      completed_questions: 0,
      total_questions: 12,
      completion_percent: 0,
    });
    setProfile(null);
    setUser(null);
    setConversations([]);
    setActiveConversation(null);
    setMessages([]);
    setChatDraft("");
    setHomeError("");
    setScreen("welcome");
    resetMessages();
  }

  async function createConversation() {
    setChatBusy(true);
    setHomeError("");
    try {
      const conversation = await apiRequest("/chat/conversations", {
        method: "POST",
        token,
        body: JSON.stringify({}),
      });
      setConversations((current) => [conversation, ...current]);
      setActiveConversation(conversation);
      setMessages([]);
      setChatDraft("");
      setHomeError("");
      setScreen("chat");
    } catch (err) {
      setHomeError(err.message);
    } finally {
      setChatBusy(false);
    }
  }

  async function openConversation(conversation) {
    setChatBusy(true);
    setHomeError("");
    try {
      const detail = await apiRequest(
        `/chat/conversations/${encodeURIComponent(conversation.id)}`,
        { token }
      );
      setActiveConversation(detail);
      setMessages(detail.messages || []);
      setChatDraft("");
      setScreen("chat");
    } catch (err) {
      setHomeError(err.message);
    } finally {
      setChatBusy(false);
    }
  }

  async function sendChatContent(content, answerToMessageId = null) {
    if (!content || !activeConversation || chatBusy) {
      return false;
    }

    setChatBusy(true);
    setHomeError("");
    try {
      const result = await apiRequest(
        `/chat/conversations/${encodeURIComponent(activeConversation.id)}/messages`,
        {
          method: "POST",
          token,
          body: JSON.stringify({
            content,
            ...(answerToMessageId
              ? { answer_to_message_id: answerToMessageId }
              : {}),
          }),
        }
      );
      setMessages((current) => [
        ...current.map((message) =>
          message.id === answerToMessageId
            ? {
                ...message,
                analysis: {
                  ...message.analysis,
                  follow_up_answer: content,
                },
              }
            : message
        ),
        ...result.messages,
      ]);
      setActiveConversation((current) => ({
        ...current,
        title: result.title,
        status: result.status,
      }));
      if (result.profile) {
        setProfile(result.profile);
      }
      setConversations((current) => {
        const updated = current.map((item) =>
          item.id === result.id
            ? {
                ...item,
                title: result.title,
                status: result.status,
                updated_at: result.updated_at,
                last_message:
                  result.messages[result.messages.length - 1].content,
                message_count: (item.message_count || 0) + 2,
              }
            : item
        );
        return updated.sort(
          (first, second) =>
            Date.parse(second.updated_at || "") -
            Date.parse(first.updated_at || "")
        );
      });
      setChatDraft("");
      return true;
    } catch (err) {
      setHomeError(err.message);
      return false;
    } finally {
      setChatBusy(false);
    }
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    const content = chatDraft.trim();
    await sendChatContent(content);
  }

  async function sendSuggestedNextStep(step) {
    if (!step?.trim()) {
      return;
    }
    const content = `Do this next: ${step.trim()}`;
    await sendChatContent(content);
  }

  async function sendFollowUpAnswer(messageId, answer) {
    return sendChatContent(answer, messageId);
  }

  function beginSavingConversation() {
    if (!activeConversation || chatBusy || messages.length === 0) {
      return;
    }
    setDecisionTitleDraft(activeConversation.title || "");
    setHomeError("");
    setSaveDialogOpen(true);
  }

  async function completeConversation(event) {
    event.preventDefault();
    if (!activeConversation || chatBusy) {
      return;
    }
    const title = decisionTitleDraft.trim();
    if (!title) {
      return;
    }
    setChatBusy(true);
    setHomeError("");
    try {
      const result = await apiRequest(
        `/chat/conversations/${encodeURIComponent(activeConversation.id)}/complete`,
        {
          method: "PATCH",
          token,
          body: JSON.stringify({ title }),
        }
      );
      setActiveConversation((current) => ({
        ...current,
        title: result.title,
        status: result.status,
      }));
      setConversations((current) =>
        current.map((item) =>
          item.id === result.id
            ? {
                ...item,
                title: result.title,
                status: result.status,
                updated_at: result.updated_at,
              }
            : item
        )
      );
      setSaveDialogOpen(false);
    } catch (err) {
      setHomeError(err.message);
    } finally {
      setChatBusy(false);
    }
  }

  async function deleteConversation(event) {
    event.preventDefault();
    if (!deleteTarget || chatBusy) {
      return;
    }

    setChatBusy(true);
    setHomeError("");
    try {
      await apiRequest(
        `/chat/conversations/${encodeURIComponent(deleteTarget.id)}`,
        { method: "DELETE", token }
      );
      setConversations((current) =>
        current.filter((item) => item.id !== deleteTarget.id)
      );
      if (activeConversation?.id === deleteTarget.id) {
        setActiveConversation(null);
        setMessages([]);
        setChatDraft("");
        setScreen("home");
      }
      setDeleteTarget(null);
    } catch (err) {
      setHomeError(err.message);
    } finally {
      setChatBusy(false);
    }
  }

  function cancelConversationDialog() {
    setSaveDialogOpen(false);
    setDeleteTarget(null);
    setHomeError("");
  }

  if (screen === "welcome") {
    return <Welcome onEnter={handleWelcomeEnter} />;
  }

  if (screen === "checking") {
    return (
      <main className="app-shell">
        <p className="app-muted">Preparing your space...</p>
        {error && <p className="app-error">{error}</p>}
      </main>
    );
  }

  if (screen === "auth") {
    return (
      <main className="app-shell">
        <section className="app-panel" key={authMode}>
          <button
            className="text-button"
            onClick={() => {
              setScreen("welcome");
              resetMessages();
            }}
          >
            ← Back
          </button>

          <p className="app-eyebrow">STRATIFY AI · YOUR SPACE</p>

          <h1>
            {authMode === "signup"
              ? "Begin with clarity."
              : "Welcome back."}
          </h1>

          <p className="app-muted">
            {authMode === "signup"
              ? "Choose a name and private Stratify username to build your thinking profile."
              : "Sign in to continue your journey."}
          </p>

          <form className="app-form" onSubmit={handleAuth}>
            {authMode === "signup" && (
              <>
                <label htmlFor="name">Your name</label>
                <input
                  id="name"
                  type="text"
                  autoComplete="name"
                  autoCapitalize="words"
                  maxLength={80}
                  required
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </>
            )}

            <label htmlFor="username">Username</label>
            <div className="username-field">
              <input
                id="username"
                type="text"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck="false"
                minLength={3}
                maxLength={24}
                pattern="[A-Za-z0-9][A-Za-z0-9._\-]{1,22}[A-Za-z0-9]"
                title="Use 3-24 letters, numbers, dots, underscores or hyphens; start and end with a letter or number."
                placeholder="yourname"
                required
                value={username}
                onChange={(event) =>
                  setUsername(event.target.value.replace(/@stratifyai$/i, ""))
                }
              />
              <span aria-hidden="true">@stratifyai</span>
            </div>
            <p className="username-hint">
              3–24 characters · letters, numbers, dots, underscores, or hyphens
            </p>

            <label htmlFor="password">Password</label>

            <input
              id="password"
              type="password"
              autoComplete={
                authMode === "signup"
                  ? "new-password"
                  : "current-password"
              }
              minLength={8}
              maxLength={128}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />

            {error && (
              <p className="app-error" role="alert">
                {error}
              </p>
            )}

            <button
              className="primary-button"
              disabled={busy}
              type="submit"
            >
              {busy
                ? "Please wait..."
                : authMode === "signup"
                  ? "Create account ↗"
                  : "Sign in ↗"}
            </button>
          </form>

          <p className="app-switch">
            {authMode === "signup"
              ? "Already have an account?"
              : "New to Stratify?"}{" "}

            <button
              className="text-button"
              onClick={() => {
                setAuthMode(
                  authMode === "signup" ? "login" : "signup"
                );
                setPassword("");
                resetMessages();
              }}
            >
              {authMode === "signup" ? "Sign in" : "Create account"}
            </button>
          </p>
        </section>
      </main>
    );
  }

  if (screen === "onboarding") {
    return (
      <main className="app-shell">
        <section className="app-panel onboarding-panel">
          <div className="onboarding-topline">
            <div>
              <p className="app-eyebrow">
                YOUR PERSONALIZED STARTING POINT
              </p>
              <p className="progress-caption">A PROFILE THAT ADAPTS TO YOU</p>
            </div>
            <div
              className="onboarding-progress"
              role="progressbar"
              aria-label={`${progress.completion_percent}% complete; ${progress.completed_questions} of ${progress.total_questions} questions answered`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress.completion_percent}
            >
              <svg viewBox="0 0 64 64" aria-hidden="true">
                <circle className="progress-track" cx="32" cy="32" r="27" />
                <circle
                  className="progress-value"
                  cx="32"
                  cy="32"
                  r="27"
                  style={{
                    strokeDashoffset:
                      169.65 * (1 - progress.completion_percent / 100),
                  }}
                />
              </svg>
              <span>{progress.completion_percent}%</span>
            </div>
          </div>

          <h1>Let's understand your world.</h1>

          <p className="app-muted">
            One question at a time. Your answers shape what we explore next.
            The assessment can adapt and finish before its 12-question limit.
          </p>

          {question ? (
            <form
              className="app-form onboarding-question"
              key={question.id}
              onSubmit={submitAnswer}
            >
              <p className="question-count">
                QUESTION {Math.min(
                  progress.completed_questions + 1,
                  progress.total_questions
                )}{" "}
                · UP TO {progress.total_questions}
              </p>

              <h2 className="question-title">{question.text}</h2>

              {question.type === "single_choice" ? (
                <div className="choice-list">
                  {(question.options || []).map((option, index) => (
                    <button
                      className={`choice-button ${
                        answer === option.value ? "selected" : ""
                      }`}
                      type="button"
                      key={option.value}
                      style={{ animationDelay: `${90 + index * 65}ms` }}
                      onClick={() => setAnswer(option.value)}
                    >
                      <span>{option.label}</span>
                      <span aria-hidden="true">
                        {answer === option.value ? "✓" : "↗"}
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <input
                  aria-label={question.text}
                  type={
                    question.type === "number" ? "number" : "text"
                  }
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  required
                  autoFocus
                />
              )}

              {error && (
                <p className="app-error" role="alert">
                  {error}
                </p>
              )}

              <button
                className="primary-button"
                type="submit"
                disabled={busy || !answer.trim()}
              >
                {busy ? "Thinking..." : "Continue ↗"}
              </button>
            </form>
          ) : (
            <p className="app-muted">Loading your next question...</p>
          )}

          <button className="text-button" onClick={logout}>
            Sign out
          </button>
        </section>
      </main>
    );
  }

  if (screen === "chat") {
    return (
      <main className="app-shell chat-page-shell">
        <header className="chat-page-header">
          <button
            className="chat-back-button"
            onClick={() => setScreen("home")}
            aria-label="Back to conversations"
          >
            <span aria-hidden="true">←</span>
            <span>All conversations</span>
          </button>
          <div className="welcome-brand">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 36 36" fill="none">
                <path d="M18 5v8m0 0L8 19m10-6 10 6M8 19v11m20-11v11" />
                <circle cx="18" cy="5" r="2.5" />
                <circle cx="18" cy="13" r="2.5" />
                <circle cx="8" cy="30" r="2.5" />
                <circle cx="28" cy="30" r="2.5" />
              </svg>
            </span>
            <span className="brand-name">STRATIFY AI</span>
          </div>
          <div className="chat-page-actions">
            <button
              className="profile-icon-button"
              onClick={() => setScreen("profile")}
              aria-label="Open profile"
              title="Your profile"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="8" r="3.5" />
                <path d="M4.5 20c.6-3.6 3.3-5.5 7.5-5.5s6.9 1.9 7.5 5.5" />
              </svg>
            </button>
            <button className="text-button" onClick={logout}>
              Sign out
            </button>
          </div>
        </header>

        <section className="chat-page" key={activeConversation?.id}>
          {activeConversation && (
            <>
              <div className="chat-page-titlebar">
                <div>
                  <p className="app-eyebrow">
                    {activeConversation.status === "completed"
                      ? "SAVED CONVERSATION"
                      : "DECISION IN PROGRESS"}
                  </p>
                  <h1>{activeConversation.title}</h1>
                </div>
                <div className="chat-decision-actions">
                  {activeConversation.status !== "completed" &&
                    messages.length > 0 && (
                      <button
                        className="finish-chat-button"
                        onClick={beginSavingConversation}
                        disabled={chatBusy}
                      >
                        Save decision
                      </button>
                    )}
                  <button
                    className="delete-decision-button"
                    onClick={() => setDeleteTarget(activeConversation)}
                    disabled={chatBusy}
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div className="chat-page-thread" aria-live="polite">
                {messages.length === 0 ? (
                  <div className="chat-empty-state">
                    <span className="chat-spark">S.</span>
                    <h2>Start with the situation.</h2>
                    <p>
                      What are you deciding, and what feels unclear right now?
                    </p>
                  </div>
                ) : (
                  messages.map((message, index) => (
                    <article
                      className={`chat-message ${message.role}`}
                      key={message.id || `${message.role}-${index}`}
                      style={{ animationDelay: `${Math.min(index * 45, 270)}ms` }}
                    >
                      <span className="chat-message-label">
                        {message.role === "assistant" ? "STRATIFY" : "YOU"}
                      </span>
                      {message.role === "assistant" && message.analysis ? (
                        <DecisionMap
                          analysis={message.analysis}
                          messageId={message.id}
                          onNextStep={sendSuggestedNextStep}
                          onSubmitFollowUp={sendFollowUpAnswer}
                          busy={chatBusy}
                        />
                      ) : (
                        <p>{message.content}</p>
                      )}
                    </article>
                  ))
                )}
                {chatBusy && (
                  <div className="chat-thinking" role="status">
                    <span className="thinking-dots" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                    </span>
                    Thinking through the decision…
                  </div>
                )}
                <div ref={chatEndRef} aria-hidden="true" />
              </div>

              {homeError && (
                <p className="app-error chat-page-error" role="alert">
                  {homeError}
                </p>
              )}

              <div className="chat-page-compose-area">
                <form className="chat-composer" onSubmit={sendChatMessage}>
                  <textarea
                    aria-label="Your message"
                    placeholder="Describe the decision you’re facing…"
                    rows={2}
                    maxLength={5000}
                    value={chatDraft}
                    onChange={(event) => setChatDraft(event.target.value)}
                    disabled={chatBusy}
                  />
                  <button
                    type="submit"
                    disabled={chatBusy || !chatDraft.trim()}
                    aria-label="Send message"
                  >
                    {chatBusy ? "…" : "↗"}
                  </button>
                </form>
                <p className="chat-disclaimer">
                  Stratify helps you examine a decision; the choice remains yours.
                </p>
              </div>
            </>
          )}
        </section>
        <ConversationDialog
          saving={saveDialogOpen}
          deleting={deleteTarget}
          title={decisionTitleDraft}
          error={homeError}
          busy={chatBusy}
          onTitleChange={setDecisionTitleDraft}
          onCancel={cancelConversationDialog}
          onSubmit={saveDialogOpen ? completeConversation : deleteConversation}
        />
      </main>
    );
  }

  if (screen === "profile") {
    const profileItems = [
      ["What you've shared", profile?.personal_memories],
      ["Goals", profile?.goals],
      ["Constraints", profile?.constraints],
      ["Preferences", profile?.preferences],
      ["Evidence", profile?.evidence],
      ["Blind spots to revisit", profile?.blind_spots],
      ["Still to explore", profile?.unknowns],
    ].filter(([, value]) => (
      Array.isArray(value) ? value.length > 0 : (
        value && typeof value === "object"
          ? Object.keys(value).length > 0
          : Boolean(value)
      )
    ));

    return (
      <main className="app-shell dashboard-shell">
        <header className="dashboard-header">
          <div className="welcome-brand">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 36 36" fill="none">
                <path d="M18 5v8m0 0L8 19m10-6 10 6M8 19v11m20-11v11" />
                <circle cx="18" cy="5" r="2.5" />
                <circle cx="18" cy="13" r="2.5" />
                <circle cx="8" cy="30" r="2.5" />
                <circle cx="28" cy="30" r="2.5" />
              </svg>
            </span>
            <span className="brand-name">STRATIFY AI</span>
          </div>
          <button className="profile-button" onClick={() => setScreen("home")}>
            Back to chats
          </button>
        </header>
        <section className="profile-dashboard">
          <p className="app-eyebrow">YOUR PERSONAL THINKING PROFILE</p>
          <p className="app-muted">
            Details you explicitly share may be saved here to personalize
            future chats. Stratify does not add inferred traits.
          </p>
          <h1>{user?.name || "Your profile"}</h1>
          <p className="profile-handle">
            {user?.handle || `@${user?.username || ""}`}
          </p>
          {profile?.role && (
            <div className="profile-role">
              <span>RIGHT NOW</span>
              <strong>{String(profile.role).replaceAll("_", " ")}</strong>
            </div>
          )}
          <div className="profile-section-grid">
            {profileItems.length ? profileItems.map(([label, value]) => (
              <article className="profile-section-card" key={label}>
                <h2>{label}</h2>
                {Array.isArray(value) ? (
                  <ul>
                    {value.map((item, index) => (
                      <li key={`${label}-${index}`}>
                        {typeof item === "string"
                          ? item
                          : item?.detail || item?.claim || item?.title ||
                            item?.question ||
                            JSON.stringify(item)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <ul>
                    {Object.entries(value).map(([key, item]) => (
                      <li key={key}>
                        <strong>{key.replaceAll("_", " ")}:</strong>{" "}
                        {typeof item === "string"
                          ? item
                          : JSON.stringify(item)}
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            )) : (
              <p className="app-muted">
                Your profile will take shape as you explore decisions with
                Stratify.
              </p>
            )}
          </div>
          <button className="text-button profile-signout" onClick={logout}>
            Sign out
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell dashboard-shell home-shell">
      <header className="dashboard-header home-header">
        <div className="welcome-brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 36 36" fill="none">
              <path d="M18 5v8m0 0L8 19m10-6 10 6M8 19v11m20-11v11" />
              <circle cx="18" cy="5" r="2.5" />
              <circle cx="18" cy="13" r="2.5" />
              <circle cx="8" cy="30" r="2.5" />
              <circle cx="28" cy="30" r="2.5" />
            </svg>
          </span>
          <span className="brand-name">STRATIFY AI</span>
        </div>
        <div className="home-header-actions">
          <button
            className="profile-icon-button"
            onClick={() => setScreen("profile")}
            aria-label="Open profile"
            title="Your profile"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="8" r="3.5" />
              <path d="M4.5 20c.6-3.6 3.3-5.5 7.5-5.5s6.9 1.9 7.5 5.5" />
            </svg>
          </button>
          <button className="text-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      <section className="home-content">
        <div className="home-heading">
          <div>
            <p className="app-eyebrow">YOUR SPACE · VOL. 01</p>
            <h1>What’s on your mind?</h1>
            <p className="app-muted">
              Bring a decision. We’ll make room to think it through.
            </p>
          </div>
          <span className="home-greeting">
            A QUIETER WAY TO FIND CLARITY
          </span>
        </div>

        <section className="conversation-section" aria-labelledby="chats-title">
          <div className="section-heading">
            <div>
              <h2 id="chats-title">Your conversations</h2>
              <p>Each circle keeps a decision in reach.</p>
            </div>
            <div className="chat-legend" aria-label="Conversation status">
              <span><i className="legend-dot saved" /> Saved</span>
              <span><i className="legend-dot active" /> In progress</span>
            </div>
          </div>

          <div className="conversation-circles">
            <button
              className="conversation-circle-item new-chat-item"
              onClick={createConversation}
              disabled={chatBusy}
              aria-label="Start a new chat"
            >
              <span className="conversation-circle new-chat-circle">+</span>
              <span className="conversation-circle-title">New chat</span>
            </button>
            {conversations.map((conversation) => (
              <div
                className={`conversation-circle-item ${
                  activeConversation?.id === conversation.id ? "current" : ""
                }`}
                key={conversation.id}
              >
                <button
                  className="conversation-open-button"
                  onClick={() => openConversation(conversation)}
                  disabled={chatBusy}
                  aria-label={`Open ${conversation.title}, ${
                    conversation.status === "completed" ? "saved" : "in progress"
                  }`}
                  title={conversation.title}
                >
                  <span
                    className={`conversation-circle ${
                      conversation.status === "completed" ? "saved" : "in-progress"
                    }`}
                  >
                    {conversation.title
                      .split(/\s+/)
                      .filter(Boolean)
                      .slice(0, 2)
                      .map((word) => word[0])
                      .join("")
                      .toUpperCase() || "…"}
                  </span>
                  <span className="conversation-circle-title">
                    {conversation.title}
                  </span>
                </button>
                <button
                  className="conversation-delete-button"
                  onClick={() => setDeleteTarget(conversation)}
                  disabled={chatBusy}
                  aria-label={`Delete ${conversation.title}`}
                >
                  Delete
                </button>
              </div>
            ))}
          </div>

          {homeError && (
            <p className="app-error" role="alert">{homeError}</p>
          )}

        </section>
        <ConversationDialog
          saving={false}
          deleting={deleteTarget}
          title={decisionTitleDraft}
          error={homeError}
          busy={chatBusy}
          onTitleChange={setDecisionTitleDraft}
          onCancel={cancelConversationDialog}
          onSubmit={deleteConversation}
        />

        <section className="home-information">
          <div className="how-it-works" id="how-it-works">
            <p className="app-eyebrow">A METHOD FOR CLEARER CHOICES</p>
            <h2>How Stratify works</h2>
            <div className="how-steps">
              <article>
                <span>01</span>
                <h3>Set the scene</h3>
                <p>Describe what matters and what constraints you’re working with.</p>
              </article>
              <article>
                <span>02</span>
                <h3>Explore the paths</h3>
                <p>Compare options, trade-offs, and realistic next steps.</p>
              </article>
              <article>
                <span>03</span>
                <h3>Look for blind spots</h3>
                <p>Surface assumptions and missing information before you decide.</p>
              </article>
            </div>
          </div>

          <div className="faq-section" id="faq">
            <p className="app-eyebrow">A FEW THINGS TO KNOW</p>
            <h2>Frequently asked</h2>
            <details>
              <summary>Does Stratify make the decision for me?</summary>
              <p>
                No. Stratify helps clarify the situation, alternatives, and
                trade-offs so you can make a more informed choice.
              </p>
            </details>
            <details>
              <summary>Can I return to a conversation later?</summary>
              <p>
                Yes. Your chats are saved to your account. Red circles are in
                progress; green circles are saved as complete.
              </p>
            </details>
            <details>
              <summary>What does Stratify do with my profile?</summary>
              <p>
                Your profile provides context for more relevant questions and
                suggestions. You can review it from your profile icon.
              </p>
            </details>
          </div>
        </section>

        <footer className="home-footer" id="contact">
          <div>
            <p className="app-eyebrow">CONTACT US</p>
            <p className="app-muted">
              Questions or ideas? Connect with the Stratify project.
            </p>
            <a
              className="github-link-button"
              href="https://github.com/Deekshith-Dgit/Stratify.ai"
              target="_blank"
              rel="noreferrer"
            >
              View Stratify on GitHub <span aria-hidden="true">↗</span>
            </a>
          </div>
          <span className="footer-signoff">AN ENVIRONMENT FOR BETTER THINKING</span>
        </footer>
      </section>
    </main>
  );
}