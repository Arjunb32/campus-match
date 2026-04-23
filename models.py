from datetime import datetime

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_code_expires_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    is_anonymous = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    profile = db.relationship(
        "Profile",
        backref="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    preferences = db.relationship(
        "Preferences",
        backref="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    answers = db.relationship(
        "UserAnswer",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User {self.email}>"


class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    profile_pic = db.Column(db.String(255), default="default_avatar.png")
    gender = db.Column(db.String(20), nullable=False)
    orientation = db.Column(db.String(20), nullable=False)
    year_of_study = db.Column(db.String(20), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    vibe = db.Column(db.String(50), nullable=True)
    hobbies = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    relationship_goal = db.Column(db.String(50), nullable=False)
    contact_info = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Profile {self.first_name} - {self.department}>"


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255), nullable=False)
    option_a = db.Column(db.String(100), nullable=False)
    option_b = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Question {self.id}>"


class UserAnswer(db.Model):
    __tablename__ = "user_answers"
    __table_args__ = (
        db.UniqueConstraint("user_id", "question_id", name="uq_user_answers_user_question"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    my_answer = db.Column(db.String(100), nullable=False)
    preferred_partner_answer = db.Column(db.String(100), nullable=False)
    importance_level = db.Column(db.Integer, default=5, nullable=False)

    question = db.relationship("Question", backref="answers")

    def __repr__(self):
        return f"<UserAnswer user={self.user_id} question={self.question_id}>"


class Match(db.Model):
    __tablename__ = "matches"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    pair_key = db.Column(db.String(64), unique=True, nullable=False)
    compatibility_score = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), default="pending", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Match {self.sender_id}->{self.receiver_id} {self.status}>"


class Preferences(db.Model):
    __tablename__ = "preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    pref_gender = db.Column(db.String(20), nullable=False)
    pref_year = db.Column(db.String(20), nullable=False)
    pref_vibe = db.Column(db.String(50), nullable=False)
    pref_hobbies = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f"<Pref {self.user_id}>"
