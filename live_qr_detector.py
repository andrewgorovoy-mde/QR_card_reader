"""
Live QR Code Detection using OpenCV (USB Webcam, Raspberry Pi-friendly)

This script captures video from a USB webcam and detects QR codes in real-time.
It uses the V4L2 backend first (good for Raspberry Pi), then falls back to others.

Features:
- Detects poker cards via QR codes from a webcam
- Tracks flop, turn, and river cards in order
- Plays audio announcements when flop/turn/river are detected
- Plays card audio files at configurable speed
- Stores detected cards in SQLite database for inter-process communication
- Handles RESET QR codes to restart the round
- Communicates with poker_hand_reader.py via shared database

Controls:
- Press 'q' to quit
- Press 's' to save current frame
- Press 'd' to toggle debug mode
- Press 'r' to reset poker hand (flop/turn/river)
- Press '1' to print & play audio for all known cards
"""

import argparse 
import time
import os
import subprocess
import platform
import sqlite3
import json
from typing import Dict

# Import shared configuration
try:
    import config
except ImportError:
    print("Error: config.py not found. Please ensure config.py exists in the same directory.")
    exit(1)

# Try to import pyserial
try:
    import serial
    HAVE_SERIAL = True
except ImportError:
    serial = None
    HAVE_SERIAL = False

# Exception type to catch for serial errors
if HAVE_SERIAL:
    SerialExceptionType = serial.SerialException
else:
    class SerialExceptionType(Exception):
        pass

# Detect if running on Raspberry Pi
def is_raspberry_pi():
    """Check if running on Raspberry Pi."""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            return 'Raspberry Pi' in cpuinfo or 'BCM' in cpuinfo
    except:
        return False

IS_RASPBERRY_PI = is_raspberry_pi()
DISPLAY_AVAILABLE = os.environ.get('DISPLAY') is not None

# ============================================================================
# SERIAL PORT CONFIGURATION
# ============================================================================

SYSTEM = platform.system()  # 'Darwin' for macOS, 'Linux' for Pi

# Get default serial port from config based on platform
if SYSTEM == "Darwin":
    DEFAULT_SERIAL_PORT = config.SERIAL_PORT_DARWIN
elif SYSTEM == "Linux":
    DEFAULT_SERIAL_PORT = config.SERIAL_PORT_LINUX
else:
    DEFAULT_SERIAL_PORT = config.SERIAL_PORT_WINDOWS

DEFAULT_BAUDRATE = config.DEFAULT_BAUDRATE

# Console formatting helpers for uniform output
class ConsoleFormatter:
    """Uniform console output formatting."""
    
    WIDTH = 70
    PREFIX_INFO = "ℹ️  "
    PREFIX_SUCCESS = "✓ "
    PREFIX_ERROR = "✗ "
    PREFIX_WARNING = "⚠️  "
    PREFIX_CARD = "🎴 "
    PREFIX_FLOP = "🎰 "
    PREFIX_TURN = "🔄 "
    PREFIX_RIVER = "🌊 "
    PREFIX_HAND = "🃏 "
    
    @staticmethod
    def header(title: str, emoji: str = ""):
        """Print a formatted header."""
        print("\n" + "=" * ConsoleFormatter.WIDTH)
        if emoji:
            print(f"{emoji} {title}")
        else:
            print(title)
        print("=" * ConsoleFormatter.WIDTH)
    
    @staticmethod
    def info(msg: str, indent: int = 0):
        """Print an info message."""
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_INFO}{msg}")
    
    @staticmethod
    def success(msg: str, indent: int = 0):
        """Print a success message."""
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_SUCCESS}{msg}")
    
    @staticmethod
    def error(msg: str, indent: int = 0):
        """Print an error message."""
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_ERROR}{msg}")
    
    @staticmethod
    def warning(msg: str, indent: int = 0):
        """Print a warning message."""
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_WARNING}{msg}")
    
    @staticmethod
    def separator():
        """Print a separator line."""
        print("-" * ConsoleFormatter.WIDTH)
    
    @staticmethod
    def bullet(msg: str, indent: int = 2):
        """Print a bullet point."""
        spaces = " " * indent
        print(f"{spaces}• {msg}")

try:
    import cv2
except ImportError:
    print("Error: opencv-python is not installed.")
    print("Please install it using:")
    print("  pip install opencv-python")
    exit(1)

try:
    import numpy as np
except ImportError:
    print("Error: numpy is not installed.")
    print("Please install it using:")
    print("  pip install numpy")
    exit(1)

# ============================================================================
# PATH CONFIGURATION
# ============================================================================

# Get script directory and construct paths using config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(SCRIPT_DIR, config.AUDIO_DIRECTORY_NAME)
CARDS_DB = os.path.join(SCRIPT_DIR, config.CARDS_DATABASE_NAME)
AUDIO_CACHE_FILE = os.path.join(SCRIPT_DIR, ".audio_cache.json")  # Cache file for audio file metadata


def format_qr_data(data):
    """Format QR code data for display."""
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"Binary: {data.hex()[:50]}..."
    else:
        text = data

    if text.startswith(("http://", "https://", "www.")):
        return text
    return text


def open_camera(idx: int):
    """
    Try to open the camera using a few backends.
    On Raspberry Pi / Linux, CAP_V4L2 is usually best for USB webcams.
    Also supports libcamera for Raspberry Pi Camera Module.
    """
    backend_candidates = []

    # On Raspberry Pi, try libcamera first (for Pi Camera Module)
    if IS_RASPBERRY_PI:
        # Try libcamera backend (for Pi Camera Module v3/v2)
        if hasattr(cv2, "CAP_V4L2"):
            # Try libcamera device path
            libcamera_paths = [
                f"/dev/video{idx}",
                "/dev/video0",
                "/dev/video1",
            ]
            for path in libcamera_paths:
                if os.path.exists(path):
                    try:
                        print(f"Trying libcamera at {path}...")
                        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
                        time.sleep(0.3)  # Give libcamera more time to initialize
                        if cap is not None and cap.isOpened():
                            ret, _ = cap.read()
                            if ret:
                                print(f"✅ Opened libcamera at {path}")
                                return cap
                            cap.release()
                    except Exception as e:
                        print(f"  libcamera attempt failed: {e}")

    # Prefer V4L2 on Linux / Pi for USB webcams
    if hasattr(cv2, "CAP_V4L2"):
        backend_candidates.append(cv2.CAP_V4L2)

    # Then try "any" backend (this might be GStreamer or others)
    backend_candidates.append(cv2.CAP_ANY)

    for backend in backend_candidates:
        print(f"Trying to open camera {idx} with backend {backend}...")
        cap = cv2.VideoCapture(idx, backend)
        # Give the backend a moment to actually open the device
        time.sleep(0.2)
        if cap is not None and cap.isOpened():
            print(f"✅ Opened camera {idx} with backend {backend}")
            return cap
        else:
            print(f"❌ Failed with backend {backend}")
            if cap is not None:
                cap.release()

    print("All backends failed for this index.")
    return None


