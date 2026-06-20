import os
import sys
import subprocess
import argparse
import threading
import time
import socket

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def run_command(cmd, cwd=None):
    return subprocess.Popen(cmd, shell=True, cwd=cwd)

def main():
    parser = argparse.ArgumentParser(description="Scholar Summary Agent Web Application Launcher")
    parser.add_argument("--dev", action="store_true", help="Launch both backend and frontend in concurrent dev mode")
    parser.add_argument("--build", action="store_true", help="Build the React frontend static assets")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.join(project_root, "frontend")

    # If --build flag is passed, or if the dist folder doesn't exist, build it
    dist_dir = os.path.join(frontend_dir, "dist")
    if args.build or (not args.dev and not os.path.exists(dist_dir)):
        print("[*] Building frontend static files...")
        # Check if node_modules exists
        if not os.path.exists(os.path.join(frontend_dir, "node_modules")):
            print("[*] Installing frontend dependencies first...")
            subprocess.run("npm install", shell=True, cwd=frontend_dir, check=True)
        subprocess.run("npm run build", shell=True, cwd=frontend_dir, check=True)
        print("[+] Frontend build completed successfully!")
        if args.build:
            return

    if args.dev:
        print("[*] Starting concurrent dev servers...")
        # Start Vite dev server on port 5173
        vite_proc = None
        if is_port_in_use(5173):
            print("[!] Port 5173 is already in use. Please check if another Vite server is running.")
        else:
            print("[*] Starting Vite dev server (http://localhost:5173)...")
            vite_proc = run_command("npm run dev", cwd=frontend_dir)
        
        # Start FastAPI dev server on port 8000
        if is_port_in_use(8000):
            print("[!] Port 8000 is already in use. Cannot start backend dev server.")
            if vite_proc:
                vite_proc.terminate()
            sys.exit(1)
            
        print("[*] Starting FastAPI dev server (http://localhost:8000)...")
        try:
            subprocess.run("uv run uvicorn backend.main:app --reload --port 8000", shell=True, cwd=project_root)
        except KeyboardInterrupt:
            print("\n[+] Shutting down dev servers.")
            if vite_proc:
                vite_proc.terminate()
    else:
        # Production single-port mode
        if is_port_in_use(8000):
            print("[!] Port 8000 is already in use. The backend server might already be running.")
            print("[*] Opening http://localhost:8000 in your browser...")
            import webbrowser
            webbrowser.open("http://localhost:8000")
            sys.exit(0)

        print("[*] Starting production backend serving both API and static frontend...")
        print("[*] Web app will be accessible at http://localhost:8000")
        
        # Open browser in a separate thread after 1.5s
        def open_browser():
            time.sleep(1.5)
            import webbrowser
            webbrowser.open("http://localhost:8000")
            
        threading.Thread(target=open_browser, daemon=True).start()
        
        try:
            subprocess.run("uv run uvicorn backend.main:app --port 8000", shell=True, cwd=project_root)
        except KeyboardInterrupt:
            print("\n[+] Shutting down backend server.")

if __name__ == "__main__":
    main()
