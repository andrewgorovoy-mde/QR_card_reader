#!/usr/bin/env python3
"""
Poker Hand Reader Script

Reads poker card input from a USB QR code reader (which acts as a keyboard).
Once two unique cards are detected, stores the hand.
Press 'R' to reset the hand.
"""

import sys
import re
import tty
import termios
import select
from typing import Set, List, Optional


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
    
    def __init__(self):
        """Initialize the poker hand reader."""
        self.current_hand: Set[str] = set()  # Use set to automatically handle duplicates
        self.hand_history: List[List[str]] = []  # Store completed hands
        
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
        Add a card to the current hand if it's unique.
        
        Args:
            card: Normalized card string
            
        Returns:
            True if card was added, False if duplicate
        """
        if card in self.current_hand:
            print(f"  ⚠️  Duplicate card: {card}")
            return False
        
        self.current_hand.add(card)
        print(f"  ✓ Card added: {card}")
        return True
    
    def get_hand(self) -> List[str]:
        """
        Get current hand as sorted list.
        
        Returns:
            List of cards in current hand, sorted
        """
        return sorted(list(self.current_hand))
    
    def store_hand(self):
        """Store the current hand in history and clear it."""
        if len(self.current_hand) >= 2:
            hand = self.get_hand()
            self.hand_history.append(hand.copy())
            print(f"\n🎴 Hand stored: {', '.join(hand)}")
            print(f"   Total hands stored: {len(self.hand_history)}")
        else:
            print(f"\n⚠️  Hand has only {len(self.current_hand)} card(s). Need at least 2 cards to store.")
        
        self.current_hand.clear()
        print("   Hand reset. Ready for new cards.\n")
    
    def reset(self):
        """Reset the current hand without storing it."""
        if self.current_hand:
            print(f"\n🔄 Resetting hand: {', '.join(self.get_hand())}")
        else:
            print("\n🔄 Resetting empty hand.")
        self.current_hand.clear()
        print("   Ready for new cards.\n")
    
    def display_status(self):
        """Display current status."""
        if self.current_hand:
            print(f"\n📊 Current hand ({len(self.current_hand)} card(s)): {', '.join(self.get_hand())}")
            if len(self.current_hand) >= 2:
                print("   ✓ Hand complete! Will be stored on next card or reset.")
        else:
            print("\n📊 No cards in current hand.")
        
        if self.hand_history:
            print(f"📚 Total hands stored: {len(self.hand_history)}")
            print(f"   Last hand: {', '.join(self.hand_history[-1])}")


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
    reader = PokerHandReader()
    
    # Save terminal settings
    old_settings = termios.tcgetattr(sys.stdin)
    
    print("=" * 60)
    print("🎴 Poker Hand Reader")
    print("=" * 60)
    print("\nInstructions:")
    print("  • Scan QR codes with poker cards (e.g., 'AS', 'KH', '2C')")
    print("  • Cards are processed automatically when 2-3 characters are entered")
    print("  • Once 2 unique cards are detected, hand will be stored")
    print("  • Press 'R' to reset current hand")
    print("  • Press 'Q' to quit")
    print("  • Press 'S' to show status")
    print("\n📥 Reading character-by-character input from QR code reader...")
    print("   (No Enter key needed - cards processed automatically)\n")
    
    try:
        # Set terminal to raw mode for character-by-character input
        tty.setraw(sys.stdin.fileno())
        
        input_buffer = ""
        
        while True:
            try:
                # Read a single character
                char = get_char(timeout=0.1)
                
                if char is None:
                    # Timeout - check if we should process the buffer
                    if input_buffer and len(input_buffer) >= 2:
                        # Process the accumulated characters
                        card = reader.validate_card(input_buffer)
                        
                        if card:
                            print(f"📥 Processed: '{input_buffer}' -> {card}")
                            reader.add_card(card)
                            
                            # Check if we have at least 2 unique cards - store automatically
                            if len(reader.current_hand) >= 2:
                                print(f"\n✅ Hand complete! ({len(reader.current_hand)} unique cards)")
                                print(f"   Hand: {', '.join(reader.get_hand())}")
                                reader.store_hand()
                        else:
                            print(f"  ❌ Invalid card: '{input_buffer}' (not in 52 valid cards)")
                        
                        input_buffer = ""
                    continue
                
                # Handle special control characters
                if ord(char) == 3:  # Ctrl+C
                    print("\n\nExiting...")
                    break
                
                if ord(char) == 4:  # Ctrl+D (EOF)
                    print("\n\nExiting...")
                    break
                
                # Handle Enter/Return key
                if char == '\r' or char == '\n':
                    if input_buffer:
                        # Process what we have
                        card = reader.validate_card(input_buffer)
                        
                        if card:
                            print(f"\n📥 Processed: '{input_buffer}' -> {card}")
                            reader.add_card(card)
                            
                            if len(reader.current_hand) >= 2:
                                print(f"\n✅ Hand complete! ({len(reader.current_hand)} unique cards)")
                                print(f"   Hand: {', '.join(reader.get_hand())}")
                                reader.store_hand()
                        else:
                            print(f"\n  ❌ Invalid card: '{input_buffer}' (not in 52 valid cards)")
                        
                        input_buffer = ""
                
                # Handle backspace
                elif ord(char) == 127 or ord(char) == 8:  # Backspace
                    if input_buffer:
                        input_buffer = input_buffer[:-1]
                        print(f"📥 Backspace (buffer: '{input_buffer}')", end='\r')
                
                # Handle printable characters
                elif char.isprintable():
                    # Check for special commands first (only if buffer is empty)
                    if not input_buffer:
                        if char.upper() == 'R':
                            print("\n")
                            reader.reset()
                            continue
                        elif char.upper() == 'Q':
                            print("\n\n👋 Goodbye!")
                            break
                        elif char.upper() == 'S':
                            print("\n")
                            reader.display_status()
                            continue
                    
                    input_buffer += char
                    print(f"📥 Char: '{char}' (buffer: '{input_buffer}')", end='\r')
                    
                    # If we have 2 or 3 characters, validate immediately
                    if len(input_buffer) >= 2:
                        card = reader.validate_card(input_buffer)
                        
                        if card:
                            # Valid card found - process it
                            print(f"\n📥 Processed: '{input_buffer}' -> {card}")
                            reader.add_card(card)
                            
                            # Check if we have at least 2 unique cards - store automatically
                            if len(reader.current_hand) >= 2:
                                print(f"\n✅ Hand complete! ({len(reader.current_hand)} unique cards)")
                                print(f"   Hand: {', '.join(reader.get_hand())}")
                                reader.store_hand()
                            
                            input_buffer = ""
                        elif len(input_buffer) == 3:
                            # 3 characters and still not valid - invalid card
                            print(f"\n  ❌ Invalid card: '{input_buffer}' (not in 52 valid cards)")
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
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    
    # Display final summary
    print("\n" + "=" * 60)
    print("📊 Final Summary")
    print("=" * 60)
    reader.display_status()
    print()


if __name__ == "__main__":
    main()

