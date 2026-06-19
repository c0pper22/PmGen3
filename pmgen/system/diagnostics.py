import sys
import os
import logging
import logging.handlers
import traceback
import platform
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMessageBox

# Reuse the path convention from your http_client
LOG_DIR = os.path.join(os.path.expanduser("~"), ".indybiz_pm")
LOG_FILE = os.path.join(LOG_DIR, "debug.log")

def setup_logging():
    """
    Initializes system-wide logging.
    - Writes to console (stdout).
    - Writes to a rolling log file (5MB limit, keeps 3 backups).
    - Captures info about the OS and App version on startup.
    """
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)

    # 1. Create Root Logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG) # Capture everything

    # 2. Formatters
    file_fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s', 
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_fmt = logging.Formatter(
        '[%(levelname)s] %(message)s'
    )

    # 3. File Handler (Rolling)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
    )
    file_handler.setFormatter(file_fmt)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # 4. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_fmt)
    console_handler.setLevel(logging.INFO) # Keep console cleaner
    logger.addHandler(console_handler)

    # 5. Log Startup Info
    logging.info("="*60)
    logging.info(f"PmGen Session Started: {datetime.now()}")
    logging.info(f"Platform: {platform.system()} {platform.release()} ({platform.version()})")
    logging.info(f"Python: {sys.version}")
    logging.info(f"Log Path: {LOG_FILE}")
    logging.info("="*60)

def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Global exception hook to intercept crashes.
    """
    # Ignore KeyboardInterrupt (Ctrl+C)
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # 1. Format the error
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    
    # 2. Log it specifically as a generic failure
    logging.critical("Uncaught Exception:\n" + error_msg)

    # 3. Show GUI Dialog if the App is running
    app = QApplication.instance()
    if app:
        try:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Fatal Application Error")
            msg.setText("An unexpected error occurred. The application may need to close.")
            msg.setInformativeText(f"Error: {exc_value}")
            msg.setDetailedText(error_msg)
            msg.setStandardButtons(QMessageBox.StandardButton.Close)
            msg.exec()
        except Exception:
            # If the GUI is broken, just print to stderr
            pass

def install_crash_handlers():
    """
    Installs hooks for various types of uncaught exceptions.
    """
    # Main thread exceptions
    sys.excepthook = handle_exception
    
    # Unraisable exceptions (e.g. errors in __del__)
    sys.unraisablehook = lambda args: logging.error(f"Unraisable exception: {args.exc_value}")

    # Thread exceptions (Python 3.8+)
    def thread_except_hook(args):
        logging.critical(f"Uncaught exception in thread: {args.thread.name}", 
                         exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    
    import threading
    threading.excepthook = thread_except_hook
    
    logging.info("Crash handlers installed.")