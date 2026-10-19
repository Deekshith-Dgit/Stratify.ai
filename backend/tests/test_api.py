
def test_health_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signup_and_login(client):
    signup = client.post(
        "/auth/signup",
        json={
            "email": "test@example.com",
            "password": "TestPassword123!",
        },
    )

    assert signup.status_code in (200, 201)

    login = client.post(
        "/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPassword123!",
        },
    )

    assert login.status_code == 200
    assert login.json()


def test_protected_endpoints_reject_anonymous_users(client):
    response = client.post(
        "/roadmap/generate",
        json={"goal": "Learn Python", "steps": []},
    )

    assert response.status_code in (401, 403)

def test_onboarding_endpoints_reject_anonymous_users(client):
    response = client.post("/onboarding/start")
    assert response.status_code in (401, 403)

    response = client.get("/onboarding/next")
    assert response.status_code in (401, 403)

    response = client.get("/onboarding/profile")
    assert response.status_code in (401, 403)

def test_authenticated_user_can_start_onboarding(client):
    # Create an account.
    signup = client.post(
        "/auth/signup",
        json={
            "email": "onboarding@example.com",
            "password": "TestPassword123!",
        },
    )

    assert signup.status_code in (200, 201)

    # Log in and reuse the returned authentication data.
    login = client.post(
        "/auth/login",
        json={
            "email": "onboarding@example.com",
            "password": "TestPassword123!",
        },
    )
    assert login.status_code == 200

    data = login.json()
    token = data.get("access_token") or data.get("token")

    assert token, f"Login response has no token field: {list(data.keys())}"

    response = client.post(
        "/onboarding/start",
        headers={"Authorization": f"Bearer {token}"},
    )
    print("ONBOARDING RESPONSE:", response.status_code, response.json())
    assert response.status_code == 200, response.text

def test_user_cannot_access_another_users_onboarding_session(client):
    def create_user_and_login(email):
        signup = client.post(
            "/auth/signup",
            json={
                "email": email,
                "password": "TestPassword123!",
            },
        )
        assert signup.status_code in (200, 201), signup.text

        login = client.post(
            "/auth/login",
            json={
                "email": email,
                "password": "TestPassword123!",
            },
        )
        assert login.status_code == 200, login.text

        data = login.json()
        token = data.get("access_token") or data.get("token")
        assert token, f"Login response has no token field: {list(data.keys())}"
        return {"Authorization": f"Bearer {token}"}

    user_a_headers = create_user_and_login("owner@example.com")
    user_b_headers = create_user_and_login("other@example.com")

    # User A creates an onboarding session.
    start = client.post(
        "/onboarding/start",
        headers=user_a_headers,
    )
    assert start.status_code == 200, start.text

    session_id = start.json()["session_id"]

    # User B tries to access User A's session.
    response = client.get(
        "/onboarding/next",
        params={"session_id": session_id},
        headers=user_b_headers,
    )

    assert response.status_code == 404, response.text

def test_onboarding_rejects_blank_answer(client):
    signup = client.post(
        "/auth/signup",
        json={
            "email": "blank-answer@example.com",
            "password": "TestPassword123!",
        },
    )
    assert signup.status_code in (200, 201), signup.text

    login = client.post(
        "/auth/login",
        json={
            "email": "blank-answer@example.com",
            "password": "TestPassword123!",
        },
    )
    assert login.status_code == 200, login.text

    data = login.json()
    token = data.get("access_token") or data.get("token")
    assert token

    headers = {"Authorization": f"Bearer {token}"}

    start = client.post("/onboarding/start", headers=headers)
    assert start.status_code == 200, start.text

    session_id = start.json()["session_id"]

    response = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": session_id,
            "question_id": "role",
            "answer": "   ",
        },
    )

    assert response.status_code == 422, response.text


def test_onboarding_accepts_valid_role_answer(client, monkeypatch):
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

    signup = client.post(
        "/auth/signup",
        json={
            "email": "valid-answer@example.com",
            "password": "TestPassword123!",
        },
    )
    assert signup.status_code in (200, 201), signup.text

    login = client.post(
        "/auth/login",
        json={
            "email": "valid-answer@example.com",
            "password": "TestPassword123!",
        },
    )
    assert login.status_code == 200, login.text

    data = login.json()
    token = data.get("access_token") or data.get("token")
    assert token

    headers = {"Authorization": f"Bearer {token}"}

    start = client.post("/onboarding/start", headers=headers)
    assert start.status_code == 200, start.text

    session_id = start.json()["session_id"]

    response = client.post(
        "/onboarding/answer",
        headers=headers,
        json={
            "session_id": session_id,
            "question_id": "role",
            "answer": "student",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer_saved"] is True
    assert response.json()["question"]["id"] == "education_level"


def test_onboarding_rejects_invalid_role_choice(client):
    signup = client.post(
        "/auth/signup",
        json={
            "email": "invalid-role@example.com",
            "password": "TestPassword123!",
        },
    )
    assert signup.status_code in (200, 201), signup.text

    login = client.post(
        "/auth/login",
        json={
            "email": "invalid-role@example.com",
            "password": "TestPassword123!",
        },
    )
    assert login.status_code == 200, login.text

    token = login.json().get("access_token") or login.json().get("token")
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


def test_onboarding_rejects_wrong_question_id(client):
    signup = client.post(
        "/auth/signup",
        json={
            "email": "wrong-question@example.com",
            "password": "TestPassword123!",
        },
    )
    assert signup.status_code in (200, 201), signup.text

    login = client.post(
        "/auth/login",
        json={
            "email": "wrong-question@example.com",
            "password": "TestPassword123!",
        },
    )
    assert login.status_code == 200, login.text

    token = login.json().get("access_token") or login.json().get("token")
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
