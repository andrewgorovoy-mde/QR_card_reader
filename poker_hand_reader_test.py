#!/usr/bin/env python3
"""
Poker Hand Reader - Test Mode Only (No Audio)

Simplified version for testing Arduino communication without audio dependencies.
Sends hand data to Arduino over serial in encoded format.

Arduino Communication:
  - Sends: HAND:<list>  (e.g. HAND:H,B,J,D,2,B) - 2 cards encoded as 6 elements
  - Sends: RESET        (reset command)
  - Receives: 'RIVER' - Logged but no action taken
  - Receives: 'HAND' - Logged but no action taken
"""

import sys
import re
import time
import platform
import argparse
import random
from typing import List, Optional

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

SYSTEM = platform.system()

# Get default serial port from config based on platform
if SYSTEM == "Darwin":
    DEFAULT_SERIAL_PORT = config.SERIAL_PORT_DARWIN
elif SYSTEM == "Linux":
    DEFAULT_SERIAL_PORT = config.SERIAL_PORT_LINUX
else:
    DEFAULT_SERIAL_PORT = config.SERIAL_PORT_WINDOWS

DEFAULT_BAUDRATE = config.DEFAULT_BAUDRATE

# Console formatting helpers
class ConsoleFormatter:
    WIDTH = 70
    PREFIX_INFO = "ℹ️  "
    PREFIX_SUCCESS = "✓ "
    PREFIX_ERROR = "✗ "
    PREFIX_WARNING = "⚠️  "
    PREFIX_ARDUINO = "[ARDUINO]"
    
    @staticmethod
    def header(title: str, emoji: str = ""):
        print("\n" + "=" * ConsoleFormatter.WIDTH)
        if emoji:
            print(f"{emoji} {title}")
        else:
            print(title)
        print("=" * ConsoleFormatter.WIDTH)
    
    @staticmethod
    def info(msg: str, indent: int = 0):
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_INFO}{msg}")
    
    @staticmethod
    def success(msg: str, indent: int = 0):
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_SUCCESS}{msg}")
    
    @staticmethod
    def error(msg: str, indent: int = 0):
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_ERROR}{msg}")
    
    @staticmethod
    def warning(msg: str, indent: int = 0):
        spaces = " " * indent
        print(f"{spaces}{ConsoleFormatter.PREFIX_WARNING}{msg}")
    
    @staticmethod
    def arduino(msg: str):
        print(f"\n{ConsoleFormatter.PREFIX_ARDUINO} {msg}")
    
    @staticmethod
    def separator():
        print("-" * ConsoleFormatter.WIDTH)


class PokerHandReader:
    """Reads and manages poker hands for Arduino communication."""
    
    RANKS = {'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'}
    SUITS = {'S', 'H', 'D', 'C'}
    
    VALID_CARDS = {
        'AS', '2S', '3S', '4S', '5S', '6S', '7S', '8S', '9S', '10S', 'JS', 'QS', 'KS',
        'AH', '2H', '3H', '4H', '5H', '6H', '7H', '8H', '9H', '10H', 'JH', 'QH', 'KH',
        'AD', '2D', '3D', '4D', '5D', '6D', '7D', '8D', '9D', '10D', 'JD', 'QD', 'KD',
        'AC', '2C', '3C', '4C', '5C', '6C', '7C', '8C', '9C', '10C', 'JC', 'QC', 'KC'
    }
    
    def __init__(self, serial_conn=None):
        self.current_cards: List[str] = []
        self.card_count: int = 0
        self.serial = serial_conn
    
    def card_to_list(self, card: str) -> List[str]:
        """
        Convert a card string to Arduino list format.
        Format: [suit, column2, column3]
        """
        rank = card[:-1]
        suit = card[-1]
        
        suit_map = {'D': 'D', 'S': 'S', 'C': 'C', 'H': 'H'}
        suit_char = suit_map.get(suit.upper(), 'D')
        
        if rank in ['2', '3', '4', '5', '6', '7']:
            return [suit_char, rank, 'B']
        elif rank in ['8', '9', '10', 'J', 'Q', 'K', 'A']:
            return [suit_char, 'B', rank]
        else:
            return [suit_char, 'B', 'B']
    
    def send_hand_to_arduino(self, cards: List[str]) -> bool:
        """Send a hand (2 cards) to Arduino as a flat list of 6 elements."""
        if self.serial is None:
            ConsoleFormatter.warning("Cannot send to Arduino: serial connection is None", indent=3)
            return False
        
        if len(cards) != config.PLAYER_HAND_SIZE:
            ConsoleFormatter.error(f"Cannot send to Arduino: expected {config.PLAYER_HAND_SIZE} cards, got {len(cards)}", indent=3)
            return False
        
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
            card1_list = self.card_to_list(cards[0])
            card2_list = self.card_to_list(cards[1])
            hand_list = card1_list + card2_list
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
            try:
                if hasattr(self.serial, 'close'):
                    self.serial.close()
            except Exception:
                pass
            self.serial = None
            return False
        except Exception as e:
            ConsoleFormatter.error(f"Unexpected error sending hand to Arduino: {e}", indent=3)
            return False
    
    def validate_card(self, input_str: str) -> Optional[str]:
        """Validate a card against the 52 valid poker cards."""
        input_str = input_str.strip().upper()
        input_str = re.sub(r'[^A-Z0-9]', '', input_str)
        
        if len(input_str) < 2 or len(input_str) > 3:
            return None
        
        if input_str in self.VALID_CARDS:
            return input_str
        
        return None
    
    def get_hand(self) -> List[str]:
        """Get current cards."""
        return self.current_cards.copy()
    
    def reset(self):
        """Reset the current hand and send reset command to Arduino."""
        if self.current_cards:
            ConsoleFormatter.info(f"Resetting hand: {', '.join(self.get_hand())}")
        else:
            ConsoleFormatter.info("Resetting empty hand.")
        self.current_cards.clear()
        self.card_count = 0
        
        if self.serial is not None:
            try:
                self.serial.write(b"RESET\n")
                self.serial.flush()
                ConsoleFormatter.info("Sent RESET command to Arduino", indent=3)
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
            ConsoleFormatter.info(
                f"Current cards ({len(self.current_cards)} card(s)): "
                f"{', '.join(self.get_hand())}"
            )
        else:
            ConsoleFormatter.info("No cards currently in hand.")
        ConsoleFormatter.separator()


