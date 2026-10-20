def test_health_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signup_and_login_with_stratify_handle(client):
    signup = client.post(
        "/auth/signup",
        json={
            "username": "Test.User@stratifyai",
            "password": "TestPassword123!",
            "name": " Test User ",
        },
    )

    assert signup.status_code == 201
    assert signup.json()["user"]["handle"] == "test.user@stratifyai"
    assert signup.json()["user"]["name"] == "Test User"
    assert signup.json()["access_token"]

    login = client.post(
        "/auth/login",
        json={
            "username": "TEST.USER",
            "password": "TestPassword123!",
        },
    )

    assert login.status_code == 200
    assert login.json()["user"]["handle"] == "test.user@stratifyai"

    me = client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {login.json()['access_token']}"
        },
    )
    assert me.status_code == 200
    assert me.json()["username"] == "test.user"
    assert me.json()["name"] == "Test User"


def test_signup_rejects_invalid_username_and_blank_name(client):
    invalid_username = client.post(
        "/auth/signup",
        json={
            "username": "ab..cd",
            "password": "TestPassword123!",
            "name": "Test User",
        },
    )
    assert invalid_username.status_code == 422

    blank_name = client.post(
        "/auth/signup",
        json={
            "username": "valid.name",
            "password": "TestPassword123!",
            "name": "   ",
        },
    )
    assert blank_name.status_code == 422


def test_signup_rejects_invalid_password(client):
    response = client.post(
        "/auth/signup",
        json={
            "username": "valid.name",
            "password": "       ",
            "name": "Test User",
        },
    )

    assert response.status_code == 422


def test_signup_rejects_duplicate_username_even_with_domain(client):
    payload = {
        "username": "same.name",
        "password": "TestPassword123!",
        "name": "Test User",
    }
    assert client.post("/auth/signup", json=payload).status_code == 201

    payload["username"] = "SAME.NAME@stratifyai"
    duplicate = client.post("/auth/signup", json=payload)

    assert duplicate.status_code == 409


