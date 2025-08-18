#!/usr/bin/env python3
"""
Sourceful Energy - Web Application Launcher
Simplified launcher for the Flask web application
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

def main():
    """Launch the web application"""
    # Load environment variables
    load_dotenv()
    
    # Ensure we're in the right directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    # Add current directory to Python path
    sys.path.insert(0, str(script_dir))
    
    # Check for required environment variables
    required_env_vars = ['ENTSOE_API_KEY']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print("⚠️  Warning: Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\nThe app will start but some features may not work.")
        print("Please create a .env file with your API keys.")
        print("See README.md for configuration details.\n")
    
    # Set default environment
    if not os.getenv('FLASK_ENV'):
        os.environ['FLASK_ENV'] = 'development'
    
    # Import and run the Flask app
    try:
        from app import app
        
        port = int(os.environ.get('PORT', 8080))
        debug = os.environ.get('FLASK_ENV') != 'production'
        
        print("🚀 Starting Sourceful Energy Web Application")
        print(f"📱 Open your browser to: http://localhost:{port}")
        print(f"🔧 Debug mode: {debug}")
        print("Press Ctrl+C to stop the server\n")
        
        app.run(host='0.0.0.0', port=port, debug=debug)
        
    except KeyboardInterrupt:
        print("\n👋 Shutting down gracefully...")
    except ImportError as e:
        print(f"❌ Failed to import Flask app: {e}")
        print("Make sure all dependencies are installed with: uv sync")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to start web application: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
