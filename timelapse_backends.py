"""Timelapse camera backend abstractions.

This module defines a pluggable backend interface so the monitor script can
support multiple camera types (DSLR via gphoto2, Raspberry Pi camera via
Picamera2 or libcamera-still CLI, and generic webcams via OpenCV) without
changing its core control & status reporting logic.

Design goals:
- Uniform initialize()/shutdown() lifecycle.
- Event-driven vs interval-driven capture distinction (gphoto2 provides
  file-added events; others rely on time interval).
- Minimal external dependencies (import lazily and degrade gracefully if
  libraries not present).
- Clear, structured errors via BackendError.

Adding a new backend requires:
- Subclass BaseTimelapseCamera
- Implement initialize() and capture_next(target_path)
- Optionally set event_driven True and implement wait_for_event(timeout_ms)
  + handle_event(event, target_path)

Note: For now we keep configuration simple; richer per-backend tuning can
be exposed later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Any, List
import time
import os
import subprocess
import logging

logger = logging.getLogger("timelapse_backends")

class BackendError(Exception):
    pass

@dataclass
class BackendConfig:
    interval: float = 1.0  # seconds (used for non event-driven)
    resolution: Optional[Tuple[int, int]] = None  # (width, height)
    device_index: int = 0  # For OpenCV / V4L2
    exposure_mode: Optional[str] = None  # backend specific
    awb: Optional[str] = None
    iso: Optional[int] = None
    shutter_us: Optional[int] = None

class BaseTimelapseCamera:
    name: str = "base"
    event_driven: bool = False

    def __init__(self, config: BackendConfig):
        self.config = config
        self._initialized = False

    def initialize(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def shutdown(self):  # pragma: no cover - abstract
        raise NotImplementedError

    # Event-driven backends override these two methods:
    def wait_for_event(self, timeout_ms: int) -> Any:
        raise BackendError("wait_for_event not supported by this backend")

    def handle_event(self, event: Any, target_path: str) -> bool:
        raise BackendError("handle_event not supported by this backend")

    # Interval / direct capture backends override this:
    def capture_next(self, target_path: str) -> bool:
        raise BackendError("capture_next not implemented")

    def ensure_initialized(self):
        if not self._initialized:
            self.initialize()
            self._initialized = True

# ------------------ GPHOTO2 DSLR BACKEND ------------------
class GPhoto2CameraBackend(BaseTimelapseCamera):
    name = "gphoto2"
    event_driven = True

    def initialize(self):
        try:
            import gphoto2 as gp  # type: ignore
        except Exception as e:  # pragma: no cover
            raise BackendError(f"gphoto2 library not available: {e}")
        self.gp = gp
        try:
            self.camera = gp.Camera()
            self.camera.init()
        except gp.GPhoto2Error as e:
            raise BackendError(f"Failed to initialize gphoto2 camera: {e}")
        logger.info("Initialized gphoto2 camera backend")

    def shutdown(self):
        try:
            if hasattr(self, "camera"):
                self.camera.exit()
        except Exception:
            pass

    def wait_for_event(self, timeout_ms: int):
        return self.camera.wait_for_event(timeout_ms)

    def handle_event(self, event: Any, target_path: str) -> bool:
        gp = self.gp
        event_type, event_data = event
        if event_type == gp.GP_EVENT_FILE_ADDED:
            try:
                cam_file = self.camera.file_get(event_data.folder, event_data.name, gp.GP_FILE_TYPE_NORMAL)
                cam_file.save(target_path)
                return True
            except gp.GPhoto2Error as e:
                logger.error(f"gphoto2 save error: {e}")
                return False
        return False

# ------------------ PICAMERA2 BACKEND ------------------
class PiCamera2Backend(BaseTimelapseCamera):
    name = "picamera2"
    event_driven = False

    def initialize(self):
        try:
            from picamera2 import Picamera2  # type: ignore
        except Exception as e:  # pragma: no cover
            raise BackendError(f"Picamera2 not available: {e}")
        self.Picamera2 = Picamera2
        self.picam = Picamera2()

        # Configure resolution
        size = None
        if self.config.resolution:
            size = {"size": self.config.resolution}
        still_config = self.picam.create_still_configuration(size) if size else self.picam.create_still_configuration()
        self.picam.configure(still_config)
        self.picam.start()

        # Exposure tweaks (best-effort)
        # NOTE: Advanced manual controls may require enabling controls after start.
        if self.config.iso or self.config.shutter_us:
            try:
                # Simple approach: set exposure/profile if API present
                if self.config.shutter_us:
                    self.picam.set_controls({"ExposureTime": self.config.shutter_us})
                if self.config.iso:
                    # ISO mapping typically via AnalogueGain; skip complex mapping for now
                    pass
            except Exception as e:
                logger.warning(f"Picamera2 exposure control warning: {e}")

        logger.info("Initialized Picamera2 backend")

    def shutdown(self):
        try:
            self.picam.stop()
            self.picam.close()
        except Exception:
            pass

    def capture_next(self, target_path: str) -> bool:
        try:
            self.picam.capture_file(target_path)
            return True
        except Exception as e:
            logger.error(f"Picamera2 capture error: {e}")
            return False

# ------------------ LIBCAMERA-CLI BACKEND ------------------
class LibcameraStillBackend(BaseTimelapseCamera):
    name = "libcamera"
    event_driven = False

    def initialize(self):
        # Verify libcamera-still exists
        from shutil import which
        if which("libcamera-still") is None:
            raise BackendError("libcamera-still not found in PATH")
        logger.info("Using libcamera-still CLI backend")

    def shutdown(self):
        pass

    def capture_next(self, target_path: str) -> bool:
        cmd = ["libcamera-still", "-n", "-q", "95", "-o", target_path]
        if self.config.resolution:
            w, h = self.config.resolution
            cmd += ["-w", str(w), "-h", str(h)]
        if self.config.shutter_us:
            cmd += ["--shutter", str(self.config.shutter_us)]
        if self.config.iso:
            cmd += ["--gain", str(self.config.iso)]  # approximation
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"libcamera-still capture error: {e}")
            return False

# ------------------ OPENCV BACKEND ------------------
class OpenCVCameraBackend(BaseTimelapseCamera):
    name = "opencv"
    event_driven = False

    def initialize(self):
        try:
            import cv2  # type: ignore
        except Exception as e:  # pragma: no cover
            raise BackendError(f"OpenCV not available: {e}")
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(self.config.device_index)
        if not self.cap.isOpened():
            raise BackendError(f"Failed to open video device index {self.config.device_index}")
        if self.config.resolution:
            w, h = self.config.resolution
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        logger.info("Initialized OpenCV camera backend")

    def shutdown(self):
        try:
            if hasattr(self, "cap"):
                self.cap.release()
        except Exception:
            pass

    def capture_next(self, target_path: str) -> bool:
        ok, frame = self.cap.read()
        if not ok or frame is None:
            logger.error("OpenCV failed to read frame")
            return False
        try:
            ok2 = self.cv2.imwrite(target_path, frame)
            if not ok2:
                logger.error("OpenCV failed to write image")
                return False
            return True
        except Exception as e:
            logger.error(f"OpenCV write error: {e}")
            return False

# -------------- BACKEND FACTORY / AUTO SELECTION --------------

def create_backend(name: str, config: BackendConfig) -> BaseTimelapseCamera:
    name = name.lower()
    if name == "gphoto2":
        return GPhoto2CameraBackend(config)
    if name == "picamera2":
        return PiCamera2Backend(config)
    if name == "libcamera":
        return LibcameraStillBackend(config)
    if name == "opencv":
        return OpenCVCameraBackend(config)
    if name == "auto":
        # Priority: gphoto2 (DSLR), picamera2, libcamera, opencv
        order = ["gphoto2", "picamera2", "libcamera", "opencv"]
        errors: List[str] = []
        for cand in order:
            try:
                backend = create_backend(cand, config)
                backend.ensure_initialized()  # attempt init
                logger.info(f"Auto-selected backend '{cand}'")
                return backend
            except Exception as e:  # collect but continue
                errors.append(f"{cand}: {e}")
        raise BackendError("All auto backend attempts failed: " + "; ".join(errors))
    raise BackendError(f"Unknown backend name '{name}'")

__all__ = [
    "BackendConfig",
    "BackendError",
    "BaseTimelapseCamera",
    "GPhoto2CameraBackend",
    "PiCamera2Backend",
    "LibcameraStillBackend",
    "OpenCVCameraBackend",
    "create_backend",
]