def test_login_rejects_wrong_password(client, signup_account):
    signup_account("existing.user")

    response = client.post(
        "/auth/login",
        json={
            "username": "existing.user@stratifyai",
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401


def test_protected_endpoints_reject_anonymous_users(client):
    roadmap = client.post(
        "/roadmap/generate",
        json={"goal": "Learn Python", "steps": []},
    )
    assert roadmap.status_code in (401, 403)

    for path, method in [
        ("/onboarding/start", "post"),
        ("/onboarding/next", "get"),
        ("/onboarding/profile", "get"),
        ("/chat/conversations", "get"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code in (401, 403)


def test_authenticated_user_can_start_onboarding(client, signup_account):
    signup = signup_account("onboarding.user")
    token = signup.json()["access_token"]

    response = client.post(
        "/onboarding/start",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["session_id"]
    assert response.json()["progress"] == {
        "completed_questions": 0,
        "total_questions": 12,
        "completion_percent": 0,
    }


def test_user_cannot_access_another_users_onboarding_session(
    client,
    signup_account,
):
    owner_token = signup_account("owner.user").json()["access_token"]
    other_token = signup_account("other.user").json()["access_token"]

    start = client.post(
        "/onboarding/start",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert start.status_code == 200, start.text

    response = client.get(
        "/onboarding/next",
        params={"session_id": start.json()["session_id"]},
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404, response.text


def test_onboarding_rejects_blank_answer(client, signup_account):
    token = signup_account("blank.answer").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    start = client.post("/onboarding/start", headers=headers)
    assert start.status_code == 200, start.text

    response = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": start.json()["session_id"],
            "question_id": "role",
            "answer": "   ",
        },
    )

    assert response.status_code == 422, response.text


def test_onboarding_accepts_valid_role_answer(
    client,
    monkeypatch,
    signup_account,
):
    import routers.onboarding as onboarding

    def fake_generate_and_store_next(session_id, user_id):
        return {
            "status": "ask",
            "question": {
                "id": "education_level",
                "text": "What is your current education level?",
                "type": "single_choice",
                "options": [
                    {"label": "School", "value": "school"},
                    {"label": "College", "value": "college"},
                ],
            },
            "reason": "Continue the assessment.",
            "profile_updates": [],
            "unknowns": [],
        }

    monkeypatch.setattr(
        onboarding,
        "generate_and_store_next",
        fake_generate_and_store_next,
    )

    token = signup_account("valid.answer").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    start = client.post("/onboarding/start", headers=headers)
    assert start.status_code == 200, start.text

    response = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": start.json()["session_id"],
            "question_id": "role",
            "answer": "student",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer_saved"] is True
    assert response.json()["question"]["id"] == "education_level"
    assert response.json()["progress"] == {
        "completed_questions": 1,
        "total_questions": 12,
        "completion_percent": 8,
    }


def test_chat_receives_saved_onboarding_question_and_answer(
    client,
    monkeypatch,
    signup_account,
):
    import routers.chat as chat
    import routers.onboarding as onboarding

    observed = {}
    generated_questions = iter([
        {
            "status": "ask",
            "question": {
                "id": "education_level",
                "text": "What are you studying?",
                "type": "text",
            },
            "reason": "Continue the assessment.",
            "profile_updates": [],
            "unknowns": [],
        },
        {
            "status": "ask",
            "question": {
                "id": "decision_priority",
                "text": "What matters most in your next step?",
                "type": "text",
            },
            "reason": "Continue the assessment.",
            "profile_updates": [],
            "unknowns": [],
        },
    ])

    monkeypatch.setattr(
        onboarding,
        "generate_next_question",
        lambda _profile, _answers: next(generated_questions),
    )
    monkeypatch.setattr(
        chat,
        "generate_reply",
        lambda _messages, profile: (
            observed.update(profile=profile)
            or {
                "summary": "A tailored reply.",
                "personal_memories": [],
            }
        ),
    )

    token = signup_account("personalized.chat").json()["access_token"]
    headers = {"Authorization": " ".join(("Bearer", token))}
    onboarding_start = client.post("/onboarding/start", headers=headers)
    assert onboarding_start.status_code == 200, onboarding_start.text

    answer = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": onboarding_start.json()["session_id"],
            "question_id": "role",
            "answer": "student",
        },
    )
    assert answer.status_code == 200, answer.text

    second_answer = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": onboarding_start.json()["session_id"],
            "question_id": "education_level",
            "answer": "Computer science",
        },
    )
    assert second_answer.status_code == 200, second_answer.text

    conversation = client.post(
        "/chat/conversations",
        headers=headers,
        json={},
    )
    assert conversation.status_code == 201, conversation.text
    reply = client.post(
        f"/chat/conversations/{conversation.json()['id']}/messages",
        headers=headers,
        json={"content": "How should I choose my next step?"},
    )

    assert reply.status_code == 200, reply.text
    assert observed["profile"]["role"] == "student"
    assert observed["profile"]["onboarding_answers"] == [
        {
            "question_id": "role",
            "question": "Which best describes you right now?",
            "answer": "student",
        },
        {
            "question_id": "education_level",
            "question": "What are you studying?",
            "answer": "Computer science",
        },
    ]


def test_chat_memories_persist_and_reach_later_chats(
    client,
    monkeypatch,
    signup_account,
):
    import routers.chat as chat

    observed_profiles = []
    generated_memories = [
        ["I prefer concise, practical options."],
        [
            "I prefer concise, practical options.",
            "i prefer concise, practical options.",
            "My long-term goal is to start a design studio.",
        ],
    ]

    def fake_generate_reply(_messages, profile):
        observed_profiles.append(profile)
        return {
            "summary": "A personalized reply.",
            "personal_memories": generated_memories[len(observed_profiles) - 1],
        }

    monkeypatch.setattr(chat, "generate_reply", fake_generate_reply)
    token = signup_account("chat.memory").json()["access_token"]
    headers = {"Authorization": " ".join(("Bearer", token))}

    first_conversation = client.post(
        "/chat/conversations",
        json={},
        headers=headers,
    )
    first_reply = client.post(
        f"/chat/conversations/{first_conversation.json()['id']}/messages",
        json={"content": "I prefer concise, practical options."},
        headers=headers,
    )
    assert first_reply.status_code == 200, first_reply.text
    assert first_reply.json()["profile"]["personal_memories"] == [
        "I prefer concise, practical options."
    ]

    second_conversation = client.post(
        "/chat/conversations",
        json={},
        headers=headers,
    )
    second_reply = client.post(
        f"/chat/conversations/{second_conversation.json()['id']}/messages",
        json={"content": "Help me think through my next career step."},
        headers=headers,
    )

    assert second_reply.status_code == 200, second_reply.text
    assert observed_profiles[1]["personal_memories"] == [
        "I prefer concise, practical options."
    ]
    assert second_reply.json()["profile"]["personal_memories"] == [
        "I prefer concise, practical options.",
        "My long-term goal is to start a design studio.",
    ]
    profile = client.get("/onboarding/profile", headers=headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()["profile"]["personal_memories"] == (
        second_reply.json()["profile"]["personal_memories"]
    )


def test_chat_keeps_user_message_when_ai_generation_fails(
    client,
    monkeypatch,
    signup_account,
):
    import routers.chat as chat

    def fail_generation(_messages, _profile):
        raise RuntimeError("The AI provider is unavailable.")

    monkeypatch.setattr(chat, "generate_reply", fail_generation)
    token = signup_account("chat.failed.memory").json()["access_token"]
    headers = {"Authorization": " ".join(("Bearer", token))}
    conversation = client.post(
        "/chat/conversations",
        json={},
        headers=headers,
    )
    content = "I prefer a stable schedule and hands-on learning."

    failed_reply = client.post(
        f"/chat/conversations/{conversation.json()['id']}/messages",
        json={"content": content},
        headers=headers,
    )
    assert failed_reply.status_code == 502

    persisted = client.get(
        f"/chat/conversations/{conversation.json()['id']}",
        headers=headers,
    )
    assert persisted.status_code == 200, persisted.text
    assert [
        (message["role"], message["content"])
        for message in persisted.json()["messages"]
    ] == [("user", content)]


def test_onboarding_rejects_invalid_role_choice(client, signup_account):
    token = signup_account("invalid.role").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    start = client.post("/onboarding/start", headers=headers)
    assert start.status_code == 200, start.text

    response = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": start.json()["session_id"],
            "question_id": "role",
            "answer": "astronaut",
        },
    )

    assert response.status_code == 422, response.text


