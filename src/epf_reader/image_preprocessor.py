# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""
Image Preprocessor Module
Preprocesses images for better OCR accuracy using OpenCV
"""

import cv2
import numpy as np
from PIL import Image
from typing import Tuple, Optional


def preprocess_image(image: Image.Image, config: dict = None) -> Image.Image:
    """
    Preprocess image for better OCR results
    
    Args:
        image: PIL Image object
        config: Configuration dictionary with preprocessing options
        
    Returns:
        Preprocessed PIL Image
    """
    if config is None:
        config = {
            'deskew': True,
            'contrast_enhancement': True,
            'remove_noise': True,
            'binarization_threshold': 150,
            'scale_factor': 1.0
        }
    
    # Convert PIL to OpenCV format
    img_cv = pil_to_cv2(image)
    
    # Apply preprocessing steps
    if config.get('deskew', True):
        img_cv = deskew_image(img_cv)
    
    if config.get('remove_noise', True):
        img_cv = remove_noise(img_cv)
    
    if config.get('contrast_enhancement', True):
        img_cv = enhance_contrast(img_cv)
    
    # Binarization (convert to black and white)
    threshold = config.get('binarization_threshold', 150)
    img_cv = binarize_image(img_cv, threshold)
    
    # Scale if needed
    scale = config.get('scale_factor', 1.0)
    if scale != 1.0:
        img_cv = scale_image(img_cv, scale)
    
    # Convert back to PIL
    return cv2_to_pil(img_cv)


def pil_to_cv2(image: Image.Image) -> np.ndarray:
    """Convert PIL Image to OpenCV format"""
    # Convert to RGB if needed
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # Convert to numpy array and BGR color space (OpenCV format)
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def cv2_to_pil(image: np.ndarray) -> Image.Image:
    """Convert OpenCV image to PIL format"""
    # Convert from BGR to RGB
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image_rgb)


def deskew_image(image: np.ndarray) -> np.ndarray:
    """
    Detect and correct skew in scanned images
    
    Args:
        image: OpenCV image (numpy array)
        
    Returns:
        Deskewed image
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply edge detection
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    
    # Detect lines using Hough transform
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
    
    if lines is None:
        return image
    
    # Calculate average angle
    angles = []
    for rho, theta in lines[:, 0]:
        angle = np.degrees(theta) - 90
        angles.append(angle)
    
    if not angles:
        return image
    
    # Get median angle
    median_angle = np.median(angles)
    
    # Only rotate if skew is significant (> 0.5 degrees)
    if abs(median_angle) < 0.5:
        return image
    
    # Rotate image to correct skew
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(
        image, 
        rotation_matrix, 
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    
    return rotated


def remove_noise(image: np.ndarray) -> np.ndarray:
    """
    Remove noise from image using morphological operations
    
    Args:
        image: OpenCV image
        
    Returns:
        Denoised image
    """
    # Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Apply bilateral filter (preserves edges)
    denoised = cv2.bilateralFilter(gray, 9, 75, 75)
    
    # Apply morphological opening to remove small noise
    kernel = np.ones((2, 2), np.uint8)
    denoised = cv2.morphologyEx(denoised, cv2.MORPH_OPEN, kernel)
    
    # Convert back to BGR if original was color
    if len(image.shape) == 3:
        denoised = cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)
    
    return denoised


def enhance_contrast(image: np.ndarray) -> np.ndarray:
    """
    Enhance contrast using CLAHE (Contrast Limited Adaptive Histogram Equalization)
    
    Args:
        image: OpenCV image
        
    Returns:
        Contrast-enhanced image
    """
    # Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Apply CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Convert back to BGR if original was color
    if len(image.shape) == 3:
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    
    return enhanced


def binarize_image(image: np.ndarray, threshold: int = 150) -> np.ndarray:
    """
    Convert image to binary (black and white) for better OCR
    
    Args:
        image: OpenCV image
        threshold: Binarization threshold (0-255)
        
    Returns:
        Binary image
    """
    # Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Apply adaptive thresholding for better results with varying lighting
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2
    )
    
    # Convert back to BGR
    binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    
    return binary_bgr


def scale_image(image: np.ndarray, scale_factor: float) -> np.ndarray:
    """
    Scale image by given factor
    
    Args:
        image: OpenCV image
        scale_factor: Scaling factor (e.g., 2.0 for 2x size)
        
    Returns:
        Scaled image
    """
    height, width = image.shape[:2]
    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)
    
    scaled = cv2.resize(
        image,
        (new_width, new_height),
        interpolation=cv2.INTER_CUBIC
    )
    
    return scaled


def remove_watermark(image: np.ndarray) -> np.ndarray:
    """
    Attempt to remove watermarks from image
    
    Args:
        image: OpenCV image
        
    Returns:
        Image with watermark reduced/removed
    """
    # Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Enhance contrast to make text more visible
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Apply thresholding to remove faint watermarks
    _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Convert back to BGR if original was color
    if len(image.shape) == 3:
        result = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
    else:
        result = thresh
    
    return result


def crop_to_table_region(image: np.ndarray, region: dict) -> np.ndarray:
    """
    Crop image to table region (skip header/footer)
    
    Args:
        image: OpenCV image
        region: Dictionary with 'top', 'bottom', 'left', 'right' as fractions (0-1)
        
    Returns:
        Cropped image
    """
    height, width = image.shape[:2]
    
    top = int(height * region.get('top', 0))
    bottom = int(height * region.get('bottom', 1))
    left = int(width * region.get('left', 0))
    right = int(width * region.get('right', 1))
    
    cropped = image[top:bottom, left:right]
    
    return cropped


def save_debug_images(original: np.ndarray, processed: np.ndarray, output_prefix: str):
    """
    Save original and processed images for debugging
    
    Args:
        original: Original OpenCV image
        processed: Processed OpenCV image
        output_prefix: Prefix for output filenames
    """
    cv2.imwrite(f"{output_prefix}_original.png", original)
    cv2.imwrite(f"{output_prefix}_processed.png", processed)
    print(f"Debug images saved: {output_prefix}_*.png")


if __name__ == "__main__":
    # Test preprocessing
    import sys
    from pdf2image import convert_from_path
    
    if len(sys.argv) < 2:
        print("Usage: python image_preprocessor.py <pdf_path> [output_prefix]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_prefix = sys.argv[2] if len(sys.argv) > 2 else "debug"
    
    print(f"Converting PDF to images: {pdf_path}")
    images = convert_from_path(pdf_path, dpi=300)
    
    if not images:
        print("No images extracted from PDF")
        sys.exit(1)
    
    print(f"Processing {len(images)} page(s)...")
    
    # Process first page
    first_page = images[0]
    original_cv = pil_to_cv2(first_page)
    
    # Apply preprocessing
    processed = preprocess_image(first_page)
    processed_cv = pil_to_cv2(processed)
    
    # Save debug images
    save_debug_images(original_cv, processed_cv, output_prefix)
    
    print("✅ Preprocessing complete")
