from app import app

# Vercel requires a WSGI application
# Create a serverless-compatible version
import sys
import os

# Ensure we're in the right directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# For Vercel deployment - the WSGI application
application = app

# Optional: Add error handling for Vercel
if __name__ == "__main__":
    print("[*] Starting Smart Template Generator in local mode...")
    print("[*] Server running on http://localhost:5000")
    app.run(debug=True, port=5000, use_reloader=False)