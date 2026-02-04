from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Initialize the database instance
db = SQLAlchemy()

# 1. THE USER MODEL (Authentication & Account Security)
class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    # College Email serves as the unique ID for verification
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    
    # Verification Flags
    is_verified = db.Column(db.Boolean, default=False) # False until they click the email link
    verification_code = db.Column(db.String(6), nullable=True) # Stores the 6-digit OTP
    
    # Privacy Settings
    is_anonymous = db.Column(db.Boolean, default=True) # If True, name/photo are hidden in search
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    profile = db.relationship('Profile', backref='user', uselist=False)
    answers = db.relationship('UserAnswer', backref='user', lazy=True)

    def __repr__(self):
        return f'<User {self.email}>'


# 2. THE PROFILE MODEL (Demographics & Display Info)
class Profile(db.Model):
    __tablename__ = 'profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Identity (Hidden in "Blind Mode")
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    profile_pic = db.Column(db.String(255), default='default_avatar.png')
    
    # Matching Criteria (Visible in "Blind Mode")
    gender = db.Column(db.String(20), nullable=False)  # e.g., 'Male', 'Female', 'Non-binary'
    orientation = db.Column(db.String(20), nullable=False) # e.g., 'Straight', 'Gay', 'Bi'
    
    # College Specifics
    year_of_study = db.Column(db.String(10), nullable=False) # e.g., '3rd Year'
    department = db.Column(db.String(50), nullable=False)    # e.g., 'Computer Science'
    
    # Personality
    bio = db.Column(db.Text, nullable=True)
    relationship_goal = db.Column(db.String(50), nullable=False) # e.g., 'Serious', 'Casual', 'Study Partner'

    # In models.py, inside class Profile(db.Model):

    # ... keep your existing columns ...
    relationship_goal = db.Column(db.String(50), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    
    # NEW: The Secret Contact Field
    contact_info = db.Column(db.String(100), nullable=False) # e.g. "Insta: @arjun_k"

    def __repr__(self):
        return f'<Profile {self.first_name} - {self.department}>'


# 3. THE QUESTION BANK (Static questions for everyone)
class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255), nullable=False) # e.g., "Are you messy or tidy?"
    option_a = db.Column(db.String(100), nullable=False)
    option_b = db.Column(db.String(100), nullable=False)
    # You can add more options or make it dynamic later


# 4. THE COMPATIBILITY ENGINE (User Answers)
class UserAnswer(db.Model):
    __tablename__ = 'user_answers'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    
    # The Logic: "I am X, looking for Y, and it matters Z amount"
    my_answer = db.Column(db.String(100), nullable=False)
    preferred_partner_answer = db.Column(db.String(100), nullable=False)
    
    # Importance Weight: 0=Irrelevant, 1=Little, 5=Very Important, 10=Mandatory
    importance_level = db.Column(db.Integer, default=5)


# 5. THE MATCH SYSTEM (Handling the "Blind" Reveal)
class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.Integer, primary_key=True)
    
    # Who is involved?
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # The Match Score (Cached here so we don't recalculate every time)
    compatibility_score = db.Column(db.Integer, nullable=False) # e.g., 85
    
    # Status of the Match
    # 'pending' = Sender liked Receiver (Receiver sees blurred request)
    # 'matched' = Receiver accepted (Profiles Revealed)
    # 'rejected' = Receiver declined
    # 'blocked' = Safety feature
    status = db.Column(db.String(20), default='pending')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 6. THE PREFERENCES MODEL (What they are looking for)
class Preferences(db.Model):
    __tablename__ = 'preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Who are they looking for?
    pref_gender = db.Column(db.String(20), nullable=False) # e.g. "Female"
    pref_year = db.Column(db.String(20), nullable=False)   # e.g. "Any" or "3rd Year"
    
    # Compatibility Questions
    pref_vibe = db.Column(db.String(50), nullable=False)   # e.g. "Chill" or "Party"
    pref_hobbies = db.Column(db.String(100), nullable=True) # e.g. "Movies, Gaming"

    def __repr__(self):
        return f'<Pref {self.user_id}>'