"""
Live QR Code Detection using OpenCV
Inspired by the camera_detect.py card detection script

This script captures video from a webcam and detects QR codes in real-time.
It displays bounding boxes around detected QR codes and shows the decoded data.

Author: Based on quirc library and OpenCV best practices
Purpose: Real-time QR code detection for live camera feeds
"""

# Import argparse module - allows us to parse command-line arguments
# This lets users customize the script behavior when running it
import argparse

# Import os module - provides functions for interacting with the operating system
# We'll use it to check if files exist on the filesystem
import os

# Try to import cv2 (OpenCV library) - this is used for video capture and image processing
# We wrap it in a try-except block to handle the case where the library isn't installed
try:
    import cv2
except ImportError:
    # If cv2 is not installed, print an error message explaining how to fix it
    print("Error: opencv-python is not installed.")
    print("Please install it using:")
    print("  pip install opencv-python")
    print("\nOr install all requirements:")
    print("  pip install -r requirements.txt")
    # exit(1) terminates the program with an error code (1 means failure)
    exit(1)

# Try to import numpy - used for array operations in image processing
# We'll use it for coordinate calculations
try:
    import numpy as np
except ImportError:
    print("Error: numpy is not installed.")
    print("Please install it using:")
    print("  pip install numpy")
    exit(1)

# OpenCV has built-in QR code detection, no additional imports needed

# Try to import pyrealsense2 for RealSense camera support (optional)
try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
except ImportError:
    REALSENSE_AVAILABLE = False
    # pyrealsense2 is optional - we can still use OpenCV for RealSense cameras


def format_qr_data(data):
    """
    Formats QR code data for display.
    
    This function handles different types of QR code data:
    - Text content
    - URLs
    - Numeric data
    - Binary data
    
    Args:
        data: Raw decoded data from QR code (string or bytes)
    
    Returns:
        Formatted string representation of the data
    """
    # If data is bytes, decode it
    if isinstance(data, bytes):
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            # If not valid UTF-8, return hex representation
            return f"Binary: {data.hex()[:50]}..."
    else:
        text = data
    
    # Check if it looks like a URL
    if text.startswith(('http://', 'https://', 'www.')):
        return text
    
    # Return the text as-is
    return text


def init_realsense_camera():
    """
    Initialize Intel RealSense D435 camera with RGB camera (wide lens) configuration.
    
    This function:
    1. Creates a RealSense pipeline
    2. Explicitly enables ONLY the RGB color stream (disables IR cameras)
    3. Configures RGB stream with wide FOV settings
    4. Starts the pipeline
    
    Returns:
        pipeline: RealSense pipeline object
        config: RealSense configuration object
    """
    if not REALSENSE_AVAILABLE:
        raise ImportError("pyrealsense2 is not installed. Install it with: pip install pyrealsense2")
    
    # Create a pipeline
    pipeline = rs.pipeline()
    
    # Create a config and configure the pipeline to stream
    config = rs.config()
    
    # IMPORTANT: Disable all streams first to ensure clean configuration
    config.disable_all_streams()
    
    # Enable ONLY the RGB color stream (not IR cameras)
    # Configure RGB stream for wide lens (1920x1080 is the widest available on D435)
    # The RGB camera has a wider FOV than the IR/depth cameras
    # rs.stream.color = RGB camera, NOT IR
    config.enable_stream(rs.stream.color, 1920, 1080, rs.format.bgr8, 30)
    
    # Explicitly do NOT enable IR streams:
    # - rs.stream.infrared (left IR camera)
    # - rs.stream.infrared2 (right IR camera) 
    # - rs.stream.depth (depth stream, uses IR)
    
    # Start streaming
    print("Starting RealSense pipeline with RGB camera (wide lens) configuration...")
    print("Note: Using RGB camera only, IR cameras are disabled.")
    pipeline.start(config)
    
    # Get the device and sensor
    profile = pipeline.get_active_profile()
    
    # Verify we're using the color stream (RGB camera)
    streams = profile.get_streams()
    enabled_streams = [s.stream_type() for s in streams]
    
    print(f"RealSense D435 initialized:")
    print(f"  Enabled streams: {[str(s) for s in enabled_streams]}")
    
    # Get color profile
    color_profile = rs.video_stream_profile(profile.get_stream(rs.stream.color))
    print(f"  RGB Camera Resolution: {color_profile.width()}x{color_profile.height()}")
    print(f"  Format: {color_profile.format()}")
    print(f"  Camera Type: RGB (wide lens) - NOT IR")
    
    # Verify no IR streams are enabled
    if rs.stream.infrared in enabled_streams or rs.stream.infrared2 in enabled_streams:
        print("  WARNING: IR streams detected! This should not happen.")
    else:
        print("  ✓ Confirmed: Only RGB camera enabled, IR cameras disabled")
    
    return pipeline, config


