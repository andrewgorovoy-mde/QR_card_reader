#!/usr/bin/env python3
"""
Poker Hand Reader Script (Pi/Mac side, with Arduino serial I/O)

Reads poker card input from a USB QR code reader (which acts as a keyboard).
Once two unique cards are detected, stores the hand.

Also sends messages to an Arduino over serial:
  - CARD:<card>  (e.g. CARD:AS)
  - HAND:<cards> (e.g. HAND:AS,7H)
  - RESET

And reads any Serial.println() output from the Arduino and prints it
to this console with a [ARDUINO] prefix.

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
from typing import List, Optional

# Try to import pyserial
try:
    import serial
    HAVE_SERIAL = True
except ImportError:
    serial = None
    HAVE_SERIAL = False

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
    
    def send_hand_to_arduino(self, cards: List[str]):
        """
        Send a hand (2 cards) to Arduino as a flat list of 6 elements.
        
        Format: [card1_face, card1_number, card1_suit, card2_face, card2_number, card2_suit]
        
        Args:
            cards: List of 2 card strings (e.g., ["AS", "7H"])
        """
        if self.serial is None:
            ConsoleFormatter.warning("Cannot send to Arduino: serial connection is None", indent=3)
            return
        
        if len(cards) != 2:
            ConsoleFormatter.error(f"Cannot send to Arduino: expected 2 cards, got {len(cards)}", indent=3)
            return
        
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
            
            self.serial.write(message.encode("ascii", errors="ignore"))
            self.serial.flush()
            
            ConsoleFormatter.success(f"Sent to Arduino: HAND:{hand_str.strip()}", indent=3)
            ConsoleFormatter.info(f"Data: {hand_list}", indent=5)
        except Exception as e:
            ConsoleFormatter.error(f"Error sending to Arduino: {e}", indent=3)
            import traceback
            ConsoleFormatter.error(f"Traceback: {traceback.format_exc()}", indent=5)
    
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
            ConsoleFormatter.info(f"Current cards: {self.current_cards}, Count: {self.card_count} (unchanged)", indent=3)
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
            self.send_hand_to_arduino(self.current_cards)
        elif len(self.current_cards) == 2:
            ConsoleFormatter.info(f"Have 2 cards but waiting (card_count={self.card_count} is odd)", indent=3)
        
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
                self.send_hand_to_arduino(hand)
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
        
        # Send reset command to Arduino
        if self.serial is not None:
            try:
                self.serial.write(b"R\n")
                self.serial.flush()
                ConsoleFormatter.info("Sent reset command 'R' to Arduino", indent=3)
            except Exception as e:
                ConsoleFormatter.error(f"Error sending reset to Arduino: {e}", indent=3)
        
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
    args = parser.parse_args()

    # Try to open serial connection to Arduino
    ser = None
    if not HAVE_SERIAL:
        ConsoleFormatter.warning(
            "pyserial not installed. Run 'pip install pyserial' to enable Arduino serial output."
        )
    elif not args.serial_port:
        ConsoleFormatter.warning(
            "No default serial port for this OS. Use --serial-port to specify one."
        )
    else:
        try:
            ConsoleFormatter.info(f"Opening serial port {args.serial_port} at {args.baudrate} baud...")
            # small timeout so .readline() won't block forever
            ser = serial.Serial(args.serial_port, args.baudrate, timeout=0.1)
            # Wait a bit for Arduino to reboot when serial opens
            time.sleep(2)
            ConsoleFormatter.success(
                f"Connected to Arduino on {args.serial_port} at {args.baudrate} baud"
            )
        except Exception as e:
            ConsoleFormatter.warning(f"Could not open serial port {args.serial_port}: {e}")
            ConsoleFormatter.info("Continuing WITHOUT Arduino connection.", indent=3)
            print()
            ser = None
    
    reader = PokerHandReader(serial_conn=ser)
    
    # Save terminal settings
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
        # Small delay to let terminal settle after raw mode
        time.sleep(0.1)
        
        # Drain any buffered input
        while select.select([sys.stdin], [], [], 0)[0]:
            try:
                sys.stdin.read(1)
            except:
                break
        
        while True:
            try:
                # --- NEW: show anything the Arduino prints ---
                if ser is not None:
                    # Drain all waiting lines so we don't fall behind
                    while ser.in_waiting:
                        line = ser.readline().decode("utf-8", errors="replace").rstrip()
                        if line:
                            ConsoleFormatter.arduino(line)
                
                # --- existing QR scanner input handling ---
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
                                ConsoleFormatter.input_msg(f"Processed: '{input_buffer}' -> {card}")
                                reader.add_card(card)
                                
                                # If at least 2 cards, hand is automatically sent to Arduino
                                if len(reader.current_cards) >= 2:
                                    print()
                                    ConsoleFormatter.success(
                                        f"Hand complete! ({len(reader.current_cards)} cards)"
                                    )
                                    ConsoleFormatter.info(f"Hand: {', '.join(reader.get_hand())}", indent=3)
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
                            ConsoleFormatter.input_msg(f"Processed: '{input_buffer}' -> {card}")
                            reader.add_card(card)
                            
                            if len(reader.current_cards) >= 2:
                                print()
                                ConsoleFormatter.success(
                                    f"Hand complete! ({len(reader.current_cards)} cards)"
                                )
                                ConsoleFormatter.info(f"Hand: {', '.join(reader.get_hand())}", indent=3)
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
                        print(f"{ConsoleFormatter.PREFIX_INPUT}Backspace (buffer: '{input_buffer}')", end='\r')
                
                # Handle printable characters
                elif char.isprintable():
                    # Debug: show what character we received
                    char_code = ord(char)
                    
                    # Add character to buffer first (for card input)
                    input_buffer += char
                    print(f"{ConsoleFormatter.PREFIX_INPUT}Char: '{char}' (code={char_code}) (buffer: '{input_buffer}')", end='\r')
                    
                    # If we have 2 or 3 characters, validate immediately
                    if len(input_buffer) >= 2:
                        card = reader.validate_card(input_buffer)
                        
                        if card:
                            # Valid card found - process it
                            print()
                            ConsoleFormatter.input_msg(f"Processed: '{input_buffer}' -> {card}")
                            reader.add_card(card)
                            
                            # Check if we have at least 2 unique cards - store automatically
                            if len(reader.current_cards) >= 2:
                                print()
                                ConsoleFormatter.success(
                                    f"Hand complete! ({len(reader.current_cards)} cards)"
                                )
                                ConsoleFormatter.info(f"Hand: {', '.join(reader.get_hand())}", indent=3)
                            
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
