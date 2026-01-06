#!/usr/bin/env python3
"""
Simple script to run the web application
"""
from app import app
import os

if __name__ == '__main__':
    # Get port from environment (Railway sets PORT)
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_ENV', 'production') == 'development'

    if debug:
        print("🚀 Starting Negative Price Calculator Web App")
        print(f"📊 Access at: http://localhost:{port}")
        print("⚠️  Make sure your .env file has ENTSOE_API_KEY configured")
        print("🔧 Press Ctrl+C to stop the server\n")

    app.run(debug=debug, host='0.0.0.0', port=port)