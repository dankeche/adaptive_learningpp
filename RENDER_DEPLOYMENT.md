# Render deployment

## Build Command
pip install -r requirements.txt

## Start Command
gunicorn app:app

## Environment variables
SECRET_KEY=<generate-a-long-random-secret>
DATABASE_URL=<copy the Internal Database URL from your Render PostgreSQL service>

## Database
Run `schema.sql` against the Render PostgreSQL database before testing the app.

## Health check
/health
