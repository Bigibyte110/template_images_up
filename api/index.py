import sys
import os
from werkzeug.wrappers import Request, Response

# Add parent directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import your Flask app
from app import app

# Vercel handler
@Request.application
def handler(request):
    # Convert Vercel request to Flask request and get response
    with app.request_context(request.environ):
        response = app.full_dispatch_request()
    return response
