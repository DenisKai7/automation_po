from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np


@dataclass
class QualityReport:
    is_blurry: bool = False
    blur_score: float = 0.0
    is_skewed: bool = False
    skew_angle: float = 0.0
    is_dark: bool = False
    brightness: float = 0.0
    has_flash_glare: bool = False
    glare_percentage: float = 0.0
    has_stains_noise: bool = False
    guidelines: List[str] = field(default_factory=list)


class ImageQualityPreprocessor:
    """
    Image Quality Assessment & Auto-Enhancement for Invoice Documents:
    1. Blur detection & Unsharp Mask sharpening
    2. Skew detection & Auto-Deskewing
    3. Dark / Underexposed correction via CLAHE & Gamma adjustment
    4. Flash / Glare suppression via background division & illumination normalization
    5. Stain & noise cleaning via bilateral filter & morphological opening
    """

    BLUR_THRESHOLD = 90.0        # Laplacian variance threshold
    DARK_THRESHOLD = 75.0        # Average grayscale brightness threshold
    GLARE_PIXEL_THRESH = 245     # Pixel intensity considered hotspot
    GLARE_AREA_THRESH = 0.03     # 3% of total pixels in hotspot indicates flash/glare
    SKEW_THRESHOLD_DEG = 1.5     # Deviation in degrees requiring deskew

    @classmethod
    def assess_quality(cls, image_path: Path | str) -> Tuple[QualityReport, np.ndarray]:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot load image at {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        report = QualityReport()

        # 1. Blur Detection (Laplacian Variance)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        report.blur_score = round(lap_var, 2)
        if lap_var < cls.BLUR_THRESHOLD:
            report.is_blurry = True
            report.guidelines.append(
                "GAMBAR BLUR: Gambar tidak fokus/goyang. Aktifkan auto-focus, pegang kamera stabil, atau gunakan scanner resolusi minimal 300 DPI."
            )

        # 2. Skew Detection (Hough Lines)
        skew_ang = cls._detect_skew_angle(gray)
        report.skew_angle = round(skew_ang, 2)
        if abs(skew_ang) >= cls.SKEW_THRESHOLD_DEG:
            report.is_skewed = True
            report.guidelines.append(
                f"ORIENTASI MIRING ({report.skew_angle}°): Posisikan dokumen sejajar tegak lurus (90°) dengan bingkai kamera."
            )

        # 3. Dark / Underexposure Detection
        mean_brightness = float(np.mean(gray))
        report.brightness = round(mean_brightness, 2)
        if mean_brightness < cls.DARK_THRESHOLD:
            report.is_dark = True
            report.guidelines.append(
                f"GAMBAR GELAP (Kecerahan: {report.brightness}): Tingkatkan pencahayaan ruangan atau naikkan exposure kamera sebelum memotret."
            )

        # 4. Flash / Glare Detection
        glare_pixels = np.sum(gray >= cls.GLARE_PIXEL_THRESH)
        glare_ratio = float(glare_pixels / gray.size)
        report.glare_percentage = round(glare_ratio * 100, 2)
        # Avoid false positive on clean uniform white digital documents (mean > 230 and std < 50)
        is_clean_white_doc = mean_brightness > 230 and float(np.std(gray)) < 50
        if not is_clean_white_doc:
            if glare_ratio > cls.GLARE_AREA_THRESH or (mean_brightness < 120 and np.std(gray) > 75):
                report.has_flash_glare = True
                report.guidelines.append(
                    "TERKENA FLASH / SILAU: Matikan lampu flash kamera. Hindari pantulan langsung pada kertas atau plastik map."
                )

        # 5. Stains / Noise Detection
        # Compare raw grayscale vs bilateral filtered difference
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)
        diff = cv2.absdiff(gray, denoised)
        noise_level = float(np.mean(diff))
        if noise_level > 6.0:
            report.has_stains_noise = True
            report.guidelines.append(
                "NODA / NOISE: Terdapat bercak atau noda mengganggu. Pastikan permukaan dokumen bersih dari coretan/kotoran fisik."
            )

        return report, img

    @classmethod
    def _detect_skew_angle(cls, gray: np.ndarray) -> float:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10)
        if lines is None:
            return 0.0

        angles = []
        for line in lines:
            pts = line.ravel()
            if len(pts) >= 4:
                x1, y1, x2, y2 = pts[:4]
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                # Filter lines roughly horizontal
                if -45 < angle < 45:
                    angles.append(angle)

        if not angles:
            return 0.0
        return float(np.median(angles))

    @classmethod
    def enhance_image(cls, img: np.ndarray, report: QualityReport) -> np.ndarray:
        """Applies adaptive filters based on detected anomalies."""
        enhanced = img.copy()

        # 1. Deskew if skewed
        if report.is_skewed and abs(report.skew_angle) >= cls.SKEW_THRESHOLD_DEG:
            h, w = enhanced.shape[:2]
            center = (w // 2, h // 2)
            rot_mat = cv2.getRotationMatrix2D(center, report.skew_angle, 1.0)
            enhanced = cv2.warpAffine(
                enhanced, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )

        # Work on grayscale/L-channel for lighting adjustments
        if len(enhanced.shape) == 3:
            gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
        else:
            gray = enhanced.copy()

        # 2. Flash / Glare & Stain Normalization (Background Illumination Division)
        if report.has_flash_glare or report.has_stains_noise:
            # Gaussian blur large kernel creates illumination map
            bg = cv2.GaussianBlur(gray, (51, 51), 0)
            gray = cv2.divide(gray, bg, scale=255)

        # 3. Dark / Underexposure Compensation (Gamma + CLAHE)
        if report.is_dark or np.mean(gray) < 100:
            # Gamma boost
            inv_gamma = 1.0 / 1.8
            table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
            gray = cv2.LUT(gray, table)
            # Contrast Limited Adaptive Histogram Equalization
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)

        # 4. Deblur & Sharpening (Unsharp Masking)
        if report.is_blurry or report.blur_score < cls.BLUR_THRESHOLD:
            gaussian = cv2.GaussianBlur(gray, (0, 0), 2.0)
            gray = cv2.addWeighted(gray, 1.6, gaussian, -0.6, 0)

        # Convert back to 3-channel BGR for Google Cloud Vision API
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    @classmethod
    def process_and_save_temp(cls, image_path: Path | str, output_path: Path | str) -> QualityReport:
        report, img = cls.assess_quality(image_path)
        enhanced = cls.enhance_image(img, report)
        cv2.imwrite(str(output_path), enhanced)
        return report
