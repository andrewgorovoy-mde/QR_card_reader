"""
Configuration file for QR Card Reader system.

This file contains shared configuration parameters used by both
live_qr_detector.py and poker_hand_reader.py.

To modify settings:
1. Edit the values below
2. Both scripts will automatically use the new values on next run

Example: To change card audio playback speed to 2x (100% faster):
    CARD_AUDIO_SPEED = 2.0

Example: To add a 0.1 second delay between card audio files:
    CARD_AUDIO_DELAY = 0.1
"""

# ============================================================================
# AUDIO PLAYBACK CONFIGURATION
# ============================================================================

# Playback speed multiplier for card audio files (e.g., 2H.wav, AS.wav)
# 1.5 = 50% faster (default)
# 1.0 = normal speed
# 2.0 = 100% faster (double speed)
CARD_AUDIO_SPEED = 2.0

# Playback speed multiplier for announcement audio files
# (flop_down.mp3, turn_down.mp3, river_down.mp3, round_over.mp3, etc.)
# These are kept at normal speed by default
ANNOUNCEMENT_AUDIO_SPEED = 2.0

# Delay between card audio files (in seconds)
# Set to 0 for immediate playback (no delay)
CARD_AUDIO_DELAY = 0.0

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

# SQLite database file name for storing detected cards
CARDS_DATABASE_NAME = "detected_cards.db"

# ============================================================================
# AUDIO DIRECTORY CONFIGURATION
# ============================================================================

# Directory name for audio files (relative to script directory)
AUDIO_DIRECTORY_NAME = "audio_out"

# ============================================================================
# SERIAL COMMUNICATION CONFIGURATION
# ============================================================================

# Default serial baudrate for Arduino communication
DEFAULT_BAUDRATE = 115200

# Serial port defaults by platform
# These can be overridden via command-line arguments
SERIAL_PORT_DARWIN = "/dev/tty.usbmodem101"  # macOS
SERIAL_PORT_LINUX = "/dev/ttyACM0"           # Linux/Raspberry Pi
SERIAL_PORT_WINDOWS = ""                     # Windows (must be specified)

# ============================================================================
# POKER GAME CONFIGURATION
# ============================================================================

# Number of cards in a flop
FLOP_CARD_COUNT = 3

# Total number of community cards (flop + turn + river)
TOTAL_COMMUNITY_CARDS = 5

# Number of cards in a player's hand
PLAYER_HAND_SIZE = 2

