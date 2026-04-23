from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app import build_pair_key, create_app, seed_default_questions
from models import Match, Preferences, Profile, Question, User, UserAnswer, db


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / "test.db"
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "SECRET_KEY": "test-secret",
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "admin-secret",
        }
    )

    with app.app_context():
        db.drop_all()
        db.create_all()
        seed_default_questions(app)

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def get_csrf_token(client, path):
    client.get(path, follow_redirects=True)
    with client.session_transaction() as session:
        return session["_csrf_token"]


def login(client, email, password="password123"):
    csrf_token = get_csrf_token(client, "/login")
    return client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "email": email,
            "password": password,
        },
        follow_redirects=True,
    )


def create_user(
    app,
    email,
    answer_mode="perfect",
    password="password123",
    verified=True,
    is_anonymous=True,
    first_name=None,
    last_name="Test",
    gender="Male",
    vibe="Chill",
    hobbies="Books",
    pref_vibe="Chill",
    pref_hobbies="Books",
):
    with app.app_context():
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            is_verified=verified,
            verified_at=datetime.utcnow() if verified else None,
            is_anonymous=is_anonymous,
        )
        db.session.add(user)
        db.session.flush()

        db.session.add(
            Profile(
                user_id=user.id,
                first_name=first_name or f"User{user.id}",
                last_name=last_name,
                gender=gender,
                department="CSE",
                year_of_study="3rd Year",
                orientation="Straight",
                vibe=vibe,
                hobbies=hobbies,
                relationship_goal="Serious",
                bio=f"Bio for user {user.id}",
                contact_info=f"user{user.id}@chat",
            )
        )
        db.session.add(
            Preferences(
                user_id=user.id,
                pref_gender="Any",
                pref_year="Any",
                pref_vibe=pref_vibe,
                pref_hobbies=pref_hobbies,
            )
        )

        questions = Question.query.order_by(Question.id.asc()).all()
        for question in questions:
            if answer_mode == "perfect":
                my_answer = question.option_a
                preferred_partner_answer = question.option_a
            elif answer_mode == "opposite":
                my_answer = question.option_b
                preferred_partner_answer = question.option_b
            else:
                my_answer = question.option_a
                preferred_partner_answer = question.option_b

            db.session.add(
                UserAnswer(
                    user_id=user.id,
                    question_id=question.id,
                    my_answer=my_answer,
                    preferred_partner_answer=preferred_partner_answer,
                    importance_level=10,
                )
            )

        db.session.commit()
        return user.id


def test_register_requires_csrf(client):
    response = client.post(
        "/register",
        data={"email": "no-csrf@example.com", "password": "password123"},
    )

    assert response.status_code == 400


def test_full_onboarding_flow(client, app):
    csrf_token = get_csrf_token(client, "/register")
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf_token,
            "email": "student@example.com",
            "password": "password123",
        },
        follow_redirects=True,
    )

    assert b"Verify Your Email" in response.data

    with app.app_context():
        user = User.query.filter_by(email="student@example.com").first()
        verification_code = user.verification_code

    csrf_token = get_csrf_token(client, "/verify-email")
    response = client.post(
        "/verify-email",
        data={"csrf_token": csrf_token, "code": verification_code},
        follow_redirects=True,
    )
    assert b"Build Your Profile" in response.data

    csrf_token = get_csrf_token(client, "/create_profile")
    response = client.post(
        "/create_profile",
        data={
            "csrf_token": csrf_token,
            "first_name": "Ava",
            "last_name": "Stone",
            "gender": "Female",
            "department": "CSE",
            "year": "3rd Year",
            "orientation": "Straight",
            "vibe": "Chill",
            "hobbies": "Gaming, Books",
            "relationship_goal": "Serious",
            "bio": "Loves hackathons",
            "contact_info": "ava_discord",
        },
        follow_redirects=True,
    )
    assert b"Partner Preferences" in response.data

    csrf_token = get_csrf_token(client, "/preferences")
    response = client.post(
        "/preferences",
        data={
            "csrf_token": csrf_token,
            "pref_gender": "Any",
            "pref_year": "Any",
            "pref_vibe": "Chill",
            "pref_hobbies": "Gaming",
        },
        follow_redirects=True,
    )
    assert b"Compatibility Questions" in response.data

    with app.app_context():
        questions = Question.query.order_by(Question.id.asc()).all()

    question_payload = {"csrf_token": get_csrf_token(client, "/questions")}
    for question in questions:
        question_payload[f"my_answer_{question.id}"] = question.option_a
        question_payload[f"preferred_partner_answer_{question.id}"] = question.option_a
        question_payload[f"importance_{question.id}"] = "10"

    response = client.post("/questions", data=question_payload, follow_redirects=True)
    assert b"Campus Match Dashboard" in response.data

    with app.app_context():
        user = User.query.filter_by(email="student@example.com").first()
        assert user.is_verified is True
        assert user.profile is not None
        assert user.preferences is not None
        assert UserAnswer.query.filter_by(user_id=user.id).count() == Question.query.count()


