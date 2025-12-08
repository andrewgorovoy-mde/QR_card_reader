#!/usr/bin/env python3
"""
Poker Hand Reader Script (Pi/Mac side, with Arduino serial I/O)

Reads poker card input from a USB QR code reader (which acts as a keyboard).
Once two unique cards are detected, stores the hand.

Features:
- Reads card input from QR code scanner (character-by-character)
- Sends hand data to Arduino over serial in encoded format
- Receives commands from Arduino ('RIVER', 'HAND') to trigger audio playback
- Communicates with live_qr_detector.py via shared SQLite database
- Detects reset signals from live_qr_detector.py when RESET card is shown
- Plays card audio files at configurable speed

Arduino Communication:
  - Sends: HAND:<list>  (e.g. HAND:H,B,J,D,2,B) - 2 cards encoded as 6 elements
  - Sends: R            (reset command)
  - Receives: 'RIVER' - Plays audio for river cards from database
  - Receives: 'HAND' - Plays audio for player's current hand

Controls:
  R - Reset current hand (without storing)
  S - Show status
  Q - Quit
"""

import sys
import re
import tty
import termios
import select
import time
import platform
import argparse
import random
import os
import subprocess
import sqlite3
import json
from typing import List, Optional, Dict

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

# ============================================================================
# PATH CONFIGURATION
# ============================================================================

# Get script directory and construct paths using config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(SCRIPT_DIR, config.AUDIO_DIRECTORY_NAME)
CARDS_DB = os.path.join(SCRIPT_DIR, config.CARDS_DATABASE_NAME)
AUDIO_CACHE_FILE = os.path.join(SCRIPT_DIR, ".audio_cache.json")  # Cache file for audio file metadata


# Console formatting helpers for uniform output
class ConsoleFormatter:
    """Uniform console output formatting."""
    
    WIDTH = 70
    PREFIX_INFO = "ℹ️  "
    PREFIX_SUCCESS = "✓ "
    PREFIX_ERROR = "✗ "
    PREFIX_WARNING = "⚠️  "
    PREFIX_CARD = "🎴 "
    PREFIX_RESET = "🔄 "
    PREFIX_STATUS = "📊 "
    PREFIX_HISTORY = "📚 "
    PREFIX_INPUT = "📥 "
    PREFIX_ARDUINO = "[ARDUINO]"
    
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
    def card(msg: str, indent: int = 0):
        """Print a card-related message."""
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_CARD}{msg}")
    
    @staticmethod
    def reset(msg: str, indent: int = 0):
        """Print a reset-related message."""
        spaces = " " * indent
        print(f"\n{spaces}{ConsoleFormatter.PREFIX_RESET}{msg}")
    
    @staticmethod
    def status(msg: str, indent: int = 0):
        """Print a status message."""
        spaces = " " * indent
        print(f"\n{spaces}{ConsoleFormatter.PREFIX_STATUS}{msg}")
    
    @staticmethod
    def history(msg: str, indent: int = 0):
        """Print a history message."""
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_HISTORY}{msg}")
    
    @staticmethod
    def input_msg(msg: str, indent: int = 0):
        """Print an input-related message."""
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_INPUT}{msg}")
    
    @staticmethod
    def arduino(msg: str):
        """Print an Arduino message."""
        print(f"\n{ConsoleFormatter.PREFIX_ARDUINO} {msg}")
    
    @staticmethod
    def separator():
        """Print a separator line."""
        print("-" * ConsoleFormatter.WIDTH)
    
    @staticmethod
    def bullet(msg: str, indent: int = 2):
        """Print a bullet point."""
        spaces = " " * indent
        print(f"{spaces}• {msg}")


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


def play_audio(path: str, speed: float = None) -> bool:
    """
    Play an audio file (.wav, .mp3, etc.) using platform-appropriate audio player with optional speed adjustment.
    
    Uses 'ffplay' (from ffmpeg) if available for speed control, otherwise falls back to
    platform-specific players. This call is blocking: it waits until the audio finishes.
    
    Args:
        path: Path to audio file
        speed: Playback speed multiplier (None = use config.CARD_AUDIO_SPEED for cards,
              config.ANNOUNCEMENT_AUDIO_SPEED for announcements)
              - 1.5 = 50% faster
              - 1.0 = normal speed
              - 2.0 = 100% faster (double speed)
    
    Returns:
        True if successful, False otherwise
    """
    if speed is None:
        speed = config.CARD_AUDIO_SPEED
    system = platform.system()
    
    # Check file extension
    _, ext = os.path.splitext(path.lower())
    is_mp3 = ext == '.mp3'
    
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
            ConsoleFormatter.info(f"Playing at {speed}x speed using filter: {af_filter}", indent=3)
        
        result = subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-af", af_filter, path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        return True
    except FileNotFoundError:
        ConsoleFormatter.warning("'ffplay' not found. Speed adjustment unavailable. Install ffmpeg:", indent=2)
        ConsoleFormatter.info("  macOS: brew install ffmpeg", indent=3)
        ConsoleFormatter.info("  Linux: sudo apt install ffmpeg", indent=3)
        # Fall back to platform-specific players (no speed control)
    except subprocess.CalledProcessError as e:
        ConsoleFormatter.warning(f"ffplay failed with speed {speed}. Error: {e.stderr if hasattr(e, 'stderr') and e.stderr else 'unknown'}", indent=2)
        ConsoleFormatter.info("Falling back to regular playback (no speed control)", indent=3)
        # Fall back to platform-specific players (no speed control)
    except Exception as e:
        ConsoleFormatter.warning(f"ffplay error: {e}", indent=2)
        # Fall back to platform-specific players (no speed control)
    
    # Fallback to platform-specific players
    try:
        if system == "Darwin":  # macOS
            # afplay supports both WAV and MP3
            subprocess.run(["afplay", path], check=True)
        elif system == "Linux":
            if is_mp3:
                # Try mpg123 first, then mpg321
                try:
                    subprocess.run(["mpg123", "-q", path], check=True)
                except FileNotFoundError:
                    try:
                        subprocess.run(["mpg321", "-q", path], check=True)
                    except FileNotFoundError:
                        ConsoleFormatter.error("MP3 playback requires 'mpg123' or 'mpg321'. Install with:", indent=2)
                        ConsoleFormatter.info("  sudo apt install mpg123", indent=3)
                        return False
            else:
                subprocess.run(["aplay", path], check=True)
        elif system == "Windows":
            subprocess.run(["start", "/WAIT", path], shell=True, check=True)
        else:
            ConsoleFormatter.warning(f"Unsupported OS '{system}'. Audio playback may not work.", indent=2)
            return False
        return True
    except FileNotFoundError:
        if system == "Darwin":
            ConsoleFormatter.error("'afplay' not found. This is unusual on macOS.", indent=2)
        elif system == "Linux":
            if is_mp3:
                ConsoleFormatter.error("MP3 player not found. Install with:", indent=2)
                ConsoleFormatter.info("  sudo apt install mpg123", indent=3)
            else:
                ConsoleFormatter.error("'aplay' not found. Install ALSA utils with:", indent=2)
                ConsoleFormatter.info("  sudo apt install alsa-utils", indent=3)
        else:
            ConsoleFormatter.error(f"Audio player not found for OS '{system}'", indent=2)
        return False
    except subprocess.CalledProcessError as e:
        ConsoleFormatter.error(f"Error playing {path}: Command failed with return code {e.returncode}", indent=2)
        return False
    except Exception as e:
        ConsoleFormatter.error(f"Error playing {path}: {e}", indent=2)
        return False


