# Quick Start Guide - Live QR Code Detection

Get up and running with QR code detection in under 5 minutes!

## Installation (3 steps)

### 1. Install Python dependencies
```bash
cd models/qr_model
pip install -r requirements.txt
```

**Or install individually:**
```bash
pip install opencv-python numpy
```

### 2. All dependencies installed!
No additional system libraries needed. OpenCV includes built-in QR code detection! 🎉

### 3. Test the installation
```bash
python live_qr_detector.py
```

If you see a camera window, you're all set!

## Basic Usage

```bash
# Start the QR code detector
python live_qr_detector.py

# Use Intel RealSense D435 camera with wide lens
python live_qr_detector.py --realsense

# Use a different camera
python live_qr_detector.py --camera 1

# Faster processing (for slower computers)
python live_qr_detector.py --scale 0.5

# Better accuracy (for better computers)
python live_qr_detector.py --scale 1.5
```

## Controls

- **Press `q`**: Quit
- **Press `s`**: Save current frame
- **Press `d`**: Toggle debug mode

## Troubleshooting

**Camera won't open?**
- Try a different camera index: `--camera 1` or `--camera 2`
- Check if another app is using the camera
- On macOS: Grant camera permissions in System Preferences

**Import errors?**
- Make sure you installed requirements.txt
- Try: `pip install opencv-python numpy`

**No QR codes detected?**
- Ensure good lighting
- Hold QR code steady and in focus
- Try `--scale 1.0` for better accuracy

## What's Next?

Check out the full [README.md](README.md) for:
- Detailed explanations
- Advanced features
- Performance tips
- Use cases

Happy scanning! 📱📷

