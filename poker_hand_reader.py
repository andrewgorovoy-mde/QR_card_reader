#!/usr/bin/env python3
"""
Poker Hand Reader Script (Pi/Mac side, with Arduino serial I/O)

Reads poker card input from a USB QR code reader (which acts as a keyboard).
Once two unique cards are detected, stores the hand.

Also sends messages to an Arduino over serial:
  - HAND:<list>  (e.g. HAND:A,B,S,N,7,H)   # 2 cards encoded as 6 elements
  - R            (reset command, you handle this on Arduino)

And reads any Serial.println() output from the Arduino and prints it
to this console with a [ARDUINO] prefix.

When Arduino sends 'RIVER' over serial, reads cards from detected_cards.txt file
(written by live_qr_detector.py) and plays audio files for those cards from the
audio_out directory.

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
from typing import List, Optional

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

# --- Default serial ports for different OSes ---

SYSTEM = platform.system()  # 'Darwin' for macOS, 'Linux' for Pi

if SYSTEM == "Darwin":
    # For your MKR WiFi 1010 on macOS
    DEFAULT_SERIAL_PORT = "/dev/cu.usbmodem1101"
elif SYSTEM == "Linux":
    # Typical Arduino device name on Raspberry Pi
    DEFAULT_SERIAL_PORT = "/dev/ttyACM0"
else:
    DEFAULT_SERIAL_PORT = ""  # unknown OS, must pass --serial-port

DEFAULT_BAUDRATE = 115200  # MKR WiFi 1010 is fine with 115200

# Path to audio_out folder (same level as this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(SCRIPT_DIR, "audio_out")
CARDS_FILE = os.path.join(SCRIPT_DIR, "detected_cards.txt")  # File to read cards from (written by live_qr_detector.py)


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


def play_wav(path: str) -> bool:
    """
    Play a .wav file using platform-appropriate audio player.
    - macOS: uses 'afplay'
    - Linux/Raspberry Pi: uses 'aplay'
    - Windows: uses 'start' command
    This call is blocking: it waits until the audio finishes.
    
    Returns:
        True if successful, False otherwise
    """
    system = platform.system()
    
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["afplay", path], check=True)
        elif system == "Linux":
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


def read_cards_from_file() -> List[str]:
    """
    Read cards from the detected_cards.txt file (written by live_qr_detector.py).
    
    Returns:
        List of card strings, empty list if file doesn't exist or is empty
    """
    if not os.path.exists(CARDS_FILE):
        return []
    
    try:
        with open(CARDS_FILE, "r", encoding="utf-8") as f:
            cards = [line.strip() for line in f.readlines() if line.strip()]
        return cards
    except Exception as e:
        ConsoleFormatter.error(f"Failed to read cards from file: {e}", indent=2)
        return []


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
            if play_wav(filepath):
                ConsoleFormatter.success("✓", indent=5)
                played_count += 1
            else:
                ConsoleFormatter.error("✗ Failed", indent=5)
            time.sleep(0.01)  # minimal pause between cards (10ms)
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
        
        Format: [face_value, number_value, suit]
        - face_value: N (not face), J, Q, K, A
        - number_value: B (blank if face card), 1-9 (number, 10 becomes 1)
        - suit: D, S, C, H
        
        Args:
            card: Card string like "AS", "7H", "10D", "KH"
            
        Returns:
            List of 3 elements [face, number, suit]
        """
        rank = card[:-1]  # Everything except last character (suit)
        suit = card[-1]   # Last character (suit)
        
        # Map suit
        suit_map = {'D': 'D', 'S': 'S', 'C': 'C', 'H': 'H'}
        suit_char = suit_map.get(suit, 'D')
        
        # Determine face card and number
        if rank == 'A':
            return ['A', 'B', suit_char]
        elif rank == 'J':
            return ['J', 'B', suit_char]
        elif rank == 'Q':
            return ['Q', 'B', suit_char]
        elif rank == 'K':
            return ['K', 'B', suit_char]
        elif rank == '10':
            return ['N', '1', suit_char]  # 10 becomes 1
        else:
            # Number card (2-9)
            return ['N', rank, suit_char]
    
    def send_hand_to_arduino(self, cards: List[str]) -> bool:
        """
        Send a hand (2 cards) to Arduino as a flat list of 6 elements.
        
        Format: [card1_face, card1_number, card1_suit, card2_face, card2_number, card2_suit]
        
        Args:
            cards: List of 2 card strings (e.g., ["AS", "7H"])
            
        Returns:
            True if sent successfully, False if failed (connection lost)
        """
        if self.serial is None:
            ConsoleFormatter.warning("Cannot send to Arduino: serial connection is None", indent=3)
            return False
        
        if len(cards) != 2:
            ConsoleFormatter.error(f"Cannot send to Arduino: expected 2 cards, got {len(cards)}", indent=3)
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
        
        # Keep only the 2 most recent cards
        if len(self.current_cards) > 2:
            self.current_cards.pop(0)
        
        ConsoleFormatter.success(f"Card {self.card_count} added: {card}", indent=2)
        ConsoleFormatter.info(f"Current cards: {self.current_cards}, Count: {self.card_count}", indent=3)
        
        # Send to Arduino only when we have 2 cards AND it's an even-numbered card (2nd, 4th, 6th, etc.)
        if len(self.current_cards) == 2 and self.card_count % 2 == 0:
            ConsoleFormatter.info(f"Sending pair to Arduino (card_count={self.card_count} is even)", indent=3)
            ConsoleFormatter.info(f"Cards to send: {self.current_cards}", indent=5)
            success = self.send_hand_to_arduino(self.current_cards)
            if not success:
                ConsoleFormatter.warning("Send failed - connection may be lost. Will retry on reconnect.", indent=3)
        elif len(self.current_cards) == 2:
            ConsoleFormatter.info(f"Have 2 cards but waiting (card_count={self.card_count} is odd)", indent=3)
        elif len(self.current_cards) < 2:
            ConsoleFormatter.info(f"Waiting for more cards (have {len(self.current_cards)}, need 2)", indent=3)
        
        return True
    
    def get_hand(self) -> List[str]:
        """
        Get current cards (up to 2 most recent).
        
        Returns:
            List of current cards
        """
        return self.current_cards.copy()
    
    def store_hand(self):
        """Store and clear the current hand."""
        if len(self.current_cards) >= 2:
            hand = self.get_hand()
            ConsoleFormatter.card(f"Hand stored: {', '.join(hand)}")
            
            # Send hand to Arduino in list format (only when we have 2 cards)
            if len(hand) == 2:
                success = self.send_hand_to_arduino(hand)
                if not success:
                    ConsoleFormatter.warning("Send failed - connection may be lost. Will retry on reconnect.", indent=3)
        else:
            ConsoleFormatter.warning(
                f"Hand has only {len(self.current_cards)} card(s). "
                f"Need at least 2 cards to store."
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
            if len(self.current_cards) >= 2:
                ConsoleFormatter.success("Hand complete! Will be stored on next card or reset.", indent=3)
        else:
            ConsoleFormatter.status("No cards currently in hand.")
        ConsoleFormatter.separator()


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
                    choice = input().strip().upper()
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

        try:
            ConsoleFormatter.info(
                f"Opening serial port {args.serial_port} at {args.baudrate} baud..."
            )
            s = serial.Serial(args.serial_port, args.baudrate, timeout=0.1)
            # Wait a bit for Arduino to reboot when serial opens
            time.sleep(2)
            ser = s
            reader.serial = ser
            ConsoleFormatter.success(
                f"Connected to Arduino on {args.serial_port} at {args.baudrate} baud"
            )
        except Exception as e:
            ConsoleFormatter.warning(
                f"Could not open serial port {args.serial_port}: {e}"
            )
            ser = None
            reader.serial = None

    # Initial connection attempt
    attempt_serial_connect(force=True)
    
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
                                    ConsoleFormatter.info("Reading cards from file and playing audio...", indent=2)
                                    # Read cards from the file written by live_qr_detector.py
                                    current_cards = read_cards_from_file()
                                    if current_cards:
                                        ConsoleFormatter.info(f"Cards from file: {', '.join(current_cards)}", indent=3)
                                        play_cards_audio(current_cards)
                                    else:
                                        ConsoleFormatter.warning("No cards found in file. Make sure live_qr_detector.py is running and has detected cards.", indent=2)
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
                                
                                # If at least 2 cards, hand is automatically sent to Arduino
                                if len(reader.current_cards) >= 2:
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
                            
                            if len(reader.current_cards) >= 2:
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
                            
                            # Check if we have at least 2 cards - hand is "ready"
                            if len(reader.current_cards) >= 2:
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
