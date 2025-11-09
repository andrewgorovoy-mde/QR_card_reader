"""
Live QR Code Detection using OpenCV (USB Webcam, Raspberry Pi-friendly)

This script captures video from a USB webcam and detects QR codes in real-time.
It uses the V4L2 backend first (good for Raspberry Pi), then falls back to others.

Extra:
- Keeps an ordered list of detected cards (card_order)
- On key '1', prints known cards and plays corresponding audio files from ./audio_out
  where each file is named <card_code>.wav (e.g., 7H.wav, AS.wav)
"""

import argparse
import time
import os          # NEW
import subprocess  # NEW
import platform    # NEW - for OS detection

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

# Path to audio_out folder (same level as this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(SCRIPT_DIR, "audio_out")


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


def play_wav(path: str):
    """
    Play a .wav file using platform-appropriate audio player.
    - macOS: uses 'afplay'
    - Linux/Raspberry Pi: uses 'aplay'
    - Windows: uses 'start' command
    This call is blocking: it waits until the audio finishes.
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
            time.sleep(0.01)  # minimal pause between cards (10ms)
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

    args = parser.parse_args()

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

            # --------- Poker logic with stable ordering  --------- #
            # Add newly seen QR codes to both the set and the ordered list
            for qr in detected_qrs:
                card = qr["data"]
                if card not in unique_qr_codes:
                    unique_qr_codes.add(card)
                    card_order.append(card)

            current_count = len(card_order)

            # FLOP: first 3 cards in detection order
            if current_count >= 3 and not flop_detected:
                flop_cards = card_order[:3]
                flop_detected = True
                ConsoleFormatter.header("FLOP DETECTED!", "🎰")
                ConsoleFormatter.info(f"Card 1: {flop_cards[0]}", indent=3)
                ConsoleFormatter.info(f"Card 2: {flop_cards[1]}", indent=3)
                ConsoleFormatter.info(f"Card 3: {flop_cards[2]}", indent=3)
                ConsoleFormatter.separator()
                print()

            # TURN: 4th card in detection order
            if current_count >= 4 and not turn_detected:
                turn_card = card_order[3]
                turn_detected = True
                ConsoleFormatter.header("TURN DETECTED!", "🔄")
                ConsoleFormatter.info(f"Turn Card: {turn_card}", indent=3)
                ConsoleFormatter.separator()
                print()

            # RIVER: 5th card in detection order
            if current_count >= 5 and not river_detected:
                river_card = card_order[4]
                river_detected = True
                ConsoleFormatter.header("RIVER DETECTED!", "🌊")
                ConsoleFormatter.info(f"River Card: {river_card}", indent=3)
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
                info_text += " | HAND COMPLETE! (5/5 cards)"
            elif turn_detected:
                info_text += " | TURN DETECTED! (4/5 cards)"
            elif flop_detected:
                info_text += " | FLOP DETECTED! (3/5 cards)"
            else:
                info_text += f" | Unique cards seen: {len(card_order)}/5"

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
                progress_text = f"Poker: {len(card_order)}/5 unique cards detected"
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
        print("Camera released. Goodbye!")


if __name__ == "__main__":
    main()
