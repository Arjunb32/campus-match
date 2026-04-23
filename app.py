import hmac
import os
import re
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps

import click
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_migrate import Migrate
from sqlalchemy import and_, inspect, or_
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from models import Match, Preferences, Profile, Question, User, UserAnswer, db


migrate = Migrate()

DEFAULT_QUESTIONS = [
    {
        "text": "What does your ideal weekend usually look like?",
        "option_a": "Quiet plans and deep conversations",
        "option_b": "Busy plans and lots of people",
    },
    {
        "text": "How do you usually show interest in someone?",
        "option_a": "Consistent effort and thoughtful messages",
        "option_b": "Playful energy and spontaneous plans",
    },
    {
        "text": "What matters more in a relationship right now?",
        "option_a": "Stability and emotional safety",
        "option_b": "Adventure and new experiences",
    },
    {
        "text": "When you are stressed, what kind of partner support helps most?",
        "option_a": "Give me calm space first",
        "option_b": "Stay close and talk it out",
    },
]
VALID_IMPORTANCE_LEVELS = {1, 5, 10}


def is_production(app):
    return app.config.get("APP_ENV") == "production" and not app.testing


def get_config_issues(app):
    issues = []

    if is_production(app):
        if not app.config.get("SECRET_KEY"):
            issues.append("SECRET_KEY is required in production.")
        if not app.config.get("ADMIN_USERNAME"):
            issues.append("ADMIN_USERNAME is required in production.")
        if not app.config.get("ADMIN_PASSWORD_HASH"):
            issues.append("ADMIN_PASSWORD_HASH is required in production.")
        if not app.config.get("SMTP_HOST"):
            issues.append("SMTP_HOST is required in production for email verification.")
        if not app.config.get("MAIL_FROM"):
            issues.append("MAIL_FROM is required in production for email verification.")

    smtp_username = app.config.get("SMTP_USERNAME")
    smtp_password = app.config.get("SMTP_PASSWORD")
    if bool(smtp_username) != bool(smtp_password):
        issues.append("SMTP_USERNAME and SMTP_PASSWORD must be set together.")

    return issues


def generate_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def verify_csrf_token():
    expected = session.get("_csrf_token")
    provided = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        abort(400, description="CSRF token missing or invalid.")


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def verified_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if not user:
            session.pop("user_id", None)
            return redirect(url_for("login"))
        if not user.is_verified:
            flash("Verify your email before continuing.")
            return redirect(url_for("verify_email"))
        return view_func(*args, **kwargs)

    return wrapped_view


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def generate_verification_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_verification_code(user, ttl_minutes):
    code = generate_verification_code()
    user.verification_code = code
    user.verification_code_expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
    return code


