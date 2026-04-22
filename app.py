import os
import hmac
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Profile, Match, Preferences, UserAnswer

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


def get_admin_credentials():
    """Read admin credentials from environment with local defaults."""
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_password_hash = os.environ.get('ADMIN_PASSWORD_HASH')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
    return admin_username, admin_password_hash, admin_password


def is_valid_admin_login(username, password):
    admin_username, admin_password_hash, admin_password = get_admin_credentials()
    valid_username = hmac.compare_digest(username, admin_username)
    if not valid_username:
        return False

    if admin_password_hash:
        return check_password_hash(admin_password_hash, password)

    return hmac.compare_digest(password, admin_password)


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return view_func(*args, **kwargs)
    return wrapped_view

@app.route('/')
def home():
    return "<h1>Campus Match</h1> <a href='/register'>Sign Up</a> | <a href='/login'>Login</a> | <a href='/admin/login'>Admin</a>"


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        if is_valid_admin_login(username, password):
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))

        flash('Invalid admin credentials')

    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    prefs_by_user = {pref.user_id: pref for pref in Preferences.query.all()}

    match_counts = {}
    for match in Match.query.all():
        match_counts[match.sender_id] = match_counts.get(match.sender_id, 0) + 1
        match_counts[match.receiver_id] = match_counts.get(match.receiver_id, 0) + 1

    stats = {
        'total_users': User.query.count(),
        'verified_users': User.query.filter_by(is_verified=True).count(),
        'profiled_users': Profile.query.count(),
        'matched_pairs': Match.query.filter_by(status='matched').count(),
    }

    return render_template(
        'admin_dashboard.html',
        users=users,
        prefs_by_user=prefs_by_user,
        match_counts=match_counts,
        stats=stats
    )


@app.route('/admin/user/<int:user_id>/toggle_verify', methods=['POST'])
@admin_required
def admin_toggle_verify(user_id):
    user = User.query.get_or_404(user_id)
    user.is_verified = not user.is_verified
    db.session.commit()
    flash(f"Verification updated for {user.email}")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<int:user_id>/toggle_anonymous', methods=['POST'])
@admin_required
def admin_toggle_anonymous(user_id):
    user = User.query.get_or_404(user_id)
    user.is_anonymous = not user.is_anonymous
    db.session.commit()
    flash(f"Anonymity updated for {user.email}")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    email = user.email

    Match.query.filter(
        (Match.sender_id == user_id) | (Match.receiver_id == user_id)
    ).delete(synchronize_session=False)
    UserAnswer.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Preferences.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Profile.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()

    flash(f"Deleted user and related data: {email}")
    return redirect(url_for('admin_dashboard'))

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

@app.route('/my_matches')
def my_matches():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    current_user_id = session['user_id']
    
    # Get all matches where status is 'matched' (both sent and received)
    matched_users = Match.query.filter(
        ((Match.sender_id == current_user_id) | (Match.receiver_id == current_user_id)),
        Match.status == 'matched'
    ).all()
    
    # Get the profiles of matched users
    matched_profiles = []
    for match in matched_users:
        other_user_id = match.receiver_id if match.sender_id == current_user_id else match.sender_id
        profile = Profile.query.filter_by(user_id=other_user_id).first()
        if profile:
            matched_profiles.append(profile)
    
    return render_template('my_matches.html', matches=matched_profiles)

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
