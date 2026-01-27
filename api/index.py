import sys
import os

# Set Playwright environment variables for Vercel
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '/tmp/.playwright'
os.environ['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '0'

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import the Flask app
from app import app as application

# Export for Vercel
app = application