def send_verification_email(app, email, code):
    smtp_host = app.config.get("SMTP_HOST")
    smtp_port = int(app.config.get("SMTP_PORT", 587))
    smtp_username = app.config.get("SMTP_USERNAME")
    smtp_password = app.config.get("SMTP_PASSWORD")
    mail_from = app.config.get("MAIL_FROM")

    if not smtp_host or not mail_from:
        app.logger.warning("Verification code for %s is %s", email, code)
        return False

    message = EmailMessage()
    message["Subject"] = "Campus Match verification code"
    message["From"] = mail_from
    message["To"] = email
    message.set_content(
        f"Your Campus Match verification code is {code}. "
        f"It expires in {app.config['VERIFICATION_CODE_TTL_MINUTES']} minutes."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.ehlo()
            if app.config.get("SMTP_USE_TLS", True):
                smtp.starttls()
                smtp.ehlo()
            if smtp_username and smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
    except Exception:
        app.logger.exception("Unable to send verification email to %s", email)
        return False

    return True


def notify_verification_code(app, user):
    delivered = send_verification_email(app, user.email, user.verification_code)
    if delivered:
        flash("Verification code sent to your email address.")
        return
    if is_production(app):
        flash("We could not send the verification email right now. Please try again later.")
        return
    flash(f"Development verification code: {user.verification_code}")


def seed_default_questions(app):
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            if "questions" not in inspector.get_table_names():
                return
            if Question.query.count() > 0:
                return
            db.session.add_all([Question(**question) for question in DEFAULT_QUESTIONS])
            db.session.commit()
    except SQLAlchemyError:
        app.logger.exception("Unable to seed default questions.")


def get_next_onboarding_endpoint(user):
    if not user:
        return "login"
    if not user.is_verified:
        return "verify_email"
    if not user.profile:
        return "create_profile"
    if not user.preferences:
        return "set_preferences"
    question_count = Question.query.count()
    answer_count = UserAnswer.query.filter_by(user_id=user.id).count()
    if question_count and answer_count < question_count:
        return "questions"
    return None


def build_answer_map(user_id):
    return {
        answer.question_id: answer
        for answer in UserAnswer.query.filter_by(user_id=user_id).all()
    }


def parse_importance_level(raw_value):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    if value not in VALID_IMPORTANCE_LEVELS:
        return None
    return value


def tokenize_hobbies(value):
    if not value:
        return set()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if token
    }


def calculate_preference_bonus(preferences, profile):
    bonus = 0

    if preferences.pref_vibe and profile.vibe:
        if preferences.pref_vibe == profile.vibe:
            bonus += 20
        else:
            bonus -= 10

    preferred_hobbies = tokenize_hobbies(preferences.pref_hobbies)
    candidate_hobbies = tokenize_hobbies(profile.hobbies)
    if preferred_hobbies and candidate_hobbies:
        shared_hobbies = preferred_hobbies & candidate_hobbies
        if shared_hobbies:
            bonus += min(len(shared_hobbies) * 8, 24)
        else:
            bonus -= 6

    return bonus


def build_pair_key(user_a_id, user_b_id):
    first_id, second_id = sorted((int(user_a_id), int(user_b_id)))
    return f"{first_id}:{second_id}"


def get_display_name(profile, user):
    if user.is_anonymous:
        return f"Student #{profile.user_id}"

    last_initial = f" {profile.last_name[0]}." if profile.last_name else ""
    return f"{profile.first_name}{last_initial}"


def get_visibility_label(user):
    if user.is_anonymous:
        return "Anonymous profile"
    return "Visible profile"


def get_department_display(profile, user):
    if user.is_anonymous:
        return "Hidden until matched"
    return profile.department


def get_bio_display(profile, user):
    if user.is_anonymous:
        return "This student will share more after a mutual match."
    return profile.bio or "No bio added yet."


def get_hobbies_display(profile, user):
    if user.is_anonymous:
        return "Hidden until matched"
    return profile.hobbies


def calculate_compatibility_score(user_id, other_user_id):
    user_answers = build_answer_map(user_id)
    other_answers = build_answer_map(other_user_id)
    shared_question_ids = set(user_answers) & set(other_answers)

    if not shared_question_ids:
        return 0

    earned_points = 0
    total_points = 0

    for question_id in shared_question_ids:
        my_answer = user_answers[question_id]
        their_answer = other_answers[question_id]

        my_weight = max(int(my_answer.importance_level or 1), 1)
        their_weight = max(int(their_answer.importance_level or 1), 1)
        total_points += my_weight + their_weight

        if their_answer.my_answer == my_answer.preferred_partner_answer:
            earned_points += my_weight
        if my_answer.my_answer == their_answer.preferred_partner_answer:
            earned_points += their_weight

    return round((earned_points / total_points) * 100) if total_points else 0


