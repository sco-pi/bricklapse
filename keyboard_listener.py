#!/usr/bin/env python3
"""
HID Keyboard Listener for BrickLapse
Monitors keyboard events and sends navigation commands to the server API.

Key mappings:
- Next Track: Next page
- Previous Track: Previous page  
- Volume Up: Next instruction (set/document)
- Volume Down: Previous instruction (set/document)
"""

import asyncio
import httpx
import yaml
import logging
from evdev import InputDevice, categorize, ecodes, list_devices
from typing import Optional, List
import sys
import os

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Server configuration
SERVER_URL = os.getenv("BRICKLAPSE_SERVER_URL", "http://localhost:8000")
SETS_FILE = os.getenv("BRICKLAPSE_SETS_FILE", "/home/smurch/BrickLapsePython/sets.yml")

# Keyboard device configuration
KEYBOARD_VENDOR_ID = os.getenv("KEYBOARD_VENDOR_ID", None)  # Optional: filter by vendor ID
KEYBOARD_PRODUCT_ID = os.getenv("KEYBOARD_PRODUCT_ID", None)  # Optional: filter by product ID
KEYBOARD_DEVICE_PATH = os.getenv("KEYBOARD_DEVICE_PATH", None)  # Optional: specific device path


class BrickLapseKeyboardController:
    """Keyboard listener that sends navigation commands to BrickLapse server."""
    
    def __init__(self, server_url: str, sets_file: str):
        self.server_url = server_url
        self.sets_file = sets_file
        self.device: Optional[InputDevice] = None
        self.current_set_index = 0
        self.current_instruction_index = 0
        self.sets_data = None
        
    def load_sets(self):
        """Load sets configuration from YAML file."""
        try:
            with open(self.sets_file, 'r') as f:
                self.sets_data = yaml.safe_load(f)
                logger.info(f"Loaded {len(self.sets_data.get('sets', []))} sets from {self.sets_file}")
        except Exception as e:
            logger.error(f"Failed to load sets file: {e}")
            self.sets_data = {'sets': []}
    
    def find_keyboard_device(self) -> Optional[InputDevice]:
        """Find the HID keyboard device with media key support.

        Selection strategy:
        1. If KEYBOARD_DEVICE_PATH provided, use it (warn if missing media keys)
        2. If KEYBOARD_VENDOR_ID/PRODUCT_ID provided, filter by those
        3. Build list of candidates with EV_KEY capability
        4. **Prefer devices with ALL required media keys** (next, previous, vol up, vol down)
        5. If none have all, pick one with most media keys and warn about missing keys
        6. Fallback to first EV_KEY device if no media keys found
        
        This automatic detection makes the service resilient to device enumeration changes.
        """
        required_media_keys = {
            ecodes.KEY_NEXTSONG: "NEXTSONG",
            ecodes.KEY_PREVIOUSSONG: "PREVIOUSSONG",
            ecodes.KEY_VOLUMEUP: "VOLUMEUP",
            ecodes.KEY_VOLUMEDOWN: "VOLUMEDOWN",
        }

        devices = [InputDevice(path) for path in list_devices()]
        logger.debug(f"Scanning {len(devices)} input devices for keyboard/media capabilities...")

        def device_summary(dev: InputDevice):
            return f"{dev.name} ({dev.path}) vendor=0x{dev.info.vendor:04x} product=0x{dev.info.product:04x}"

        # If explicit path given
        if KEYBOARD_DEVICE_PATH:
            try:
                dev = InputDevice(KEYBOARD_DEVICE_PATH)
                logger.info(f"Using specified keyboard device: {device_summary(dev)}")
                key_codes = dev.capabilities().get(ecodes.EV_KEY, [])
                missing = [name for code, name in required_media_keys.items() if code not in key_codes]
                if missing:
                    logger.warning(f"Specified device missing media keys: {', '.join(missing)}")
                else:
                    logger.info("Specified device has all required media keys.")
                return dev
            except Exception as e:
                logger.error(f"Failed to open specified device {KEYBOARD_DEVICE_PATH}: {e}")
                return None

        candidates = []
        for dev in devices:
            caps = dev.capabilities()
            if ecodes.EV_KEY not in caps:
                continue
            # Vendor/product filtering
            if KEYBOARD_VENDOR_ID and dev.info.vendor != int(KEYBOARD_VENDOR_ID, 16):
                continue
            if KEYBOARD_PRODUCT_ID and dev.info.product != int(KEYBOARD_PRODUCT_ID, 16):
                continue
            key_codes = caps.get(ecodes.EV_KEY, [])
            media_present = [code for code in required_media_keys if code in key_codes]
            candidates.append((dev, media_present, key_codes))
            logger.debug(
                f"Candidate device: {device_summary(dev)} has {len(media_present)} media keys: "
                + ", ".join(required_media_keys[c] for c in media_present)
            )

        if not candidates:
            logger.error("No input devices with EV_KEY capability matched criteria.")
            return None

        # Prefer full media key support
        full_media = [c for c in candidates if len(c[1]) == len(required_media_keys)]
        if full_media:
            dev, media_present, key_codes = full_media[0]
            logger.info(f"Selected device with full media keys: {device_summary(dev)}")
            logger.info("Media keys present: " + ", ".join(required_media_keys[c] for c in media_present))
            return dev

        # Otherwise pick the one with most media keys
        candidates.sort(key=lambda t: len(t[1]), reverse=True)
        dev, media_present, key_codes = candidates[0]
        missing = [name for code, name in required_media_keys.items() if code not in media_present]
        logger.warning(
            "No device with full media keys found. Selected: " + device_summary(dev) +
            f" (present: {', '.join(required_media_keys[c] for c in media_present) or 'none'}; "
            f"missing: {', '.join(missing) or 'none'})"
        )
        return dev
    
    async def send_next_page(self):
        """Send next page command to server."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.server_url}/api/next")
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Next page: {data.get('page')}")
                else:
                    logger.error(f"Failed to send next page: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending next page command: {e}")
    
    async def send_previous_page(self):
        """Send previous page command to server."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.server_url}/api/previous")
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Previous page: {data.get('page')}")
                else:
                    logger.error(f"Failed to send previous page: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending previous page command: {e}")
    
    async def send_next_instruction(self):
        """Call server API to move to next instruction."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.server_url}/api/instruction/next")
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Next instruction -> {data.get('instruction')} page reset to {data.get('page')}")
                else:
                    logger.error(f"Failed next instruction: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"Error sending next instruction command: {e}")
    
    async def send_previous_instruction(self):
        """Call server API to move to previous instruction."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.server_url}/api/instruction/previous")
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Previous instruction -> {data.get('instruction')} page reset to {data.get('page')}")
                else:
                    logger.error(f"Failed previous instruction: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"Error sending previous instruction command: {e}")
    
    async def handle_key_event(self, event):
        """Handle keyboard events and trigger appropriate actions."""
        # Only handle key down events
        if event.value != 1:  # 1 = key down, 0 = key up, 2 = key hold
            return
        
        key_code = event.code
        
        # Map media control key codes to actions
        if key_code == ecodes.KEY_NEXTSONG:
            logger.debug("Key: Next Track -> Next Page")
            await self.send_next_page()
        
        elif key_code == ecodes.KEY_PREVIOUSSONG:
            logger.debug("Key: Previous Track -> Previous Page")
            await self.send_previous_page()
        
        elif key_code == ecodes.KEY_VOLUMEUP:
            logger.debug("Key: Volume Up -> Next Instruction")
            await self.send_next_instruction()
        
        elif key_code == ecodes.KEY_VOLUMEDOWN:
            logger.debug("Key: Volume Down -> Previous Instruction")
            await self.send_previous_instruction()
    
    async def run(self):
        """Main event loop to monitor keyboard and send commands."""
        logger.info(f"BrickLapse Keyboard Listener starting...")
        logger.info(f"Server URL: {self.server_url}")
        
        # Load sets configuration
        self.load_sets()
        
        # Find keyboard device
        self.device = self.find_keyboard_device()
        if not self.device:
            logger.error("No keyboard device found. Exiting.")
            sys.exit(1)
        
        logger.info("Keyboard listener active. Monitoring for key presses...")
        logger.info("Key mappings:")
        logger.info("  Next Track -> Next Page")
        logger.info("  Previous Track -> Previous Page")
        logger.info("  Volume Up -> Next Instruction")
        logger.info("  Volume Down -> Previous Instruction")
        
        try:
            # Read events from the device
            async for event in self.device.async_read_loop():
                if event.type == ecodes.EV_KEY:
                    await self.handle_key_event(event)
        except KeyboardInterrupt:
            logger.info("Keyboard listener stopped by user")
        except Exception as e:
            logger.error(f"Error in event loop: {e}")
            raise


def main():
    """Entry point for the keyboard listener service."""
    controller = BrickLapseKeyboardController(
        server_url=SERVER_URL,
        sets_file=SETS_FILE
    )
    
    try:
        asyncio.run(controller.run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
