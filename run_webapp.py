#!/usr/bin/env python3
"""
Simple script to run the web application
"""
from app import app
import os

if __name__ == '__main__':
    # Set environment variables for development
    os.environ['FLASK_ENV'] = 'development'
    
    port = 8080
    print("🚀 Starting Negative Price Calculator Web App")
    print(f"📊 Access at: http://localhost:{port}")
    print("⚠️  Make sure your .env file has ENTSOE_API_KEY configured")
    print("🔧 Press Ctrl+C to stop the server\n")
    
    app.run(debug=True, host='0.0.0.0', port=port)