def play_wav(path: str, speed: float = None) -> bool:
    """
    Play a .wav file (backwards compatibility wrapper).
    
    Args:
        path: Path to audio file
        speed: Playback speed multiplier (None = use config.CARD_AUDIO_SPEED)
    
    Returns:
        True if successful, False otherwise
    """
    return play_audio(path, speed)


def prewarm_audio_system():
    """
    Pre-initialize the audio system to reduce first-play delay.
    This is done by attempting to initialize the audio player without actually playing anything.
    The first audio playback often has delay due to:
    - Audio driver initialization
    - Process startup overhead
    - Audio buffer allocation
    
    By checking if the audio player is available and accessible, we trigger
    any lazy loading and reduce the delay on first actual playback.
    """
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            # Pre-warm by checking if afplay is available (triggers any lazy loading)
            # Use --help to verify command exists without playing anything
            result = subprocess.run(
                ["afplay", "--help"],
                capture_output=True,
                timeout=2,
                text=True
            )
            # Even if it fails, the process was started which helps warm up the system
        elif system == "Linux":
            # Pre-warm by checking if aplay is available
            # This initializes ALSA and reduces first-play delay
            result = subprocess.run(
                ["aplay", "--version"],
                capture_output=True,
                timeout=2,
                text=True
            )
        # Windows doesn't need pre-warming as 'start' is always available
    except subprocess.TimeoutExpired:
        # Command took too long, but at least we tried to initialize
        pass
    except Exception:
        # Silently fail - pre-warming is optional and shouldn't break startup
        pass


