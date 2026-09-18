"""Auto-update checker for receipt printer application.

Tracks the configured branch on origin (via `git ls-remote`) and pulls
whenever the remote HEAD moves, rather than relying on GitHub releases/tags
— this repo is updated by plain pushes to main, not cut releases.
"""

import logging
import subprocess
import time
import threading
import requests
from pathlib import Path

from . import config


class UpdateChecker(threading.Thread):
    """Background thread that checks for updates and optionally auto-updates.
    
    Periodically checks GitHub releases API for new versions. If AUTO_UPDATE is enabled
    and running in server mode, will automatically git pull and restart the service.
    
    Args:
        interval (int): Check interval in seconds (default from config.UPDATE_CHECK_INTERVAL)
        server_mode (bool): If True, running as systemd service (can auto-restart)
        error_notifier (str): Optional ntfy URL for error notifications
    """
    
    def __init__(self, interval=None, server_mode=False, error_notifier=None):
        super().__init__(daemon=True, name="UpdateChecker")
        self.interval = interval or config.UPDATE_CHECK_INTERVAL
        self.server_mode = server_mode
        self.error_notifier = error_notifier
        self._stop_event = threading.Event()
        self.current_version = self._get_current_version()
        
    def run(self):
        """Main update checking loop."""
        if not config.AUTO_UPDATE:
            logging.info("Auto-update disabled (AUTO_UPDATE=false)")
            return
            
        logging.info(f"Update checker started (interval: {self.interval}s, repo: {config.GITHUB_REPO})")
        logging.info(f"Current version: {self.current_version or 'unknown'}")
        
        # Wait a bit before first check to let app fully start
        time.sleep(60)
        
        while not self._stop_event.is_set() and not config.STOP_EVENT.is_set():
            try:
                self._check_for_updates()
            except Exception as e:
                logging.error(f"Update check failed: {e}")
                if self.error_notifier:
                    self._send_error("Update Check Failed", str(e))
            
            # Sleep in small intervals so we can exit quickly if needed
            for _ in range(self.interval):
                if self._stop_event.is_set() or config.STOP_EVENT.is_set():
                    break
                time.sleep(1)
    
    def stop(self):
        """Stop the update checker."""
        self._stop_event.set()
    
    def _get_current_version(self):
        """Get current git commit hash.

        Returns:
            str: Short commit hash, or None if not in git repo
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self._get_repo_path()
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logging.debug(f"Could not get current version: {e}")

        return None
    
    def _get_repo_path(self):
        """Get the repository root path.
        
        Returns:
            Path: Repository root directory
        """
        return Path(__file__).parent.parent
    
    def _check_for_updates(self):
        """Check origin's branch head via `git ls-remote` and pull if it moved."""
        branch = config.GIT_BRANCH
        repo_path = self._get_repo_path()
        logging.debug(f"Checking {config.GITHUB_REPO}@{branch} for updates...")

        try:
            remote = subprocess.run(
                ["git", "ls-remote", "origin", f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=repo_path,
            )
            if remote.returncode != 0 or not remote.stdout.strip():
                logging.warning(f"git ls-remote failed: {remote.stderr.strip()}")
                return
            remote_sha = remote.stdout.split()[0]

            local = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=repo_path,
            )
            if local.returncode != 0:
                logging.warning(f"git rev-parse HEAD failed: {local.stderr.strip()}")
                return
            local_sha = local.stdout.strip()

            if remote_sha == local_sha:
                logging.debug(f"Already up to date with {branch} ({local_sha[:7]})")
                return

            logging.info(f"New commits on {branch}: {local_sha[:7]} -> {remote_sha[:7]}")
            if config.AUTO_UPDATE:
                self._perform_update(remote_sha[:7])
            else:
                logging.info("Auto-update disabled - skipping update")

        except subprocess.TimeoutExpired:
            logging.warning("git ls-remote timed out")
        except Exception as e:
            logging.warning(f"Failed to check for updates: {e}")

    def _perform_update(self, new_version):
        """Perform git pull and restart service.
        
        Args:
            new_version (str): Version being updated to
        """
        logging.info(f"Starting update to version {new_version}...")
        
        try:
            repo_path = self._get_repo_path()
            
            # Ensure we're on a clean state
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=repo_path
            )
            
            if result.stdout.strip():
                logging.warning("Working directory has uncommitted changes - skipping update")
                self._send_error("Update Skipped", "Working directory has uncommitted changes")
                return
            
            # Pull latest changes
            logging.info("Running git pull...")
            result = subprocess.run(
                ["git", "pull", "origin", config.GIT_BRANCH],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=repo_path
            )
            
            if result.returncode != 0:
                error_msg = f"Git pull failed: {result.stderr}"
                logging.error(error_msg)
                self._send_error("Update Failed", error_msg)
                return
            
            logging.info(f"Successfully updated to {new_version}")
            logging.info("Git pull output: " + result.stdout.strip())
            
            # Restart service if in server mode
            if self.server_mode:
                self._restart_service()
            else:
                logging.info("Not in server mode - manual restart required")
                print(f"\n{'='*60}")
                print(f"🔄 Updated to version {new_version}")
                print(f"   Please restart the application to apply changes")
                print(f"{'='*60}\n")
                
        except Exception as e:
            error_msg = f"Update failed: {str(e)}"
            logging.error(error_msg, exc_info=True)
            self._send_error("Update Failed", error_msg)
    
    def _restart_service(self):
        """Restart the systemd service."""
        logging.info("Restarting systemd service...")
        
        try:
            # Trigger service restart by exiting with special code
            # The systemd service should have Restart=always configured
            logging.info("Triggering service restart...")
            config.STOP_EVENT.set()
            
            # Alternative: directly call systemctl (requires sudo privileges)
            # subprocess.run(["systemctl", "restart", "receipt-printer"], timeout=5)
            
        except Exception as e:
            logging.error(f"Failed to restart service: {e}")
            self._send_error("Restart Failed", str(e))
    
    def _send_error(self, title, message):
        """Send error notification to ntfy topic using native format."""
        if not self.error_notifier:
            return
        try:
            import socket
            hostname = socket.gethostname()
            # Use ntfy native format: POST with title and tags as headers
            headers = {
                "Title": f"Application Error on {hostname}",
                "Tags": "rotating_light,error",
                "Priority": "high"
            }
            requests.post(self.error_notifier, data=message, headers=headers, timeout=5)
        except Exception as e:
            logging.error(f"Failed to send error notification: {e}")