# ============================================================================
# DATABASE HELPERS
# ============================================================================

def init_cards_database():
    """
    Initialize the SQLite database for card storage.
    
    Creates the database file and tables if they don't exist:
    - cards: Stores detected cards with position and timestamp
    - game_state: Stores inter-process communication flags (reset requests)
    
    This function is called on startup by both scripts to ensure the database
    is properly initialized.
    """
    try:
        conn = sqlite3.connect(CARDS_DB, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card TEXT NOT NULL,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                position INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_position ON cards(position)
        """)
        # Create game_state table for inter-process communication
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                reset_requested INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Initialize game_state row if it doesn't exist
        cursor.execute("""
            INSERT OR IGNORE INTO game_state (id, reset_requested) VALUES (1, 0)
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error: Failed to initialize cards database: {e}")


def add_card_to_database(card: str, position: int):
    """
    Add a card to the database.
    
    Args:
        card: Card string (e.g., "AS", "7H")
        position: Position in detection order (0-indexed)
    """
    try:
        conn = sqlite3.connect(CARDS_DB, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO cards (card, position) VALUES (?, ?)", (card, position))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error: Failed to add card to database: {e}")


def clear_cards_database():
    """
    Clear all cards from the database.
    """
    try:
        conn = sqlite3.connect(CARDS_DB, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cards")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error: Failed to clear cards database: {e}")


def set_reset_flag():
    """
    Set the reset flag in the database to signal poker_hand_reader.py to reset the player's hand.
    
    This is called when a RESET QR code is detected by live_qr_detector.py.
    The poker_hand_reader.py script periodically checks this flag and resets
    the player's hand when it detects the flag is set.
    """
    try:
        conn = sqlite3.connect(CARDS_DB, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE game_state SET reset_requested = 1, updated_at = CURRENT_TIMESTAMP WHERE id = 1
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error: Failed to set reset flag: {e}")


def try_serial_ports(base_port: str, baudrate: int):
    """
    Try to connect to serial port, attempting multiple port numbers on macOS if needed.
    
    On macOS, if the port matches /dev/(cu|tty).usbmodemXXXX pattern, tries multiple port numbers:
    - First tries the specified port
    - Then tries ports with the same prefix (cu or tty)
    - Falls back to the other prefix if needed
    
    Args:
        base_port: Base serial port path (e.g., "/dev/tty.usbmodem101" or "/dev/cu.usbmodem2101")
        baudrate: Serial baudrate
        
    Returns:
        Serial connection object if successful, None otherwise
    """
    if not HAVE_SERIAL:
        return None
    
    # On macOS, try multiple port numbers if it's a usbmodem port
    if SYSTEM == "Darwin" and "usbmodem" in base_port:
        # Detect prefix (cu or tty)
        prefix = "tty" if "/dev/tty.usbmodem" in base_port else "cu"
        
        # Extract port number from base_port if it exists
        # e.g., "/dev/tty.usbmodem101" -> extract "101"
        try:
            base_port_num = int(base_port.replace(f"/dev/{prefix}.usbmodem", ""))
        except ValueError:
            base_port_num = None
        
        # List of port numbers to try (in order)
        port_numbers = [2101, 1101, 101]
        
        # If base_port has a specific number not in our list, try it first
        if base_port_num is not None and base_port_num not in port_numbers:
            port_numbers.insert(0, base_port_num)
        
        # Try ports with the same prefix first
        for port_num in port_numbers:
            port_path = f"/dev/{prefix}.usbmodem{port_num}"
            
            try:
                ConsoleFormatter.info(f"Trying serial port {port_path}...", indent=2)
                s = serial.Serial(port_path, baudrate, timeout=0.1)
                # Wait a bit for Arduino to reboot when serial opens
                time.sleep(2)
                ConsoleFormatter.success(f"Connected to Arduino on {port_path} at {baudrate} baud")
                return s
            except Exception as e:
                ConsoleFormatter.warning(f"Failed to connect to {port_path}: {e}", indent=3)
                continue
        
        # If same prefix failed, try the other prefix
        other_prefix = "cu" if prefix == "tty" else "tty"
        for port_num in port_numbers:
            port_path = f"/dev/{other_prefix}.usbmodem{port_num}"
            
            try:
                ConsoleFormatter.info(f"Trying serial port {port_path}...", indent=2)
                s = serial.Serial(port_path, baudrate, timeout=0.1)
                time.sleep(2)
                ConsoleFormatter.success(f"Connected to Arduino on {port_path} at {baudrate} baud")
                return s
            except Exception as e:
                ConsoleFormatter.warning(f"Failed to connect to {port_path}: {e}", indent=3)
                continue
        
        # If all attempts failed, return None
        ConsoleFormatter.error("Could not connect to any serial port. Tried:", indent=2)
        for port_num in port_numbers:
            ConsoleFormatter.info(f"  /dev/{prefix}.usbmodem{port_num}", indent=3)
            ConsoleFormatter.info(f"  /dev/{other_prefix}.usbmodem{port_num}", indent=3)
        return None
    else:
        # On other platforms, just try the specified port
        try:
            ConsoleFormatter.info(f"Opening serial port {base_port} at {baudrate} baud...")
            s = serial.Serial(base_port, baudrate, timeout=0.1)
            # Wait a bit for Arduino to reboot when serial opens
            time.sleep(2)
            ConsoleFormatter.success(f"Connected to Arduino on {base_port} at {baudrate} baud")
            return s
        except Exception as e:
            ConsoleFormatter.warning(f"Could not open serial port {base_port}: {e}")
            return None


def send_reset_to_arduino(ser):
    """
    Send RESET command to Arduino over serial connection.
    
    Args:
        ser: Serial connection object (or None if not connected)
    
    Returns:
        True if sent successfully, False otherwise
    """
    if ser is None:
        return False
    
    # Check if serial port is still open
    try:
        if not hasattr(ser, 'is_open') or not ser.is_open:
            return False
    except Exception:
        return False
    
    try:
        message = "RESET\n"
        ser.write(message.encode("ascii", errors="ignore"))
        ser.flush()
        ConsoleFormatter.success("RESET command sent to Arduino", indent=3)
        return True
    except (OSError, SerialExceptionType) as e:
        ConsoleFormatter.error(f"Serial error sending RESET to Arduino: {e}", indent=3)
        return False
    except Exception as e:
        ConsoleFormatter.error(f"Unexpected error sending RESET to Arduino: {e}", indent=3)
        return False


# ---------- AUDIO HELPERS ---------- #

def extract_card_code(card_str: str) -> str:
    """
    Extract a card code suitable for filename from the card string.
    Examples:
      "7H"         -> "7H"
      "AS"         -> "AS"
      "7H extra"   -> "7H"
      "  as  "     -> "AS"
    We take leading alphanumeric characters, uppercase them.
    """
    s = card_str.strip().upper()
    code = ""
    for ch in s:
        if ch.isalnum():
            code += ch
        else:
            break
    return code


def play_wav(path: str, speed: float = None):
    """
    Play a .wav file using platform-appropriate audio player with optional speed adjustment.
    
    Uses 'ffplay' (from ffmpeg) if available for speed control, otherwise falls back to
    platform-specific players. This call is blocking: it waits until the audio finishes.
    
    Args:
        path: Path to audio file
        speed: Playback speed multiplier (None = use config.CARD_AUDIO_SPEED)
              - 1.5 = 50% faster
              - 1.0 = normal speed
              - 2.0 = 100% faster (double speed)
              - 4.0 = 300% faster (quadruple speed) - requires chained filters
    
    Returns:
        True if successful, False otherwise
    """
    if speed is None:
        speed = config.CARD_AUDIO_SPEED
    system = platform.system()
    
    # Try ffplay first for speed control (works on all platforms)
    try:
        # ffplay supports speed adjustment via audio filter
        # atempo filter has limits: 0.5 to 2.0 range
        # For speeds > 2.0, chain multiple atempo filters
        if speed <= 2.0:
            af_filter = f"atempo={speed}"
        else:
            # Chain filters for speeds > 2.0
            # e.g., 4.0 = atempo=2.0,atempo=2.0
            filters = []
            remaining_speed = speed
            while remaining_speed > 2.0:
                filters.append("atempo=2.0")
                remaining_speed /= 2.0
            if remaining_speed > 1.0:
                filters.append(f"atempo={remaining_speed:.2f}")
            af_filter = ",".join(filters)
        
        # Debug: show filter being used (only if speed > 1.0 to avoid spam)
        if speed != 1.0:
            print(f"Playing at {speed}x speed using filter: {af_filter}")
        
        result = subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-af", af_filter, path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        return True
    except FileNotFoundError:
        print(f"Warning: 'ffplay' not found. Speed adjustment unavailable. Install ffmpeg:")
        print(f"  macOS: brew install ffmpeg")
        print(f"  Linux: sudo apt install ffmpeg")
        # Fall back to platform-specific players (no speed control)
    except subprocess.CalledProcessError as e:
        print(f"Warning: ffplay failed with speed {speed}. Error: {e.stderr if hasattr(e, 'stderr') else 'unknown'}")
        print(f"Falling back to regular playback (no speed control)")
        # Fall back to platform-specific players (no speed control)
    except Exception as e:
        print(f"Warning: ffplay error: {e}")
        # Fall back to platform-specific players (no speed control)
    
    # Fallback to platform-specific players
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["afplay", path], check=True)
        elif system == "Linux":
            subprocess.run(["aplay", path], check=True)
        elif system == "Windows":
            subprocess.run(["start", "/WAIT", path], shell=True, check=True)
        else:
            print(f"Warning: Unsupported OS '{system}'. Audio playback may not work.")
            return False
        return True
    except FileNotFoundError:
        if system == "Darwin":
            print(f"Error: 'afplay' not found. This is unusual on macOS.")
        elif system == "Linux":
            print("Error: 'aplay' not found. Install ALSA utils with:")
            print("  sudo apt install alsa-utils")
        else:
            print(f"Error: Audio player not found for OS '{system}'")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error playing {path}: Command failed with return code {e.returncode}")
        return False
    except Exception as e:
        print(f"Error playing {path}: {e}")
        return False


def play_audio(path: str, speed: float = None):
    """
    Play an audio file (wav or mp3) using platform-appropriate audio player with optional speed adjustment.
    
    Uses 'ffplay' (from ffmpeg) if available for speed control, otherwise falls back to
    platform-specific players. This call is blocking: it waits until the audio finishes.
    
    Args:
        path: Path to audio file
        speed: Playback speed multiplier (None = use config.ANNOUNCEMENT_AUDIO_SPEED)
              - 1.5 = 50% faster
              - 1.0 = normal speed
              - 2.0 = 100% faster (double speed)
    
    Returns:
        True if successful, False otherwise
    """
    if speed is None:
        speed = config.ANNOUNCEMENT_AUDIO_SPEED
    if not os.path.exists(path):
        print(f"Error: Audio file not found: {path}")
        return False
    
    system = platform.system()
    file_ext = os.path.splitext(path)[1].lower()
    
    # Try ffplay first for speed control (works on all platforms, supports WAV and MP3)
    try:
        # ffplay supports speed adjustment via audio filter
        # atempo filter has limits: 0.5 to 2.0 range
        # For speeds > 2.0, chain multiple atempo filters
        if speed <= 2.0:
            af_filter = f"atempo={speed}"
        else:
            # Chain filters for speeds > 2.0
            # e.g., 4.0 = atempo=2.0,atempo=2.0
            filters = []
            remaining_speed = speed
            while remaining_speed > 2.0:
                filters.append("atempo=2.0")
                remaining_speed /= 2.0
            if remaining_speed > 1.0:
                filters.append(f"atempo={remaining_speed:.2f}")
            af_filter = ",".join(filters)
        
        # Debug: show filter being used (only if speed > 1.0 to avoid spam)
        if speed != 1.0:
            print(f"Playing at {speed}x speed using filter: {af_filter}")
        
        result = subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-af", af_filter, path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        return True
    except FileNotFoundError:
        print(f"Warning: 'ffplay' not found. Speed adjustment unavailable. Install ffmpeg:")
        print(f"  macOS: brew install ffmpeg")
        print(f"  Linux: sudo apt install ffmpeg")
        # Fall back to platform-specific players (no speed control)
    except subprocess.CalledProcessError as e:
        print(f"Warning: ffplay failed with speed {speed}. Error: {e.stderr if hasattr(e, 'stderr') and e.stderr else 'unknown'}")
        print(f"Falling back to regular playback (no speed control)")
        # Fall back to platform-specific players (no speed control)
    except Exception as e:
        print(f"Warning: ffplay error: {e}")
        # Fall back to platform-specific players (no speed control)
    
    # Fallback to platform-specific players
    try:
        if system == "Darwin":  # macOS - afplay supports both wav and mp3
            subprocess.run(["afplay", path], check=True)
            return True
        elif system == "Linux":
            if file_ext == ".wav":
                subprocess.run(["aplay", path], check=True)
                return True
            elif file_ext == ".mp3":
                # Try mpg123 first, then omxplayer (Pi)
                players = ["mpg123", "omxplayer"]
                for player in players:
                    try:
                        if player == "omxplayer":
                            # omxplayer needs special handling
                            subprocess.run([player, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            subprocess.run([player, "-q", path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return True
                    except (FileNotFoundError, subprocess.CalledProcessError):
                        continue
                print("Error: No MP3 player found. Install one of: mpg123, ffmpeg (for ffplay), or omxplayer")
                print("  sudo apt install mpg123")
                print("  or: sudo apt install ffmpeg")
                return False
            else:
                print(f"Warning: Unsupported audio format: {file_ext}")
                return False
        elif system == "Windows":
            subprocess.run(["start", "/WAIT", path], shell=True, check=True)
            return True
        else:
            print(f"Warning: Unsupported OS '{system}'. Audio playback may not work.")
            return False
    except FileNotFoundError:
        print(f"Error: Audio player not found for OS '{system}'")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error playing {path}: Command failed with return code {e.returncode}")
        return False
    except Exception as e:
        print(f"Error playing {path}: {e}")
        return False


def load_audio_cache() -> Dict:
    """
    Load audio file cache from JSON file.
    
    Returns:
        Dictionary with cache data, or empty dict if cache doesn't exist or is invalid
    """
    if not os.path.exists(AUDIO_CACHE_FILE):
        return {}
    
    try:
        with open(AUDIO_CACHE_FILE, 'r') as f:
            cache = json.load(f)
        return cache
    except (json.JSONDecodeError, IOError):
        return {}


def save_audio_cache(cache: Dict):
    """
    Save audio file cache to JSON file.
    
    Args:
        cache: Dictionary with cache data
    """
    try:
        with open(AUDIO_CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        print(f"Warning: Failed to save audio cache: {e}")


def check_file_needs_update(filepath: str, cached_mtime: float) -> bool:
    """
    Check if a file needs to be re-checked based on modification time.
    
    Args:
        filepath: Path to the file
        cached_mtime: Cached modification time (0 if file didn't exist)
        
    Returns:
        True if file needs update, False if cache is still valid
    """
    if not os.path.exists(filepath):
        return cached_mtime != 0  # File was deleted, need to update cache
    
    try:
        current_mtime = os.path.getmtime(filepath)
        return abs(current_mtime - cached_mtime) > 0.1  # Allow 0.1s tolerance
    except OSError:
        return True  # Can't get mtime, assume needs update


def preload_audio_files():
    """
    Preload and verify all audio files exist to reduce first-play delay.
    Uses a cache file to avoid checking files on every startup.
    Only re-checks files if they've been modified or cache is missing.
    """
    if not os.path.exists(AUDIO_DIR):
        print(f"⚠️  Audio directory not found: {AUDIO_DIR}")
        print("   Creating directory...")
        try:
            os.makedirs(AUDIO_DIR, exist_ok=True)
            print(f"   ✓ Directory created.")
        except Exception as e:
            print(f"   ✗ Failed to create directory: {e}")
        return
    
    print("Checking audio files (using cache)...")
    
    # Load cache
    cache = load_audio_cache()
    cache_needs_update = False
    
    # All 52 valid poker cards
    valid_cards = [
        'AS', '2S', '3S', '4S', '5S', '6S', '7S', '8S', '9S', '10S', 'JS', 'QS', 'KS',
        'AH', '2H', '3H', '4H', '5H', '6H', '7H', '8H', '9H', '10H', 'JH', 'QH', 'KH',
        'AD', '2D', '3D', '4D', '5D', '6D', '7D', '8D', '9D', '10D', 'JD', 'QD', 'KD',
        'AC', '2C', '3C', '4C', '5C', '6C', '7C', '8C', '9C', '10C', 'JC', 'QC', 'KC'
    ]
    
    # Announcement files
    announcement_files = [
        'flop_down.mp3',
        'turn_down.mp3',
        'river_down.mp3',
        'round_over.mp3',
        'waiting.mp3',
        'waiting_hand.mp3'
    ]
    
    # Initialize cache structure if needed
    if 'card_files' not in cache:
        cache['card_files'] = {}
    if 'announcement_files' not in cache:
        cache['announcement_files'] = {}
    
    card_files_found = 0
    card_files_missing = 0
    
    # Check card audio files (only if cache is stale)
    for card in valid_cards:
        filename = f"{card}.wav"
        filepath = os.path.join(AUDIO_DIR, filename)
        cached_data = cache['card_files'].get(filename, {})
        cached_mtime = cached_data.get('mtime', 0)
        cached_exists = cached_data.get('exists', False)
        
        # Only check file if cache is missing or file has changed
        if check_file_needs_update(filepath, cached_mtime):
            if os.path.exists(filepath):
                try:
                    mtime = os.path.getmtime(filepath)
                    # Verify file is readable (triggers OS caching)
                    with open(filepath, 'rb') as f:
                        f.read(1)  # Read first byte to verify access
                    cache['card_files'][filename] = {'exists': True, 'mtime': mtime}
                    card_files_found += 1
                    cache_needs_update = True
                except Exception:
                    cache['card_files'][filename] = {'exists': False, 'mtime': 0}
                    card_files_missing += 1
                    cache_needs_update = True
            else:
                cache['card_files'][filename] = {'exists': False, 'mtime': 0}
                card_files_missing += 1
                cache_needs_update = True
        else:
            # Use cached data
            if cached_exists:
                card_files_found += 1
            else:
                card_files_missing += 1
    
    # Check announcement files (only if cache is stale)
    announcement_files_found = 0
    announcement_files_missing = 0
    
    for ann_file in announcement_files:
        filepath = os.path.join(AUDIO_DIR, ann_file)
        cached_data = cache['announcement_files'].get(ann_file, {})
        cached_mtime = cached_data.get('mtime', 0)
        cached_exists = cached_data.get('exists', False)
        
        # Only check file if cache is missing or file has changed
        if check_file_needs_update(filepath, cached_mtime):
            if os.path.exists(filepath):
                try:
                    mtime = os.path.getmtime(filepath)
                    # Verify file is readable (triggers OS caching)
                    with open(filepath, 'rb') as f:
                        f.read(1)
                    cache['announcement_files'][ann_file] = {'exists': True, 'mtime': mtime}
                    announcement_files_found += 1
                    cache_needs_update = True
                except Exception:
                    cache['announcement_files'][ann_file] = {'exists': False, 'mtime': 0}
                    announcement_files_missing += 1
                    cache_needs_update = True
            else:
                cache['announcement_files'][ann_file] = {'exists': False, 'mtime': 0}
                announcement_files_missing += 1
                cache_needs_update = True
        else:
            # Use cached data
            if cached_exists:
                announcement_files_found += 1
            else:
                announcement_files_missing += 1
    
    # Save cache if it was updated
    if cache_needs_update:
        save_audio_cache(cache)
        print("  Cache updated")
    else:
        print("  Using cached information (fast)")
    
    print(f"  Card audio files: {card_files_found}/52 found")
    if card_files_missing > 0:
        print(f"  ⚠️  {card_files_missing} card audio file(s) missing")
    
    print(f"  Announcement files: {announcement_files_found}/{len(announcement_files)} found")
    if announcement_files_missing > 0:
        print(f"  ⚠️  {announcement_files_missing} announcement file(s) missing")
    
    # Pre-warm audio system with a test (if possible)
    # Try to find any existing audio file to test playback
    test_file = None
    for card in valid_cards[:5]:  # Check first 5 cards
        filename = f"{card}.wav"
        if cache['card_files'].get(filename, {}).get('exists', False):
            test_file = os.path.join(AUDIO_DIR, filename)
            break
    
    if not test_file:
        # Try announcement files
        for ann_file in announcement_files:
            if cache['announcement_files'].get(ann_file, {}).get('exists', False):
                test_file = os.path.join(AUDIO_DIR, ann_file)
                break
    
    if test_file:
        # Do a quick test to warm up the system
        system = platform.system()
        try:
            if system == "Darwin":
                # On macOS, just verify afplay works (doesn't actually play)
                subprocess.run(["afplay", "--help"], 
                             capture_output=True, timeout=1, check=False)
            elif system == "Linux":
                # On Linux, verify aplay works
                subprocess.run(["aplay", "--version"], 
                             capture_output=True, timeout=1, check=False)
        except Exception:
            pass  # Silently fail - pre-warming is optional
    
    print("✓ Audio files verified")
    print()


def play_cards_audio(card_order):
    """
    For each known card in card_order, play the corresponding audio file
    from AUDIO_DIR. Files are expected to be named <card_code>.wav,
    e.g., '7H.wav', 'AS.wav'.
    """
    if not card_order:
        print("No known cards to play.")
        return

    # Check if audio directory exists
    if not os.path.exists(AUDIO_DIR):
        print(f"\n⚠️  Audio directory not found: {AUDIO_DIR}")
        print("   Creating directory...")
        try:
            os.makedirs(AUDIO_DIR, exist_ok=True)
            print(f"   ✓ Directory created. Please add .wav files named like 'AS.wav', '7H.wav', etc.")
        except Exception as e:
            print(f"   ✗ Failed to create directory: {e}")
        return

    print(f"\nPlaying audio for known cards (from {AUDIO_DIR}):")
    played_count = 0
    for i, card in enumerate(card_order, 1):
        code = extract_card_code(card)
        if not code:
            print(f"  {i}. '{card}' -> could not extract code, skipping.")
            continue

        filename = f"{code}.wav"
        filepath = os.path.join(AUDIO_DIR, filename)

        if os.path.exists(filepath):
            print(f"  {i}. {card} -> Playing {filename}...", end=" ", flush=True)
            if play_wav(filepath):
                print("✓")
                played_count += 1
            else:
                print("✗ Failed")
            # Delay between cards (configurable via config.CARD_AUDIO_DELAY)
            if config.CARD_AUDIO_DELAY > 0:
                time.sleep(config.CARD_AUDIO_DELAY)
        else:
            print(f"  {i}. {card} -> ⚠️  missing audio file: {filename}")
    
    if played_count == 0:
        print("\n⚠️  No audio files were played. Check that:")
        print(f"   1. Audio files exist in: {AUDIO_DIR}")
        print(f"   2. Files are named correctly (e.g., 'AS.wav', '7H.wav')")
    else:
        print(f"\n✓ Successfully played {played_count} audio file(s).")
    print()


# ---------- MAIN LOOP ---------- #

def main():
    parser = argparse.ArgumentParser(description="Live QR Code Detection with USB Webcam")
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Camera device index (default: 0)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=0.75 if IS_RASPBERRY_PI else 1.0,
        help="Scale factor for frame processing (default: 0.75 on Pi, 1.0 otherwise)",
    )
    parser.add_argument(
        "--window-name",
        type=str,
        default="Live QR Code Detection",
        help='Window name for display (default: "Live QR Code Detection")',
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without display window (useful for headless Raspberry Pi)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=640 if IS_RASPBERRY_PI else 640,
        help="Camera frame width (default: 640)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480 if IS_RASPBERRY_PI else 480,
        help="Camera frame height (default: 480)",
    )
    parser.add_argument(
        "--serial-port",
        default=DEFAULT_SERIAL_PORT,
        help=f"Serial port for Arduino "
             f"(default: '{DEFAULT_SERIAL_PORT or 'NONE'}' for {SYSTEM})",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"Serial baudrate (default: {DEFAULT_BAUDRATE})",
    )

    args = parser.parse_args()

    # Initialize serial connection (optional)
    ser = None
    if HAVE_SERIAL and args.serial_port:
        ser = try_serial_ports(args.serial_port, args.baudrate)
        if ser is None:
            ConsoleFormatter.info("Continuing without serial connection...", indent=2)
    elif not HAVE_SERIAL:
        ConsoleFormatter.info("pyserial not available - serial communication disabled", indent=2)
        ConsoleFormatter.info("Install with: pip install pyserial", indent=3)
    elif not args.serial_port:
        ConsoleFormatter.info("No serial port specified - serial communication disabled", indent=2)

    # Initialize cards database
    init_cards_database()
    # Clear database on startup
    clear_cards_database()
    ConsoleFormatter.info("River database cleared on startup", indent=2)
    
    # Preload all audio files to reduce first-play delay
    preload_audio_files()

    # Auto-enable headless mode on Pi if no display available
    if IS_RASPBERRY_PI and not DISPLAY_AVAILABLE and not args.headless:
        print("⚠️  No display detected. Running in headless mode.")
        args.headless = True

    if IS_RASPBERRY_PI:
        print("🍓 Raspberry Pi detected - optimizing for Pi performance")
        if args.headless:
            print("   Running in headless mode (no display window)")

    print(f"Initializing camera at index {args.camera}...")
    cap = open_camera(args.camera)

    if cap is None or not cap.isOpened():
        print(f"\nError: Could not open camera {args.camera}")
        print("Troubleshooting:")
        print("  1. Check which devices exist with:   ls /dev/video*")
        print("  2. If you see /dev/video1, try:      python3 script.py --camera 1")
        print("  3. Make sure no other app is using the webcam (libcamera-*, VLC, etc.)")
        print("  4. On Raspberry Pi: ensure your user is in the 'video' group:")
        print("       sudo usermod -a -G video $USER")
        print("       (then log out and back in)")
        return

    # Only set properties AFTER we know the camera is open
    # Use lower resolution on Pi for better performance
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    
    # Set buffer size to 1 to reduce latency (important for Pi)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except:
        pass  # Some backends don't support this

    # Warm up camera
    print("Warming up camera...")
    for _ in range(10):
        ret, _ = cap.read()
        if ret:
            break
        time.sleep(0.1)

    ret, test_frame = cap.read()
    if not ret or test_frame is None:
        print("Error: Camera opened but cannot read frames.")
        cap.release()
        return

    print("Camera ready!")

    print("\nStarting video stream...")
    if not args.headless:
        print("Press 'q' to quit")
        print("Press 's' to save current frame")
        print("Press 'd' to toggle debug mode")
    print("Press 'r' to reset poker hand (flop/turn/river)")
    print("Press '1' to print & play audio for all known cards")
    if args.headless:
        print("Press Ctrl+C to quit (headless mode)")
    print("-" * 50)

    qr_detector = cv2.QRCodeDetector()

    frame_count = 0
    saved_count = 0
    debug_mode = False

    # Poker state
    unique_qr_codes = set()  # for fast membership checks
    card_order = []          # preserves order of first-seen cards

    flop_detected = False
    flop_cards = []
    turn_detected = False
    turn_card = None
    river_detected = False
    river_card = None

    try:
        while True:
            ret, frame = cap.read()

            if not ret or frame is None:
                print("Error: Failed to capture frame from USB webcam.")
                break

            # Optional scaling for speed
            if args.scale != 1.0:
                h, w = frame.shape[:2]
                new_w = int(w * args.scale)
                new_h = int(h * args.scale)
                processing_frame = cv2.resize(frame, (new_w, new_h))
            else:
                processing_frame = frame

            annotated_frame = frame.copy()

            retval, decoded_info, points, _ = qr_detector.detectAndDecodeMulti(processing_frame)
            detected_qrs = []

            if retval:
                for data, pts in zip(decoded_info, points):
                    if not data:
                        continue

                    formatted_data = format_qr_data(data)
                    detected_qrs.append({"data": formatted_data, "points": pts})

                    # Scale points back if we resized
                    if args.scale != 1.0:
                        scaled_points = [
                            (int(p[0] / args.scale), int(p[1] / args.scale)) for p in pts
                        ]
                    else:
                        scaled_points = [(int(p[0]), int(p[1])) for p in pts]

                    pts_array = np.array(scaled_points, dtype=np.int32)
                    cv2.polylines(annotated_frame, [pts_array], True, (0, 255, 0), 2)

                    for p in scaled_points:
                        cv2.circle(annotated_frame, p, 5, (255, 0, 0), -1)

                    text_x = min(p[0] for p in scaled_points)
                    text_y = min(p[1] for p in scaled_points) - 10

                    label = formatted_data[:50]
                    if len(formatted_data) > 50:
                        label += "..."

                    (text_width, text_height), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                    )

                    overlay = annotated_frame.copy()
                    cv2.rectangle(
                        overlay,
                        (text_x, text_y - text_height - 5),
                        (text_x + text_width + 5, text_y + baseline + 5),
                        (0, 0, 0),
                        -1,
                    )
                    cv2.addWeighted(overlay, 0.7, annotated_frame, 0.3, 0, annotated_frame)

                    cv2.putText(
                        annotated_frame,
                        label,
                        (text_x, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        1,
                    )

                    ConsoleFormatter.info(f"QR Code detected: {formatted_data}")
                    
                    # Check if QR code contains "RESET" command
                    if "RESET" in formatted_data.upper():
                        print()
                        ConsoleFormatter.header("RESET DETECTED", "🔄")
                        ConsoleFormatter.info("Restarting round...", indent=2)
                        
                        # Clear all card tracking
                        unique_qr_codes.clear()
                        card_order.clear()
                        flop_detected = False
                        flop_cards = []
                        turn_detected = False
                        turn_card = None
                        river_detected = False
                        river_card = None
                        
                        # Clear the river database
                        try:
                            clear_cards_database()
                            ConsoleFormatter.success("River database cleared", indent=3)
                        except Exception as e:
                            ConsoleFormatter.error(f"Failed to clear river database: {e}", indent=3)
                        
                        # Set reset flag to signal poker_hand_reader.py to reset player's hand
                        try:
                            set_reset_flag()
                            ConsoleFormatter.success("Reset flag set for poker_hand_reader.py", indent=3)
                        except Exception as e:
                            ConsoleFormatter.error(f"Failed to set reset flag: {e}", indent=3)
                        
                        # Send RESET command to Arduino over serial
                        if ser is not None:
                            send_reset_to_arduino(ser)
                        
                        # Play round_over.mp3
                        ConsoleFormatter.info("Playing round_over.mp3...", indent=2)
                        round_over_path = os.path.join(AUDIO_DIR, "round_over.mp3")
                        if os.path.exists(round_over_path):
                            if play_audio(round_over_path):
                                ConsoleFormatter.success("Round over audio played successfully", indent=3)
                            else:
                                ConsoleFormatter.error("Failed to play round_over.mp3", indent=3)
                        else:
                            ConsoleFormatter.warning(f"round_over.mp3 not found at: {round_over_path}", indent=3)
                        
                        ConsoleFormatter.info("Round restarted. Ready for new cards...", indent=2)
                        ConsoleFormatter.separator()
                        print()

            # --------- Poker logic with stable ordering  --------- #
            # Add newly seen QR codes to both the set and the ordered list
            # Skip RESET command QR codes - they should not be tracked as cards
            for qr in detected_qrs:
                card = qr["data"]
                # Skip RESET command QR codes
                if "RESET" in card.upper():
                    continue
                if card not in unique_qr_codes:
                    unique_qr_codes.add(card)
                    card_order.append(card)
                    # Write new card to database
                    position = len(card_order) - 1  # 0-indexed position
                    add_card_to_database(card, position)
                    
                    # Play card_drop.mp3 for unique card detection
                    card_drop_path = os.path.join(AUDIO_DIR, "card_drop.mp3")
                    if os.path.exists(card_drop_path):
                        play_audio(card_drop_path)

            current_count = len(card_order)

            # FLOP: first N cards in detection order (N = config.FLOP_CARD_COUNT)
            if current_count >= config.FLOP_CARD_COUNT and not flop_detected:
                flop_cards = card_order[:config.FLOP_CARD_COUNT]
                flop_detected = True
                
                # Play flop_down.mp3
                flop_down_path = os.path.join(AUDIO_DIR, "flop_down.mp3")
                if os.path.exists(flop_down_path):
                    ConsoleFormatter.info("Playing flop_down.mp3...", indent=2)
                    play_audio(flop_down_path)
                
                ConsoleFormatter.header("FLOP DETECTED!", "🎰")
                ConsoleFormatter.info(f"Card 1: {flop_cards[0]}", indent=3)
                ConsoleFormatter.info(f"Card 2: {flop_cards[1]}", indent=3)
                ConsoleFormatter.info(f"Card 3: {flop_cards[2]}", indent=3)
                
                # Read out the flop cards
                ConsoleFormatter.info("Reading out flop cards...", indent=2)
                play_cards_audio(flop_cards)
                
                ConsoleFormatter.separator()
                print()

            # TURN: (FLOP_CARD_COUNT + 1)th card in detection order
            if current_count >= config.FLOP_CARD_COUNT + 1 and not turn_detected:
                turn_card = card_order[config.FLOP_CARD_COUNT]
                turn_detected = True
                
                # Play turn_down.mp3
                turn_down_path = os.path.join(AUDIO_DIR, "turn_down.mp3")
                if os.path.exists(turn_down_path):
                    ConsoleFormatter.info("Playing turn_down.mp3...", indent=2)
                    play_audio(turn_down_path)
                
                ConsoleFormatter.header("TURN DETECTED!", "🔄")
                ConsoleFormatter.info(f"Turn Card: {turn_card}", indent=3)
                
                # Read out the turn card
                ConsoleFormatter.info("Reading out turn card...", indent=2)
                play_cards_audio([turn_card])
                
                ConsoleFormatter.separator()
                print()

            # RIVER: Last card in detection order (TOTAL_COMMUNITY_CARDS)
            if current_count >= config.TOTAL_COMMUNITY_CARDS and not river_detected:
                river_card = card_order[config.TOTAL_COMMUNITY_CARDS - 1]
                river_detected = True
                
                # Play river_down.mp3
                river_down_path = os.path.join(AUDIO_DIR, "river_down.mp3")
                if os.path.exists(river_down_path):
                    ConsoleFormatter.info("Playing river_down.mp3...", indent=2)
                    play_audio(river_down_path)
                
                ConsoleFormatter.header("RIVER DETECTED!", "🌊")
                ConsoleFormatter.info(f"River Card: {river_card}", indent=3)
                
                # Read out the river card
                ConsoleFormatter.info("Reading out river card...", indent=2)
                play_cards_audio([river_card])
                
                ConsoleFormatter.separator()
                print()

                ConsoleFormatter.header("COMPLETE HAND SUMMARY", "🃏")
                ConsoleFormatter.info("Flop:", indent=3)
                for i, card in enumerate(flop_cards, 1):
                    ConsoleFormatter.info(f"Card {i}: {card}", indent=5)
                ConsoleFormatter.info(f"Turn:  {turn_card}", indent=3)
                ConsoleFormatter.info(f"River: {river_card}", indent=3)
                ConsoleFormatter.separator()
                print()

            # ----------------------------------------------------- #

            info_text = f"Detected QR codes this frame: {len(detected_qrs)}"
            if river_detected:
                info_text += f" | HAND COMPLETE! ({config.TOTAL_COMMUNITY_CARDS}/{config.TOTAL_COMMUNITY_CARDS} cards)"
            elif turn_detected:
                info_text += f" | TURN DETECTED! ({config.FLOP_CARD_COUNT + 1}/{config.TOTAL_COMMUNITY_CARDS} cards)"
            elif flop_detected:
                info_text += f" | FLOP DETECTED! ({config.FLOP_CARD_COUNT}/{config.TOTAL_COMMUNITY_CARDS} cards)"
            else:
                info_text += f" | Unique cards seen: {len(card_order)}/{config.TOTAL_COMMUNITY_CARDS}"

            cv2.putText(
                annotated_frame,
                info_text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

            frame_count += 1
            cv2.putText(
                annotated_frame,
                f"Frame: {frame_count}",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

            if args.scale != 1.0:
                cv2.putText(
                    annotated_frame,
                    f"Scale: {args.scale}x",
                    (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (128, 128, 128),
                    1,
                )

            y_offset = 120
            if debug_mode:
                cv2.putText(
                    annotated_frame,
                    "Debug Mode: ON",
                    (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 165, 255),
                    2,
                )
                y_offset += 30

            h, w = annotated_frame.shape[:2]

            if river_detected:
                box_y_start = h - 180
                box_y_end = h - 10
                box_x_start = 10
                box_x_end = w - 10
                overlay = annotated_frame.copy()
                cv2.rectangle(overlay, (box_x_start, box_y_start), (box_x_end, box_y_end), (255, 0, 255), -1)
                cv2.addWeighted(overlay, 0.3, annotated_frame, 0.7, 0, annotated_frame)
                cv2.putText(
                    annotated_frame,
                    "🃏 HAND COMPLETE! 🃏",
                    (20, box_y_start + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 0, 255),
                    2,
                )
                cv2.putText(
                    annotated_frame,
                    "Flop:",
                    (20, box_y_start + 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )
                for i, card in enumerate(flop_cards):
                    cv2.putText(
                        annotated_frame,
                        f"  Card {i+1}: {card[:30]}",
                        (20, box_y_start + 70 + (i * 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),
                        1,
                    )
                cv2.putText(
                    annotated_frame,
                    f"Turn:  {turn_card[:30]}",
                    (20, box_y_start + 135),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )
                cv2.putText(
                    annotated_frame,
                    f"River: {river_card[:30]}",
                    (20, box_y_start + 155),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )
            elif turn_detected:
                box_y_start = h - 160
                box_y_end = h - 10
                box_x_start = 10
                box_x_end = w - 10
                overlay = annotated_frame.copy()
                cv2.rectangle(overlay, (box_x_start, box_y_start), (box_x_end, box_y_end), (0, 165, 255), -1)
                cv2.addWeighted(overlay, 0.3, annotated_frame, 0.7, 0, annotated_frame)
                cv2.putText(
                    annotated_frame,
                    "🔄 TURN DETECTED! 🔄",
                    (20, box_y_start + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 165, 255),
                    2,
                )
                cv2.putText(
                    annotated_frame,
                    "Flop:",
                    (20, box_y_start + 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )
                for i, card in enumerate(flop_cards):
                    cv2.putText(
                        annotated_frame,
                        f"  Card {i+1}: {card[:30]}",
                        (20, box_y_start + 70 + (i * 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),
                        1,
                    )
                cv2.putText(
                    annotated_frame,
                    f"Turn:  {turn_card[:30]}",
                    (20, box_y_start + 135),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )
            elif flop_detected:
                box_y_start = h - 120
                box_y_end = h - 10
                box_x_start = 10
                box_x_end = w - 10
                overlay = annotated_frame.copy()
                cv2.rectangle(overlay, (box_x_start, box_y_start), (box_x_end, box_y_end), (0, 255, 0), -1)
                cv2.addWeighted(overlay, 0.3, annotated_frame, 0.7, 0, annotated_frame)
                cv2.putText(
                    annotated_frame,
                    "🎰 FLOP DETECTED! 🎰",
                    (20, box_y_start + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )
                for i, card in enumerate(flop_cards):
                    cv2.putText(
                        annotated_frame,
                        f"Card {i+1}: {card[:30]}",
                        (20, box_y_start + 50 + (i * 25)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 255),
                        2,
                    )
            else:
                progress_text = f"Poker: {len(card_order)}/{config.TOTAL_COMMUNITY_CARDS} unique cards detected"
                if len(card_order) > 0:
                    cv2.putText(
                        annotated_frame,
                        progress_text,
                        (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 0),
                        2,
                    )

            # Only show window if not in headless mode
            if not args.headless:
                cv2.imshow(args.window_name, annotated_frame)
                key = cv2.waitKey(1) & 0xFF  # 1ms delay for frame processing
            else:
                # In headless mode, don't wait for key input (non-blocking)
                key = -1
                # Small delay to prevent 100% CPU usage
                time.sleep(0.01)

            if key == ord("q"):
                print("\nQuitting...")
                break
            elif key == ord("s"):
                saved_count += 1
                filename = f"qr_detection_{saved_count}.jpg"
                cv2.imwrite(filename, annotated_frame)
                print(f"Saved frame to {filename}")
            elif key == ord("d"):
                debug_mode = not debug_mode
                print(f"Debug mode {'enabled' if debug_mode else 'disabled'}")
            elif key == ord("r"):
                unique_qr_codes.clear()
                card_order.clear()
                flop_detected = False
                flop_cards = []
                turn_detected = False
                turn_card = None
                river_detected = False
                river_card = None
                # Clear the cards database
                try:
                    clear_cards_database()
                    ConsoleFormatter.info("Cards database cleared", indent=3)
                except Exception as e:
                    ConsoleFormatter.error(f"Failed to clear cards database: {e}", indent=3)
                ConsoleFormatter.header("HAND RESET", "🔄")
                ConsoleFormatter.info("All cards cleared. Ready to detect a new hand...", indent=3)
                ConsoleFormatter.separator()
                print()
            elif key == ord("1"):
                print()
                ConsoleFormatter.info("Known cards so far:")
                if not card_order:
                    ConsoleFormatter.info("(none yet)", indent=3)
                else:
                    for i, card in enumerate(card_order, 1):
                        ConsoleFormatter.info(f"{i}. {card}", indent=3)
                print()
                # Play audio for all known cards
                play_cards_audio(card_order)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()
        # Close serial if open
        if ser is not None:
            try:
                if ser.is_open:
                    ser.close()
            except Exception:
                pass
        print("Camera released. Goodbye!")


if __name__ == "__main__":
    main()