def init_cards_database():
    """
    Initialize the SQLite database for card storage.
    Creates the database and table if they don't exist.
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
        ConsoleFormatter.error(f"Failed to initialize cards database: {e}", indent=2)


def read_cards_from_database() -> List[str]:
    """
    Read cards from the SQLite database (written by live_qr_detector.py).
    Returns cards in the order they were detected.
    
    Returns:
        List of card strings, empty list if database is empty or doesn't exist
    """
    try:
        if not os.path.exists(CARDS_DB):
            return []
        
        conn = sqlite3.connect(CARDS_DB, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT card FROM cards ORDER BY position ASC")
        rows = cursor.fetchall()
        conn.close()
        
        cards = [row[0] for row in rows]
        return cards
    except Exception as e:
        ConsoleFormatter.error(f"Failed to read cards from database: {e}", indent=2)
        return []


def check_and_clear_reset_flag() -> bool:
    """
    Check if reset flag is set in the database and clear it atomically.
    
    This function is called periodically by poker_hand_reader.py to check if
    live_qr_detector.py has detected a RESET QR code. When the flag is detected,
    it's cleared immediately to prevent duplicate resets.
    
    Returns:
        True if reset was requested (and flag was cleared), False otherwise
    """
    try:
        if not os.path.exists(CARDS_DB):
            return False
        
        conn = sqlite3.connect(CARDS_DB, timeout=5.0)
        cursor = conn.cursor()
        # Check if reset is requested
        cursor.execute("SELECT reset_requested FROM game_state WHERE id = 1")
        row = cursor.fetchone()
        
        if row and row[0] == 1:
            # Reset flag is set, clear it
            cursor.execute("UPDATE game_state SET reset_requested = 0, updated_at = CURRENT_TIMESTAMP WHERE id = 1")
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False
    except Exception as e:
        # If table doesn't exist yet or other error, just return False
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
        ConsoleFormatter.warning(f"Failed to save audio cache: {e}", indent=2)


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
        ConsoleFormatter.warning(f"Audio directory not found: {AUDIO_DIR}", indent=2)
        ConsoleFormatter.info("Creating directory...", indent=3)
        try:
            os.makedirs(AUDIO_DIR, exist_ok=True)
            ConsoleFormatter.success("Directory created.", indent=3)
        except Exception as e:
            ConsoleFormatter.error(f"Failed to create directory: {e}", indent=3)
        return
    
    ConsoleFormatter.info("Checking audio files (using cache)...", indent=2)
    
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
        ConsoleFormatter.info("Audio cache updated", indent=3)
    else:
        ConsoleFormatter.info("Using cached audio file information (fast)", indent=3)
    
    ConsoleFormatter.info(f"Card audio files: {card_files_found}/52 found", indent=3)
    if card_files_missing > 0:
        ConsoleFormatter.warning(f"{card_files_missing} card audio file(s) missing", indent=3)
    
    ConsoleFormatter.info(f"Announcement files: {announcement_files_found}/{len(announcement_files)} found", indent=3)
    if announcement_files_missing > 0:
        ConsoleFormatter.warning(f"{announcement_files_missing} announcement file(s) missing", indent=3)
    
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
    
    ConsoleFormatter.success("Audio files verified", indent=2)
    print()


def play_cards_audio(card_order: List[str]):
    """
    For each known card in card_order, play the corresponding audio file
    from AUDIO_DIR. Files are expected to be named <card_code>.wav,
    e.g. '7H.wav', 'AS.wav'.
    
    Args:
        card_order: List of card strings (e.g., ["AS", "7H"])
    """
    if not card_order:
        ConsoleFormatter.info("No cards to play audio for.", indent=2)
        return

    # Check if audio directory exists
    if not os.path.exists(AUDIO_DIR):
        ConsoleFormatter.warning(f"Audio directory not found: {AUDIO_DIR}", indent=2)
        ConsoleFormatter.info("Creating directory...", indent=3)
        try:
            os.makedirs(AUDIO_DIR, exist_ok=True)
            ConsoleFormatter.success(f"Directory created. Please add .wav files named like 'AS.wav', '7H.wav', etc.", indent=3)
        except Exception as e:
            ConsoleFormatter.error(f"Failed to create directory: {e}", indent=3)
        return

    ConsoleFormatter.info(f"Playing audio for cards (from {AUDIO_DIR}):", indent=2)
    played_count = 0
    for i, card in enumerate(card_order, 1):
        code = extract_card_code(card)
        if not code:
            ConsoleFormatter.warning(f"'{card}' -> could not extract code, skipping.", indent=3)
            continue

        filename = f"{code}.wav"
        filepath = os.path.join(AUDIO_DIR, filename)

        if os.path.exists(filepath):
            ConsoleFormatter.info(f"{i}. {card} -> Playing {filename}...", indent=3)
            if play_audio(filepath):
                ConsoleFormatter.success("✓", indent=5)
                played_count += 1
            else:
                ConsoleFormatter.error("✗ Failed", indent=5)
            # Delay between cards (configurable via config.CARD_AUDIO_DELAY)
            if config.CARD_AUDIO_DELAY > 0:
                time.sleep(config.CARD_AUDIO_DELAY)
        else:
            ConsoleFormatter.warning(f"{i}. {card} -> missing audio file: {filename}", indent=3)
    
    if played_count == 0:
        ConsoleFormatter.warning("No audio files were played. Check that:", indent=2)
        ConsoleFormatter.info(f"1. Audio files exist in: {AUDIO_DIR}", indent=3)
        ConsoleFormatter.info(f"2. Files are named correctly (e.g., 'AS.wav', '7H.wav')", indent=3)
    else:
        ConsoleFormatter.success(f"Successfully played {played_count} audio file(s).", indent=2)
    print()


class PokerHandReader:
    """Reads and manages poker hands from QR code scanner input."""
    
    # Valid card ranks and suits
    RANKS = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
    SUITS = {'S', 'H', 'D', 'C'}  # Spades, Hearts, Diamonds, Clubs
    
    # All 52 valid poker cards
    VALID_CARDS = {
        'AS', '2S', '3S', '4S', '5S', '6S', '7S', '8S', '9S', '10S', 'JS', 'QS', 'KS',
        'AH', '2H', '3H', '4H', '5H', '6H', '7H', '8H', '9H', '10H', 'JH', 'QH', 'KH',
        'AD', '2D', '3D', '4D', '5D', '6D', '7D', '8D', '9D', '10D', 'JD', 'QD', 'KD',
        'AC', '2C', '3C', '4C', '5C', '6C', '7C', '8C', '9C', '10C', 'JC', 'QC', 'KC'
    }
    
    def __init__(self, serial_conn=None):
        """Initialize the poker hand reader."""
        self.current_cards: List[str] = []         # Only keep 2 most recent cards
        self.card_count: int = 0                   # Total number of cards seen
        self.serial = serial_conn                  # Serial connection to Arduino (or None)
    
    def card_to_list(self, card: str) -> List[str]:
        """
        Convert a card string to Arduino list format.
        
        Format: [suit, column2, column3]
        - Column 1 (suit): H, S, C, D
        - Column 2: 2,3,4,5,6,7,B (B if rank is in column 3)
        - Column 3: 8,9,10,J,Q,K,A,B (B if rank is in column 2)
        
        Examples:
        - Jack of Hearts: [H, B, J]
        - 2 of Diamonds: [D, 2, B]
        - 10 of Spades: [S, B, 10]
        - 7 of Clubs: [C, 7, B]
        
        Args:
            card: Card string like "AS", "7H", "10D", "KH"
            
        Returns:
            List of 3 elements [suit, column2, column3]
        """
        rank = card[:-1]  # Everything except last character (suit)
        suit = card[-1]   # Last character (suit)
        
        # Map suit (ensure uppercase)
        suit_map = {'D': 'D', 'S': 'S', 'C': 'C', 'H': 'H'}
        suit_char = suit_map.get(suit.upper(), 'D')
        
        # Column 2 values: 2,3,4,5,6,7,B
        # Column 3 values: 8,9,10,J,Q,K,A,B
        
        # If rank is 2,3,4,5,6,7 → Column 2 = rank, Column 3 = B
        if rank in ['2', '3', '4', '5', '6', '7']:
            return [suit_char, rank, 'B']
        
        # If rank is 8,9,10,J,Q,K,A → Column 2 = B, Column 3 = rank
        elif rank in ['8', '9', '10', 'J', 'Q', 'K', 'A']:
            return [suit_char, 'B', rank]
        
        else:
            # Fallback for unexpected ranks (shouldn't happen with valid cards)
            return [suit_char, 'B', 'B']
    
    def send_hand_to_arduino(self, cards: List[str]) -> bool:
        """
        Send a hand (2 cards) to Arduino as a flat list of 6 elements.
        
        Format: [card1_suit, card1_column2, card1_column3, card2_suit, card2_column2, card2_column3]
        - Column 2: 2,3,4,5,6,7,B (B if rank is in column 3)
        - Column 3: 8,9,10,J,Q,K,A,B (B if rank is in column 2)
        
        Example: ["JH", "2D"] -> [H,B,J,D,2,B]
        
        Args:
            cards: List of 2 card strings (e.g., ["AS", "7H"])
            
        Returns:
            True if sent successfully, False if failed (connection lost)
        """
        if self.serial is None:
            ConsoleFormatter.warning("Cannot send to Arduino: serial connection is None", indent=3)
            return False
        
        if len(cards) != config.PLAYER_HAND_SIZE:
            ConsoleFormatter.error(f"Cannot send to Arduino: expected {config.PLAYER_HAND_SIZE} cards, got {len(cards)}", indent=3)
            return False
        
        # Check if serial port is still open
        try:
            if not hasattr(self.serial, 'is_open') or not self.serial.is_open:
                ConsoleFormatter.warning("Cannot send to Arduino: serial port is not open", indent=3)
                self.serial = None
                return False
        except Exception as e:
            ConsoleFormatter.warning(f"Cannot check serial port status: {e}", indent=3)
            self.serial = None
            return False
        
        try:
            # Convert both cards to list format
            card1_list = self.card_to_list(cards[0])
            card2_list = self.card_to_list(cards[1])
            
            # Flatten into single list of 6 elements
            hand_list = card1_list + card2_list
            
            # Convert to string format for Arduino
            # Format: HAND:A,B,S,N,7,H
            hand_str = ",".join(hand_list)
            message = f"HAND:{hand_str}\n"
            
            ConsoleFormatter.info(f"Attempting to send: {message.strip()}", indent=5)
            self.serial.write(message.encode("ascii", errors="ignore"))
            self.serial.flush()
            
            ConsoleFormatter.success(f"Sent to Arduino: HAND:{hand_str.strip()}", indent=3)
            ConsoleFormatter.info(f"Data: {hand_list}", indent=5)
            return True
        except (OSError, SerialExceptionType) as e:
            ConsoleFormatter.error(f"Serial error sending hand to Arduino: {e}", indent=3)
            # Drop serial connection; main loop will try to reconnect
            try:
                if hasattr(self.serial, 'close'):
                    self.serial.close()
            except Exception:
                pass
            self.serial = None
            return False
        except Exception as e:
            ConsoleFormatter.error(f"Unexpected error sending hand to Arduino: {e}", indent=3)
            import traceback
            ConsoleFormatter.error(f"Traceback: {traceback.format_exc()}", indent=5)
            return False
    
    def validate_card(self, input_str: str) -> Optional[str]:
        """
        Validate a card against the 52 valid poker cards.
        
        Args:
            input_str: Input string (2 or 3 characters)
            
        Returns:
            Valid card string (e.g., "AS") or None if invalid
        """
        # Remove whitespace and convert to uppercase
        input_str = input_str.strip().upper()
        
        # Remove any non-alphanumeric characters
        input_str = re.sub(r'[^A-Z0-9]', '', input_str)
        
        # Check if it's exactly 2 or 3 characters
        if len(input_str) < 2 or len(input_str) > 3:
            return None
        
        # Check if it matches a valid card
        if input_str in self.VALID_CARDS:
            return input_str
        
        return None
    
    def add_card(self, card: str) -> bool:
        """
        Add a card, keeping only the 2 most recent cards.
        Send to Arduino only when we have 2 cards AND it's an even-numbered card (2nd, 4th, 6th, etc.).
        Duplicate cards are rejected and will not be sent.
        
        Args:
            card: Normalized card string
            
        Returns:
            True if card was added, False if duplicate
        """
        # Check for duplicate - if card already exists in current cards, reject it
        if card in self.current_cards:
            ConsoleFormatter.warning(f"Duplicate card rejected: {card}", indent=2)
            ConsoleFormatter.info(
                f"Current cards: {self.current_cards}, Count: {self.card_count} (unchanged)",
                indent=3
            )
            return False
        
        # Increment card count
        self.card_count += 1
        
        # Add the new card
        self.current_cards.append(card)
        
        # Keep only the most recent cards (up to PLAYER_HAND_SIZE)
        if len(self.current_cards) > config.PLAYER_HAND_SIZE:
            self.current_cards.pop(0)
        
        ConsoleFormatter.success(f"Card {self.card_count} added: {card}", indent=2)
        ConsoleFormatter.info(f"Current cards: {self.current_cards}, Count: {self.card_count}", indent=3)
        
        # Send to Arduino only when we have required cards AND it's an even-numbered card (2nd, 4th, 6th, etc.)
        if len(self.current_cards) == config.PLAYER_HAND_SIZE and self.card_count % 2 == 0:
            ConsoleFormatter.info(f"Sending pair to Arduino (card_count={self.card_count} is even)", indent=3)
            ConsoleFormatter.info(f"Cards to send: {self.current_cards}", indent=5)
            success = self.send_hand_to_arduino(self.current_cards)
            if not success:
                ConsoleFormatter.warning("Send failed - connection may be lost. Will retry on reconnect.", indent=3)
        elif len(self.current_cards) == config.PLAYER_HAND_SIZE:
            ConsoleFormatter.info(f"Have {config.PLAYER_HAND_SIZE} cards but waiting (card_count={self.card_count} is odd)", indent=3)
        elif len(self.current_cards) < config.PLAYER_HAND_SIZE:
            ConsoleFormatter.info(f"Waiting for more cards (have {len(self.current_cards)}, need {config.PLAYER_HAND_SIZE})", indent=3)
        
        return True
    
    def get_hand(self) -> List[str]:
        """
        Get current cards (up to PLAYER_HAND_SIZE most recent).
        
        Returns:
            List of current cards
        """
        return self.current_cards.copy()
    
    def store_hand(self):
        """Store and clear the current hand."""
        if len(self.current_cards) >= config.PLAYER_HAND_SIZE:
            hand = self.get_hand()
            ConsoleFormatter.card(f"Hand stored: {', '.join(hand)}")
            
            # Send hand to Arduino in list format (only when we have required number of cards)
            if len(hand) == config.PLAYER_HAND_SIZE:
                success = self.send_hand_to_arduino(hand)
                if not success:
                    ConsoleFormatter.warning("Send failed - connection may be lost. Will retry on reconnect.", indent=3)
        else:
            ConsoleFormatter.warning(
                f"Hand has only {len(self.current_cards)} card(s). "
                f"Need at least {config.PLAYER_HAND_SIZE} cards to store."
            )
        
        self.current_cards.clear()
        ConsoleFormatter.info("Hand reset. Ready for new cards.", indent=3)
        print()
    
    def reset(self):
        """Reset the current hand without storing it."""
        if self.current_cards:
            ConsoleFormatter.reset(f"Resetting hand: {', '.join(self.get_hand())}")
        else:
            ConsoleFormatter.reset("Resetting empty hand.")
        self.current_cards.clear()
        self.card_count = 0  # Reset card counter
        
        # Send reset command to Arduino (single-letter 'R' per your current sketch)
        if self.serial is not None:
            try:
                self.serial.write(b"R\n")
                self.serial.flush()
                ConsoleFormatter.info("Sent reset command 'R' to Arduino", indent=3)
            except (OSError, SerialExceptionType) as e:
                ConsoleFormatter.error(f"Serial error sending reset to Arduino: {e}", indent=3)
                self.serial = None
            except Exception as e:
                ConsoleFormatter.error(f"Unexpected error sending reset to Arduino: {e}", indent=3)
        
        ConsoleFormatter.info("Ready for new cards.", indent=3)
        print()
    
    def display_status(self):
        """Display current status."""
        ConsoleFormatter.separator()
        if self.current_cards:
            ConsoleFormatter.status(
                f"Current cards ({len(self.current_cards)} card(s)): "
                f"{', '.join(self.get_hand())}"
            )
            if len(self.current_cards) >= config.PLAYER_HAND_SIZE:
                ConsoleFormatter.success("Hand complete! Will be stored on next card or reset.", indent=3)
        else:
            ConsoleFormatter.status("No cards currently in hand.")
        ConsoleFormatter.separator()


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


def get_char(timeout=0.1):
    """
    Read a single character from stdin with optional timeout.
    
    Args:
        timeout: Timeout in seconds (0.1 = 100ms)
        
    Returns:
        Character read, or None if timeout
    """
    if select.select([sys.stdin], [], [], timeout)[0]:
        return sys.stdin.read(1)
    return None


def show_test_menu():
    """Display ASCII menu for test mode."""
    ConsoleFormatter.header("TEST MODE MENU", "🧪")
    print()
    print("  [1] Generate and send random hand")
    print("  [2] Generate and send N random hands")
    print("  [3] Auto-generate hands (continuous)")
    print("  [4] Send reset command (R)")
    print("  [5] Show current status")
    print("  [6] Manually input cards to send")
    print("  [7] Send RESET command to Arduino")
    print("  [Q] Quit test mode")
    print()
    ConsoleFormatter.separator()


def generate_random_hand() -> List[str]:
    """
    Generate a random poker hand (2 unique cards).
    
    Returns:
        List of 2 card strings (e.g., ["AS", "7H"])
    """
    cards = list(PokerHandReader.VALID_CARDS)
    hand = random.sample(cards, 2)
    return hand


def run_test_mode(reader: PokerHandReader, ser=None):
    """
    Run test mode with interactive menu.
    
    Args:
        reader: PokerHandReader instance
        ser: Serial connection (optional)
    """
    # Ensure reader has serial connection
    if ser is not None:
        reader.serial = ser
    
    ConsoleFormatter.header("TEST MODE ACTIVATED", "🧪")
    ConsoleFormatter.info("Test mode allows you to generate random hands", indent=2)
    ConsoleFormatter.info("and send them in the expected format to Arduino", indent=2)
    if reader.serial is not None:
        ConsoleFormatter.success("Serial connection active - hands will be sent to Arduino", indent=2)
    else:
        ConsoleFormatter.warning("No serial connection - hands will be displayed but not sent", indent=2)
    print()
    
    auto_mode = False
    auto_interval = 2.0  # seconds between auto-generated hands
    
    try:
        while True:
            if not auto_mode:
                show_test_menu()
                ConsoleFormatter.input_msg("Enter choice: ", indent=0)
                try:
                    # Flush stdout to ensure menu is displayed
                    sys.stdout.flush()
                    # Small delay to ensure output is displayed
                    time.sleep(0.05)
                    choice = input().strip().upper()
                    
                    # Check if user accidentally typed cards instead of menu choice
                    # Cards typically contain commas or are 2-3 characters
                    if (',' in choice or (len(choice) >= 2 and len(choice) <= 3 and 
                        any(c.isdigit() for c in choice) and any(c in 'HSDC' for c in choice.upper()))):
                        ConsoleFormatter.warning(f"'{choice}' looks like card input, not a menu choice.", indent=2)
                        ConsoleFormatter.info("Please select option [6] first, then enter your cards.", indent=2)
                        print()
                        continue
                        
                except (EOFError, KeyboardInterrupt):
                    print()
                    ConsoleFormatter.info("Exiting test mode...", indent=2)
                    break
            else:
                # Auto mode - generate hand automatically
                choice = '1'
                try:
                    time.sleep(auto_interval)
                except KeyboardInterrupt:
                    print()
                    auto_mode = False
                    ConsoleFormatter.info("Auto mode stopped by user", indent=2)
                    print()
                    continue
            
            if choice == '1':
                # Generate and send one random hand
                hand = generate_random_hand()
                ConsoleFormatter.info(f"Generated random hand: {', '.join(hand)}", indent=2)
                
                # Simulate adding cards to reader
                reader.current_cards.clear()
                reader.card_count = 0
                for card in hand:
                    reader.add_card(card)
                
                # Send to Arduino if connected
                if reader.serial is not None:
                    success = reader.send_hand_to_arduino(hand)
                    if success:
                        ConsoleFormatter.success("Hand sent successfully!", indent=2)
                    else:
                        ConsoleFormatter.warning("Failed to send hand (serial may be disconnected)", indent=2)
                else:
                    # Show what would be sent
                    card1_list = reader.card_to_list(hand[0])
                    card2_list = reader.card_to_list(hand[1])
                    hand_list = card1_list + card2_list
                    hand_str = ",".join(hand_list)
                    ConsoleFormatter.info(f"Would send: HAND:{hand_str}", indent=2)
                    ConsoleFormatter.warning("Serial not connected - data not sent", indent=2)
                
                print()
                
            elif choice == '2':
                # Generate N random hands
                ConsoleFormatter.input_msg("How many hands to generate? ", indent=0)
                try:
                    n = int(input().strip())
                    if n < 1:
                        ConsoleFormatter.error("Please enter a positive number", indent=2)
                        continue
                except ValueError:
                    ConsoleFormatter.error("Invalid number", indent=2)
                    continue
                except (EOFError, KeyboardInterrupt):
                    print()
                    ConsoleFormatter.info("Cancelled", indent=2)
                    continue
                
                ConsoleFormatter.info(f"Generating {n} random hands...", indent=2)
                print()
                
                try:
                    for i in range(n):
                        hand = generate_random_hand()
                        ConsoleFormatter.info(f"Hand {i+1}/{n}: {', '.join(hand)}", indent=2)
                        
                        # Simulate adding cards
                        reader.current_cards.clear()
                        reader.card_count = 0
                        for card in hand:
                            reader.add_card(card)
                        
                        # Send to Arduino if connected
                        if reader.serial is not None:
                            success = reader.send_hand_to_arduino(hand)
                            if success:
                                ConsoleFormatter.success("Sent!", indent=4)
                            else:
                                ConsoleFormatter.warning("Send failed", indent=4)
                        else:
                            card1_list = reader.card_to_list(hand[0])
                            card2_list = reader.card_to_list(hand[1])
                            hand_list = card1_list + card2_list
                            hand_str = ",".join(hand_list)
                            ConsoleFormatter.info(f"Would send: HAND:{hand_str}", indent=4)
                        
                        if i < n - 1:
                            time.sleep(0.5)  # Small delay between hands
                        print()
                except KeyboardInterrupt:
                    print()
                    ConsoleFormatter.info("Interrupted by user", indent=2)
                    print()
            
            elif choice == '3':
                # Toggle auto mode
                auto_mode = not auto_mode
                if auto_mode:
                    ConsoleFormatter.info("Auto mode ENABLED", indent=2)
                    ConsoleFormatter.info(f"Generating hands every {auto_interval} seconds", indent=2)
                    ConsoleFormatter.info("Press Ctrl+C to stop", indent=2)
                    print()
                else:
                    ConsoleFormatter.info("Auto mode DISABLED", indent=2)
                    print()
            
            elif choice == '4':
                # Send reset command
                ConsoleFormatter.info("Sending reset command (R) to Arduino...", indent=2)
                reader.reset()
                print()
            
            elif choice == '5':
                # Show status
                reader.display_status()
                print()
            
            elif choice == '6':
                # Manually input cards - stay in this mode until user exits
                ConsoleFormatter.header("MANUAL CARD INPUT MODE", "✍️")
                ConsoleFormatter.info("Enter 2 cards (e.g., 'AS 7H' or 'AS,7H' or one per line)", indent=2)
                ConsoleFormatter.info("Valid format: Rank + Suit (e.g., AS, KH, 2C, 10D)", indent=2)
                ConsoleFormatter.info("Type 'q' or 'back' to return to menu", indent=2)
                ConsoleFormatter.separator()
                print()
                
                # Loop to keep user in manual input mode
                while True:
                    try:
                        # Flush stdout to ensure prompt is displayed
                        sys.stdout.flush()
                        # Small delay to ensure output is displayed
                        time.sleep(0.1)
                        ConsoleFormatter.input_msg("Enter cards (or 'q' to quit): ", indent=0)
                        sys.stdout.flush()
                        user_input = input().strip()
                        
                        if not user_input:
                            ConsoleFormatter.warning("No input provided. Type 'q' to exit manual mode.", indent=2)
                            print()
                            continue
                        
                        # Check if user wants to exit
                        if user_input.upper() in ['Q', 'QUIT', 'BACK', 'EXIT']:
                            ConsoleFormatter.info("Exiting manual input mode...", indent=2)
                            print()
                            break
                        
                        # Parse input - handle comma, space, or newline separated
                        cards_input = []
                        if ',' in user_input:
                            cards_input = [c.strip().upper() for c in user_input.split(',') if c.strip()]
                        elif ' ' in user_input:
                            # Split by spaces, but handle multiple spaces
                            cards_input = [c.strip().upper() for c in user_input.split() if c.strip()]
                        else:
                            # Single card, ask for second
                            cards_input = [user_input.strip().upper()]
                            sys.stdout.flush()
                            ConsoleFormatter.input_msg("Enter second card: ", indent=0)
                            sys.stdout.flush()
                            second_card = input().strip().upper()
                            if second_card:
                                cards_input.append(second_card)
                        
                        # Debug: show what we parsed
                        ConsoleFormatter.info(f"Parsed input: {cards_input}", indent=3)
                        
                        # Validate cards
                        validated_cards = []
                        for card_input in cards_input:
                            # Clean the input more thoroughly
                            card_input_clean = card_input.strip().upper()
                            ConsoleFormatter.info(f"Validating: '{card_input_clean}'", indent=3)
                            validated = reader.validate_card(card_input_clean)
                            if validated:
                                validated_cards.append(validated)
                                ConsoleFormatter.success(f"Valid: '{card_input_clean}' -> {validated}", indent=4)
                            else:
                                ConsoleFormatter.error(f"Invalid card: '{card_input_clean}'", indent=2)
                        
                        if len(validated_cards) < 2:
                            ConsoleFormatter.warning(f"Need 2 valid cards. Got {len(validated_cards)}.", indent=2)
                            if validated_cards:
                                ConsoleFormatter.info(f"Valid cards found: {validated_cards}", indent=3)
                            print()
                            continue
                        
                        if len(validated_cards) > 2:
                            ConsoleFormatter.warning(f"More than 2 cards provided. Using first 2: {validated_cards[:2]}", indent=2)
                            validated_cards = validated_cards[:2]
                        
                        # Check for duplicates
                        if validated_cards[0] == validated_cards[1]:
                            ConsoleFormatter.error("Duplicate cards detected. Please provide 2 different cards.", indent=2)
                            print()
                            continue
                        
                        hand = validated_cards[:2]
                        ConsoleFormatter.success(f"Valid hand: {', '.join(hand)}", indent=2)
                        
                        # Simulate adding cards to reader (but suppress output to avoid clutter)
                        reader.current_cards.clear()
                        reader.card_count = 0
                        # Add cards directly without going through add_card to avoid extra output
                        for card in hand:
                            reader.current_cards.append(card)
                            reader.card_count += 1
                        
                        # Send to Arduino if connected
                        if reader.serial is not None:
                            success = reader.send_hand_to_arduino(hand)
                            if success:
                                ConsoleFormatter.success("Hand sent successfully!", indent=2)
                            else:
                                ConsoleFormatter.warning("Failed to send hand (serial may be disconnected)", indent=2)
                        else:
                            # Show what would be sent
                            card1_list = reader.card_to_list(hand[0])
                            card2_list = reader.card_to_list(hand[1])
                            hand_list = card1_list + card2_list
                            hand_str = ",".join(hand_list)
                            ConsoleFormatter.info(f"Would send: HAND:{hand_str}", indent=2)
                            ConsoleFormatter.warning("Serial not connected - data not sent", indent=2)
                        
                        print()
                        
                    except (EOFError, KeyboardInterrupt):
                        print()
                        ConsoleFormatter.info("Exiting manual input mode...", indent=2)
                        print()
                        break
                    except Exception as e:
                        ConsoleFormatter.error(f"Error: {e}", indent=2)
                        import traceback
                        ConsoleFormatter.error(f"Traceback: {traceback.format_exc()}", indent=3)
                        print()
                        # Continue the loop to allow user to try again
                        continue
            
            elif choice == '7':
                # Send RESET command to Arduino
                ConsoleFormatter.info("Sending RESET command to Arduino...", indent=2)
                if reader.serial is not None:
                    try:
                        # Check if serial port is still open
                        if not hasattr(reader.serial, 'is_open') or not reader.serial.is_open:
                            ConsoleFormatter.warning("Serial port is not open", indent=3)
                            reader.serial = None
                        else:
                            reader.serial.write(b"RESET\n")
                            reader.serial.flush()
                            ConsoleFormatter.success("RESET command sent successfully!", indent=2)
                    except (OSError, SerialExceptionType) as e:
                        ConsoleFormatter.error(f"Serial error sending RESET: {e}", indent=2)
                        reader.serial = None
                    except Exception as e:
                        ConsoleFormatter.error(f"Unexpected error sending RESET: {e}", indent=2)
                else:
                    ConsoleFormatter.warning("No serial connection - RESET command not sent", indent=2)
                print()
            
            elif choice == 'Q':
                ConsoleFormatter.info("Exiting test mode...", indent=2)
                break
                
            else:
                ConsoleFormatter.error(f"Invalid choice: '{choice}'", indent=2)
                print()
    
    except KeyboardInterrupt:
        print()
        ConsoleFormatter.info("Test mode interrupted by user", indent=2)


def show_startup_menu():
    """Display startup menu to choose between normal and test mode."""
    ConsoleFormatter.header("POKER HAND READER", "🎴")
    print()
    print("  [1] Normal Mode (read from QR scanner)")
    print("  [2] Test Mode (generate random hands)")
    print("  [Q] Quit")
    print()
    ConsoleFormatter.separator()
    ConsoleFormatter.input_msg("Select mode: ", indent=0)
    choice = input().strip().upper()
    return choice


def main():
    """Main function to run the poker hand reader."""
    parser = argparse.ArgumentParser(description="Poker Hand Reader with Arduino output")
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
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Skip menu and go directly to test mode",
    )
    args = parser.parse_args()

    # Serial connection and auto-reconnect state
    ser = None
    last_serial_attempt = 0.0
    RECONNECT_INTERVAL = 5.0  # seconds between reconnect attempts

    reader = PokerHandReader(serial_conn=None)

    def attempt_serial_connect(force: bool = False):
        """Try to (re)open the serial port if needed."""
        nonlocal ser, last_serial_attempt

        if not HAVE_SERIAL:
            return

        if not args.serial_port:
            return

        now = time.time()
        if not force and now - last_serial_attempt < RECONNECT_INTERVAL:
            return

        last_serial_attempt = now

        # If we already have an open port, nothing to do
        if ser is not None and hasattr(ser, "is_open") and ser.is_open:
            return

        s = try_serial_ports(args.serial_port, args.baudrate)
        if s is not None:
            ser = s
            reader.serial = ser
        else:
            ser = None
            reader.serial = None

    # Initialize cards database
    init_cards_database()
    
    # Preload all audio files to reduce first-play delay
    preload_audio_files()
    
    # Pre-warm audio system to reduce first-play delay
    ConsoleFormatter.info("Pre-initializing audio system...", indent=0)
    prewarm_audio_system()
    
    # Initial connection attempt
    attempt_serial_connect(force=True)
    
    # Send reset command to Arduino to ensure it starts in blank/B position
    if ser is not None and reader.serial is not None:
        try:
            if hasattr(reader.serial, 'is_open') and reader.serial.is_open:
                ConsoleFormatter.info("Sending initial reset command to Arduino...", indent=0)
                reader.serial.write(b"R\n")
                reader.serial.flush()
                ConsoleFormatter.success("Reset command sent - Arduino initialized to blank/B position", indent=0)
                # Small delay to ensure Arduino processes the command
                time.sleep(0.2)
        except (OSError, SerialExceptionType) as e:
            ConsoleFormatter.warning(f"Failed to send initial reset command: {e}", indent=0)
        except Exception as e:
            ConsoleFormatter.warning(f"Unexpected error sending initial reset: {e}", indent=0)
    
    # Show startup menu unless --test-mode flag is used
    if args.test_mode:
        # Direct test mode
        run_test_mode(reader, ser)
        return
    else:
        mode_choice = show_startup_menu()
        if mode_choice == 'Q':
            ConsoleFormatter.info("Goodbye!")
            return
        elif mode_choice == '2':
            # Test mode selected
            run_test_mode(reader, ser)
            return
        elif mode_choice != '1':
            ConsoleFormatter.error("Invalid choice. Exiting.")
            return
    
    # Normal mode - save terminal settings
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    ConsoleFormatter.header("Poker Hand Reader", "🎴")
    print("\nInstructions:")
    ConsoleFormatter.bullet("Scan QR codes with poker cards (e.g., 'AS', 'KH', '2C')")
    ConsoleFormatter.bullet("Cards are processed automatically when 2–3 characters are entered")
    ConsoleFormatter.bullet("Once 2 unique cards are detected, hand will be stored")
    ConsoleFormatter.bullet("Press 'R' to reset current hand")
    ConsoleFormatter.bullet("Press 'Q' to quit")
    ConsoleFormatter.bullet("Press 'S' to show status")
    print()
    ConsoleFormatter.input_msg("Reading character-by-character input from QR code reader...")
    ConsoleFormatter.info("No Enter key needed - cards processed automatically", indent=3)
    if ser is not None:
        ConsoleFormatter.info("Arduino output will appear prefixed as [ARDUINO] ...", indent=3)
    print()
    
    try:
        # Set terminal to raw mode for character-by-character input
        tty.setraw(fd)
        
        input_buffer = ""
        
        # Flush any buffered input before starting
        time.sleep(0.1)
        while select.select([sys.stdin], [], [], 0)[0]:
            try:
                sys.stdin.read(1)
            except Exception:
                break
        
        while True:
            try:
                # Check for reset flag from live_qr_detector.py (when RESET card is shown)
                if check_and_clear_reset_flag():
                    print()
                    ConsoleFormatter.header("RESET DETECTED FROM CAMERA", "🔄")
                    ConsoleFormatter.info("Reset card detected by live_qr_detector.py", indent=2)
                    reader.reset()
                
                # Attempt reconnect if serial is currently down
                if ser is None or reader.serial is None:
                    attempt_serial_connect(force=False)
                    # Ensure reader has the latest serial connection
                    reader.serial = ser

                # --- Read anything the Arduino prints (if connected) ---
                if ser is not None and reader.serial is not None:
                    try:
                        # Drain all waiting lines so we don't fall behind
                        while ser.in_waiting:
                            line = ser.readline().decode("utf-8", errors="replace").rstrip()
                            if line:
                                ConsoleFormatter.arduino(line)
                                
                                # Check if Arduino sent 'RIVER' command to trigger audio playback
                                if line.upper().strip() == "RIVER":
                                    print()
                                    ConsoleFormatter.header("RIVER DETECTED", "🎵")
                                    ConsoleFormatter.success("RIVER command received from Arduino", indent=2)
                                    ConsoleFormatter.info("Reading cards from database and playing audio...", indent=2)
                                    # Read cards from the database written by live_qr_detector.py
                                    current_cards = read_cards_from_database()
                                    if len(current_cards) < config.FLOP_CARD_COUNT:
                                        # Less than flop count - play waiting audio
                                        ConsoleFormatter.warning(f"Only {len(current_cards)} card(s) in database (need {config.FLOP_CARD_COUNT}+ for river). Playing waiting audio...", indent=2)
                                        waiting_path = os.path.join(AUDIO_DIR, "waiting.mp3")
                                        if os.path.exists(waiting_path):
                                            ConsoleFormatter.info("Playing waiting.mp3...", indent=3)
                                            if play_audio(waiting_path, speed=config.ANNOUNCEMENT_AUDIO_SPEED):
                                                ConsoleFormatter.success("Waiting audio played successfully", indent=3)
                                            else:
                                                ConsoleFormatter.error("Failed to play waiting audio", indent=3)
                                        else:
                                            ConsoleFormatter.warning(f"waiting.mp3 not found at {waiting_path}", indent=2)
                                    elif current_cards:
                                        ConsoleFormatter.info(f"Cards from database: {', '.join(current_cards)}", indent=3)
                                        play_cards_audio(current_cards)
                                    else:
                                        ConsoleFormatter.warning("No cards found in database. Make sure live_qr_detector.py is running and has detected cards.", indent=2)
                                    ConsoleFormatter.separator()
                                    print()
                                
                                # Check if Arduino sent 'HAND' command to trigger audio playback for player's current hand
                                elif line.upper().strip() == "HAND":
                                    print()
                                    ConsoleFormatter.header("HAND DETECTED", "🃏")
                                    ConsoleFormatter.success("HAND command received from Arduino", indent=2)
                                    ConsoleFormatter.info("Reading current player hand and playing audio...", indent=2)
                                    # Get current hand from reader
                                    current_hand = reader.get_hand()
                                    if len(current_hand) < config.PLAYER_HAND_SIZE:
                                        # Less than required cards - play waiting hand audio
                                        ConsoleFormatter.warning(f"Only {len(current_hand)} card(s) scanned (need {config.PLAYER_HAND_SIZE} for hand). Playing waiting hand audio...", indent=2)
                                        waiting_hand_path = os.path.join(AUDIO_DIR, "waiting_hand.mp3")
                                        if os.path.exists(waiting_hand_path):
                                            ConsoleFormatter.info("Playing waiting_hand.mp3...", indent=3)
                                            if play_audio(waiting_hand_path, speed=config.ANNOUNCEMENT_AUDIO_SPEED):
                                                ConsoleFormatter.success("Waiting hand audio played successfully", indent=3)
                                            else:
                                                ConsoleFormatter.error("Failed to play waiting hand audio", indent=3)
                                        else:
                                            ConsoleFormatter.warning(f"waiting_hand.mp3 not found at {waiting_hand_path}", indent=2)
                                        if len(current_hand) == 1:
                                            ConsoleFormatter.info(f"Current card: {current_hand[0]}", indent=3)
                                    elif len(current_hand) == config.PLAYER_HAND_SIZE:
                                        ConsoleFormatter.info(f"Current hand: {', '.join(current_hand)}", indent=3)
                                        play_cards_audio(current_hand)
                                    ConsoleFormatter.separator()
                                    print()
                    except (OSError, SerialExceptionType) as e:
                        ConsoleFormatter.error(
                            f"Serial I/O error talking to Arduino: {e}. "
                            "Disabling Arduino connection; will retry later.",
                            indent=2,
                        )
                        try:
                            ser.close()
                        except Exception:
                            pass
                        ser = None
                        reader.serial = None
                        # Force next reconnect attempt quickly
                        last_serial_attempt = 0.0

                # --- QR scanner / keyboard input handling ---
                char = get_char(timeout=0.1)
                
                if char is None:
                    # Timeout - check if we should process the buffer
                    if input_buffer:
                        # Check for standalone commands (R, Q, S) - only if single character
                        if len(input_buffer) == 1 and input_buffer.isalpha():
                            cmd = input_buffer.upper()
                            if cmd == 'R':
                                print("\n")
                                ConsoleFormatter.info("Reset command received")
                                reader.reset()
                                input_buffer = ""
                                continue
                            elif cmd == 'Q':
                                print("\n")
                                ConsoleFormatter.info("Quit command received")
                                ConsoleFormatter.success("Goodbye!")
                                break
                            elif cmd == 'S':
                                print("\n")
                                ConsoleFormatter.info("Status command received")
                                reader.display_status()
                                input_buffer = ""
                                continue
                        
                        # Process as card if we have 2+ characters
                        if len(input_buffer) >= 2:
                            card = reader.validate_card(input_buffer)
                            
                            if card:
                                ConsoleFormatter.input_msg(
                                    f"Processed: '{input_buffer}' -> {card}"
                                )
                                reader.add_card(card)
                                
                                # If at least required cards, hand is automatically sent to Arduino
                                if len(reader.current_cards) >= config.PLAYER_HAND_SIZE:
                                    print()
                                    ConsoleFormatter.success(
                                        f"Hand complete! ({len(reader.current_cards)} cards)"
                                    )
                                    ConsoleFormatter.info(
                                        f"Hand: {', '.join(reader.get_hand())}",
                                        indent=3
                                    )
                            else:
                                ConsoleFormatter.error(
                                    f"Invalid card: '{input_buffer}' (not in 52 valid cards)",
                                    indent=2
                                )
                            
                            input_buffer = ""
                    continue
                
                # Handle special control characters
                if ord(char) == 3:  # Ctrl+C
                    print("\n")
                    ConsoleFormatter.info("Exiting...")
                    break
                
                if ord(char) == 4:  # Ctrl+D (EOF)
                    print("\n")
                    ConsoleFormatter.info("Exiting...")
                    break
                
                # Handle Enter/Return key
                if char == '\r' or char == '\n':
                    if input_buffer:
                        # Process what we have
                        card = reader.validate_card(input_buffer)
                        
                        if card:
                            print()
                            ConsoleFormatter.input_msg(
                                f"Processed: '{input_buffer}' -> {card}"
                            )
                            reader.add_card(card)
                            
                            if len(reader.current_cards) >= config.PLAYER_HAND_SIZE:
                                print()
                                ConsoleFormatter.success(
                                    f"Hand complete! ({len(reader.current_cards)} cards)"
                                )
                                ConsoleFormatter.info(
                                    f"Hand: {', '.join(reader.get_hand())}",
                                    indent=3
                                )
                        else:
                            print()
                            ConsoleFormatter.error(
                                f"Invalid card: '{input_buffer}' (not in 52 valid cards)",
                                indent=2
                            )
                        
                        input_buffer = ""
                
                # Handle backspace
                elif ord(char) == 127 or ord(char) == 8:  # Backspace
                    if input_buffer:
                        input_buffer = input_buffer[:-1]
                        print(
                            f"{ConsoleFormatter.PREFIX_INPUT}Backspace (buffer: '{input_buffer}')",
                            end='\r'
                        )
                
                # Handle printable characters
                elif char.isprintable():
                    # Add character to buffer first (for card input)
                    input_buffer += char
                    print(
                        f"{ConsoleFormatter.PREFIX_INPUT}Char: '{char}' (buffer: '{input_buffer}')",
                        end='\r'
                    )
                    
                    # If we have 2 or 3 characters, validate immediately
                    if len(input_buffer) >= 2:
                        card = reader.validate_card(input_buffer)
                        
                        if card:
                            # Valid card found - process it
                            print()
                            ConsoleFormatter.input_msg(
                                f"Processed: '{input_buffer}' -> {card}"
                            )
                            reader.add_card(card)
                            
                            # Check if we have at least required cards - hand is "ready"
                            if len(reader.current_cards) >= config.PLAYER_HAND_SIZE:
                                print()
                                ConsoleFormatter.success(
                                    f"Hand complete! ({len(reader.current_cards)} cards)"
                                )
                                ConsoleFormatter.info(
                                    f"Hand: {', '.join(reader.get_hand())}",
                                    indent=3
                                )
                            
                            input_buffer = ""
                        elif len(input_buffer) == 3:
                            # 3 characters and still not valid - invalid card
                            print()
                            ConsoleFormatter.error(
                                f"Invalid card: '{input_buffer}' (not in 52 valid cards)",
                                indent=2
                            )
                            input_buffer = ""
                
            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback
                traceback.print_exc()
                break
    
    finally:
        # Restore terminal settings
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        
        # Close serial if open
        if ser is not None:
            try:
                if ser.is_open:
                    ser.close()
            except Exception:
                pass
    
    # Display final summary
    ConsoleFormatter.header("Final Summary", "📊")
    reader.display_status()
    print()


if __name__ == "__main__":
    main()
