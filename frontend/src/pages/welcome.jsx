
import "../styles/welcome.css";

export default function Welcome({ onEnter }) {
  return (
    <main className="welcome-page">
      <div className="welcome-grain" aria-hidden="true" />

      <header className="welcome-header">
        <div className="welcome-brand" aria-label="Stratify AI">
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
        <span className="welcome-edition">A CLEARER PERSPECTIVE · VOL. 01</span>
      </header>

      <div className="welcome-layout">
        <section className="welcome-content">
          <p className="welcome-eyebrow">A BETTER WAY TO DECIDE</p>

          <h1>
            <span>Think deeper.</span>
            <span>Choose with clarity.</span>
          </h1>

          <p className="welcome-description">
            Explore the situation, compare possible paths, and surface the
            assumptions hiding in your decision.
          </p>

          <button className="welcome-enter" onClick={onEnter}>
            <span>Enter Stratify</span>
            <span className="enter-arrow" aria-hidden="true">
              ↗
            </span>
          </button>

          <p className="welcome-caption">YOUR THINKING. YOUR DIRECTION.</p>
        </section>

        <div className="welcome-art" aria-hidden="true">
          <span className="art-index">A DECISION, SEEN FROM THREE SIDES</span>
          <div className="decision-map">
            <span className="decision-link link-situation" />
            <span className="decision-link link-paths" />
            <span className="decision-link link-assumptions" />
            <span className="decision-hub" />
            <div className="decision-node node-situation">
              <span>THE SITUATION</span>
            </div>
            <div className="decision-node node-paths">
              <span>POSSIBLE PATHS</span>
            </div>
            <div className="decision-node node-assumptions">
              <span>HIDDEN ASSUMPTIONS</span>
            </div>
          </div>
          <span className="art-note">CONNECTED LENSES, NOT A FIXED PATH</span>
        </div>
      </div>

      <footer className="welcome-footer">
        <span>STRATIFY.AI</span>
        <span>AN ENVIRONMENT FOR BETTER THINKING</span>
      </footer>
    </main>
  );
}
