"""
QR Model Module

This module provides live QR code detection capabilities using OpenCV's built-in QRCodeDetector.
It's inspired by the quirc library from https://github.com/dlbeer/quirc.

Main components:
- live_qr_detector: Real-time QR code detection from camera feed
"""

__version__ = "1.0.0"
__author__ = "Phyigital OCR Team"

from .live_qr_detector import main as run_detector

__all__ = ['run_detector']