def test_onboarding_rejects_wrong_question_id(client, signup_account):
    token = signup_account("wrong.question").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    start = client.post("/onboarding/start", headers=headers)
    assert start.status_code == 200, start.text

    response = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": start.json()["session_id"],
            "question_id": "fake_question",
            "answer": "student",
        },
    )

    assert response.status_code == 409, response.text


def test_chat_conversations_persist_messages_and_completion(
    client,
    monkeypatch,
    signup_account,
):
    import routers.chat as chat

    observed = {}

    def fake_generate_reply(messages, profile):
        observed["messages"] = messages
        observed["profile"] = profile
        return {
            "stage": "compare",
            "decision_frame": "Whether a career change is worth exploring now.",
            "summary": "Let's compare what matters most and what remains uncertain.",
            "known_facts": ["You are considering a career change."],
            "decision_criteria": ["Growth matters more than short-term certainty."],
            "critical_unknowns": ["Your financial runway is not yet clear."],
            "paths": [
                {
                    "name": "Explore a change",
                    "upside": "It may better match your goals.",
                    "downside": "The transition may take time.",
                    "fit": "This may fit if growth matters more than short-term certainty.",
                },
                {
                    "name": "Stay and reassess",
                    "upside": "It preserves current stability while you gather evidence.",
                    "downside": "It may delay a change that matters to you.",
                    "fit": "This may fit if reducing near-term risk is the priority.",
                },
            ],
            "tradeoffs": ["Growth may compete with stability."],
            "blind_spots": ["Your financial runway is not yet clear."],
            "next_step": "Write down the constraints you cannot compromise on.",
            "follow_up": "What would make a transition feel manageable?",
            "personal_memories": [],
        }

    monkeypatch.setattr(chat, "generate_reply", fake_generate_reply)
    token = signup_account("chat.owner").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post("/chat/conversations", json={}, headers=headers)
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    assert created.json()["status"] == "active"

    reply = client.post(
        f"/chat/conversations/{conversation_id}/messages",
        json={"content": "Should I change my career path?"},
        headers=headers,
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["title"] == "Should I change my career path?"
    assert [message["role"] for message in reply.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assistant_message = reply.json()["messages"][1]
    assert assistant_message["analysis"]["paths"][0]["name"] == "Explore a change"
    assert assistant_message["analysis"]["stage"] == "compare"
    assert observed["messages"][-1]["content"] == (
        "Should I change my career path?"
    )
    assert isinstance(observed["profile"], dict)

    detail = client.get(
        f"/chat/conversations/{conversation_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 2
    assert detail.json()["messages"][1]["analysis"] == assistant_message["analysis"]

    completed = client.patch(
        f"/chat/conversations/{conversation_id}/complete",
        json={"title": "Career direction"},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["title"] == "Career direction"

    resumed = client.post(
        f"/chat/conversations/{conversation_id}/messages",
        json={"content": "What should I consider first?"},
        headers=headers,
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"

    conversations = client.get("/chat/conversations", headers=headers)
    assert conversations.status_code == 200
    assert conversations.json()["conversations"][0]["status"] == "active"
    assert conversations.json()["conversations"][0]["message_count"] == 4
    assert any(
        message["role"] == "assistant"
        and "Decision map:" in message["content"]
        for message in observed["messages"]
    )


def test_chat_can_be_deleted_only_by_its_owner(
    client,
    signup_account,
):
    owner_token = signup_account("chat.delete.owner").json()["access_token"]
    other_token = signup_account("chat.delete.other").json()["access_token"]
    created = client.post(
        "/chat/conversations",
        json={"title": "Decision to remove"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    denied = client.delete(
        f"/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert denied.status_code == 404
    still_exists = client.get(
        f"/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert still_exists.status_code == 200

    deleted = client.delete(
        f"/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert deleted.status_code == 204
    missing = client.get(
        f"/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert missing.status_code == 404


def test_chat_engine_rejects_invalid_decision_map():
    from services.chat_engine import validate_decision_map

    try:
        validate_decision_map(
            {
                "stage": "compare",
                "decision_frame": "A grounded decision frame.",
                "summary": "A grounded summary.",
                "known_facts": [],
                "decision_criteria": [],
                "critical_unknowns": [],
                "paths": [
                    {"name": "Path one", "upside": "x" * 700},
                    {"name": "Path two"},
                ],
                "tradeoffs": [],
                "blind_spots": [],
                "next_step": "Take a small next step.",
            }
        )
    except ValueError as error:
        assert "path upside" in str(error)
    else:
        raise AssertionError("Expected oversized path detail to be rejected.")


def test_chat_engine_requires_clarification_before_offering_paths():
    from services.chat_engine import validate_decision_map

    clarification = validate_decision_map(
        {
            "stage": "clarify",
            "decision_frame": "The choice and its constraints are not clear yet.",
            "summary": "I need one detail because it changes which options are safe.",
            "known_facts": ["You are considering a change."],
            "decision_criteria": [],
            "critical_unknowns": ["The relevant deadline is unknown."],
            "paths": [],
            "tradeoffs": [],
            "blind_spots": [],
            "next_step": "Tell me when the decision needs to be made.",
            "follow_up": "When do you need to make this decision?",
            "personal_memories": [],
        }
    )
    assert clarification["stage"] == "clarify"
    assert clarification["paths"] == []
    assert clarification["follow_up"]

    invalid_compare = {
        **clarification,
        "stage": "compare",
        "paths": [
            {
                "name": "Make the change",
                "upside": "Could address the current concern.",
                "downside": "The impact is uncertain.",
                "fit": "If change is the priority.",
            },
        ],
        "follow_up": "",
    }
    try:
        validate_decision_map(invalid_compare)
    except ValueError as error:
        assert "at least two" in str(error)
    else:
        raise AssertionError("Expected comparisons to include multiple paths.")


def test_chat_engine_accepts_more_than_three_relevant_paths():
    from services.chat_engine import validate_decision_map

    result = validate_decision_map(
        {
            "stage": "compare",
            "decision_frame": "Choose between distinct available paths.",
            "summary": "Several distinct paths are relevant based on the facts.",
            "known_facts": [
                f"Relevant fact {index}."
                for index in range(1, 7)
            ],
            "decision_criteria": [],
            "critical_unknowns": [],
            "paths": [
                {
                    "name": f"Distinct path {index}",
                    "upside": "A different potential benefit.",
                    "downside": "A different cost to consider.",
                    "fit": "If its corresponding priority matters most.",
                }
                for index in range(1, 6)
            ],
            "tradeoffs": [],
            "blind_spots": [],
            "next_step": "Compare the options against your stated priorities.",
            "follow_up": "",
            "personal_memories": [],
        }
    )

    assert len(result["paths"]) == 5
    assert len(result["known_facts"]) == 6


def test_chat_engine_retries_once_when_provider_returns_invalid_schema():
    import json
    from types import SimpleNamespace

    from services.chat_engine import _request_decision_map

    valid_response = {
        "stage": "clarify",
        "decision_frame": "The decision deadline could change the options.",
        "summary": "I need the deadline before comparing paths.",
        "known_facts": ["You are weighing a decision."],
        "decision_criteria": [],
        "critical_unknowns": ["The deadline is unknown."],
        "paths": [],
        "tradeoffs": [],
        "blind_spots": [],
        "next_step": "Share the deadline.",
        "follow_up": "When must you decide?",
        "personal_memories": [],
    }
    observed_messages = []
    responses = iter([
        '{"stage":"compare","paths":[]}',
        json.dumps(valid_response),
    ])

    class Completions:
        def create(self, **kwargs):
            observed_messages.append(kwargs["messages"])
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=next(responses))
                    )
                ]
            )

    provider = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )

    result = _request_decision_map(
        provider,
        "mock-model",
        [{"role": "user", "content": "I am weighing a decision."}],
        max_completion_tokens=3000,
    )

    assert result["stage"] == "clarify"
    assert len(observed_messages) == 2
    assert "did not pass" in observed_messages[1][-1]["content"]


def test_chat_engine_requires_explicit_personal_memory_field():
    from services.chat_engine import validate_decision_map

    incomplete = {
        "stage": "clarify",
        "decision_frame": "The deadline could change the options.",
        "summary": "I need the deadline before comparing paths.",
        "known_facts": [],
        "decision_criteria": [],
        "critical_unknowns": [],
        "paths": [],
        "tradeoffs": [],
        "blind_spots": [],
        "next_step": "Share the deadline.",
        "follow_up": "When must you decide?",
    }

    try:
        validate_decision_map(incomplete)
    except ValueError as error:
        assert "personal_memories" in str(error)
    else:
        raise AssertionError("Expected missing personal memories to be rejected.")


def test_chat_engine_includes_onboarding_answers_in_personalization_context(
    monkeypatch,
):
    import services.chat_engine as chat_engine

    observed = {}

    def capture_request(_client, _model, messages, **_token_limit):
        observed["system_message"] = messages[0]["content"]
        return {"stage": "test"}

    monkeypatch.setattr(
        chat_engine,
        "_request_decision_map",
        capture_request,
    )
    monkeypatch.delenv("TOKENHARBOR_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    result = chat_engine.generate_reply(
        [{"role": "user", "content": "Help me choose a course."}],
        {
            "role": "student",
            "personal_memories": [
                "I prefer practical examples over abstract explanations."
            ],
            "onboarding_answers": [
                {
                    "question_id": "learning_style",
                    "question": "How do you prefer to learn?",
                    "answer": "By building practical projects.",
                }
            ],
        },
    )

    assert result == {"stage": "test"}
    assert "How do you prefer to learn?" in observed["system_message"]
    assert "By building practical projects." in observed["system_message"]
    assert (
        "I prefer practical examples over abstract explanations."
        in observed["system_message"]
    )
    assert "Use relevant onboarding answers to personalize" in (
        observed["system_message"]
    )


def test_chat_follow_up_answer_is_attached_to_question_and_saved(
    client,
    monkeypatch,
    signup_account,
):
    import routers.chat as chat

    observed = {}

    def fake_generate_reply(messages, _profile):
        observed["messages"] = messages
        return {
            "stage": "clarify",
            "decision_frame": "The right paths depend on the decision deadline.",
            "summary": "I need the deadline before mapping viable options.",
            "known_facts": [],
            "decision_criteria": [],
            "critical_unknowns": ["The decision deadline is not known."],
            "paths": [],
            "tradeoffs": [],
            "blind_spots": [],
            "next_step": "Tell me when this decision must be made.",
            "follow_up": "When do you need to make this decision?",
            "personal_memories": [],
        }

    monkeypatch.setattr(chat, "generate_reply", fake_generate_reply)
    token = signup_account("chat.followup.answer").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/chat/conversations", json={}, headers=headers)
    conversation_id = created.json()["id"]

    initial = client.post(
        f"/chat/conversations/{conversation_id}/messages",
        json={"content": "I am considering a career change."},
        headers=headers,
    )
    assert initial.status_code == 200, initial.text
    question_message = initial.json()["messages"][1]

    answered = client.post(
        f"/chat/conversations/{conversation_id}/messages",
        json={
            "content": "Within the next six months.",
            "answer_to_message_id": question_message["id"],
        },
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    assert observed["messages"][-1]["content"] == (
        "Answer to your question, "
        "'When do you need to make this decision?':\n"
        "Within the next six months."
    )

    detail = client.get(
        f"/chat/conversations/{conversation_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    saved_question = detail.json()["messages"][1]["analysis"]
    assert saved_question["follow_up_answer"] == "Within the next six months."

    duplicate = client.post(
        f"/chat/conversations/{conversation_id}/messages",
        json={
            "content": "Another answer.",
            "answer_to_message_id": question_message["id"],
        },
        headers=headers,
    )
    assert duplicate.status_code == 409


def test_chat_engine_uses_tokenharbor_when_groq_fails(monkeypatch):
    import json
    from types import SimpleNamespace

    import services.chat_engine as chat_engine

    class FailingCompletions:
        @staticmethod
        def create(**_kwargs):
            raise RuntimeError("Primary provider unavailable.")

    fallback_reply = {
        "stage": "compare",
        "decision_frame": "Choose between two feasible paths.",
        "summary": "Both paths remain open based on the information shared.",
        "known_facts": [],
        "decision_criteria": [],
        "critical_unknowns": [],
        "paths": [
            {
                "name": "Path one",
                "upside": "Potential benefit.",
                "downside": "Potential cost.",
                "fit": "If this criterion matters most.",
            },
            {
                "name": "Path two",
                "upside": "Another potential benefit.",
                "downside": "Another potential cost.",
                "fit": "If another criterion matters most.",
            },
        ],
        "tradeoffs": [],
        "blind_spots": [],
        "next_step": "Compare the two stated criteria.",
        "follow_up": "",
        "personal_memories": [],
    }

    request_observed = {}
    payload_string = json.dumps(fallback_reply)
    request_count = 0

    def fake_post(url, headers, json: dict, timeout):
        nonlocal request_count
        request_count += 1
        request_observed.update({
            "url": url,
            "headers": headers,
            "body": json,
            "timeout": timeout,
        })
        return chat_engine.httpx.Response(
            503 if request_count == 1 else 200,
            json=(
                {"error": "temporary overload"}
                if request_count == 1
                else {
                    "choices": [
                        {"message": {"content": payload_string}}
                    ]
                }
            ),
            request=chat_engine.httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        chat_engine,
        "client",
        SimpleNamespace(chat=SimpleNamespace(
            completions=FailingCompletions(),
        )),
    )
    monkeypatch.setattr(chat_engine.httpx, "post", fake_post)
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "test-fallback-secret")
    monkeypatch.setenv(
        "TOKENHARBOR_BASE_URL",
        "https://api.tokenharbor.example/v1/",
    )
    monkeypatch.setenv("TOKENHARBOR_MODEL", "deepseek-test-model")

    result = chat_engine.generate_reply(
        [{"role": "user", "content": "Which path fits?"}],
        {},
    )

    assert result["stage"] == "compare"
    assert request_observed["url"] == (
        "https://api.tokenharbor.example/v1/chat/completions"
    )
    assert request_observed["headers"]["Authorization"] == (
        "Bearer test-fallback-secret"
    )
    assert request_observed["body"]["model"] == "deepseek-test-model"
    assert request_observed["body"]["max_tokens"] == 3000
    assert request_count == 2


def test_chat_engine_uses_nvidia_after_tokenharbor_fails(monkeypatch):
    import json
    from types import SimpleNamespace

    import services.chat_engine as chat_engine

    class FailingCompletions:
        @staticmethod
        def create(**_kwargs):
            raise RuntimeError("Primary provider unavailable.")

    reply = {
        "stage": "clarify",
        "decision_frame": "One missing constraint changes the available paths.",
        "summary": "The deadline matters before comparing these options.",
        "known_facts": [],
        "decision_criteria": [],
        "critical_unknowns": ["The deadline is unknown."],
        "paths": [],
        "tradeoffs": [],
        "blind_spots": [],
        "next_step": "Share the decision deadline.",
        "follow_up": "When do you need to decide?",
        "personal_memories": [],
    }
    request_urls = []
    response_content = json.dumps(reply)

    def fake_post(url, **_kwargs):
        request_urls.append(url)
        if "tokenharbor.ai" in url:
            return chat_engine.httpx.Response(
                503,
                json={"error": "temporary overload"},
                request=chat_engine.httpx.Request("POST", url),
            )
        return chat_engine.httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": response_content}}
                ]
            },
            request=chat_engine.httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        chat_engine,
        "client",
        SimpleNamespace(chat=SimpleNamespace(
            completions=FailingCompletions(),
        )),
    )
    monkeypatch.setattr(chat_engine.httpx, "post", fake_post)
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "test-tokenharbor-key")
    monkeypatch.setenv(
        "TOKENHARBOR_BASE_URL",
        "https://tokenharbor.ai/v1",
    )
    monkeypatch.setenv("TOKENHARBOR_MODEL", "deepseek-test-model")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv(
        "NVIDIA_BASE_URL",
        "https://integrate.api.nvidia.com/v1",
    )
    monkeypatch.setenv("NVIDIA_MODEL", "nvidia/test-model")
    monkeypatch.setattr(chat_engine.time, "sleep", lambda _seconds: None)

    result = chat_engine.generate_reply(
        [{"role": "user", "content": "What detail do you need?"}],
        {},
    )

    assert result["stage"] == "clarify"
    assert request_urls == [
        "https://tokenharbor.ai/v1/chat/completions",
        "https://tokenharbor.ai/v1/chat/completions",
        "https://integrate.api.nvidia.com/v1/chat/completions",
    ]


def test_chat_reports_invalid_ai_response_but_keeps_user_message(
    client,
    monkeypatch,
    signup_account,
):
    import routers.chat as chat

    monkeypatch.setattr(
        chat,
        "generate_reply",
        lambda _messages, _profile: "unstructured response",
    )
    token = signup_account("chat.invalid.response").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/chat/conversations", json={}, headers=headers)
    assert created.status_code == 201, created.text

    response = client.post(
        f"/chat/conversations/{created.json()['id']}/messages",
        json={"content": "What should I consider?"},
        headers=headers,
    )

    assert response.status_code == 502
    detail = client.get(
        f"/chat/conversations/{created.json()['id']}",
        headers=headers,
    )
    assert [
        (message["role"], message["content"])
        for message in detail.json()["messages"]
    ] == [("user", "What should I consider?")]


def test_chat_conversations_are_private(client, signup_account):
    owner_token = signup_account("chat.owner").json()["access_token"]
    other_token = signup_account("chat.other").json()["access_token"]

    created = client.post(
        "/chat/conversations",
        json={},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    conversation_id = created.json()["id"]

    response = client.get(
        f"/chat/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 404


def test_chat_rejects_blank_messages(client, signup_account):
    token = signup_account("chat.blank").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/chat/conversations", json={}, headers=headers)

    unsent_complete = client.patch(
        f"/chat/conversations/{created.json()['id']}/complete",
        headers=headers,
    )
    assert unsent_complete.status_code == 409

    response = client.post(
        f"/chat/conversations/{created.json()['id']}/messages",
        json={"content": "   "},
        headers=headers,
    )

    assert response.status_code == 422