def test_dashboard_sorts_by_compatibility(client, app):
    create_user(app, "primary@example.com", answer_mode="perfect")
    high_match_id = create_user(app, "high@example.com", answer_mode="perfect")
    low_match_id = create_user(app, "low@example.com", answer_mode="opposite")

    login(client, "primary@example.com")
    response = client.get("/dashboard")
    html = response.get_data(as_text=True)

    assert f"Student #{high_match_id}" in html
    assert f"Student #{low_match_id}" in html
    assert html.find(f"Student #{high_match_id}") < html.find(f"Student #{low_match_id}")


def test_match_accept_flow_reveals_contact_info(client, app):
    sender_id = create_user(app, "sender@example.com", answer_mode="perfect")
    receiver_id = create_user(app, "receiver@example.com", answer_mode="perfect")

    login(client, "sender@example.com")
    csrf_token = get_csrf_token(client, "/dashboard")
    response = client.post(
        f"/send_interest/{receiver_id}",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert b"Interest sent" in response.data

    client.get("/logout")
    login(client, "receiver@example.com")

    with app.app_context():
        match = Match.query.filter_by(sender_id=sender_id, receiver_id=receiver_id).first()
        assert match is not None
        match_id = match.id

    csrf_token = get_csrf_token(client, "/dashboard")
    response = client.post(
        f"/match/{match_id}/accept",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    assert b"user1@chat" in response.data

    with app.app_context():
        match = db.session.get(Match, match_id)
        assert match.status == "matched"
        assert match.compatibility_score == 100


def test_admin_can_verify_and_delete_user(client, app):
    user_id = create_user(app, "pending@example.com", verified=False)

    csrf_token = get_csrf_token(client, "/admin/login")
    response = client.post(
        "/admin/login",
        data={
            "csrf_token": csrf_token,
            "username": "admin",
            "password": "admin-secret",
        },
        follow_redirects=True,
    )
    assert b"Admin Dashboard" in response.data

    csrf_token = get_csrf_token(client, "/admin")
    client.post(
        f"/admin/user/{user_id}/toggle_verify",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.is_verified is True

    csrf_token = get_csrf_token(client, "/admin")
    client.post(
        f"/admin/user/{user_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    with app.app_context():
        assert db.session.get(User, user_id) is None


def test_invalid_question_importance_shows_error_instead_of_500(client, app):
    create_user(app, "importance@example.com")
    login(client, "importance@example.com")

    with app.app_context():
        questions = Question.query.order_by(Question.id.asc()).all()

    payload = {"csrf_token": get_csrf_token(client, "/questions")}
    for question in questions:
        payload[f"my_answer_{question.id}"] = question.option_a
        payload[f"preferred_partner_answer_{question.id}"] = question.option_a
        payload[f"importance_{question.id}"] = "abc"

    response = client.post("/questions", data=payload, follow_redirects=True)

    assert response.status_code == 200
    assert b"Importance must be Low, Medium, or High." in response.data


def test_anonymous_toggle_changes_dashboard_identity_display(client, app):
    candidate_id = create_user(
        app,
        "anonymous@example.com",
        is_anonymous=True,
        first_name="Visible",
        last_name="Person",
    )
    create_user(app, "seeker@example.com", gender="Female")

    login(client, "seeker@example.com")
    response = client.get("/dashboard")
    assert f"Student #{candidate_id}".encode() in response.data
    assert b"Visible P." not in response.data
    assert b"Hidden until matched" in response.data
    assert b"This student will share more after a mutual match." in response.data
    assert b"Bio for user" not in response.data

    with app.app_context():
        candidate = db.session.get(User, candidate_id)
        candidate.is_anonymous = False
        db.session.commit()

    response = client.get("/dashboard")
    assert b"Visible P." in response.data
    assert f"Student #{candidate_id}".encode() not in response.data
    assert b"Bio for user" in response.data


def test_vibe_and_hobby_preferences_affect_match_order(client, app):
    lower_ranked_id = create_user(
        app,
        "calm@example.com",
        vibe="Chill",
        hobbies="Books, Chess",
    )
    higher_ranked_id = create_user(
        app,
        "party@example.com",
        vibe="Party",
        hobbies="Sports, Music",
    )
    create_user(
        app,
        "prefers-party@example.com",
        gender="Female",
        pref_vibe="Party",
        pref_hobbies="Sports",
    )

    login(client, "prefers-party@example.com")
    html = client.get("/dashboard").get_data(as_text=True)

    assert html.find(f"Student #{higher_ranked_id}") < html.find(f"Student #{lower_ranked_id}")


def test_rejected_pairs_can_retry_interest(client, app):
    sender_id = create_user(app, "retry-sender@example.com")
    receiver_id = create_user(app, "retry-receiver@example.com")

    login(client, "retry-sender@example.com")
    csrf_token = get_csrf_token(client, "/dashboard")
    client.post(
        f"/send_interest/{receiver_id}",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    client.get("/logout")
    login(client, "retry-receiver@example.com")

    with app.app_context():
        match = Match.query.filter_by(sender_id=sender_id, receiver_id=receiver_id).first()
        match_id = match.id

    csrf_token = get_csrf_token(client, "/dashboard")
    client.post(
        f"/match/{match_id}/reject",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    client.get("/logout")
    login(client, "retry-sender@example.com")
    dashboard_response = client.get("/dashboard")
    assert f"Student #{receiver_id}".encode() in dashboard_response.data
    csrf_token = get_csrf_token(client, "/dashboard")
    response = client.post(
        f"/send_interest/{receiver_id}",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    assert b"Interest sent again" in response.data

    with app.app_context():
        matches = Match.query.filter(
            ((Match.sender_id == sender_id) & (Match.receiver_id == receiver_id))
            | ((Match.sender_id == receiver_id) & (Match.receiver_id == sender_id))
        ).all()
        assert len(matches) == 1
        assert matches[0].status == "pending"
        assert matches[0].sender_id == sender_id
        assert matches[0].receiver_id == receiver_id


def test_match_pair_key_is_unique_at_database_level(app):
    sender_id = create_user(app, "db-unique-a@example.com")
    receiver_id = create_user(app, "db-unique-b@example.com")

    with app.app_context():
        db.session.add(
            Match(
                sender_id=sender_id,
                receiver_id=receiver_id,
                pair_key=build_pair_key(sender_id, receiver_id),
                compatibility_score=100,
                status="pending",
            )
        )
        db.session.commit()

        db.session.add(
            Match(
                sender_id=receiver_id,
                receiver_id=sender_id,
                pair_key=build_pair_key(sender_id, receiver_id),
                compatibility_score=100,
                status="pending",
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_production_config_requires_secure_admin_and_email_settings(tmp_path):
    database_path = tmp_path / "prod.db"

    with pytest.raises(RuntimeError):
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "prod-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
                "ADMIN_USERNAME": "admin",
            }
        )