def main():
    """
    Main function that orchestrates the entire QR code detection process.
    
    This function:
    1. Sets up command-line arguments so users can customize behavior
    2. Initializes the webcam
    3. Continuously captures frames, runs detection, and displays results
    4. Handles user input (quit, save frame)
    5. Cleans up resources when done
    """
    
    # Create an ArgumentParser object to handle command-line arguments
    # This allows users to pass options like --camera, --scale, etc. when running the script
    parser = argparse.ArgumentParser(description='Live QR Code Detection with Webcam')
    
    # Add --camera argument: specifies which camera to use (0 = first camera, 1 = second, etc.)
    # type=int means it expects a whole number
    # default=0 means use the first camera by default
    parser.add_argument('--camera', type=int, default=0,
                        help='Camera device index (default: 0)')
    
    # Add --scale argument: scale factor for resizing frames (for better performance)
    # type=float means it expects a decimal number (like 0.5)
    # Lower values = smaller frames = faster processing but may miss small QR codes
    parser.add_argument('--scale', type=float, default=1.0,
                        help='Scale factor for frame processing (default: 1.0, 0.5 = half size)')
    
    # Add --window-name argument: name of the display window
    # type=str means it expects text
    parser.add_argument('--window-name', type=str, default='Live QR Code Detection',
                        help='Window name for display (default: "Live QR Code Detection")')
    
    # Add --realsense argument: use Intel RealSense D435 camera with wide lens
    # action='store_true' means it's a flag (on/off)
    parser.add_argument('--realsense', action='store_true',
                        help='Use Intel RealSense D435 camera with wide lens configuration')
    
    # Parse all the command-line arguments the user provided
    # This converts the raw command-line input into a Python object (args)
    # We can then access args.camera, args.scale, etc. in the code
    args = parser.parse_args()
    
    # Initialize webcam/camera for video capture
    # Check if RealSense camera is requested
    realsense_pipeline = None
    realsense_align = None
    
    if args.realsense:
        # Initialize Intel RealSense D435 camera with RGB camera (wide lens)
        try:
            realsense_pipeline, realsense_config = init_realsense_camera()
            # Note: We don't need alignment since we're only using RGB camera (no depth)
            cap = None  # We won't use OpenCV VideoCapture for RealSense
        except Exception as e:
            print(f"Error initializing RealSense camera: {e}")
            print("Falling back to OpenCV VideoCapture...")
            args.realsense = False  # Disable RealSense flag and use regular camera
    
    if not args.realsense:
        # Use regular OpenCV VideoCapture
        # cv2.VideoCapture() creates a VideoCapture object that connects to a camera
        # args.camera is the camera index (0 = first camera, 1 = second camera, etc.)
        # On most laptops, 0 is the built-in webcam
        print(f"Initializing camera {args.camera}...")
        cap = cv2.VideoCapture(args.camera)
        
        # Check if the camera was successfully opened
        # cap.isOpened() returns True if camera is accessible, False otherwise
        # This could fail if camera is in use by another app, doesn't exist, or permissions denied
        if not cap.isOpened():
            print(f"Error: Could not open camera {args.camera}")
            print("Troubleshooting:")
            print("  1. Try a different camera index: --camera 1 or --camera 2")
            print("  2. Check if camera is being used by another application")
            print("  3. On macOS: Grant camera permissions in System Preferences")
            print("  4. On Linux: Check video device permissions (/dev/video*)")
            print("  5. Try restarting the application or your computer")
            # return exits the function - we can't continue without a camera
            return
        
        # Set camera properties to optimize video quality and performance
        # These are "requests" to the camera - the camera may ignore them if it doesn't support them
        
        # Set frame width to 1280 pixels (HD width)
        # This makes the video wider and provides more detail for detection
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        
        # Set frame height to 720 pixels (HD height)
        # This makes the video taller and provides more detail for detection
        # Together with width, this gives us 1280x720 resolution (720p HD)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        # Set frames per second (FPS) to 30
        # This requests 30 frames per second capture rate
        # Higher FPS = smoother video but more processing required
        cap.set(cv2.CAP_PROP_FPS, 30)
    
    # Allow camera to warm up - some cameras need time to initialize
    # Read a few frames to allow the camera to stabilize
    print("Warming up camera...")
    import time
    
    if args.realsense:
        # Warm up RealSense camera
        for i in range(5):
            frames = realsense_pipeline.wait_for_frames()
            if frames:
                break
            time.sleep(0.1)
        
        # Verify we can actually read frames
        frames = realsense_pipeline.wait_for_frames()
        if not frames:
            print("Error: RealSense camera opened but cannot read frames")
            print("Troubleshooting:")
            print("  1. Check RealSense camera connection")
            print("  2. Make sure no other application is using the camera")
            print("  3. Try unplugging and replugging the camera")
            realsense_pipeline.stop()
            return
        
        # Get color frame
        color_frame = frames.get_color_frame()
        if not color_frame:
            print("Error: RealSense camera cannot get color frames")
            realsense_pipeline.stop()
            return
        
        print("RealSense camera ready!")
    else:
        # Warm up regular OpenCV camera
        for i in range(5):
            ret, _ = cap.read()
            if ret:
                break
            time.sleep(0.1)
        
        # Verify we can actually read frames
        ret, test_frame = cap.read()
        if not ret or test_frame is None:
            print("Error: Camera opened but cannot read frames")
            print("Troubleshooting:")
            print("  1. Camera may be in use by another application - close other apps using the camera")
            print("  2. Try a different camera index with --camera flag")
            print("  3. Check camera permissions in system settings")
            print("  4. Try unplugging and replugging USB cameras")
            cap.release()
            return
        
        print("Camera ready!")
    
    # Print instructions for the user
    print("\nStarting video stream...")
    print("Press 'q' to quit")
    print("Press 's' to save current frame")
    print("Press 'd' to toggle debug mode (show processing steps)")
    print("Press 'r' to reset entire hand (flop, turn, river)")
    print("Poker: Detects Flop (3 cards), Turn (4th card), and River (5th card)")
    print("-" * 50)
    
    # Initialize QR code detector
    # OpenCV's QRCodeDetector is a built-in detector/decoder
    qr_detector = cv2.QRCodeDetector()
    
    # Initialize counters to track statistics
    # frame_count: counts how many frames we've processed (for display)
    frame_count = 0
    # saved_count: counts how many frames we've saved (for unique filenames)
    saved_count = 0
    # debug_mode: whether to show debug information
    debug_mode = False
    
    # Poker logic: Track unique QR codes for flop, turn, and river detection
    # Use a set to automatically track unique QR codes (cards)
    unique_qr_codes = set()
    flop_detected = False  # Flag to track if flop has been detected
    flop_cards = []  # Store the 3 cards that make up the flop
    turn_detected = False  # Flag to track if turn has been detected
    turn_card = None  # Store the 4th card (turn)
    river_detected = False  # Flag to track if river has been detected
    river_card = None  # Store the 5th card (river)
    
    # Wrap the main loop in a try-except-finally block for proper error handling
    # try: code that might fail
    # except: what to do if an error occurs
    # finally: code that always runs, even if there's an error (cleanup)
    try:
        # Main processing loop - runs continuously until user quits
        # while True means "loop forever until break is called"
        while True:
            # Read a single frame from the camera
            ret = True
            
            if args.realsense:
                # Read frame from RealSense RGB camera (NOT IR)
                try:
                    frames = realsense_pipeline.wait_for_frames()
                    if frames:
                        # Get ONLY the color frame from RGB camera
                        color_frame = frames.get_color_frame()
                        if color_frame:
                            # Verify this is actually a color frame (not IR)
                            # get_stream_type() should return rs.stream.color
                            if color_frame.get_profile().stream_type() == rs.stream.color:
                                # Convert RealSense RGB frame to numpy array
                                frame = np.asanyarray(color_frame.get_data())
                            else:
                                print("ERROR: Received non-color frame! This should not happen.")
                                ret = False
                        else:
                            ret = False
                    else:
                        ret = False
                except Exception as e:
                    print(f"Error reading RealSense RGB frame: {e}")
                    ret = False
            else:
                # Read frame from regular OpenCV camera
                # cap.read() returns two values:
                #   ret: boolean (True if frame was read successfully, False if error)
                #   frame: numpy array containing the image data (height x width x 3 colors)
                ret, frame = cap.read()
            
            # Check if we successfully captured a frame
            # If ret is False, the camera might be disconnected or there's an error
            if not ret or frame is None:
                print("Error: Failed to capture frame")
                if args.realsense:
                    print("RealSense camera may have disconnected or been closed.")
                    print("Attempting to reconnect...")
                    try:
                        realsense_pipeline.stop()
                        import time
                        time.sleep(1)
                        realsense_pipeline, realsense_config = init_realsense_camera()
                        print("RealSense camera reconnected successfully!")
                        continue
                    except Exception as e:
                        print(f"Failed to reconnect RealSense camera: {e}")
                        break
                else:
                    print("Camera may have disconnected or been closed by another application.")
                    print("Attempting to reconnect...")
                    
                    # Try to reopen the camera
                    cap.release()
                    import time
                    time.sleep(1)  # Wait a bit before retrying
                    cap = cv2.VideoCapture(args.camera)
                    
                    if not cap.isOpened():
                        print("Failed to reconnect to camera. Exiting...")
                        break
                    
                    # Warm up again and get a valid frame
                    ret = False
                    for attempt in range(5):
                        ret, test_frame = cap.read()
                        if ret and test_frame is not None:
                            print("Camera reconnected successfully!")
                            frame = test_frame
                            break
                        time.sleep(0.1)
                    
                    if not ret:
                        print("Could not read frames after reconnection. Exiting...")
                        break
            
            # Apply scaling if specified
            if args.scale != 1.0:
                # Resize the frame for faster processing
                h, w = frame.shape[:2]
                new_w = int(w * args.scale)
                new_h = int(h * args.scale)
                processing_frame = cv2.resize(frame, (new_w, new_h))
            else:
                processing_frame = frame
            
            # Create a copy of the frame for annotation
            # We'll draw on this copy, leaving the original frame unchanged
            annotated_frame = frame.copy()
            
            # Detect and decode QR codes in the frame
            # OpenCV's detectAndDecodeMulti detects multiple QR codes and returns:
            # - retval: List of decoded strings (one per QR code)
            # - points: List of point arrays (4 points per QR code)
            retval, decoded_info, points, _ = qr_detector.detectAndDecodeMulti(processing_frame)
            
            # Extract information about detected QR codes for display
            # Create empty list to store QR code data
            detected_qrs = []
            
            # Process each detected QR code
            if retval:
                for i, (data, pts) in enumerate(zip(decoded_info, points)):
                    # Only process successfully decoded QR codes
                    if data:  # data will be empty string if decode failed
                        # Format the data for display
                        formatted_data = format_qr_data(data)
                        
                        # Add to detected list
                        detected_qrs.append({
                            'data': formatted_data,
                            'points': pts
                        })
                        
                        # Draw bounding box on the annotated frame
                        # We need to scale coordinates back if we scaled the processing frame
                        if args.scale != 1.0:
                            # Scale the bounding box coordinates back to original frame size
                            scaled_points = []
                            for point in pts:
                                scaled_points.append([int(point[0] / args.scale), int(point[1] / args.scale)])
                            # Draw with scaled coordinates
                            pts_array = np.array(scaled_points, dtype=np.int32)
                            cv2.polylines(annotated_frame, [pts_array], True, (0, 255, 0), 2)
                            for point in scaled_points:
                                cv2.circle(annotated_frame, tuple(point), 5, (255, 0, 0), -1)
                            
                            # Calculate text position from scaled bounding box
                            text_x = int(min(p[0] for p in scaled_points))
                            text_y = int(min(p[1] for p in scaled_points) - 10)
                        else:
                            # Use coordinates as-is
                            pts_array = np.array(pts, dtype=np.int32)
                            cv2.polylines(annotated_frame, [pts_array], True, (0, 255, 0), 2)
                            for point in pts:
                                cv2.circle(annotated_frame, (int(point[0]), int(point[1])), 5, (255, 0, 0), -1)
                            
                            # Calculate text position from bounding box
                            text_x = int(min(p[0] for p in pts))
                            text_y = int(min(p[1] for p in pts) - 10)
                        
                        # Draw the decoded data as text above the QR code
                        label = formatted_data[:50]  # Limit to 50 characters for display
                        if len(formatted_data) > 50:
                            label += "..."
                        
                        # Draw text with background for better visibility
                        # Calculate text size
                        (text_width, text_height), baseline = cv2.getTextSize(
                            label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                        )
                        
                        # Draw semi-transparent background rectangle
                        overlay = annotated_frame.copy()
                        cv2.rectangle(
                            overlay,
                            (text_x, text_y - text_height - 5),
                            (text_x + text_width + 5, text_y + baseline + 5),
                            (0, 0, 0),
                            -1
                        )
                        cv2.addWeighted(overlay, 0.7, annotated_frame, 0.3, 0, annotated_frame)
                        
                        # Draw the text
                        cv2.putText(
                            annotated_frame,
                            label,
                            (text_x, text_y),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (0, 255, 0),
                            1
                        )
                        
                        # Print decoded data to console (only once per QR code)
                        # We keep track of seen QR codes to avoid printing duplicates
                        print(f"QR Code detected: {formatted_data}")
            
            # Poker logic: Track unique QR codes and detect flop, turn, and river
            # Add current frame's QR codes to the unique set
            previous_count = len(unique_qr_codes)
            for qr in detected_qrs:
                qr_data = qr['data']
                unique_qr_codes.add(qr_data)
            
            current_count = len(unique_qr_codes)
            unique_list = list(unique_qr_codes)  # Convert to list to access by index
            
            # Check if we have exactly 3 unique QR codes (the flop)
            if current_count >= 3 and not flop_detected:
                # Get the first 3 unique QR codes as the flop
                flop_cards = unique_list[:3]
                flop_detected = True
                
                # Print the flop to console with nice formatting
                print("\n" + "="*60)
                print("🎰 FLOP DETECTED! 🎰")
                print("="*60)
                print(f"Card 1: {flop_cards[0]}")
                print(f"Card 2: {flop_cards[1]}")
                print(f"Card 3: {flop_cards[2]}")
                print("="*60)
                print()
            
            # Check if we have exactly 4 unique QR codes (the turn)
            if current_count >= 4 and not turn_detected:
                # The 4th card is the turn
                turn_card = unique_list[3]
                turn_detected = True
                
                # Print the turn to console
                print("\n" + "="*60)
                print("🔄 TURN DETECTED! 🔄")
                print("="*60)
                print(f"Turn Card: {turn_card}")
                print("="*60)
                print()
            
            # Check if we have exactly 5 unique QR codes (the river)
            if current_count >= 5 and not river_detected:
                # The 5th card is the river
                river_card = unique_list[4]
                river_detected = True
                
                # Print the river to console
                print("\n" + "="*60)
                print("🌊 RIVER DETECTED! 🌊")
                print("="*60)
                print(f"River Card: {river_card}")
                print("="*60)
                print()
                
                # Print complete hand summary
                print("\n" + "="*60)
                print("🃏 COMPLETE HAND SUMMARY 🃏")
                print("="*60)
                print("Flop:")
                for i, card in enumerate(flop_cards, 1):
                    print(f"  Card {i}: {card}")
                print(f"Turn:  {turn_card}")
                print(f"River: {river_card}")
                print("="*60)
                print()
            
            # Create text to display on the screen showing detection info
            # Start with the count of detected QR codes
            info_text = f"Detected QR codes: {len(detected_qrs)}"
            
            # Add poker hand status to info text
            if river_detected:
                info_text += f" | HAND COMPLETE! (5/5 cards)"
            elif turn_detected:
                info_text += f" | TURN DETECTED! (4/5 cards)"
            elif flop_detected:
                info_text += f" | FLOP DETECTED! (3/5 cards)"
            else:
                info_text += f" | Unique cards: {len(unique_qr_codes)}/5"
            
            # Draw the info text on the annotated frame
            cv2.putText(
                annotated_frame,           # Image to draw on
                info_text,                 # Text to draw
                (10, 30),                  # Position (x, y) - top-left corner
                cv2.FONT_HERSHEY_SIMPLEX, # Font style
                0.7,                       # Font scale (size multiplier)
                (0, 255, 0),               # Color in BGR format (green)
                2                          # Line thickness
            )
            
            # Add a frame counter display
            frame_count += 1
            fps_text = f"Frame: {frame_count}"
            
            # Draw the frame counter on the image
            cv2.putText(
                annotated_frame,
                fps_text,
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),           # White color
                2
            )
            
            # Add scale factor display if not 1.0
            if args.scale != 1.0:
                scale_text = f"Scale: {args.scale}x"
                cv2.putText(
                    annotated_frame,
                    scale_text,
                    (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (128, 128, 128),       # Gray color
                    1
                )
            
            # Display debug info if enabled
            y_offset = 120
            if debug_mode:
                debug_text = "Debug Mode: ON"
                cv2.putText(
                    annotated_frame,
                    debug_text,
                    (10, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 165, 255),         # Orange color
                    2
                )
                y_offset += 30
            
            # Display poker hand detection status and cards
            h, w = annotated_frame.shape[:2]
            
            if river_detected:
                # Draw a semi-transparent box for complete hand display
                box_y_start = h - 180
                box_y_end = h - 10
                box_x_start = 10
                box_x_end = w - 10
                
                # Create overlay for semi-transparent background (magenta for complete hand)
                overlay = annotated_frame.copy()
                cv2.rectangle(
                    overlay,
                    (box_x_start, box_y_start),
                    (box_x_end, box_y_end),
                    (255, 0, 255),  # Magenta background for complete hand
                    -1
                )
                cv2.addWeighted(overlay, 0.3, annotated_frame, 0.7, 0, annotated_frame)
                
                # Draw header
                header = "🃏 HAND COMPLETE! 🃏"
                cv2.putText(
                    annotated_frame,
                    header,
                    (20, box_y_start + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 0, 255),  # Magenta text
                    2
                )
                
                # Draw flop cards
                cv2.putText(
                    annotated_frame,
                    "Flop:",
                    (20, box_y_start + 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),  # White text
                    1
                )
                for i, card in enumerate(flop_cards):
                    card_text = f"  Card {i+1}: {card[:30]}"  # Truncate long card names
                    cv2.putText(
                        annotated_frame,
                        card_text,
                        (20, box_y_start + 70 + (i * 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),  # White text
                        1
                    )
                
                # Draw turn
                turn_text = f"Turn:  {turn_card[:30]}"
                cv2.putText(
                    annotated_frame,
                    turn_text,
                    (20, box_y_start + 135),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),  # White text
                    1
                )
                
                # Draw river
                river_text = f"River: {river_card[:30]}"
                cv2.putText(
                    annotated_frame,
                    river_text,
                    (20, box_y_start + 155),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),  # White text
                    1
                )
                
            elif turn_detected:
                # Draw a semi-transparent box for turn display
                box_y_start = h - 160
                box_y_end = h - 10
                box_x_start = 10
                box_x_end = w - 10
                
                # Create overlay for semi-transparent background (orange for turn)
                overlay = annotated_frame.copy()
                cv2.rectangle(
                    overlay,
                    (box_x_start, box_y_start),
                    (box_x_end, box_y_end),
                    (0, 165, 255),  # Orange background
                    -1
                )
                cv2.addWeighted(overlay, 0.3, annotated_frame, 0.7, 0, annotated_frame)
                
                # Draw header
                header = "🔄 TURN DETECTED! 🔄"
                cv2.putText(
                    annotated_frame,
                    header,
                    (20, box_y_start + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 165, 255),  # Orange text
                    2
                )
                
                # Draw flop cards
                cv2.putText(
                    annotated_frame,
                    "Flop:",
                    (20, box_y_start + 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),  # White text
                    1
                )
                for i, card in enumerate(flop_cards):
                    card_text = f"  Card {i+1}: {card[:30]}"
                    cv2.putText(
                        annotated_frame,
                        card_text,
                        (20, box_y_start + 70 + (i * 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),  # White text
                        1
                    )
                
                # Draw turn
                turn_text = f"Turn:  {turn_card[:30]}"
                cv2.putText(
                    annotated_frame,
                    turn_text,
                    (20, box_y_start + 135),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),  # White text
                    1
                )
                
            elif flop_detected:
                # Draw a semi-transparent box for flop display
                box_y_start = h - 120
                box_y_end = h - 10
                box_x_start = 10
                box_x_end = w - 10
                
                # Create overlay for semi-transparent background (green for flop)
                overlay = annotated_frame.copy()
                cv2.rectangle(
                    overlay,
                    (box_x_start, box_y_start),
                    (box_x_end, box_y_end),
                    (0, 255, 0),  # Green background
                    -1
                )
                cv2.addWeighted(overlay, 0.3, annotated_frame, 0.7, 0, annotated_frame)
                
                # Draw flop header
                flop_header = "🎰 FLOP DETECTED! 🎰"
                cv2.putText(
                    annotated_frame,
                    flop_header,
                    (20, box_y_start + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),  # Green text
                    2
                )
                
                # Draw each flop card
                for i, card in enumerate(flop_cards):
                    card_text = f"Card {i+1}: {card[:30]}"
                    cv2.putText(
                        annotated_frame,
                        card_text,
                        (20, box_y_start + 50 + (i * 25)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 255),  # White text
                        2
                    )
            else:
                # Show progress toward hand detection
                progress_text = f"Poker: {len(unique_qr_codes)}/5 unique cards detected"
                if len(unique_qr_codes) > 0:
                    cv2.putText(
                        annotated_frame,
                        progress_text,
                        (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 0),  # Yellow color
                        2
                    )
            
            # Display the annotated frame in a window
            # cv2.imshow() creates a window and displays the image
            # args.window_name is the window title
            # annotated_frame is the image to display
            cv2.imshow(args.window_name, annotated_frame)
            
            # Check for keyboard input from the user
            # cv2.waitKey(1) waits for 1 millisecond for a key press
            # & 0xFF masks the result to get only the lowest 8 bits (the actual key code)
            key = cv2.waitKey(1) & 0xFF
            
            # Check if the user pressed 'q' (quit)
            # ord('q') converts the character 'q' to its ASCII code
            if key == ord('q'):
                print("\nQuitting...")
                break
            
            # Check if the user pressed 's' (save frame)
            elif key == ord('s'):
                # Save current frame to a file
                saved_count += 1
                filename = f"qr_detection_{saved_count}.jpg"
                cv2.imwrite(filename, annotated_frame)
                print(f"Saved frame to {filename}")
            
            # Check if the user pressed 'd' (toggle debug mode)
            elif key == ord('d'):
                debug_mode = not debug_mode
                if debug_mode:
                    print("Debug mode enabled")
                else:
                    print("Debug mode disabled")
            
            # Check if the user pressed 'r' (reset entire hand)
            elif key == ord('r'):
                unique_qr_codes.clear()
                flop_detected = False
                flop_cards = []
                turn_detected = False
                turn_card = None
                river_detected = False
                river_card = None
                print("\n" + "="*60)
                print("🔄 HAND RESET 🔄")
                print("="*60)
                print("All cards cleared. Ready to detect a new hand...")
                print("="*60)
                print()
    
    # Handle the case where user presses Ctrl+C to interrupt the program
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    
    # The finally block always runs, even if there's an error or break
    finally:
        # Cleanup: Release the camera so other programs can use it
        if args.realsense and realsense_pipeline:
            try:
                realsense_pipeline.stop()
                print("\nRealSense camera pipeline stopped.")
            except Exception as e:
                print(f"\nError stopping RealSense pipeline: {e}")
        elif cap is not None:
            cap.release()
            print("\nCamera released.")
        
        # Close all OpenCV windows that were opened
        cv2.destroyAllWindows()
        
        # Print goodbye message
        print("Goodbye!")


# This is the entry point of the script - code that runs when script is executed directly
# __name__ is a special Python variable that equals "__main__" when script is run directly
# If someone imports this file as a module, __name__ would be "live_qr_detector" instead
# This check ensures main() only runs when script is executed, not when imported
if __name__ == "__main__":
    # Call the main() function to start the program
    main()

