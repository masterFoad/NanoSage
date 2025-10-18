#!/usr/bin/env python3
"""
NanoSage Web UI Launcher

This script helps you start the NanoSage web interface quickly.
It will start both the backend API server and provide instructions for the frontend.
"""

import os
import sys
import subprocess
import platform
import webbrowser
from pathlib import Path


def print_banner():
    """Print a welcome banner"""
    banner = """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║        🧙‍♂️  NanoSage Web Interface Launcher  🧙‍♂️           ║
    ║                                                           ║
    ║   Advanced Recursive Search & Report Generation          ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


def check_dependencies():
    """Check if required dependencies are installed"""
    print("\n[1/4] Checking dependencies...")

    missing_deps = []

    # Check Python packages
    try:
        import fastapi
        import uvicorn
        import pydantic
        print("  ✓ Backend dependencies found")
    except ImportError as e:
        missing_deps.append(f"Python package: {e.name}")
        print(f"  ✗ Missing Python package: {e.name}")

    # Check Node.js
    try:
        result = subprocess.run(
            ['node', '--version'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"  ✓ Node.js {result.stdout.strip()} found")
        else:
            missing_deps.append("Node.js")
            print("  ✗ Node.js not found")
    except FileNotFoundError:
        missing_deps.append("Node.js")
        print("  ✗ Node.js not found")

    if missing_deps:
        print("\n⚠️  Missing dependencies detected!")
        print("\nTo install missing dependencies:")
        print("  - Python packages: pip install -r requirements.txt")
        print("  - Node.js: Download from https://nodejs.org/")
        print("\nSee WEB_UI_SETUP.md for detailed instructions.")
        return False

    return True


def check_frontend_installed():
    """Check if frontend dependencies are installed"""
    print("\n[2/4] Checking frontend setup...")

    frontend_dir = Path(__file__).parent / "frontend"
    node_modules = frontend_dir / "node_modules"

    if not node_modules.exists():
        print("  ✗ Frontend dependencies not installed")
        print("\n  Please run the following commands:")
        print("    cd frontend")
        print("    npm install")
        print("\n  Then run this script again.")
        return False

    print("  ✓ Frontend dependencies found")
    return True


def start_backend():
    """Start the FastAPI backend server"""
    print("\n[3/4] Starting backend API server...")

    try:
        # Start backend in a subprocess
        print("  Starting FastAPI server on http://localhost:8000")
        print("  API Documentation: http://localhost:8000/docs")
        print("\n  Press Ctrl+C to stop the server\n")

        subprocess.run([
            sys.executable,
            "-m",
            "uvicorn",
            "backend.api.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload"
        ])

    except KeyboardInterrupt:
        print("\n\n✓ Backend server stopped")
    except Exception as e:
        print(f"\n✗ Error starting backend: {e}")
        print("\nTry running manually:")
        print("  python -m uvicorn backend.api.main:app --reload")


def print_frontend_instructions():
    """Print instructions for starting the frontend"""
    print("\n[4/4] Frontend Instructions")
    print("=" * 60)
    print("\nTo start the frontend, open a NEW terminal and run:")
    print("\n  cd frontend")
    print("  npm start")
    print("\nThe web interface will open at: http://localhost:3000")
    print("=" * 60)


def main():
    """Main launcher function"""
    print_banner()

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Check frontend installation
    frontend_ready = check_frontend_installed()

    # Print frontend instructions
    if frontend_ready:
        print_frontend_instructions()

    # Start backend
    try:
        start_backend()
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
