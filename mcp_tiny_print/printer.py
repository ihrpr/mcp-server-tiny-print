#!/usr/bin/env python3
"""
Tiny Printer Module
"""

import asyncio
from bleak import BleakScanner, BleakClient
from PIL import Image, ImageDraw, ImageFont

# printer characteristics - these are going to be different for different printers
WRITE_CHAR = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR = "0000ff01-0000-1000-8000-00805f9b34fb"

PRINT_WIDTH = 384  # pixels (typical thermal printer width)


class TinyPrinter:
    def __init__(self):
        self.client = None

    async def find_and_connect(self):
        """Find and connect printer"""
        devices = await BleakScanner.discover(timeout=10.0)

        printer = None
        for device in devices:
            if device.name and "PPG" in device.name:
                printer = device
                break

        if not printer:
            return False

        try:
            self.client = BleakClient(printer.address)
            await self.client.connect()

            await asyncio.sleep(1)
            return True

        except Exception:
            return False

    async def send_data(self, data):
        """Send data to printer"""
        if isinstance(data, str):
            data = data.encode("ascii")
        assert self.client is not None, "Client not connected"

        await self.client.write_gatt_char(WRITE_CHAR, data, response=False)
        await asyncio.sleep(0.1)

    def markdown_to_bitmap(self, markdown_text):
        """Convert text to bitmap and fit to printer width"""

        # Clean up text: convert \n strings to actual newlines, remove markdown symbols, add bullets
        text = (
            markdown_text.replace("\\n", "\n")
            .replace("□", "• ")
            .replace("☐", "• ")
            .replace("#", "")
            .replace("*", "")
        )

        # Create image with BIG text
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        except:
            font = ImageFont.load_default()

        img = Image.new("RGB", (PRINT_WIDTH, 2000), "white")  # Use printer width
        draw = ImageDraw.Draw(img)
        draw.multiline_text((10, 10), text, font=font, fill="black")

        # Convert to black/white and crop
        img = img.convert("1")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)

        # Already at printer width, just crop height

        # Invert for thermal printer
        img = img.point(lambda x: 255 - x)

        return img

    def text_to_bitmap(self, text):
        """Convert text to bitmap - text fills the full width naturally"""
        # Split text into lines
        lines = [line.strip() for line in text.split("\n")]
        lines = [line for line in lines if line]  # Remove empty lines

        # Find the longest line to determine font size
        longest_line = max(lines, key=len)

        # Binary search to find the largest font that makes the longest line fit exactly
        min_font = 8
        max_font = 200
        best_font_size = 16

        while min_font <= max_font:
            test_font_size = (min_font + max_font) // 2

            try:
                test_font = ImageFont.truetype(
                    "/System/Library/Fonts/Helvetica.ttc", test_font_size
                )
            except:
                try:
                    test_font = ImageFont.truetype(
                        "/System/Library/Fonts/Arial.ttf", test_font_size
                    )
                except:
                    test_font = ImageFont.load_default()

            # Test how wide the longest line would be
            temp_img = Image.new("1", (1, 1), "white")
            temp_draw = ImageDraw.Draw(temp_img)
            bbox = temp_draw.textbbox((0, 0), longest_line, font=test_font)
            text_width = bbox[2] - bbox[0]

            # We want the text to be exactly PRINT_WIDTH - 20 pixels (small margin)
            target_width = PRINT_WIDTH - 20

            if text_width <= target_width:
                best_font_size = test_font_size
                min_font = test_font_size + 1
            else:
                max_font = test_font_size - 1

        # Create the final font
        try:
            font = ImageFont.truetype(
                "/System/Library/Fonts/Helvetica.ttc", best_font_size
            )
        except:
            try:
                font = ImageFont.truetype(
                    "/System/Library/Fonts/Arial.ttf", best_font_size
                )
            except:
                font = ImageFont.load_default()

        # Calculate total height needed
        temp_img = Image.new("1", (1, 1), "white")
        temp_draw = ImageDraw.Draw(temp_img)

        total_height = 10  # Top margin
        line_heights = []

        for line in lines:
            bbox = temp_draw.textbbox((0, 0), line, font=font)
            height = bbox[3] - bbox[1]
            line_heights.append(height)
            total_height += height + 5  # Add line spacing

        # Create image exactly PRINT_WIDTH pixels wide
        img = Image.new("1", (PRINT_WIDTH, int(total_height + 10)), "white")
        draw = ImageDraw.Draw(img)

        # Draw each line, centered in the full width
        y_pos = 10
        for i, line in enumerate(lines):
            # Measure this line for centering
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            x = (PRINT_WIDTH - line_width) // 2  # Center in full width

            # Draw the line
            draw.text((x, y_pos), line, font=font, fill="black")
            y_pos += line_heights[i] + 5

        # Invert the image since printer prints inverted
        img = img.point(lambda x: 255 - x)

        return img

    async def print_bitmap(self, img):
        """Print bitmap using ESC/POS GS v 0 method"""
        width, height = img.size

        # Ensure width is exactly 96 pixels
        if width != PRINT_WIDTH:
            new_img = Image.new("1", (PRINT_WIDTH, height), "white")
            if width < PRINT_WIDTH:
                # Center smaller image
                offset = (PRINT_WIDTH - width) // 2
                new_img.paste(img, (offset, 0))
            else:
                # Crop larger image
                img = img.crop((0, 0, PRINT_WIDTH, height))
                new_img = img
            img = new_img
            width = PRINT_WIDTH

        # Convert to bitmap bytes
        pixels = img.tobytes()
        width_bytes = width // 8  # 96 pixels = 12 bytes per line

        # NOTE: Those will be very different for different printers

        command = bytearray()
        command.extend(b"\x1b\x40")  # Initialize printer first
        command.extend(b"\x1d\x76\x30\x00")  # GS v 0 m
        command.append(width_bytes & 0xFF)  # xL (width in bytes)
        command.append((width_bytes >> 8) & 0xFF)  # xH
        command.append(height & 0xFF)  # yL (height)
        command.append((height >> 8) & 0xFF)  # yH
        command.extend(pixels)  # Bitmap data
        command.extend(b"\n\n\n")  # Feed paper

        # Send the complete command
        await self.send_data(bytes(command))

    async def print_markdown(self, markdown_text):
        """Print markdown text with formatting"""

        # Convert markdown to bitmap with formatting
        img = self.markdown_to_bitmap(markdown_text)

        # Print the bitmap
        await self.print_bitmap(img)