def try_serial_ports(base_port: str, baudrate: int):
    """Try to connect to serial port, attempting multiple port numbers on macOS if needed."""
    if not HAVE_SERIAL:
        return None
    
    if SYSTEM == "Darwin" and "usbmodem" in base_port:
        # Detect prefix (cu or tty)
        prefix = "tty" if "/dev/tty.usbmodem" in base_port else "cu"
        
        try:
            base_port_num = int(base_port.replace(f"/dev/{prefix}.usbmodem", ""))
        except ValueError:
            base_port_num = None
        
        port_numbers = [2101, 1101, 101]
        if base_port_num is not None and base_port_num not in port_numbers:
            port_numbers.insert(0, base_port_num)
        
        # Try ports with the same prefix first
        for port_num in port_numbers:
            port_path = f"/dev/{prefix}.usbmodem{port_num}"
            try:
                ConsoleFormatter.info(f"Trying serial port {port_path}...", indent=2)
                s = serial.Serial(port_path, baudrate, timeout=0.1)
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
        
        ConsoleFormatter.error("Could not connect to any serial port.", indent=2)
        return None
    else:
        try:
            ConsoleFormatter.info(f"Opening serial port {base_port} at {baudrate} baud...")
            s = serial.Serial(base_port, baudrate, timeout=0.1)
            time.sleep(2)
            ConsoleFormatter.success(f"Connected to Arduino on {base_port} at {baudrate} baud")
            return s
        except Exception as e:
            ConsoleFormatter.warning(f"Could not open serial port {base_port}: {e}")
            return None


def generate_random_hand() -> List[str]:
    """Generate a random poker hand (2 unique cards)."""
    cards = list(PokerHandReader.VALID_CARDS)
    hand = random.sample(cards, 2)
    return hand


def show_test_menu():
    """Display ASCII menu for test mode."""
    ConsoleFormatter.header("TEST MODE MENU", "🧪")
    print()
    print("  [1] Generate and send random hand")
    print("  [2] Generate and send N random hands")
    print("  [3] Auto-generate hands (continuous)")
    print("  [4] Send reset command")
    print("  [5] Show current status")
    print("  [6] Manually input cards to send")
    print("  [7] Send RESET command to Arduino")
    print("  [Q] Quit test mode")
    print()
    ConsoleFormatter.separator()


