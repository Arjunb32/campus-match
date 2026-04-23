# Campus Match

Campus Match is a Flask app for student matchmaking with email verification, compatibility questions, private contact reveal on matched pairs, and an admin dashboard.

## Features

- Email verification with 6-digit codes
- CSRF protection on all form submissions
- Compatibility scoring from saved question answers
- Pending, matched, and rejected match states
- Admin controls for verification, anonymity, and deletion
- Flask-Migrate based schema migrations
- Pytest coverage for auth, onboarding, matching, and admin flows

## Local setup

1. Create and activate a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Set environment variables if you want persistent local secrets:
   - `SECRET_KEY`
   - `ADMIN_USERNAME`
   - `ADMIN_PASSWORD_HASH` or `ADMIN_PASSWORD`
   - `SMTP_HOST` and `MAIL_FROM` if you want real email delivery
4. Run migrations with `flask db upgrade`.
5. Start the app with `flask run` or `gunicorn app:app`.

If admin credentials are not set in non-production, the app generates a temporary development password and writes it to the server log.

## Email verification

To send real verification emails, configure:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS`
- `MAIL_FROM`

Without SMTP in non-production, the app logs the verification code and flashes it on screen for development.

In production, the app now fails fast if `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `SMTP_HOST`, or `MAIL_FROM` are missing.

## Database migrations

Initialize the database with:

```bash
flask db upgrade
flask seed-questions
```

You can also run a config preflight before deploy:

```bash
flask check-config
```

Create a new migration after model changes with:

```bash
flask db migrate -m "describe change"
flask db upgrade
```

## Tests

Run the suite with:

```bash
pytest
```

## Admin password hash helper

You can generate a hashed admin password with:

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('change-me'))"
```