def get_admin_credentials(app):
    username = app.config.get("ADMIN_USERNAME")
    password_hash = app.config.get("ADMIN_PASSWORD_HASH")
    password = app.config.get("ADMIN_PASSWORD")

    if username and (password_hash or password):
        return username, password_hash, password

    if is_production(app):
        return None, None, None

    if not app.config.get("_DEV_ADMIN_PASSWORD"):
        app.config["_DEV_ADMIN_USERNAME"] = "admin"
        app.config["_DEV_ADMIN_PASSWORD"] = secrets.token_urlsafe(12)
        app.logger.warning(
            "Development admin credentials generated. username=%s password=%s",
            app.config["_DEV_ADMIN_USERNAME"],
            app.config["_DEV_ADMIN_PASSWORD"],
        )

    return (
        app.config["_DEV_ADMIN_USERNAME"],
        None,
        app.config["_DEV_ADMIN_PASSWORD"],
    )


def is_valid_admin_login(app, username, password):
    admin_username, admin_password_hash, admin_password = get_admin_credentials(app)
    if not admin_username:
        return False
    if not hmac.compare_digest(username, admin_username):
        return False
    if admin_password_hash:
        return check_password_hash(admin_password_hash, password)
    return bool(admin_password) and hmac.compare_digest(password, admin_password)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        APP_ENV=os.environ.get("FLASK_ENV", "development"),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///matchmaker.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        VERIFICATION_CODE_TTL_MINUTES=10,
        ENABLE_CSRF=True,
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
        ADMIN_PASSWORD_HASH=os.environ.get("ADMIN_PASSWORD_HASH"),
        SMTP_HOST=os.environ.get("SMTP_HOST"),
        SMTP_PORT=os.environ.get("SMTP_PORT", "587"),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME"),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD"),
        SMTP_USE_TLS=os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
        MAIL_FROM=os.environ.get("MAIL_FROM"),
    )

    if test_config:
        app.config.update(test_config)

    database_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if database_uri.startswith("postgres://"):
        app.config["SQLALCHEMY_DATABASE_URI"] = database_uri.replace(
            "postgres://", "postgresql://", 1
        )

    if not app.config.get("SECRET_KEY"):
        if is_production(app):
            raise RuntimeError("SECRET_KEY must be set in production.")
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    config_issues = get_config_issues(app)
    if config_issues and is_production(app):
        raise RuntimeError("Production configuration errors: " + " ".join(config_issues))

    app.config["SESSION_COOKIE_SECURE"] = is_production(app)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    @app.before_request
    def csrf_protect():
        if not app.config.get("ENABLE_CSRF", True):
            return
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        if request.endpoint == "static":
            return
        verify_csrf_token()

    @app.context_processor
    def inject_template_helpers():
        return {"csrf_token": generate_csrf_token}

    @app.cli.command("seed-questions")
    def seed_questions_command():
        seed_default_questions(app)
        click.echo("Question bank checked.")

    @app.cli.command("check-config")
    def check_config_command():
        issues = get_config_issues(app)
        if issues:
            for issue in issues:
                click.echo(f"- {issue}")
            raise click.ClickException("Configuration issues found.")
        click.echo("Configuration looks good.")

    @app.route("/")
    def home():
        user = get_current_user()
        if user:
            next_step = get_next_onboarding_endpoint(user)
            if next_step:
                return redirect(url_for(next_step))
            return redirect(url_for("dashboard"))
        return (
            "<h1>Campus Match</h1>"
            " <a href='/register'>Sign Up</a> | <a href='/login'>Login</a> |"
            " <a href='/admin/login'>Admin</a>"
        )

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email = request.form["email"].strip().lower()
            password = request.form["password"]

            if len(password) < 8:
                flash("Password must be at least 8 characters long.")
                return render_template("register.html")

            if User.query.filter_by(email=email).first():
                flash("Email already registered. Please log in instead.")
                return render_template("register.html")

            user = User(email=email, password_hash=generate_password_hash(password))
            issue_verification_code(user, app.config["VERIFICATION_CODE_TTL_MINUTES"])
            db.session.add(user)
            db.session.commit()

            session.clear()
            session["user_id"] = user.id
            notify_verification_code(app, user)
            return redirect(url_for("verify_email"))

        return render_template("register.html")

    @app.route("/verify-email", methods=["GET", "POST"])
    @login_required
    def verify_email():
        user = get_current_user()
        if not user:
            session.pop("user_id", None)
            return redirect(url_for("login"))
        if user.is_verified:
            next_step = get_next_onboarding_endpoint(user)
            return redirect(url_for(next_step or "dashboard"))

        if request.method == "POST":
            code = request.form["code"].strip()
            if user.verification_code != code:
                flash("Invalid verification code.")
                return render_template("verify_email.html", user=user)
            if (
                user.verification_code_expires_at
                and user.verification_code_expires_at < datetime.utcnow()
            ):
                flash("Verification code expired. Request a new code.")
                return render_template("verify_email.html", user=user)

            user.is_verified = True
            user.verified_at = datetime.utcnow()
            user.verification_code = None
            user.verification_code_expires_at = None
            db.session.commit()

            flash("Email verified. You can finish setting up your profile now.")
            return redirect(url_for("create_profile"))

        return render_template("verify_email.html", user=user)

    @app.route("/resend-verification", methods=["POST"])
    @login_required
    def resend_verification():
        user = get_current_user()
        if not user:
            session.pop("user_id", None)
            return redirect(url_for("login"))
        if user.is_verified:
            flash("Your email is already verified.")
            return redirect(url_for("dashboard"))

        issue_verification_code(user, app.config["VERIFICATION_CODE_TTL_MINUTES"])
        db.session.commit()
        notify_verification_code(app, user)
        return redirect(url_for("verify_email"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            user = User.query.filter_by(email=email).first()

            if not user or not check_password_hash(user.password_hash, password):
                flash("Invalid email or password.")
                return render_template("login.html")

            session.pop("is_admin", None)
            session["user_id"] = user.id
            next_step = get_next_onboarding_endpoint(user)
            return redirect(url_for(next_step or "dashboard"))

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.pop("user_id", None)
        return redirect(url_for("login"))

    @app.route("/create_profile", methods=["GET", "POST"])
    @login_required
    @verified_required
    def create_profile():
        user = get_current_user()
        profile = user.profile or Profile(user_id=user.id)

        if request.method == "POST":
            profile.first_name = request.form["first_name"].strip()
            profile.last_name = request.form["last_name"].strip()
            profile.gender = request.form["gender"]
            profile.department = request.form["department"].strip()
            profile.year_of_study = request.form["year"]
            profile.orientation = request.form["orientation"]
            profile.vibe = request.form["vibe"]
            profile.hobbies = request.form.get("hobbies", "").strip() or None
            profile.relationship_goal = request.form["relationship_goal"]
            profile.bio = request.form["bio"].strip()
            profile.contact_info = request.form["contact_info"].strip()

            if not user.profile:
                db.session.add(profile)
            db.session.commit()
            flash("Profile saved.")
            return redirect(url_for("set_preferences"))

        return render_template("create_profile.html", profile=profile)

    @app.route("/preferences", methods=["GET", "POST"])
    @login_required
    @verified_required
    def set_preferences():
        user = get_current_user()
        if not user.profile:
            flash("Create your profile first.")
            return redirect(url_for("create_profile"))

        preferences = user.preferences or Preferences(user_id=user.id)

        if request.method == "POST":
            preferences.pref_gender = request.form["pref_gender"]
            preferences.pref_year = request.form["pref_year"]
            preferences.pref_vibe = request.form["pref_vibe"]
            preferences.pref_hobbies = request.form.get("pref_hobbies", "").strip()

            if not user.preferences:
                db.session.add(preferences)
            db.session.commit()
            flash("Preferences saved.")
            return redirect(url_for("questions"))

        return render_template("preferences.html", preferences=preferences)

    @app.route("/questions", methods=["GET", "POST"])
    @login_required
    @verified_required
    def questions():
        user = get_current_user()
        if not user.profile:
            flash("Create your profile first.")
            return redirect(url_for("create_profile"))
        if not user.preferences:
            flash("Set your preferences first.")
            return redirect(url_for("set_preferences"))

        question_list = Question.query.order_by(Question.id.asc()).all()
        existing_answers = {
            answer.question_id: answer
            for answer in UserAnswer.query.filter_by(user_id=user.id).all()
        }

        if request.method == "POST":
            for question in question_list:
                my_answer = request.form.get(f"my_answer_{question.id}")
                preferred_partner_answer = request.form.get(
                    f"preferred_partner_answer_{question.id}"
                )
                importance_level = parse_importance_level(
                    request.form.get(f"importance_{question.id}", "5")
                )

                if not my_answer or not preferred_partner_answer:
                    flash("Answer every compatibility question before continuing.")
                    return render_template(
                        "questions.html",
                        questions=question_list,
                        existing_answers=existing_answers,
                    )

                if my_answer not in {question.option_a, question.option_b}:
                    flash("One of your answers used an invalid option. Please try again.")
                    return render_template(
                        "questions.html",
                        questions=question_list,
                        existing_answers=existing_answers,
                    )

                if preferred_partner_answer not in {question.option_a, question.option_b}:
                    flash("One preferred answer used an invalid option. Please try again.")
                    return render_template(
                        "questions.html",
                        questions=question_list,
                        existing_answers=existing_answers,
                    )

                if importance_level is None:
                    flash("Importance must be Low, Medium, or High.")
                    return render_template(
                        "questions.html",
                        questions=question_list,
                        existing_answers=existing_answers,
                    )

                answer = existing_answers.get(question.id) or UserAnswer(
                    user_id=user.id,
                    question_id=question.id,
                )
                answer.my_answer = my_answer
                answer.preferred_partner_answer = preferred_partner_answer
                answer.importance_level = importance_level

                if question.id not in existing_answers:
                    db.session.add(answer)

            db.session.commit()
            flash("Compatibility answers saved.")
            return redirect(url_for("dashboard"))

        return render_template(
            "questions.html",
            questions=question_list,
            existing_answers=existing_answers,
        )

    @app.route("/dashboard")
    @login_required
    @verified_required
    def dashboard():
        user = get_current_user()
        next_step = get_next_onboarding_endpoint(user)
        if next_step:
            return redirect(url_for(next_step))

        my_prefs = user.preferences
        current_user_id = user.id

        pending_incoming = (
            Match.query.filter_by(receiver_id=current_user_id, status="pending")
            .order_by(Match.created_at.desc())
            .all()
        )
        incoming_requests = []
        for match in pending_incoming:
            sender_profile = Profile.query.filter_by(user_id=match.sender_id).first()
            sender_user = db.session.get(User, match.sender_id)
            if sender_profile and sender_user:
                incoming_requests.append(
                    {
                        "match": match,
                        "profile": sender_profile,
                        "sender": sender_user,
                    }
                )

        existing_connections = {
            frozenset({match.sender_id, match.receiver_id})
            for match in Match.query.filter(
                or_(Match.sender_id == current_user_id, Match.receiver_id == current_user_id),
                Match.status != "rejected",
            ).all()
        }

        query = (
            Profile.query.join(User, User.id == Profile.user_id)
            .filter(Profile.user_id != current_user_id, User.is_verified.is_(True))
            .order_by(Profile.id.asc())
        )

        if my_prefs.pref_gender != "Any":
            query = query.filter(Profile.gender == my_prefs.pref_gender)
        if my_prefs.pref_year != "Any":
            query = query.filter(Profile.year_of_study == my_prefs.pref_year)

        matches = []
        for profile in query.all():
            candidate_user = db.session.get(User, profile.user_id)
            if not candidate_user:
                continue
            if frozenset({current_user_id, profile.user_id}) in existing_connections:
                continue

            preference_bonus = calculate_preference_bonus(my_prefs, profile)
            matches.append(
                {
                    "profile": profile,
                    "user": candidate_user,
                    "display_name": get_display_name(profile, candidate_user),
                    "visibility_label": get_visibility_label(candidate_user),
                    "department_display": get_department_display(profile, candidate_user),
                    "bio_display": get_bio_display(profile, candidate_user),
                    "hobbies_display": get_hobbies_display(profile, candidate_user),
                    "compatibility_score": calculate_compatibility_score(
                        current_user_id, profile.user_id
                    ),
                    "preference_bonus": preference_bonus,
                }
            )

        matches.sort(
            key=lambda item: (
                item["compatibility_score"] + item["preference_bonus"],
                item["compatibility_score"],
                item["profile"].id,
            ),
            reverse=True,
        )

        for item in incoming_requests:
            item["display_name"] = get_display_name(item["profile"], item["sender"])
            item["visibility_label"] = get_visibility_label(item["sender"])
            item["department_display"] = get_department_display(item["profile"], item["sender"])
            item["bio_display"] = get_bio_display(item["profile"], item["sender"])
            item["hobbies_display"] = get_hobbies_display(item["profile"], item["sender"])

        sent_pending_count = Match.query.filter_by(
            sender_id=current_user_id, status="pending"
        ).count()
        matched_count = Match.query.filter(
            or_(Match.sender_id == current_user_id, Match.receiver_id == current_user_id),
            Match.status == "matched",
        ).count()

        return render_template(
            "dashboard.html",
            matches=matches,
            incoming_requests=incoming_requests,
            sent_pending_count=sent_pending_count,
            matched_count=matched_count,
        )

    @app.route("/send_interest/<int:receiver_id>", methods=["POST"])
    @login_required
    @verified_required
    def send_interest(receiver_id):
        sender_id = session["user_id"]

        if sender_id == receiver_id:
            flash("You cannot send interest to yourself.")
            return redirect(url_for("dashboard"))

        receiver = db.session.get(User, receiver_id)
        receiver_profile = Profile.query.filter_by(user_id=receiver_id).first()
        if not receiver or not receiver.is_verified or not receiver_profile:
            flash("That profile is not available right now.")
            return redirect(url_for("dashboard"))

        pair_key = build_pair_key(sender_id, receiver_id)
        existing = Match.query.filter_by(pair_key=pair_key).first()

        if existing:
            if existing.status == "rejected":
                existing.sender_id = sender_id
                existing.receiver_id = receiver_id
                existing.pair_key = pair_key
                existing.compatibility_score = calculate_compatibility_score(
                    sender_id, receiver_id
                )
                existing.status = "pending"
                existing.created_at = datetime.utcnow()
                db.session.commit()
                flash("Interest sent again. The other student can review it now.")
                return redirect(url_for("dashboard"))
            flash("Interest already exists for this profile.")
            return redirect(url_for("dashboard"))

        new_match = Match(
            sender_id=sender_id,
            receiver_id=receiver_id,
            pair_key=pair_key,
            compatibility_score=calculate_compatibility_score(sender_id, receiver_id),
            status="pending",
        )
        db.session.add(new_match)
        db.session.commit()

        flash("Interest sent. The other student can now accept or reject it.")
        return redirect(url_for("dashboard"))

    @app.route("/match/<int:match_id>/accept", methods=["POST"])
    @login_required
    @verified_required
    def accept_match(match_id):
        match = Match.query.filter_by(
            id=match_id, receiver_id=session["user_id"], status="pending"
        ).first_or_404()
        match.status = "matched"
        match.compatibility_score = calculate_compatibility_score(
            match.sender_id, match.receiver_id
        )
        db.session.commit()
        flash("Match accepted. Contact details are now visible in My Matches.")
        return redirect(url_for("my_matches"))

    @app.route("/match/<int:match_id>/reject", methods=["POST"])
    @login_required
    @verified_required
    def reject_match(match_id):
        match = Match.query.filter_by(
            id=match_id, receiver_id=session["user_id"], status="pending"
        ).first_or_404()
        match.status = "rejected"
        db.session.commit()
        flash("Match request rejected.")
        return redirect(url_for("dashboard"))

    @app.route("/my_matches")
    @login_required
    @verified_required
    def my_matches():
        current_user_id = session["user_id"]
        matched_rows = (
            Match.query.filter(
                or_(Match.sender_id == current_user_id, Match.receiver_id == current_user_id),
                Match.status == "matched",
            )
            .order_by(Match.created_at.desc())
            .all()
        )

        matched_profiles = []
        for match in matched_rows:
            other_user_id = (
                match.receiver_id if match.sender_id == current_user_id else match.sender_id
            )
            profile = Profile.query.filter_by(user_id=other_user_id).first()
            if profile:
                matched_profiles.append({"profile": profile, "match": match})

        return render_template("my_matches.html", matches=matched_profiles)

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))

        if request.method == "GET" and not is_production(app):
            get_admin_credentials(app)

        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"]

            if not get_admin_credentials(app)[0]:
                flash("Admin credentials are not configured.")
                return render_template("admin_login.html")

            if is_valid_admin_login(app, username, password):
                session["is_admin"] = True
                return redirect(url_for("admin_dashboard"))

            flash("Invalid admin credentials.")

        return render_template("admin_login.html")

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("is_admin", None)
        return redirect(url_for("admin_login"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        users = User.query.order_by(User.created_at.desc()).all()
        prefs_by_user = {pref.user_id: pref for pref in Preferences.query.all()}

        match_counts = {}
        for match in Match.query.all():
            match_counts[match.sender_id] = match_counts.get(match.sender_id, 0) + 1
            match_counts[match.receiver_id] = match_counts.get(match.receiver_id, 0) + 1

        stats = {
            "total_users": User.query.count(),
            "verified_users": User.query.filter_by(is_verified=True).count(),
            "profiled_users": Profile.query.count(),
            "matched_pairs": Match.query.filter_by(status="matched").count(),
            "pending_pairs": Match.query.filter_by(status="pending").count(),
        }

        return render_template(
            "admin_dashboard.html",
            users=users,
            prefs_by_user=prefs_by_user,
            match_counts=match_counts,
            stats=stats,
        )

    @app.route("/admin/user/<int:user_id>/toggle_verify", methods=["POST"])
    @admin_required
    def admin_toggle_verify(user_id):
        user = db.session.get(User, user_id)
        if not user:
            abort(404)
        user.is_verified = not user.is_verified
        if user.is_verified:
            user.verified_at = datetime.utcnow()
            user.verification_code = None
            user.verification_code_expires_at = None
        db.session.commit()
        flash(f"Verification updated for {user.email}.")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/user/<int:user_id>/toggle_anonymous", methods=["POST"])
    @admin_required
    def admin_toggle_anonymous(user_id):
        user = db.session.get(User, user_id)
        if not user:
            abort(404)
        user.is_anonymous = not user.is_anonymous
        db.session.commit()
        flash(f"Anonymity updated for {user.email}.")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
    @admin_required
    def admin_delete_user(user_id):
        user = db.session.get(User, user_id)
        if not user:
            abort(404)
        email = user.email

        Match.query.filter(
            or_(Match.sender_id == user_id, Match.receiver_id == user_id)
        ).delete(synchronize_session=False)
        db.session.delete(user)
        db.session.commit()

        flash(f"Deleted user and related data: {email}")
        return redirect(url_for("admin_dashboard"))

    seed_default_questions(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=not is_production(app), host="0.0.0.0")