def run_test_mode(reader: PokerHandReader, ser=None):
    """Run test mode with interactive menu."""
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
    auto_interval = 2.0
    
    try:
        while True:
            if not auto_mode:
                show_test_menu()
                ConsoleFormatter.info("Enter choice: ", indent=0)
                try:
                    sys.stdout.flush()
                    time.sleep(0.05)
                    choice = input().strip().upper()
                    
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
                hand = generate_random_hand()
                ConsoleFormatter.info(f"Generated random hand: {', '.join(hand)}", indent=2)
                
                reader.current_cards.clear()
                reader.card_count = 0
                for card in hand:
                    reader.current_cards.append(card)
                    reader.card_count += 1
                
                if reader.serial is not None:
                    success = reader.send_hand_to_arduino(hand)
                    if success:
                        ConsoleFormatter.success("Hand sent successfully!", indent=2)
                    else:
                        ConsoleFormatter.warning("Failed to send hand (serial may be disconnected)", indent=2)
                else:
                    card1_list = reader.card_to_list(hand[0])
                    card2_list = reader.card_to_list(hand[1])
                    hand_list = card1_list + card2_list
                    hand_str = ",".join(hand_list)
                    ConsoleFormatter.info(f"Would send: HAND:{hand_str}", indent=2)
                    ConsoleFormatter.warning("Serial not connected - data not sent", indent=2)
                
                print()
                
            elif choice == '2':
                ConsoleFormatter.info("How many hands to generate? ", indent=0)
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
                        
                        reader.current_cards.clear()
                        reader.card_count = 0
                        for card in hand:
                            reader.current_cards.append(card)
                            reader.card_count += 1
                        
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
                            time.sleep(0.5)
                        print()
                except KeyboardInterrupt:
                    print()
                    ConsoleFormatter.info("Interrupted by user", indent=2)
                    print()
            
            elif choice == '3':
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
                ConsoleFormatter.info("Sending reset command...", indent=2)
                reader.reset()
                print()
            
            elif choice == '5':
                reader.display_status()
                print()
            
            elif choice == '6':
                ConsoleFormatter.header("MANUAL CARD INPUT MODE", "✍️")
                ConsoleFormatter.info("Enter 2 cards (e.g., 'AS 7H' or 'AS,7H' or one per line)", indent=2)
                ConsoleFormatter.info("Valid format: Rank + Suit (e.g., AS, KH, 2C, 10D)", indent=2)
                ConsoleFormatter.info("Type 'q' or 'back' to return to menu", indent=2)
                ConsoleFormatter.separator()
                print()
                
                while True:
                    try:
                        sys.stdout.flush()
                        time.sleep(0.1)
                        ConsoleFormatter.info("Enter cards (or 'q' to quit): ", indent=0)
                        sys.stdout.flush()
                        user_input = input().strip()
                        
                        if not user_input:
                            ConsoleFormatter.warning("No input provided. Type 'q' to exit manual mode.", indent=2)
                            print()
                            continue
                        
                        if user_input.upper() in ['Q', 'QUIT', 'BACK', 'EXIT']:
                            ConsoleFormatter.info("Exiting manual input mode...", indent=2)
                            print()
                            break
                        
                        cards_input = []
                        if ',' in user_input:
                            cards_input = [c.strip().upper() for c in user_input.split(',') if c.strip()]
                        elif ' ' in user_input:
                            cards_input = [c.strip().upper() for c in user_input.split() if c.strip()]
                        else:
                            cards_input = [user_input.strip().upper()]
                            sys.stdout.flush()
                            ConsoleFormatter.info("Enter second card: ", indent=0)
                            sys.stdout.flush()
                            second_card = input().strip().upper()
                            if second_card:
                                cards_input.append(second_card)
                        
                        ConsoleFormatter.info(f"Parsed input: {cards_input}", indent=3)
                        
                        validated_cards = []
                        for card_input in cards_input:
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
                        
                        if validated_cards[0] == validated_cards[1]:
                            ConsoleFormatter.error("Duplicate cards detected. Please provide 2 different cards.", indent=2)
                            print()
                            continue
                        
                        hand = validated_cards[:2]
                        ConsoleFormatter.success(f"Valid hand: {', '.join(hand)}", indent=2)
                        
                        reader.current_cards.clear()
                        reader.card_count = 0
                        for card in hand:
                            reader.current_cards.append(card)
                            reader.card_count += 1
                        
                        if reader.serial is not None:
                            success = reader.send_hand_to_arduino(hand)
                            if success:
                                ConsoleFormatter.success("Hand sent successfully!", indent=2)
                            else:
                                ConsoleFormatter.warning("Failed to send hand (serial may be disconnected)", indent=2)
                        else:
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
                        print()
                        continue
            
            elif choice == '7':
                ConsoleFormatter.info("Sending RESET command to Arduino...", indent=2)
                if reader.serial is not None:
                    try:
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


def main():
    """Main function to run the poker hand reader test mode."""
    parser = argparse.ArgumentParser(description="Poker Hand Reader - Test Mode Only")
    parser.add_argument(
        "--serial-port",
        default=DEFAULT_SERIAL_PORT,
        help=f"Serial port for Arduino (default: '{DEFAULT_SERIAL_PORT or 'NONE'}' for {SYSTEM})",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"Serial baudrate (default: {DEFAULT_BAUDRATE})",
    )
    args = parser.parse_args()

    ser = None
    reader = PokerHandReader(serial_conn=None)

    # Try to connect to serial port
    if HAVE_SERIAL and args.serial_port:
        ser = try_serial_ports(args.serial_port, args.baudrate)
        if ser is not None:
            reader.serial = ser
            # Send initial reset command
            try:
                if hasattr(reader.serial, 'is_open') and reader.serial.is_open:
                    ConsoleFormatter.info("Sending initial reset command to Arduino...", indent=0)
                    reader.serial.write(b"RESET\n")
                    reader.serial.flush()
                    ConsoleFormatter.success("Reset command sent - Arduino initialized", indent=0)
                    time.sleep(0.2)
            except Exception as e:
                ConsoleFormatter.warning(f"Failed to send initial reset: {e}", indent=0)
    
    # Run test mode
    run_test_mode(reader, ser)
    
    # Close serial if open
    if ser is not None:
        try:
            if ser.is_open:
                ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

