#!/usr/bin/env python3
"""
Simple Camera Test Script for Raspberry Pi Zero 2W

Tests camera module connectivity and basic functionality.
Supports both libcamera (newer) and legacy picamera.
"""

import sys
import os
import time

def test_libcamera():
    """Test using libcamera (recommended for Pi Zero 2W)."""
    print("=" * 60)
    print("Testing libcamera (recommended for Pi Zero 2W)")
    print("=" * 60)
    
    try:
        import subprocess
        
        # Test if libcamera-hello works (preview)
        print("\n1. Testing libcamera-hello (preview)...")
        print("   (This will show a 5-second preview)")
        result = subprocess.run(
            ["libcamera-hello", "-t", "5000"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print("   ✓ libcamera-hello works!")
        else:
            print(f"   ✗ libcamera-hello failed: {result.stderr}")
            return False
        
        # Test taking a photo
        print("\n2. Testing libcamera-jpeg (capture photo)...")
        test_image = "test_camera_photo.jpg"
        result = subprocess.run(
            ["libcamera-jpeg", "-o", test_image, "-t", "2000"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0 and os.path.exists(test_image):
            print(f"   ✓ Photo captured: {test_image}")
            file_size = os.path.getsize(test_image)
            print(f"   File size: {file_size} bytes")
            return True
        else:
            print(f"   ✗ Photo capture failed: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("   ✗ libcamera commands not found")
        print("   Install with: sudo apt install libcamera-apps")
        return False
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False


def test_picamera2():
    """Test using picamera2 (Python library)."""
    print("\n" + "=" * 60)
    print("Testing picamera2 (Python library)")
    print("=" * 60)
    
    try:
        from picamera2 import Picamera2
        
        print("\n1. Initializing camera...")
        picam2 = Picamera2()
        
        print("2. Configuring camera...")
        config = picam2.create_preview_configuration(main={"size": (640, 480)})
        picam2.configure(config)
        
        print("3. Starting camera...")
        picam2.start()
        time.sleep(2)  # Let camera settle
        
        print("4. Capturing photo...")
        test_image = "test_picamera2_photo.jpg"
        picam2.capture_file(test_image)
        
        picam2.stop()
        
        if os.path.exists(test_image):
            print(f"   ✓ Photo captured: {test_image}")
            file_size = os.path.getsize(test_image)
            print(f"   File size: {file_size} bytes")
            return True
        else:
            print("   ✗ Photo file not created")
            return False
            
    except ImportError:
        print("   ✗ picamera2 not installed")
        print("   Install with: sudo apt install python3-picamera2")
        return False
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_opencv():
    """Test using OpenCV."""
    print("\n" + "=" * 60)
    print("Testing OpenCV camera access")
    print("=" * 60)
    
    try:
        import cv2
        
        print("\n1. Trying to open camera with OpenCV...")
        
        # Try different camera indices
        for idx in [0, 1]:
            print(f"   Trying camera index {idx}...")
            cap = cv2.VideoCapture(idx)
            
            if cap.isOpened():
                print(f"   ✓ Camera {idx} opened successfully!")
                
                # Try to read a frame
                ret, frame = cap.read()
                if ret and frame is not None:
                    print(f"   ✓ Frame captured: {frame.shape}")
                    
                    # Save test image
                    test_image = f"test_opencv_camera{idx}.jpg"
                    cv2.imwrite(test_image, frame)
                    if os.path.exists(test_image):
                        print(f"   ✓ Photo saved: {test_image}")
                        cap.release()
                        return True
                else:
                    print(f"   ✗ Could not read frame from camera {idx}")
                
                cap.release()
            else:
                print(f"   ✗ Camera {idx} not available")
        
        return False
        
    except ImportError:
        print("   ✗ OpenCV not installed")
        print("   Install with: pip install opencv-python")
        return False
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_camera_module():
    """Check if camera module is detected."""
    print("=" * 60)
    print("Checking Camera Module Detection")
    print("=" * 60)
    
    # Check /dev/video* devices
    print("\n1. Checking /dev/video* devices...")
    video_devices = []
    for i in range(10):
        dev_path = f"/dev/video{i}"
        if os.path.exists(dev_path):
            video_devices.append(dev_path)
            print(f"   ✓ Found: {dev_path}")
    
    if not video_devices:
        print("   ⚠️  No /dev/video* devices found")
        print("   Make sure camera module is connected and enabled in raspi-config")
    else:
        print(f"   Found {len(video_devices)} video device(s)")
    
    # Check vcgencmd (Raspberry Pi specific)
    print("\n2. Checking camera status via vcgencmd...")
    try:
        import subprocess
        result = subprocess.run(
            ["vcgencmd", "get_camera"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"   {result.stdout.strip()}")
        else:
            print("   ⚠️  vcgencmd not available or camera not detected")
    except FileNotFoundError:
        print("   ⚠️  vcgencmd not found (may not be on Raspberry Pi)")
    except Exception as e:
        print(f"   Error: {e}")
    
    return len(video_devices) > 0


def main():
    """Main test function."""
    print("\n" + "=" * 60)
    print("Raspberry Pi Zero 2W Camera Module Test")
    print("=" * 60)
    print("\nThis script will test different camera access methods.")
    print("Press Ctrl+C to skip any test.\n")
    
    # Check camera detection first
    camera_detected = check_camera_module()
    
    if not camera_detected:
        print("\n⚠️  WARNING: No camera devices detected!")
        print("   Please check:")
        print("   1. Camera module is properly connected")
        print("   2. Camera is enabled: sudo raspi-config")
        print("   3. System is up to date: sudo apt update && sudo apt upgrade")
        print("\n   Continuing with tests anyway...\n")
    
    results = {}
    
    # Test libcamera (recommended)
    try:
        print("\n" + "=" * 60)
        print("TEST 1: libcamera (Command Line)")
        print("=" * 60)
        results['libcamera'] = test_libcamera()
    except KeyboardInterrupt:
        print("\n   Skipped by user")
        results['libcamera'] = None
    except Exception as e:
        print(f"\n   Test failed: {e}")
        results['libcamera'] = False
    
    # Test picamera2
    try:
        print("\n" + "=" * 60)
        print("TEST 2: picamera2 (Python Library)")
        print("=" * 60)
        results['picamera2'] = test_picamera2()
    except KeyboardInterrupt:
        print("\n   Skipped by user")
        results['picamera2'] = None
    except Exception as e:
        print(f"\n   Test failed: {e}")
        results['picamera2'] = False
    
    # Test OpenCV
    try:
        print("\n" + "=" * 60)
        print("TEST 3: OpenCV")
        print("=" * 60)
        results['opencv'] = test_opencv()
    except KeyboardInterrupt:
        print("\n   Skipped by user")
        results['opencv'] = None
    except Exception as e:
        print(f"\n   Test failed: {e}")
        results['opencv'] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for test_name, result in results.items():
        if result is True:
            print(f"✓ {test_name}: PASSED")
        elif result is False:
            print(f"✗ {test_name}: FAILED")
        else:
            print(f"- {test_name}: SKIPPED")
    
    if any(results.values()):
        print("\n✓ At least one camera method works!")
        print("  You can use the working method in your application.")
    else:
        print("\n✗ No camera methods worked.")
        print("\nTroubleshooting:")
        print("1. Enable camera: sudo raspi-config → Interface Options → Camera → Enable")
        print("2. Install libcamera: sudo apt install libcamera-apps")
        print("3. Install picamera2: sudo apt install python3-picamera2")
        print("4. Reboot: sudo reboot")
        print("5. Check connections and try again")
    
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

