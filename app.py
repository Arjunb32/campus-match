from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
# IMPORT THE NEW 'Preferences' MODEL
from models import db, User, Profile, Match, Preferences 

app = Flask(__name__)
import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Profile, Match, Preferences

app = Flask(__name__)

# --- PRODUCTION CONFIG ---
# Use environment variable for secret key, fallback for local dev
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-only-for-local')

# Database: Use PostgreSQL in production, SQLite locally
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Render provides PostgreSQL URL starting with postgres://, SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///matchmaker.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

@app.route('/')
def home():
    return "<h1>Campus Match</h1> <a href='/register'>Sign Up</a> | <a href='/login'>Login</a>"

# --- REGISTRATION FLOW ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            return "Email taken. <a href='/login'>Login</a>"
        
        new_user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        
        session['user_id'] = new_user.id
        # Step 1: Go to Profile Creation
        return redirect(url_for('create_profile')) 
    return render_template('register.html')

@app.route('/create_profile', methods=['GET', 'POST'])
def create_profile():
    if 'user_id' not in session: return redirect(url_for('login'))

    if request.method == 'POST':
        # Get data from form
        new_profile = Profile(
            user_id=session['user_id'],
            first_name=request.form['first_name'],
            last_name=request.form['last_name'],
            gender=request.form['gender'],
            department=request.form['department'],
            year_of_study=request.form['year'],
            orientation=request.form['orientation'],
            relationship_goal=request.form['relationship_goal'],
            bio=request.form['bio'],
            contact_info=request.form['contact_info']  # <--- NEW FIELD SAVED HERE
        )

        db.session.add(new_profile)
        db.session.commit()
        
        return redirect(url_for('set_preferences'))

    return render_template('create_profile.html')

# --- NEW: PREFERENCES ROUTE ---
@app.route('/preferences', methods=['GET', 'POST'])
def set_preferences():
    if 'user_id' not in session: return redirect(url_for('login'))

    if request.method == 'POST':
        # Save their ideal partner choices
        new_pref = Preferences(
            user_id=session['user_id'],
            pref_gender=request.form['pref_gender'],
            pref_year=request.form['pref_year'],
            pref_vibe=request.form['pref_vibe']
        )
        db.session.add(new_pref)
        db.session.commit()
        # Step 3: Go to Dashboard (Finally!)
        return redirect(url_for('dashboard'))

    return render_template('preferences.html')

# --- LOGIC: THE MATCHING DASHBOARD ---
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    current_user_id = session['user_id']

    # 1. Get the user's preferences
    my_prefs = Preferences.query.filter_by(user_id=current_user_id).first()
    
    # If they haven't set preferences, send them back to that page
    if not my_prefs:
        return redirect(url_for('set_preferences'))

    # 2. Start with Everyone
    query = Profile.query.filter(Profile.user_id != current_user_id)

    # 3. Apply Filters based on Preferences
    
    # Filter by Gender (if they didn't say "Any")
    if my_prefs.pref_gender != "Any":
        query = query.filter(Profile.gender == my_prefs.pref_gender)
    
    # Filter by Year (if they didn't say "Any")
    if my_prefs.pref_year != "Any":
        query = query.filter(Profile.year_of_study == my_prefs.pref_year)

    # (Optional) Filter by Vibe - You would need to add 'vibe' to Profile to match this!
    # For now, we will just show the matches based on Gender and Year.
    
    matches = query.all()

    return render_template('dashboard.html', matches=matches)

# ... (Keep your Login, Logout, and Send Interest routes exactly as they were) ...
# Paste the 'login', 'send_interest', and 'logout' functions here from your old file.

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/send_interest/<int:receiver_id>', methods=['POST'])
def send_interest(receiver_id):
    # 1. Check if user is logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    sender_id = session['user_id']
    
    # 2. Prevent sending interest to yourself
    if sender_id == receiver_id:
        flash("You can't match with yourself!")
        return redirect(url_for('dashboard'))
    
    # 3. Check if match already exists (either direction)
    existing = Match.query.filter(
        ((Match.sender_id == sender_id) & (Match.receiver_id == receiver_id)) |
        ((Match.sender_id == receiver_id) & (Match.receiver_id == sender_id))
    ).first()
    
    if existing:
        flash("Interest already sent or match already exists!")
        return redirect(url_for('dashboard'))
    
    # 4. Create new match request with status 'pending'
    new_match = Match(
        sender_id=sender_id,
        receiver_id=receiver_id,
        compatibility_score=0,  # You can add scoring logic later
        status='pending'
    )
    
    db.session.add(new_match)
    db.session.commit()
    
    flash("Interest sent! Waiting for their response.")
    return redirect(url_for('dashboard'))

# Create tables on startup (for first deploy)
with app.app_context():
    db.create_all()
    print("Database tables created/verified!")

if __name__ == "__main__":
    # host='0.0.0.0' allows other devices on the network to connect
    app.run(debug=True, host='0.0.0.0')