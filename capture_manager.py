import os
import time
import threading
import subprocess
import cv2
from typing import List, Dict, Any, Optional

try:
    from picamera2 import Picamera2
    from PIL import Image
    _PICAMERA2_AVAILABLE = True
except Exception:  # pragma: no cover
    Picamera2 = None  # type: ignore
    Image = None  # type: ignore
    _PICAMERA2_AVAILABLE = False


class CameraCaptureError(Exception):
    pass


class CameraCaptureManager:
    """Encapsulates multiple capture backends with a unified API.

    Methods supported: picamera2, opencv, rpicam, raspistill.
    Auto priority order: picamera2 -> opencv -> rpicam -> raspistill.
    """

    def __init__(self, test_image_path: str = "/tmp/pi_test_image.jpg") -> None:
        self.test_image_path = test_image_path
        # Picamera2 may be None if not available; store as Optional[Any] to avoid type issues
        self._picam2_instance: Optional[object] = None
        self._picam2_lock = threading.Lock()

    # ---------------- Picamera2 ----------------
    def _ensure_picamera2(self):
        if not _PICAMERA2_AVAILABLE:
            raise CameraCaptureError("picamera2 module not available (install python3-picamera2 & Pillow)")
        if self._picam2_instance is None:
            p = Picamera2()
            p.configure(p.create_still_configuration(main={"size": (1920, 1080)}))
            p.start()
            time.sleep(0.8)
            self._picam2_instance = p
        return self._picam2_instance

    def capture_picamera2(self) -> None:
        p = self._ensure_picamera2()
        with self._picam2_lock:
            arr = p.capture_array()
        if Image is None:
            raise CameraCaptureError("Pillow not available to encode JPEG from picamera2 frame")
        Image.fromarray(arr).save(self.test_image_path, format="JPEG", quality=90)

    # ---------------- OpenCV ----------------
    def capture_opencv(self, device_index: int = 0, width=None, height=None, warmup_frames: int = 5,
                       retries: int = 3, retry_delay: float = 0.15) -> Dict[str, Any]:
        start_ts = time.time()
        cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise CameraCaptureError(f"OpenCV cannot open device index {device_index}")
        diag = {"requested_width": width, "requested_height": height}
        try:
            if width:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
            if height:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
            actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
            fps = cap.get(cv2.CAP_PROP_FPS)
            diag.update({"actual_width": actual_w, "actual_height": actual_h, "fps": fps, "fourcc": fourcc})
            for _ in range(max(0, warmup_frames)):
                cap.read()
                time.sleep(0.02)
            last_err = None
            for attempt in range(1, retries + 1):
                ret, frame = cap.read()
                if ret and frame is not None:
                    cv2.imwrite(self.test_image_path, frame)
                    diag.update({"attempts": attempt, "duration_sec": round(time.time() - start_ts, 3)})
                    return diag
                last_err = f"attempt {attempt} ret={ret} frame_is_none={frame is None}"
                time.sleep(retry_delay)
            raise CameraCaptureError(f"Failed to read frame after {retries} attempts: {last_err}")
        finally:
            cap.release()

    # ---------------- CLI tools (rpicam & raspistill) ----------------
    def capture_rpicam(self) -> None:
        result = subprocess.run(["rpicam-still", "-o", self.test_image_path, "-t", "1000", "--nopreview"],
                                capture_output=True)
        if result.returncode != 0:
            raise CameraCaptureError(result.stderr.decode() or "rpicam-still failed")

    def capture_raspistill(self) -> None:
        result = subprocess.run(["raspistill", "-o", self.test_image_path, "-t", "1000", "-n"], capture_output=True)
        if result.returncode != 0:
            raise CameraCaptureError(result.stderr.decode() or "raspistill failed")

    # ---------------- Public orchestration ----------------
    def capture(self, method: str = "auto", device_index: int = 0, width=None, height=None,
                warmup_frames: int = 5) -> Dict[str, Any]:
        """Capture an image using the specified method.

        Returns a dict with keys: image_path, method_requested, method_used, attempts (list of attempt dicts).
        """
        requested_method = method.lower()
        attempts: List[Dict[str, Any]] = []
        actual_method: Optional[str] = None

        def record(name: str, err: Optional[Exception] = None):
            attempts.append({
                "method": name,
                "success": err is None,
                "error": None if err is None else str(err)
            })

        try:
            if requested_method == "auto":
                # Priority order
                if actual_method is None:
                    if _PICAMERA2_AVAILABLE:
                        try:
                            self.capture_picamera2()
                            actual_method = "picamera2"
                            record("picamera2")
                        except Exception as e:
                            record("picamera2", e)
                if actual_method is None:
                    try:
                        self.capture_opencv(device_index, width, height, warmup_frames)
                        actual_method = "opencv"
                        record("opencv")
                    except Exception as e:
                        record("opencv", e)
                if actual_method is None:
                    try:
                        self.capture_rpicam()
                        actual_method = "rpicam"
                        record("rpicam")
                    except Exception as e:
                        record("rpicam", e)
                if actual_method is None:
                    try:
                        self.capture_raspistill()
                        actual_method = "raspistill"
                        record("raspistill")
                    except Exception as e:
                        record("raspistill", e)
                if actual_method is None:
                    raise CameraCaptureError("All capture methods failed")
            elif requested_method == "picamera2":
                self.capture_picamera2()
                actual_method = "picamera2"
                record("picamera2")
            elif requested_method == "opencv":
                self.capture_opencv(device_index, width, height, warmup_frames)
                actual_method = "opencv"
                record("opencv")
            elif requested_method == "rpicam":
                self.capture_rpicam()
                actual_method = "rpicam"
                record("rpicam")
            elif requested_method == "raspistill":
                self.capture_raspistill()
                actual_method = "raspistill"
                record("raspistill")
            else:
                raise CameraCaptureError(f"Unknown method '{requested_method}'")

            if not os.path.exists(self.test_image_path):
                raise CameraCaptureError("Image not created")

            return {
                "image_path": self.test_image_path,
                "method_requested": requested_method,
                "method_used": actual_method or requested_method,
                "attempts": attempts
            }
        except Exception as e:
            # If exception without prior record for the requested method (non-auto), record it.
            if requested_method != "auto" and not attempts:
                record(requested_method, e if isinstance(e, Exception) else Exception(str(e)))
            raise